"""
Render statement PDF pages to PNG files for visual inspection.

This helper is intended for image-based statements such as HSBC, where Codex or
Claude needs page images instead of extractable PDF text.

Usage:
    cd backend && python render_statement_pages.py ../statements/2025/07/hsbc/hsbc_visa_revolution_6207_2025_07.pdf
    cd backend && python render_statement_pages.py ../statements/2025/07/hsbc/hsbc_visa_revolution_6207_2025_07.pdf --pages 1
    cd backend && python render_statement_pages.py ../statements/2025/07/hsbc/hsbc_visa_revolution_6207_2025_07.pdf --output-dir ../tmp/hsbc_preview
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import pypdfium2 as pdfium


def parse_pages(spec: str | None, page_count: int) -> list[int]:
    if spec is None or spec.strip() == "":
        return list(range(page_count))

    selected: set[int] = set()
    for chunk in spec.split(","):
        part = chunk.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start < 1 or end < start:
                raise ValueError(f"Invalid page range: {part}")
            for page_num in range(start, end + 1):
                selected.add(page_num - 1)
        else:
            page_num = int(part)
            if page_num < 1:
                raise ValueError(f"Invalid page number: {part}")
            selected.add(page_num - 1)

    invalid = [idx + 1 for idx in sorted(selected) if idx >= page_count]
    if invalid:
        raise ValueError(f"Page(s) out of range: {', '.join(str(i) for i in invalid)}")

    return sorted(selected)


def render_pdf_pages(
    pdf_path: Path,
    pages: list[int] | None = None,
    output_dir: Path | None = None,
    scale: float = 2.0,
) -> list[Path]:
    pdf_path = pdf_path.resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = pdfium.PdfDocument(str(pdf_path))
    page_indexes = pages or list(range(len(doc)))

    if output_dir is None:
        safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in pdf_path.stem)
        output_dir = Path(tempfile.gettempdir()) / "expense_statement_pages" / safe_stem
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    for page_index in page_indexes:
        page = doc[page_index]
        image = page.render(scale=scale).to_pil()
        out_path = output_dir / f"{pdf_path.stem}_page_{page_index + 1}.png"
        image.save(out_path)
        outputs.append(out_path)

    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render statement PDF pages to PNG for visual inspection.")
    parser.add_argument("pdf_path", help="Path to the PDF statement.")
    parser.add_argument("--pages", help="1-based page selection, e.g. '1' or '1,3-4'. Defaults to all pages.")
    parser.add_argument("--output-dir", help="Optional output directory. Defaults to a temp directory.")
    parser.add_argument("--scale", type=float, default=2.0, help="Render scale multiplier. Default: 2.0")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    pdf_path = Path(args.pdf_path)
    doc = pdfium.PdfDocument(str(pdf_path.resolve()))
    pages = parse_pages(args.pages, len(doc))

    output_dir = Path(args.output_dir) if args.output_dir else None
    outputs = render_pdf_pages(pdf_path, pages=pages, output_dir=output_dir, scale=args.scale)

    print(f"Rendered {len(outputs)} page(s) from {pdf_path.resolve()}")
    for out_path in outputs:
        print(out_path)


if __name__ == "__main__":
    main()
