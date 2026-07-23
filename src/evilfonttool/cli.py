import argparse
import logging
import os
import sys

from evilfonttool._core import (
    createfonts,
    createstealthfont,
    createhtml,
    create_doc,
    create_pdf,
)

logger = logging.getLogger(__name__)


def setup_parser():
    parser = argparse.ArgumentParser(
        description="EvilFontTool — Evil Font steganography tool for security research.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--log',
        default='WARNING',
        metavar='LEVEL',
        help='Log level: DEBUG, INFO, WARNING, ERROR (default: WARNING).',
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    # --- create ---
    create_parser = subparsers.add_parser(
        'create',
        help='Generate an Evil Font family from a reference font.',
        description=(
            'Produces one font variant per printable character plus a stealth font, '
            'along with a fonts.css file for web use.'
        ),
    )
    create_parser.add_argument('reference_font', help='Path to the source .ttf font file.')
    create_parser.add_argument('output_dir',     help='Directory to write fonts and CSS into.')
    create_parser.add_argument('font_name',      help='Internal name prefix for the font family.')

    # --- web ---
    web_parser = subparsers.add_parser(
        'web',
        help='Generate a steganographic HTML file.',
        description=(
            'Wraps computer-file characters in Evil Font spans so the page displays '
            'human-file text visually while the raw HTML contains the computer text. '
            'fonts.css must be present in the output directory.'
        ),
    )
    web_parser.add_argument('input_human_file',    help='Text visible to human readers.')
    web_parser.add_argument('input_computer_file', help='Text visible to machines / AI.')
    web_parser.add_argument('output_file',         help='Path for the generated HTML file.')

    # --- doc ---
    doc_parser = subparsers.add_parser(
        'doc',
        help='Generate a steganographic DOCX file.',
        description=(
            'Produces a Word document using Evil Fonts so the displayed text differs '
            'from the underlying Unicode. font_name must match the value used in create.'
        ),
    )
    doc_parser.add_argument('input_human_file',    help='Text visible to human readers.')
    doc_parser.add_argument('input_computer_file', help='Text visible to machines / AI.')
    doc_parser.add_argument('output_file',         help='Path for the generated DOCX file.')
    doc_parser.add_argument('font_name',           help='Font family name (must match create step).')
    doc_parser.add_argument('--author', default="anonymous",
                            help='DOCX document author metadata (default: none).')
    doc_parser.add_argument(
        '--ttf-dir',
        help='Directory of Evil Font TTFs (e.g. <output_dir>/ttffonts). If given, '
             'the fonts actually used are embedded directly into the .docx, so '
             'the deception renders correctly without installing them system-wide.'
             'Only embeds letters included in the human file.',
    )

    # --- pdf ---
    pdf_parser = subparsers.add_parser(
        'pdf',
        help='Convert an Evil Font DOCX into a copy-paste-safe PDF.',
        description=(
            'Renders the DOCX with LibreOffice so the PDF looks identical to the '
            'document, then overlays the hidden payload as an invisible copy layer '
            'so it survives copy-paste in every viewer. font_name must match the '
            'value used in create.'
        ),
    )
    pdf_parser.add_argument('input_docx',  help='Path to the Evil Font DOCX (from the doc step).')
    pdf_parser.add_argument('output_file', help='Path for the generated PDF file.')
    # pdf_parser.add_argument('font_name',   help='Font family name (must match create step).')
    pdf_parser.add_argument(
        '--ttf-dir',
        help='Directory of Evil Font TTFs (e.g. <output_dir>/ttffonts). Exposed to '
             'LibreOffice so the disguise renders. Omit only if the fonts are '
             'installed system-wide. Or are embedded in the file.',
    )
    pdf_parser.add_argument('--dpi', type=int, default=200,
                            help='Rasterisation quality of the visible layer (default: 200).')
    pdf_parser.add_argument('--soffice', default='soffice',
                            help="Path to the LibreOffice binary (default: 'soffice').")
    pdf_parser.add_argument('--ink-font', default=None,
                            help='TTF for the invisible copy layer (default: a system sans).')
    pdf_parser.add_argument('--title', default="Untitled",
                            help='PDF document title metadata (default: "Untitled").')
    pdf_parser.add_argument('--author', default=None,
                            help='PDF document author metadata (default: none).')
    pdf_parser.add_argument('--subject', default=None,
                            help='PDF document subject metadata (default: none).')
    pdf_parser.add_argument('--producer', default=None,
                            help='PDF producer metadata (default: none).')

    return parser


def main():
    parser = setup_parser()
    args = parser.parse_args()

    level = getattr(logging, args.log.upper(), None)
    if not isinstance(level, int):
        print(f"Error: invalid log level '{args.log}'. Choose from DEBUG, INFO, WARNING, ERROR.", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(level=level, format='%(message)s', stream=sys.stderr)

    if args.command == 'create':
        if not os.path.isfile(args.reference_font):
            logger.error("'%s' does not exist.", args.reference_font)
            sys.exit(1)

        for subdir in ('', '/fonts', '/ttffonts'):
            os.makedirs(args.output_dir + subdir, exist_ok=True)

        createfonts(args.reference_font, args.output_dir, args.font_name)
        createstealthfont(args.reference_font, args.output_dir, args.font_name)

    elif args.command == 'web':
        for path in (args.input_human_file, args.input_computer_file):
            if not os.path.isfile(path):
                logger.error("'%s' does not exist.", path)
                sys.exit(1)
        createhtml(args.input_human_file, args.input_computer_file, args.output_file)

    elif args.command == 'doc':
        for path in (args.input_human_file, args.input_computer_file):
            if not os.path.isfile(path):
                logger.error("'%s' does not exist.", path)
                sys.exit(1)
        if args.ttf_dir and not os.path.isdir(args.ttf_dir):
            logger.error("'%s' is not a directory.", args.ttf_dir)
            sys.exit(1)
        create_doc(
            args.input_human_file,
            args.input_computer_file,
            args.output_file,
            args.font_name,
            author=args.author,
            ttf_dir=args.ttf_dir,
        )

    elif args.command == 'pdf':
        if not os.path.isfile(args.input_docx):
            logger.error("'%s' does not exist.", args.input_docx)
            sys.exit(1)
        if args.ttf_dir and not os.path.isdir(args.ttf_dir):
            logger.error("'%s' is not a directory.", args.ttf_dir)
            sys.exit(1)
        create_pdf(
            args.input_docx,
            args.output_file,
            ttf_dir=args.ttf_dir,
            dpi=args.dpi,
            soffice=args.soffice,
            ink_font=args.ink_font,
            title=args.title,
            author=args.author,
            subject=args.subject,
            producer=args.producer,
        )