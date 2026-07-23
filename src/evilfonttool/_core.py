import codecs
import copy
import logging
import os
import pathlib
import re
import string
import uuid
import zipfile
from xml.sax.saxutils import escape as _xml_escape

from fontTools.ttLib import TTFont
from docx import Document
from docx.oxml.ns import qn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# The set of characters to include in the font family.
# Modify this to limit which characters are processed.
LETTERS = (
    string.ascii_lowercase
    + " "
    + string.punctuation
    + string.ascii_uppercase
    + string.digits
)

# Advance width for invisible (stealth) characters.
# 0 works for most renderers, but some applications may behave unexpectedly.
WIDTH = 0

# Path to the bundled HTML template.
_TEMPLATE = pathlib.Path(__file__).parent / "data" / "template.html"


def _read_lines(path):
    """Read a user-supplied text file and split it into lines.

    A bare open(path) decodes with the platform-default encoding, which on
    Windows is not UTF-8 or UTF-16 -- and PowerShell's `>` / `echo` / `Out-File`
    (plus Notepad's "Unicode" option) write UTF-16 with a BOM. Reading that
    with the platform default doesn't raise; it silently produces a string
    full of embedded NUL bytes, which only surfaces later as a confusing lxml
    error. Sniff the BOM (if any) and decode accordingly instead.
    """
    with open(path, "rb") as handle:
        raw = handle.read()
    for bom, encoding in (
        (codecs.BOM_UTF8, "utf-8"),
        (codecs.BOM_UTF16_LE, "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16-be"),
    ):
        if raw.startswith(bom):
            # utf-16-le/-be don't strip their own BOM on decode (unlike
            # utf-8-sig for utf-8); slice it off ourselves in all three cases.
            return raw[len(bom):].decode(encoding).splitlines()
    return raw.decode("utf-8").splitlines()


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

def _get_unicode_cmap(font):
    """Return the first suitable Windows Unicode cmap subtable (format 4 or 12).

    Raises ValueError if none is found.
    """
    for table in font['cmap'].tables:
        if (table.format in (4, 12)
                and table.platformID == 3
                and table.platEncID in (1, 10)):
            return table
    raise ValueError("No suitable Unicode cmap subtable found in the font.")


def _remove_layout_tables(font):
    """Remove OpenType tables that control ligatures, kerning, and substitution.

    These tables operate on glyph names rather than cmap entries, so they can
    override our remapping in unpredictable ways depending on surrounding characters.
    """
    for tag in ('GSUB', 'GPOS', 'kern', 'GDEF'):
        if tag in font:
            del font[tag]


def _rename_font(font, new_name):
    """Overwrite the family name records in the font's name table."""
    for record in font['name'].names:
        if record.nameID in (1, 4, 6):
            record.string = new_name.encode("utf-16-be")


# ---------------------------------------------------------------------------
# Core font generation
# ---------------------------------------------------------------------------

def createstealthfont(reference_font, output_dir, font_name):
    """Generate a stealth font where every character renders as an invisible space.

    The stealth font is used to hide the extra computer-file characters that
    have no corresponding human-file character to disguise themselves as.
    It is saved as both WOFF (web) and TTF (document/desktop).
    """
    font = TTFont(reference_font)
    unicode_cmap = _get_unicode_cmap(font)

    # Use the space glyph as the target — all other characters will map to it
    space_glyph_name = unicode_cmap.cmap.get(ord(" "))

    # Remap every character in LETTERS to the space glyph and zero its advance width
    for table in font['cmap'].tables:
        for char in LETTERS:
            if ord(char) in table.cmap:
                table.cmap[ord(char)] = space_glyph_name
                font['hmtx'].metrics[space_glyph_name] = (
                    WIDTH,
                    font['hmtx'].metrics[space_glyph_name][1],
                )

    _remove_layout_tables(font)

    # Internal font name for the stealth variant uses "0" as a sentinel
    new_name = f'{font_name} 0'
    _rename_font(font, new_name)
    logger.debug(f"  Stealth font internal name: {new_name}")

    # Append the @font-face CSS rule for the stealth font
    with open(f'{output_dir}/fonts.css', "a") as css_file:
        css_file.write(
            "@font-face {"
            'font-family: "0";'
            'src: url("fonts/0.woff") format(\'woff\');'
            "}"
        )

    # Save WOFF (flavor must be set explicitly) then TTF
    font.flavor = 'woff'
    font.save(f'{output_dir}/fonts/0.woff')
    font.flavor = None
    font.save(f'{output_dir}/ttffonts/0.ttf')

    logger.debug(f"[DONE] stealth font -> {output_dir}/fonts/0.woff + ttffonts/0.ttf")


