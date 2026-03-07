# EvilFontTool

> **A font-based deception tool for red teaming, security research, and whatever else.**

EvilFontTool hides machine-readable text inside a document that displays completely different text to a human reader. It does this using **Evil Fonts** — fonts that intentionally deceive the viewer by rendering a different letter than understood by a computer. By remapping font glyphs, the document's visible characters show humans one thing while terminals, AI systems, and clipboard copy paste see another.

## Evil Font Demo !!DON'T MISS THIS!!

**[View the Demo → Coming Soon](#)** *(hosted on GitHub Pages)*

---

## Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [Ethical Use & Disclaimer](#ethical-use--disclaimer)
- [Contributing](#contributing)

---

## [How It Works — Blog Post Coming Soon](#)

---

## Installation

### Standard (Ubuntu/Debian)

```bash
git clone https://github.com/DoctorEww/EvilFontTool.git
cd EvilFontTool
pip install fonttools python-docx
```

### Dependencies
- `fonttools` — font parsing and manipulation
- `python-docx` — DOCX generation

---

## Usage

All functionality is exposed via a single CLI with three subcommands.

### `create` — Generate the font family for use in HTML or DOC files

```bash
python evilfonttool.py create <reference_font> <output_dir> <font_name>
```

| Argument | Description |
|---|---|
| `reference_font` | Path to a `.ttf` or `.woff` source font |
| `output_dir` | Directory to write fonts and CSS into |
| `font_name` | Internal name prefix for the generated font family |

**Example:**
```bash
python evilfonttool.py create fonts/Arial.ttf output/ 'Arial'
```

Outputs:
- `output/fonts/*.woff` — web fonts, one per character
- `output/ttffonts/*.ttf` — TTF fonts for document embedding
- `output/fonts.css` — `@font-face` declarations for web use

---

### `web` — Generate an evil font HTML file

```bash
python evilfonttool.py web <human_file> <computer_file> <output_file>
```

> Requires `fonts.css` and the generated fonts to be in the output directory so the HTML file can use it (or change the path in the HTML file).

**Example:**
```bash
python evilfonttool.py web human.txt computer.txt output/index.html
```

---

### `doc` — Generate a evil font DOCX file

```bash
python evilfonttool.py doc <human_file> <computer_file> <output_file> <font_name>
```

> The `font_name` must match the name used in the `create` step. The TTF fonts must be installed on the system or embedded in the document. When saving the doc file you can choose in the file -> options -> save to embed the fonts in the file so its portable. 

**Example:**
```bash
python evilfonttool.py doc human.txt computer.txt output/secret.docx MyFont
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


