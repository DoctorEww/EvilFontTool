import copy
import logging
import pathlib
import string

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

    with open(input_human_file, "r") as human_file, \
         open(input_computer_file, "r") as computer_file:

        for human_line, computer_line in zip(
            (l.rstrip('\n') for l in human_file),
            (l.rstrip('\n') for l in computer_file),
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
# DOCX output
# ---------------------------------------------------------------------------

def create_doc(input_human_file, input_computer_file, output_file, font_name_in):
    """Build a steganographic DOCX file from human and computer text files.

    Works identically to createhtml() but outputs a Word document. Each run is
    assigned an Evil Font by setting all four font slots (ascii, hAnsi, eastAsia,
    cs) to prevent Word from falling back to a system font.

    The TTF variants of the Evil Fonts must be installed on the system (or
    embedded in the document) for the deception to render correctly in Word.

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

    with open(input_human_file, "r") as human_file, \
         open(input_computer_file, "r") as computer_file:

        for human_line, computer_line in zip(
            (l.rstrip('\n') for l in human_file),
            (l.rstrip('\n') for l in computer_file),
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

            lines_processed += 1
            total_hidden += diff

    doc.save(output_file)
    logger.debug(f"[DONE] DOCX written -> {output_file} ({lines_processed} lines, {total_hidden} hidden chars)")