def createfonts(reference_font, output_dir, font_name):
    """Generate one Evil Font variant per character in LETTERS.

    In each variant, every character's glyph is replaced with the glyph for
    `currentletter`. This means that no matter what Unicode byte is stored in
    the document, the renderer will draw `currentletter` — the core Evil Font trick.

    Also writes all @font-face rules to fonts.css (overwrites any existing file).
    """
    logger.debug(f"Source font:  {reference_font}")
    logger.debug(f"Output dir:   {output_dir}")
    logger.debug(f"Characters:   {len(LETTERS)} variants to generate")

    with open(f'{output_dir}/fonts.css', "w") as css_file:

        for currentletter in LETTERS:
            # Load a fresh copy of the font for each variant to avoid cross-contamination
            font = TTFont(reference_font)
            font.recalcBBoxes = False

            unicode_cmap = _get_unicode_cmap(font)

            # Get the source glyph and its advance width for this letter
            source_glyph_name = unicode_cmap.cmap.get(ord(currentletter))
            source_width = font['hmtx'].metrics[source_glyph_name][0]

            # Take a deep copy of the source glyph to use as a stamp
            source_glyph = copy.deepcopy(font['glyf'][source_glyph_name])

            # Remap every other character in LETTERS to look like currentletter
            for table in font['cmap'].tables:
                for char in LETTERS:
                    if char == currentletter:
                        continue
                    if ord(char) not in table.cmap:
                        continue

                    target_glyph_name = table.cmap[ord(char)]
                    target_original = font['glyf'][target_glyph_name]

                    # Preserve the target's original bounding box so that
                    # spacing and baseline positioning remain correct
                    orig_xMin = getattr(target_original, 'xMin', 0)
                    orig_yMax = getattr(target_original, 'yMax', 0)
                    orig_yMin = getattr(target_original, 'yMin', 0)

                    # Stamp a copy of the source glyph into the target slot
                    font['glyf'][target_glyph_name] = copy.deepcopy(source_glyph)

                    # Restore the vertical bounds (keeps line height consistent)
                    font['glyf'][target_glyph_name].yMax = orig_yMax
                    font['glyf'][target_glyph_name].yMin = orig_yMin

                    # Match advance width to source; preserve original LSB for positioning
                    font['hmtx'].metrics[target_glyph_name] = (source_width, orig_xMin)

            _remove_layout_tables(font)

            # Each font variant is named using the hex encoding of the letter
            # so the name is unique and safely usable as a filename
            letter_hex = currentletter.encode().hex()
            new_name = f'{font_name} {letter_hex}'
            _rename_font(font, new_name)

            # Save as WOFF for web use and TTF for document/desktop use
            font.flavor = 'woff'
            font.save(f'{output_dir}/fonts/{letter_hex}.woff')
            font.flavor = None
            font.save(f'{output_dir}/ttffonts/{letter_hex}.ttf')

            # Write the @font-face rule for this variant
            css_file.write(
                f'@font-face {{'
                f'font-family: "{letter_hex}";'
                f'src: url("fonts/{letter_hex}.woff") format(\'woff\');'
                f'}}'
            )

            logger.debug(f"  [{letter_hex}] '{currentletter}' -> {output_dir}/fonts/{letter_hex}.woff + ttffonts/{letter_hex}.ttf")


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------

def _write_html(output_file, content):
    """Inject `content` into the bundled HTML template and write to `output_file`."""
    html = _TEMPLATE.read_text()
    html = html.replace("<!-- #STUFF HERE -->", content)
    with open(output_file, "w") as f:
        f.write(html)


def createhtml(input_human_file, input_computer_file, output_file):
    """Build a steganographic HTML file from human and computer text files.

    Each character from the computer file is wrapped in a <span> that applies
    an Evil Font chosen by the corresponding human file character. To a human
    reading the rendered page, the text looks like the human file. A machine
    parsing the raw HTML sees the computer file.

    Lines where the computer text is shorter than the human text are skipped.
    Extra computer characters (beyond the human line length) are hidden using
    the stealth font (font-family: '0').
    """
    logger.debug(f"Human file:    {input_human_file}")
    logger.debug(f"Computer file: {input_computer_file}")
    logger.debug(f"Output file:   {output_file}")

    spans = []
    lines_processed = 0
    total_hidden = 0
    line_number = 0

    for human_line, computer_line in zip(
        _read_lines(input_human_file),
        _read_lines(input_computer_file),
    ):
        h_len = len(human_line)
        c_len = len(computer_line)

        line_number += 1
        logger.debug(f"Human   ({h_len} chars): {human_line}")
        logger.debug(f"Computer({c_len} chars): {computer_line}")

        if c_len < h_len:
            logger.warning(f"  Skipping line {line_number}: computer line must be >= human line length.")
            continue

        # Extra computer characters are inserted at the midpoint of the human text
        diff = c_len - h_len
        mid = h_len // 2

        logger.debug(f"  diff={diff}, hidden chars inserted at mid={mid}")

        line_spans = []
        h_index = 0

        for i, computer_char in enumerate(computer_line):
            if mid <= i < mid + diff:
                # Hidden character — rendered invisibly using the stealth font
                line_spans.append(
                    f"<span style=\"font-family: '0';\">{computer_char}</span>"
                )
            else:
                # Visible character — disguised as the corresponding human character
                human_char = human_line[h_index]
                letter_hex = human_char.encode().hex()
                line_spans.append(
                    f"<span style=\"font-family: '{letter_hex}';\">{computer_char}</span>"
                )
                h_index += 1

        spans.append("".join(line_spans))
        lines_processed += 1
        total_hidden += diff

    _write_html(output_file, "\n<br>\n".join(spans))
    logger.debug(f"[DONE] HTML written -> {output_file} ({lines_processed} lines, {total_hidden} hidden chars)")


