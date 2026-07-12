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
