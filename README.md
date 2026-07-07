# EvilFontTool

> **A font-based deception tool for red teaming, security research, and whatever else.**

EvilFontTool hides machine-readable text inside a document that displays completely different text to a human reader. It does this using **Evil Fonts** — fonts that intentionally deceive the viewer by rendering a different letter than understood by a computer. By remapping font glyphs, the document's visible characters show humans one thing while terminals, AI systems, and clipboard copy paste see another.

## Evil Font Demo !!DON'T MISS THIS!!

**[View the Demo → Here](https://doctoreww.github.io/EvilFontTool/)** *(hosted on GitHub Pages)*

---

## Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [Ethical Use & Disclaimer](#ethical-use--disclaimer)
- [Contributing](#contributing)
- [Help me somethings not working!](#help-me-somethings-not-working)

---

## [How It Works — Blog Post Coming Soon](#)

---

## Installation

```bash
git clone https://github.com/DoctorEww/EvilFontTool.git
cd EvilFontTool
pip install .
```

For development (editable install):

```bash
pip install -e .
```

### Dependencies

Installed automatically via `pip`:
- `fonttools` — font parsing and manipulation
- `brotli` — WOFF2 compression (used by `fonttools`)
- `python-docx` — DOCX generation
- `reportlab` — PDF generation
- `pdf2image` — PDF-to-image conversion
- `pdfminer.six` — PDF text/layout extraction
- `Pillow` — image handling for the PDF pipeline

System requirements (not installed by `pip` — must be on your `PATH`):
- **[poppler-utils](https://poppler.freedesktop.org/)** — required by `pdf2image` to render PDF pages for the `pdf` command
  - Ubuntu/Debian: `sudo apt install poppler-utils`
  - macOS: `brew install poppler`
  - Windows: [poppler for Windows](https://github.com/oschwartz10612/poppler-windows)
- **[LibreOffice](https://www.libreoffice.org/)** — required for the `pdf` command, which shells out to `soffice --headless` to convert DOCX to PDF
  - Ubuntu/Debian: `sudo apt install libreoffice`
  - macOS: `brew install --cask libreoffice`
  - Windows: [download installer](https://www.libreoffice.org/download/)

---
## Where can I find fonts to use?

* Ubuntu: `/usr/share/fonts`
* Windows: `C:\Windows\Fonts`
* https://fonts.google.com/
* The internet??


---

## Usage tips

* Generate fonts and pdf's on Linux. Windows has not been tested. 
* Embed fonts using Word on Windows not LibreOffice on Linux. Install the fonts to the system and then embed them with Word. After significant testing I could not get LibreOffice to embed evil fonts.

## Usage

All functionality is exposed via a single CLI with four subcommands.

### `create` — Generate the font family for use in HTML or DOC files

```bash
evilfonttool create <reference_font> <output_dir> <font_name>
```

| Argument | Description |
|---|---|
| `reference_font` | Path to a `.ttf` or `.woff` source font |
| `output_dir` | Directory to write fonts and CSS into |
| `font_name` | Internal name prefix for the generated font family |

**Example:**
```bash
evilfonttool create fonts/Arial.ttf output/ 'Arial'
```

Outputs:
- `output/fonts/*.woff` — web fonts, one per character
- `output/ttffonts/*.ttf` — TTF fonts for document embedding
- `output/fonts.css` — `@font-face` declarations for web use

---

### `web` — Generate an evil font HTML file

```bash
evilfonttool web <human_file> <computer_file> <output_file>
```

> Requires `fonts.css` and the generated fonts to be in the output directory so the HTML file can use it (or change the path in the HTML file).

| Argument | Description |
|---|---|
| `input_human_file` | Text visible to human readers. Can be multiple lines |
| `input_computer_file` | Text visible to machines / AI. Can be multiple lines |
| `output_file` | Path for the generated HTML file |

**Example:**
```bash
evilfonttool web human.txt computer.txt output/index.html
```

---

### `doc` — Generate a evil font DOCX file

```bash
evilfonttool doc <human_file> <computer_file> <output_file> <font_name> [--author AUTHOR]
```

> The `font_name` must match the name used in the `create` step. The TTF fonts must be installed on the system or embedded in the document. When saving the doc file you can choose in the file -> options -> save to embed the fonts in the file so its portable. 

There is an issue with saving fonts inside LibreOffice. I have only had success in word. If you figure out how to embed the fonts in LibreOffice successfully please make an edit to this readme.

| Argument | Description |
|---|---|
| `input_human_file` | Text visible to human readers. Can be multiple lines |
| `input_computer_file` | Text visible to machines / AI. Can be multiple lines |
| `output_file` | Path for the generated DOCX file |
| `font_name` | Font family name (must match `create` step) |
| `--author` | DOCX document author metadata (default: none) |

**Example:**
```bash
evilfonttool doc human.txt computer.txt output/secret.docx MyFont --author "Finance Team"
```

---

### `pdf` — Convert an Evil Font DOCX into a copy-paste-safe PDF

```bash
evilfonttool pdf <input_docx> <output_file> [--ttf-dir DIR] [--dpi DPI] [--soffice PATH] [--ink-font FONT] [--title TITLE] [--author AUTHOR] [--subject SUBJECT] [--producer PRODUCER]
```

Renders the DOCX with LibreOffice so the PDF looks identical to the document, then overlays the hidden payload as an invisible copy layer so it survives copy-paste in every viewer (including poppler-based ones).

| Argument | Description |
|---|---|
| `input_docx` | Path to the Evil Font DOCX (from the `doc` step) |
| `output_file` | Path for the generated PDF file |
| `--ttf-dir` | Directory of Evil Font TTFs (e.g. `<output_dir>/ttffonts`), exposed to LibreOffice so the disguise renders. Omit only if the fonts are installed system-wide or embedded in the file |
| `--dpi` | Rasterisation quality of the visible layer (default: `200`) |
| `--soffice` | Path to the LibreOffice binary (default: `soffice`) |
| `--ink-font` | TTF for the invisible copy layer (default: a system sans) |
| `--title` | PDF document title metadata (default: `Untitled`) |
| `--author` | PDF document author metadata (default: none) |
| `--subject` | PDF document subject metadata (default: none) |
| `--producer` | PDF document producer metadata (default: none) |

> Requires LibreOffice (`soffice`) and `poppler-utils` — see [Dependencies](#dependencies).

**Example:**
```bash
evilfonttool pdf output/secret.docx output/secret.pdf --ttf-dir output/fonts/ttffonts --title secret
```

---

### Input File Format

- Plain `.txt` files, one sentence or phrase per line
- Each line in `computer_file` must be **equal to or longer** than the corresponding line in `human_file`
- Lines are matched positionally (line 1 to line 1, etc.)

---

## Ethical Use & Disclaimer

**You are responsible for how you use this tool.** Deploying this technique against systems or individuals without explicit authorization is unethical and may be illegal. The authors provide this tool to help defenders understand and test for this class of vulnerability — not to enable attacks.

---

## Contributing

Contributions are welcome. If you've found a new attack surface, an improvement to the font generation pipeline, or a defense technique worth documenting, please open an issue or PR.

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Open a pull request with a clear description of what changed and why


## Help me somethings not working!

This tool is really hard to test due to the complexity of word documents, pdfs,
and fonts. If you find a repeatable issue please open a GitHub issue and I will
get to it as soon as I can.

Please include the following in the issue:
* OS + LibreOffice version, and where you're viewing the file (Word / LibreOffice
  / something else).
* Whether the fonts are **installed**, **embedded**, or neither.
* The exact command you ran and any terminal output (especially `mismatch` warnings).
* A minimal `.docx` / input that reproduces it, if you can share one.
* Anything else that could be causing the issues.