# ---------------------------------------------------------------------------
# DOCX font embedding
# ---------------------------------------------------------------------------

# OOXML content type for an obfuscated embedded font part (ECMA-376 Part 1, 17.9).
_FONTDATA_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.obfuscatedFont"


def _obfuscate_font_bytes(data, guid_bytes):
    """XOR the first 32 bytes of TTF `data` with `guid_bytes`, taken in reverse.

    This is the OOXML font-embedding obfuscation algorithm (ECMA-376 Part 1,
    17.9.2). Word reverses it with the identical XOR -- using the GUID stored
    as the embedded part's fontKey -- before treating the bytes as a normal
    TTF; XOR being its own inverse is exactly why one function does both
    directions.
    """
    data = bytearray(data)
    for i in range(min(32, len(data))):
        data[i] ^= guid_bytes[15 - (i % 16)]
    return bytes(data)


def _next_rel_id(rels_xml):
    """Return an rIdN not already used in a .rels part's raw XML text."""
    used = {int(n) for n in re.findall(r'Id="rId(\d+)"', rels_xml)}
    n = 1
    while n in used:
        n += 1
    return f"rId{n}"


def _embed_fonts(docx_path, ttf_dir, font_names):
    """Embed the given Evil Font TTFs directly into a saved .docx, in place.

    `font_names` are the exact font family names used in the document's runs
    (e.g. 'MyFont 68', 'MyFont 0'); each one's TTF is found in `ttf_dir` by the
    hex/'0' suffix after the last space -- the same naming createfonts() and
    createstealthfont() use. This builds the OOXML font-embedding parts
    (fontTable.xml entries, obfuscated font data, relationships, content
    types) directly, rather than relying on Word's -- or LibreOffice's, which
    doesn't work for Evil Fonts -- own "embed fonts" save option.

    python-docx's default template always ships a word/fontTable.xml (listing
    the built-in style fonts) and a document.xml.rels entry for it already, so
    only new <w:font> entries need appending; nothing else needs to reference
    fontTable.xml for the first time.
    """
    with zipfile.ZipFile(docx_path, "r") as zin:
        parts = {name: zin.read(name) for name in zin.namelist()}

    fonttable_xml = parts["word/fontTable.xml"].decode("utf-8")
    fonttable_rels_xml = parts.get(
        "word/_rels/fontTable.xml.rels",
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>',
    ).decode("utf-8")
    content_types_xml = parts["[Content_Types].xml"].decode("utf-8")

    new_fonts, new_rels, new_overrides = [], [], []
    idx = 0
    for font_name in sorted(font_names):
        suffix = font_name.rsplit(" ", 1)[-1]
        ttf_path = os.path.join(ttf_dir, f"{suffix}.ttf")
        if not os.path.isfile(ttf_path):
            logger.warning("embed: no TTF for font '%s' at %s -- skipping.", font_name, ttf_path)
            continue

        idx += 1
        part_name = f"fonts/font{idx}.fntdata"
        rid = _next_rel_id(fonttable_rels_xml + "".join(new_rels))

        guid = uuid.uuid4()
        with open(ttf_path, "rb") as handle:
            raw = handle.read()
        parts[f"word/{part_name}"] = _obfuscate_font_bytes(raw, guid.bytes)

        new_fonts.append(
            f'<w:font w:name="{_xml_escape(font_name)}">'
            f'<w:embedRegular r:id="{rid}" w:fontKey="{{{str(guid).upper()}}}" w:subsetted="false"/>'
            f'</w:font>'
        )
        new_rels.append(
            f'<Relationship Id="{rid}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/font" '
            f'Target="{part_name}"/>'
        )
        new_overrides.append(
            f'<Override PartName="/word/{part_name}" ContentType="{_FONTDATA_CONTENT_TYPE}"/>'
        )

    if not new_fonts:
        logger.warning("embed: no fonts embedded (none of the used fonts had a matching TTF).")
        return

    parts["word/fontTable.xml"] = fonttable_xml.replace(
        "</w:fonts>", "".join(new_fonts) + "</w:fonts>").encode("utf-8")
    parts["word/_rels/fontTable.xml.rels"] = fonttable_rels_xml.replace(
        "</Relationships>", "".join(new_rels) + "</Relationships>").encode("utf-8")
    parts["[Content_Types].xml"] = content_types_xml.replace(
        "</Types>", "".join(new_overrides) + "</Types>").encode("utf-8")

    settings_xml = parts["word/settings.xml"].decode("utf-8")
    if "<w:embedTrueTypeFonts" not in settings_xml:
        if "<w:proofState" in settings_xml:
            settings_xml = settings_xml.replace(
                "<w:proofState", "<w:embedTrueTypeFonts/><w:proofState", 1)
        else:
            insert_at = settings_xml.index(">", settings_xml.index("<w:settings")) + 1
            settings_xml = (settings_xml[:insert_at] + "<w:embedTrueTypeFonts/>"
                            + settings_xml[insert_at:])
        parts["word/settings.xml"] = settings_xml.encode("utf-8")

    with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in parts.items():
            zout.writestr(name, data)

    logger.debug(f"[DONE] Embedded {idx} font(s) into {docx_path}")


