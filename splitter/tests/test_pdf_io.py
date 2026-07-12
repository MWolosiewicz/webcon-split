import io

import pytest
from pypdf import PdfReader, PdfWriter

from webcon_pdf_splitter.pdf_io import (
    parse_page_range,
)


def test_parse_page_range_single_and_ranges():
    assert parse_page_range("2-4,7", 10) == [2, 3, 4, 7]


def test_parse_page_range_deduplicates_and_sorts():
    assert parse_page_range("7,2-3,3", 10) == [2, 3, 7]


def test_parse_page_range_rejects_empty():
    with pytest.raises(ValueError):
        parse_page_range("   ", 10)


def test_parse_page_range_rejects_out_of_bounds():
    with pytest.raises(ValueError):
        parse_page_range("5-8", 6)


def test_parse_page_range_rejects_reversed():
    with pytest.raises(ValueError):
        parse_page_range("5-2", 10)


def test_parse_page_range_rejects_garbage():
    with pytest.raises(ValueError):
        parse_page_range("2-x", 10)


def _pdf_path(tmp_path, name, page_count):
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    path = tmp_path / name
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _page_count(pdf_bytes):
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def test_remove_pages_drops_selected(tmp_path):
    from webcon_pdf_splitter.pdf_io import remove_pages

    source = _pdf_path(tmp_path, "src.pdf", 5)
    out = remove_pages(source, [2, 4])
    assert _page_count(out) == 3


def test_remove_pages_rejects_removing_all(tmp_path):
    from webcon_pdf_splitter.pdf_io import remove_pages

    source = _pdf_path(tmp_path, "src.pdf", 2)
    with pytest.raises(ValueError):
        remove_pages(source, [1, 2])


def test_extract_pages_keeps_only_selected(tmp_path):
    from webcon_pdf_splitter.pdf_io import extract_pages

    source = _pdf_path(tmp_path, "src.pdf", 6)
    out = extract_pages(source, [2, 3, 5])
    assert _page_count(out) == 3


def test_merge_pdfs_sums_pages_in_order(tmp_path):
    from webcon_pdf_splitter.pdf_io import merge_pdfs

    a = _pdf_path(tmp_path, "a.pdf", 2)
    b = _pdf_path(tmp_path, "b.pdf", 3)
    out = merge_pdfs([b, a])
    assert _page_count(out) == 5


def test_merge_pdfs_rejects_empty():
    from webcon_pdf_splitter.pdf_io import merge_pdfs

    with pytest.raises(ValueError):
        merge_pdfs([])
