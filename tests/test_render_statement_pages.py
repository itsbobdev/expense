from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from render_statement_pages import parse_pages, render_pdf_pages


def test_parse_pages_supports_single_and_range_selection():
    assert parse_pages("1,3-4", 5) == [0, 2, 3]


def test_render_pdf_pages_creates_pngs_for_hsbc_sample(tmp_path):
    pdf_path = Path(
        r"D:\D drive\GitHub\expense\statements\2025\07\hsbc\hsbc_visa_revolution_6207_2025_07.pdf"
    )

    outputs = render_pdf_pages(pdf_path, pages=[0], output_dir=tmp_path)

    assert len(outputs) == 1
    assert outputs[0].exists()
    assert outputs[0].suffix == ".png"