# ---------------------------------------------------------------------------
# DOCX output
# ---------------------------------------------------------------------------

def create_doc(input_human_file, input_computer_file, output_file, font_name_in,
               author="anonymous", ttf_dir=None):
    """Build a steganographic DOCX file from human and computer text files.

    Works identically to createhtml() but outputs a Word document. Each run is
    assigned an Evil Font by setting all four font slots (ascii, hAnsi, eastAsia,
    cs) to prevent Word from falling back to a system font.

    If `ttf_dir` is given (the `ttffonts` directory from the `create` step), the
    Evil Font TTFs actually used are embedded directly into the saved .docx, so
    the deception renders correctly even where the fonts aren't installed.
    Otherwise the TTF variants must be installed on the system for the
    deception to render correctly in Word.

    Lines where the computer text is shorter than the human text are skipped.
    """
    logger.debug(f"Human file:    {input_human_file}")
    logger.debug(f"Computer file: {input_computer_file}")
    logger.debug(f"Output file:   {output_file}")
    logger.debug(f"Font family:   {font_name_in}")

    doc = Document()
    lines_processed = 0
    total_hidden = 0
    line_number = 0
    used_font_names = set()

    for human_line, computer_line in zip(
        _read_lines(input_human_file),
        _read_lines(input_computer_file),
    ):
        h_len = len(human_line)
        c_len = len(computer_line)

        line_number += 1
        logger.debug(f"Human   ({h_len} chars): {human_line}")
        logger.debug(f"Computer({c_len} chars): {computer_line}")

        if c_len < h_len:
            logger.warning(f"  Skipping line {line_number}: computer line must be >= human line length.")
            continue

        diff = c_len - h_len
        mid = h_len // 2

        logger.debug(f"  diff={diff}, hidden chars inserted at mid={mid}")

        p = doc.add_paragraph()
        h_index = 0

        for i, computer_char in enumerate(computer_line):
            if mid <= i < mid + diff:
                # Hidden character — use the stealth (zero-width) font
                font_name = f'{font_name_in} 0'
            else:
                # Visible character — disguised as the corresponding human character
                human_char = human_line[h_index]
                font_name = f'{font_name_in} {human_char.encode().hex()}'
                h_index += 1

            # Add a run and explicitly set all four font slots.
            # Word will fall back to a system font if any slot is unset,
            # which would break the illusion.
            run = p.add_run(computer_char)
            run.font.name = font_name
            rFonts = run._element.rPr.rFonts
            rFonts.set(qn("w:ascii"),   font_name)
            rFonts.set(qn("w:hAnsi"),   font_name)
            rFonts.set(qn("w:eastAsia"), font_name)
            rFonts.set(qn("w:cs"),      font_name)
            used_font_names.add(font_name)

        lines_processed += 1
        total_hidden += diff

    doc.core_properties.comments = ""
    if author is not None:
        doc.core_properties.author = author

    doc.save(output_file)

    if ttf_dir:
        _embed_fonts(output_file, ttf_dir, used_font_names)

    logger.debug(f"[DONE] DOCX written -> {output_file} ({lines_processed} lines, {total_hidden} hidden chars)")

# ---------------------------------------------------------------------------
# PDF output (copy-paste-safe two-layer render)
# ---------------------------------------------------------------------------
#
# Turns an Evil Font DOCX (produced by create_doc) into a PDF that:
#   * looks EXACTLY like the docx  -- LibreOffice renders the real document,
#     so all formatting/headers/footers are preserved and rasterised as a
#     non-selectable image layer, and
#   * copy-pastes the hidden payload correctly in every viewer (incl. poppler),
#     by squishing each rendered line's payload (visible + hidden chars) onto
#     that line's exact box as invisible text (PDF render mode 3).
#
# Runtime requirements (install once):
#   * LibreOffice ('soffice' on PATH) and poppler-utils
#   * pip install reportlab pdf2image pdfminer.six Pillow

import os
import subprocess
import tempfile

from docx.document import Document as _DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from reportlab.pdfgen import canvas as _rl_canvas
from reportlab.lib.utils import ImageReader as _ImageReader
from reportlab.pdfbase import pdfmetrics as _pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as _RLTTFont
from pdf2image import convert_from_path as _convert_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError as _PDFInfoNotInstalledError
from pdfminer.high_level import extract_pages as _extract_pages
from pdfminer.layout import LTChar as _LTChar

