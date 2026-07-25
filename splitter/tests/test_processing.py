import io

from pypdf import PdfWriter

from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.processing import parse_patterns_field, process


def _pdf(tmp_path, pages=2):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    path = tmp_path / "paczka.pdf"
    with open(path, "wb") as handle:
        writer.write(handle)
    return str(path)


def test_process_dziala_bez_warstwy_http(tmp_path):
    # rdzen nie moze wymagac UploadFile ani petli zdarzen
    settings = SplitterSettings(_env_file=None, ocr_enabled=False)

    result = process(settings, _pdf(tmp_path, pages=3), "paczka.pdf", None)

    assert result.sourceFileName == "paczka.pdf"
    assert result.pageCount == 3
    assert result.documents


def test_process_przyjmuje_wzorce_jako_json(tmp_path):
    settings = SplitterSettings(_env_file=None, ocr_enabled=False)
    patterns = '[{"documentType":"Umowa","header":"UMOWA O PRACE"}]'

    result = process(settings, _pdf(tmp_path), "paczka.pdf", patterns)

    assert result.pageCount == 2


def test_parse_patterns_field_odrzuca_zly_json():
    try:
        parse_patterns_field("{nie-json}")
    except ValueError:
        return
    raise AssertionError("oczekiwano ValueError")


def test_dokument_nie_ma_juz_pola_metadata(tmp_path):
    settings = SplitterSettings(_env_file=None, ocr_enabled=False)

    result = process(settings, _pdf(tmp_path), "paczka.pdf", None)

    assert not hasattr(result.documents[0], "metadata")