_INK_FONT = "__ink__"     # reportlab name for the invisible copy layer
_REGION_TOL = 2.0             # pt tolerance for header/footer classification


def _iter_block_items(parent):
    """Yield every paragraph in the document, in reading order.

    docx `doc.paragraphs` skips text inside tables, so we walk the raw XML body
    instead: paragraphs (CT_P) are yielded directly, and tables (CT_Tbl) are
    descended into cell-by-cell (recursively, since cells can contain tables).
    This keeps the payload order identical to how the page reads top-to-bottom,
    which is what the copy layer relies on.
    """
    # A document's runs live on `.element.body`; a table cell's on `._tc`.
    elem = parent.element.body if isinstance(parent, _DocxDocument) else parent._tc
    for child in elem.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            table = Table(child, parent)
            for row in table.rows:
                for cell in row.cells:
                    yield from _iter_block_items(cell)


def _run_font_name(run):
    """Return the font family assigned to a run.

    `run.font.name` covers the common case, but create_doc sets the four w:rFonts
    slots directly (ascii/hAnsi/eastAsia/cs), so fall back to reading them off the
    XML when the high-level property is empty. Without this fallback some runs
    would look font-less and their stealth/visible status would be misjudged.
    """
    name = run.font.name
    if name:
        return name
    rpr = run._element.rPr
    if rpr is not None:
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is not None:
            return rfonts.get(qn("w:ascii")) or rfonts.get(qn("w:hAnsi")) or ""
    return ""


def _is_stealth_font(font_name):
    """True if `font_name` is a stealth font.

    createstealthfont always names the stealth font '<prefix> 0', while disguise
    fonts always end in a hex code (>= 2 digits, e.g. '<prefix> 61'). So a name
    ending in ' 0' is unambiguously the stealth font -- independent of the prefix,
    which means it doesn't matter whether the font_name passed to create_pdf
    exactly matches the one used to build the doc. Rendered PDFs may prepend a
    subset tag like 'ABCDEF+', so strip that first.
    """
    base = (font_name or "").split("+", 1)[-1]
    return base.endswith(" 0")


def _is_decorative_glyph(char_text):
    """True if `char_text` is a native list-bullet/symbol glyph, not payload content.

    Word/LibreOffice draw list bullets (and other auto-numbering glyphs) straight
    from the paragraph's numbering definition using a symbol font (e.g. Wingdings),
    at render time -- that glyph never appears in any run's text, so the docx
    parser has no way to know about it and it is absent from the payload entirely.
    These glyphs are reliably encoded in the Unicode Private Use Area, which our
    disguised payload characters (always plain ASCII) never use, so PUA codepoints
    are a safe signal to exclude them from the visible glyph count.
    """
    return len(char_text) == 1 and 0xE000 <= ord(char_text) <= 0xF8FF


def _paragraph_payload(paragraphs):
    """Flatten runs into the character stream we must reproduce on copy.

    Returns (payload, visible):
      * payload  -- every character in order as (char, is_hidden) tuples. This is
                    the FULL computer text (disguised chars + stealth chars) and
                    is exactly what a copy-paste of the PDF must yield.
      * visible  -- just the non-hidden characters, joined. Its length must match
                    the number of visible glyphs LibreOffice actually draws; that
                    is how the copy layer keeps its place (see _assign_payload).
    """
    payload, visible = [], []
    for paragraph in paragraphs:
        for run in paragraph.runs:
            hidden = _is_stealth_font(_run_font_name(run))
            for char in run.text:
                payload.append((char, hidden))
                if not hidden:          # stealth chars have no visible glyph
                    visible.append(char)
    return payload, "".join(visible)


def _parse_docx_payload(docx_path):
    """Pull the body/header/footer payloads and page geometry from the docx.

    Header and footer text lives outside the body (in the section), so it is read
    separately here and later placed on every page. The top/bottom margins are
    returned in points so rendered lines can be classified into those three
    regions by y-position. Only the first section is consulted (the common case).
    """
    doc = Document(docx_path)
    body = _paragraph_payload(list(_iter_block_items(doc)))
    section = doc.sections[0]
    header = _paragraph_payload(section.header.paragraphs)
    footer = _paragraph_payload(section.footer.paragraphs)
    # `.pt` converts EMUs -> points; margins can be None if the doc leaves them
    # at the Word default (1 inch = 72 pt).
    top = section.top_margin.pt if section.top_margin is not None else 72.0
    bottom = section.bottom_margin.pt if section.bottom_margin is not None else 72.0
    return {"body": body, "header": header, "footer": footer,
            "top_margin": top, "bottom_margin": bottom}


def _render_docx_to_pdf(docx_path, ttf_dir, workdir, soffice):
    """Render the ORIGINAL docx to PDF with LibreOffice.

    Rendering the real document (rather than re-typesetting it ourselves) is what
    makes the PDF look identical -- margins, wrapping, images, and formatting are
    all whatever the doc already says. The Evil Fonts must be visible to
    LibreOffice for the disguise to render, so if a ttf_dir is given we point
    fontconfig at it via a throwaway config instead of installing the fonts
    system-wide.
    """
    # Resolve to absolute before any cwd changes (below, for the soffice
    # subprocess) so a relative path the caller passed still resolves against
    # the original working directory, not soffice's.
    docx_path = os.path.abspath(docx_path)

    env = dict(os.environ)
    if ttf_dir:
        # Build a temporary fontconfig that adds ttf_dir on top of the system
        # fonts, and expose it through FONTCONFIG_FILE for this render only.
        conf = os.path.join(workdir, "fonts.conf")
        cache = os.path.join(workdir, "fccache")
        os.makedirs(cache, exist_ok=True)
        with open(conf, "w") as handle:
            handle.write(
                '<?xml version="1.0"?>\n'
                '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
                "<fontconfig>\n"
                f"  <dir>{os.path.abspath(ttf_dir)}</dir>\n"
                f"  <cachedir>{cache}</cachedir>\n"
                '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
                "</fontconfig>\n"
            )
        env["FONTCONFIG_FILE"] = conf
        try:
            subprocess.run(["fc-cache", "-f"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            # fc-cache (fontconfig) isn't available on Windows; --ttf-dir is
            # exposed to LibreOffice via FONTCONFIG_FILE regardless, but without
            # fc-cache to prime it, a stale/missing cache may make LibreOffice
            # miss the fonts on the first run.
            logger.warning(
                "'fc-cache' not found -- skipping font cache refresh. If the "
                "disguise doesn't render, try running the command again."
            )
    # A private user profile avoids clashing with any LibreOffice already running.
    # Building the URI by hand (e.g. "file://" + a Windows path) produces a
    # malformed "file://C:\..." URI -- backslashes instead of "/", and no
    # leading slash before the drive letter -- which LibreOffice on Windows
    # can't resolve, manifesting as a "bootstrap.ini is corrupt" popup.
    # Path.as_uri() builds a correct file:// URI on every platform.
    profile = pathlib.Path(workdir, "loprofile").resolve().as_uri()
    # On Windows, soffice.exe resolves bootstrap.ini relative to its own
    # working directory -- double-clicking it in Explorer sets that
    # automatically, but a subprocess otherwise inherits our cwd instead,
    # which soffice.exe misreads as a corrupt config. Run it from its own
    # directory to match how Explorer launches it.
    soffice_dir = os.path.dirname(soffice) or None
    try:
        result = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", workdir,
             docx_path, f"-env:UserInstallation={profile}"],
            env=env, cwd=soffice_dir,
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            f"Could not find the LibreOffice binary '{soffice}'. On Windows, "
            "it's usually not on PATH even after installing -- pass --soffice "
            "with the full path, e.g. "
            "--soffice \"C:\\Program Files\\LibreOffice\\program\\soffice.exe\"."
        ) from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"LibreOffice failed to convert '{docx_path}' to PDF "
            f"(exit code {result.returncode})."
            + (f"\n{detail}" if detail else " No further output was captured.")
        )
    # LibreOffice names the output after the input stem, in --outdir.
    out = os.path.join(
        workdir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
    if not os.path.exists(out):
        # soffice can exit 0 even when it fails (e.g. "source file could not
        # be loaded" for a missing/corrupt input) rather than a nonzero code,
        # so surface whatever it printed here too.
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"LibreOffice produced no PDF for '{docx_path}'."
            + (f"\n{detail}" if detail else " No further output was captured.")
        )
    return out


def _split_row_by_gaps(row, gap_factor=2.5):
    """Split a left-to-right sorted row of glyphs into segments wherever the gap
    between consecutive glyphs is much larger than the text size (an inline
    image, a tab stop, or a column break). Normal inter-word spaces stay joined."""
    if not row:
        return []
    segments, current = [], [row[0]]
    for prev, glyph in zip(row, row[1:]):
        gap = glyph.x0 - prev.x1
        if gap > gap_factor * max(prev.size, glyph.size, 1.0):
            segments.append(current)
            current = [glyph]
        else:
            current.append(glyph)
    segments.append(current)
    return segments


def _visible_lines(pdf_path, y_tol=3.0):
    """Recover the on-page text lines from the rendered PDF.

    We cluster the glyphs ourselves rather than trusting pdfminer's own line
    grouping, because the zero-width stealth glyphs sit on top of their neighbours
    and scramble pdfminer's ordering. Returns, per page, its size and a list of
    line segments -- each a {"box": (x0,y0,x1,y1), "n": visible_glyph_count} -- in
    reading order. Those boxes are exactly where the copy layer gets placed.
    """
    pages = []
    for layout in _extract_pages(pdf_path):
        # pdfminer nests glyphs inside containers/figures; flatten to every LTChar.
        glyphs, stack = [], [layout]
        while stack:
            obj = stack.pop()
            if isinstance(obj, _LTChar):
                glyphs.append(obj)
            elif hasattr(obj, "__iter__"):
                try:
                    stack.extend(list(obj))
                except TypeError:
                    pass
        # A glyph is hidden if it is drawn with the stealth font (robust), is
        # ~zero-width (belt-and-braces), or is a native decorative glyph (list
        # bullets etc.) that never appears in the payload. Everything else is a
        # visible glyph, and the visible-glyph count per line is what anchors
        # the copy layer.
        visible = [g for g in glyphs
                   if not _is_stealth_font(g.fontname)
                   and (g.x1 - g.x0) > 0.1 * max(g.size, 1.0)
                   and not _is_decorative_glyph(g.get_text())]
        # Group glyphs into rows: sort top-to-bottom (PDF y grows upward, so -y0)
        # then left-to-right, and start a new row when the baseline jumps.
        visible.sort(key=lambda g: (-g.y0, g.x0))
        rows, current, base_y = [], [], None
        for g in visible:
            if base_y is None or abs(g.y0 - base_y) <= y_tol:
                current.append(g)
                base_y = g.y0 if base_y is None else base_y
            else:
                rows.append(current)
                current, base_y = [g], g.y0
        if current:
            rows.append(current)
        lines = []
        for row in rows:
            row.sort(key=lambda g: g.x0)
            # Split the row wherever there is a large horizontal gap (an inline
            # image, a column break, etc.) so the invisible copy layer never
            # stretches across an image and becomes selectable "behind" it.
            for segment in _split_row_by_gaps(row):
                # Tight bounding box of this segment's glyphs = where its slice of
                # the payload will be squished in.
                box = (min(g.x0 for g in segment), min(g.y0 for g in segment),
                       max(g.x1 for g in segment), max(g.y1 for g in segment))
                lines.append({"box": box, "n": len(segment)})
        pages.append({"size": (layout.width, layout.height), "lines": lines})
    return pages


def _assign_payload(payload, counts):
    """Split the payload into one string per line, matching the rendered layout.

    `counts[i]` is how many visible glyphs line i actually has. We build a lookup
    from "nth visible character" -> "line index", then replay the payload: every
    visible char advances one slot through that lookup, while hidden chars simply
    ride along on whichever line the surrounding visible chars are on (so an
    injected stealth run stays with the words it was hidden between). If the
    counts don't cover the payload (a layout we couldn't line up), the remainder
    falls onto the last line so nothing is dropped from a copy.
    """
    visible_line = []
    for line_index, n in enumerate(counts):
        visible_line.extend([line_index] * n)
    total = len(visible_line)
    buffers = ["" for _ in counts]
    pointer = 0
    for char, hidden in payload:
        if not counts:
            break
        line_index = visible_line[pointer] if pointer < total else len(counts) - 1
        if not hidden:                 # only visible chars consume a glyph slot
            pointer += 1
        buffers[line_index] += char
    return buffers


def _draw_invisible(pdf, text, box, min_size=4.0, max_size=144.0):
    """Lay `text` into `box` as invisible, selectable text (the copy layer).

    Render mode 3 draws no ink but keeps the text fully selectable and copyable in
    every viewer -- the same trick OCR "searchable" PDFs use. The horizontal scale
    compresses the whole string (which is longer than the visible line, since it
    also carries the hidden chars) to exactly the line's width, so it sits under
    the matching visible text with no overlap or spill.

    The font size is derived from the line's own bounding-box height rather than
    a fixed constant, so the invisible text -- and the selection highlight a
    viewer draws for it -- roughly matches the size of the visible text underneath
    (a heading and a footnote no longer both highlight at the same fixed size).
    """
    if not text:
        return
    x0, y0, x1, y1 = box
    width = max(1.0, x1 - x0)
    size = max(min_size, min(max_size, y1 - y0))
    natural = _pdfmetrics.stringWidth(text, _INK_FONT, size) or 1.0
    text_obj = pdf.beginText(x0, y0)
    text_obj.setFont(_INK_FONT, size)
    text_obj.setTextRenderMode(3)                     # invisible but selectable
    text_obj.setHorizScale(width / natural * 100.0)   # squish onto the line's width
    text_obj.textOut(text)
    pdf.drawText(text_obj)


def _resolve_ink_font(ink_font):
    """Pick the TTF used to draw the (invisible) copy layer.

    Its shape never shows, so any Unicode-capable font works; we just need real
    per-character widths so the text lays out sanely. Prefer an explicit font,
    otherwise ask fontconfig for a broad system sans.
    """
    if ink_font:
        return ink_font
    for query in ("DejaVu Sans", "Liberation Sans", "sans-serif"):
        try:
            found = subprocess.run(
                ["fc-match", "-f", "%{file}", query],
                capture_output=True, text=True).stdout.strip()
            if found and os.path.exists(found):
                return found
        except FileNotFoundError:
            break
    raise RuntimeError(
        "Could not auto-detect a system font for the invisible copy layer "
        "(this uses 'fc-match', which isn't available on Windows and may be "
        "missing elsewhere too). Pass --ink-font pointing at any TTF on your "
        "system, e.g. --ink-font \"C:\\Windows\\Fonts\\times.ttf\" on Windows, "
        "or --ink-font /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf on Linux."
    )


def create_pdf(input_docx, output_pdf, ttf_dir=None,
               dpi=200, soffice="soffice", ink_font=None, title="Untitled",
               author=None, subject=None, producer=None):
    """Convert an Evil Font DOCX into a copy-paste-safe PDF that looks identical.

    Hidden (stealth) text is detected structurally -- any font named '<prefix> 0'
    -- so `font_name_in` need not match the doc exactly; it is kept only for CLI
    compatibility. `ttf_dir` is the folder of Evil Font TTFs (e.g.
    output_dir/ttffonts); it is exposed to LibreOffice so the disguise renders.
    If the fonts are already installed system-wide it may be omitted.
    """
    _pdfmetrics.registerFont(_RLTTFont(_INK_FONT, _resolve_ink_font(ink_font)))

    # 1. Read the text to hide (body + header + footer) and the page margins.
    info = _parse_docx_payload(input_docx)
    body_payload, body_visible = info["body"]
    header_payload, _ = info["header"]
    footer_payload, _ = info["footer"]
    top_margin, bottom_margin = info["top_margin"], info["bottom_margin"]
    has_header, has_footer = bool(header_payload), bool(footer_payload)

    # 2. Render the doc for its exact look, and recover the line boxes + a raster
    #    of each page. (Temp dir is cleaned up on exit; the images stay in memory.)
    with tempfile.TemporaryDirectory() as workdir:
        look_pdf = _render_docx_to_pdf(input_docx, ttf_dir, workdir, soffice)
        pages = _visible_lines(look_pdf)
        try:
            images = _convert_from_path(look_pdf, dpi=dpi)
        except _PDFInfoNotInstalledError:
            raise RuntimeError(
                "Could not find poppler's 'pdfinfo'/'pdftoppm' (used by pdf2image "
                "to rasterise the page). On Windows, install poppler and add its "
                "'Library\\bin' folder to PATH -- see "
                "https://github.com/oschwartz10612/poppler-windows -- then open a "
                "new terminal so PATH changes take effect. On Linux/macOS, install "
                "the 'poppler-utils' package."
            ) from None

    # 3. Classify every rendered line as header / body / footer by its y-position
    #    against the margins. Headers/footers sit in the margin bands; everything
    #    between the margins is body.
    page_regions = []
    for page in pages:
        page_height = page["size"][1]
        regions = {"header": [], "body": [], "footer": []}
        for line in page["lines"]:                    # already top -> bottom
            y0 = line["box"][1]
            if has_header and y0 >= page_height - top_margin - _REGION_TOL:
                regions["header"].append(line)
            elif has_footer and y0 <= bottom_margin + _REGION_TOL:
                regions["footer"].append(line)
            else:
                regions["body"].append(line)
        page_regions.append(regions)

    # 4. Map the body payload across all body lines (it flows page to page). A
    #    count mismatch here means the rendered glyphs didn't line up with the
    #    doc's visible chars (unusual layout), so we warn rather than fail.
    body_counts = [line["n"] for regions in page_regions
                   for line in regions["body"]]
    if sum(body_counts) and sum(body_counts) != len(body_visible):
        logger.warning("body glyph/char count mismatch (%d vs %d); copy-layer "
                       "alignment may be approximate for this layout.",
                       sum(body_counts), len(body_visible))
    body_text = _assign_payload(body_payload, body_counts)

    # 5. Assemble each page: the rasterised look underneath, the invisible copy
    #    layer on top, positioned line-by-line.
    pdf = _rl_canvas.Canvas(output_pdf)
    if title:
        pdf.setTitle(title)
    if author:
        pdf.setAuthor(author)
    if subject is None:
        pdf.setAuthor("")
    else:
        pdf.setSubject(subject)
    if producer is None:
        pdf.setProducer("")
    else:
        pdf.setProducer(producer)

    body_index = 0
    for page_number, page in enumerate(pages):
        page_width, page_height = page["size"]
        pdf.setPageSize((page_width, page_height))
        # The full-page image is the visible layer; it carries all formatting and
        # images and, being an image, contributes no selectable text of its own.
        pdf.drawImage(_ImageReader(images[page_number]), 0, 0,
                      width=page_width, height=page_height)
        regions = page_regions[page_number]
        # Header/footer text repeats on every page, so re-place it per page.
        for region_payload, region_lines in (
                (header_payload, regions["header"]),
                (footer_payload, regions["footer"])):
            texts = _assign_payload(region_payload, [ln["n"] for ln in region_lines])
            for line, text in zip(region_lines, texts):
                _draw_invisible(pdf, text, line["box"])
        # Body text is a single stream that continues across page breaks, so we
        # keep a running index into body_text rather than resetting per page.
        for line in regions["body"]:
            _draw_invisible(pdf, body_text[body_index], line["box"])
            body_index += 1
        pdf.showPage()
    pdf.save()
    logger.debug("[DONE] PDF written -> %s (%d page(s), header=%s footer=%s)",
                 output_pdf, len(pages), has_header, has_footer)
    return output_pdf