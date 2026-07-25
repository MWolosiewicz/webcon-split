import shutil

import pytest

from webcon_pdf_splitter.ocr import (
    TesseractPageOcr,
    TextLayerWithOcrFallback,
    alnum_count,
)

_TESSERACT_MISSING = shutil.which("tesseract") is None


class _FakeTextLayer:
    def __init__(self, texts):
        self._texts = texts

    def extract_page_texts(self, pdf_path):
        return list(self._texts)


class _FakePageOcr:
    def __init__(self, results):
        self._results = results  # dict[int, str]
        self.calls = []

    def ocr_pages(self, pdf_path, page_indices):
        self.calls.append(list(page_indices))
        return {i: self._results.get(i, "") for i in page_indices}


class _RaisingPageOcr:
    def ocr_pages(self, pdf_path, page_indices):
        raise RuntimeError("tesseract binary missing")


def test_alnum_count_ignores_whitespace_and_punctuation():
    assert alnum_count("   \n\t  ") == 0
    assert alnum_count("... --- ,,, ;") == 0


def test_alnum_count_counts_letters_and_digits():
    # "Umowa 2024" -> U m o w a 2 0 2 4 = 9
    assert alnum_count("Umowa 2024") == 9


def test_alnum_count_counts_polish_letters():
    # str.isalnum() jest swiadome Unicode: polskie litery licza sie
    assert alnum_count("zazolc gesla jazn") == 15
    assert alnum_count("łódź") == 4


def test_keeps_text_layer_and_skips_ocr_when_above_threshold():
    ocr = _FakePageOcr({})
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(
            [
                "Pelna umowa o prace z wieloma slowami w warstwie tekstowej",
                "Druga strona umowy rowniez z obszernym tekstem tutaj",
            ]
        ),
        min_text_chars=25,
    )

    result = composite.extract_page_texts("born-digital.pdf")

    assert result == [
        "Pelna umowa o prace z wieloma slowami w warstwie tekstowej",
        "Druga strona umowy rowniez z obszernym tekstem tutaj",
    ]
    assert ocr.calls == []  # OCR nie wolany dla stron z tekstem


def test_ocrs_only_pages_below_threshold_and_substitutes_text():
    ocr = _FakePageOcr({1: "TEKST Z OCR PO ROZPOZNANIU SKANU"})
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(
            ["Strona pierwsza ma duzo tekstu w warstwie tekstowej", ""]
        ),
        min_text_chars=25,
    )

    result = composite.extract_page_texts("mixed.pdf")

    assert result[0].startswith("Strona pierwsza")
    assert result[1] == "TEKST Z OCR PO ROZPOZNANIU SKANU"
    assert ocr.calls == [[1]]  # OCR tylko dla pustej strony, jednym wywolaniem


def test_page_stays_empty_when_ocr_returns_nothing():
    ocr = _FakePageOcr({1: "   "})
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(
            ["Strona pierwsza ma duzo tekstu w warstwie tekstowej", ""]
        ),
        min_text_chars=25,
    )

    result = composite.extract_page_texts("blank-scan.pdf")

    assert result[1] == ""  # OCR nic nie znalazl -> oryginal (pusty) zachowany


def test_ocr_result_ignored_when_shorter_than_text_layer():
    # strona ma krotki, ale realny tekst warstwy (< prog) -> OCR probuje,
    # ale zwraca mniej znakow -> zachowujemy oryginal (brak utraty danych)
    ocr = _FakePageOcr({0: ""})
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(["Zalacznik nr 3 podpisany"]),  # 21 alnum < 25
        min_text_chars=25,
    )

    result = composite.extract_page_texts("born-digital-short.pdf")

    assert result[0] == "Zalacznik nr 3 podpisany"


def test_logs_pages_where_ocr_did_not_improve_text(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.ocr")
    ocr = _FakePageOcr({0: "", 1: "TEKST Z OCR PO ROZPOZNANIU SKANU"})
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(["Zalacznik nr 3 podpisany", ""]),  # obie < prog
        min_text_chars=25,
    )

    composite.extract_page_texts("mixed.pdf")

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "OCR nie poprawil stron [1] - zachowano tekst warstwy" == message
        for message in messages
    )
    # strona 2 zostala uzupelniona -> raportowana w dotychczasowym wpisie
    assert any("uzupelniono" in message for message in messages)


def test_ocr_failure_does_not_break_extraction():
    composite = TextLayerWithOcrFallback(
        page_ocr=_RaisingPageOcr(),
        text_layer=_FakeTextLayer(
            ["Strona pierwsza ma duzo tekstu w warstwie tekstowej", ""]
        ),
        min_text_chars=25,
    )

    result = composite.extract_page_texts("scan.pdf")

    # brak binarki tesseract -> zadanie przetwarzane dalej, strona pusta
    assert result[0].startswith("Strona pierwsza")
    assert result[1] == ""


def _two_blank_pages_pdf(tmp_path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    pdf_path = tmp_path / "dwie-strony.pdf"
    with open(pdf_path, "wb") as handle:
        writer.write(handle)
    return pdf_path


def test_ocr_pages_run_in_parallel(tmp_path, monkeypatch):
    import threading

    pdf_path = _two_blank_pages_pdf(tmp_path)
    # bariera na 2 watki: jesli OCR stron bylby sekwencyjny, pierwszy wait()
    # przekroczy timeout i test nie przejdzie
    barrier = threading.Barrier(2, timeout=5)

    def fake_ocr_image(self, image):
        barrier.wait()
        return "TEKST Z OCR"

    monkeypatch.setattr(TesseractPageOcr, "_ocr_image", fake_ocr_image)
    engine = TesseractPageOcr(workers=2)

    result = engine.ocr_pages(str(pdf_path), [0, 1])

    assert result == {0: "TEKST Z OCR", 1: "TEKST Z OCR"}


def test_parallel_ocr_error_in_one_page_keeps_other_pages(tmp_path, monkeypatch):
    import threading

    pdf_path = _two_blank_pages_pdf(tmp_path)
    lock = threading.Lock()
    calls = []

    def fake_ocr_image(self, image):
        with lock:
            calls.append(1)
            fail = len(calls) == 1
        if fail:
            raise RuntimeError("tesseract timeout")
        return "TEKST Z OCR"

    monkeypatch.setattr(TesseractPageOcr, "_ocr_image", fake_ocr_image)
    engine = TesseractPageOcr(workers=2)

    result = engine.ocr_pages(str(pdf_path), [0, 1])

    # jedna strona pada -> pusta, druga rozpoznana; zadanie sie nie wywraca
    assert sorted(result.values()) == ["", "TEKST Z OCR"]


@pytest.mark.skipif(_TESSERACT_MISSING, reason="brak binarki tesseract")
def test_tesseract_ocr_recognizes_rendered_text(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (700, 220), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=64)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((30, 70), "UMOWA", fill="black", font=font)
    pdf_path = tmp_path / "scan.pdf"
    image.save(str(pdf_path), "PDF")

    engine = TesseractPageOcr(languages="eng", dpi=200)
    result = engine.ocr_pages(str(pdf_path), [0])

    assert "UMOWA" in result[0].upper()


@pytest.mark.skipif(_TESSERACT_MISSING, reason="brak binarki tesseract")
def test_tesseract_ocr_empty_index_list_returns_empty_dict(tmp_path):
    from PIL import Image

    pdf_path = tmp_path / "scan.pdf"
    Image.new("RGB", (200, 200), "white").save(str(pdf_path), "PDF")

    engine = TesseractPageOcr()
    assert engine.ocr_pages(str(pdf_path), []) == {}


def test_read_pages_returns_text_and_blank_flag():
    from webcon_pdf_splitter.ocr import PageRead, PdfTextOcrEngine

    composite = TextLayerWithOcrFallback(
        page_ocr=_FakePageOcr({}),
        text_layer=_FakeTextLayer(["Pelna umowa o prace z wieloma slowami w warstwie"]),
        min_text_chars=25,
    )

    reads = composite.read_pages("born-digital.pdf")

    assert reads == [
        PageRead(text="Pelna umowa o prace z wieloma slowami w warstwie", blank=False)
    ]
    # nakladka zachowuje dotychczasowy interfejs
    assert composite.extract_page_texts("born-digital.pdf") == [
        "Pelna umowa o prace z wieloma slowami w warstwie"
    ]
    assert PdfTextOcrEngine().read_pages.__name__ == "read_pages"


class _FakeBlankDetector:
    def __init__(self, blank_indices):
        self._blank = set(blank_indices)
        self.calls = []

    def detect_blank_pages(self, pdf_path, page_indices):
        self.calls.append(list(page_indices))
        return {i for i in page_indices if i in self._blank}


def test_visually_blank_page_skips_ocr_and_is_marked():
    ocr = _FakePageOcr({1: "NIE POWINNO ZOSTAC UZYTE", 2: "TEKST Z OCR"})
    detector = _FakeBlankDetector([1])
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(
            ["Pelna umowa o prace z wieloma slowami w warstwie tekstowej", "", ""]
        ),
        min_text_chars=25,
        blank_detector=detector,
    )

    reads = composite.read_pages("scan.pdf")

    # detektor dostal kandydatow (strony ubogie w tekst), OCR tylko niepustych
    assert detector.calls == [[1, 2]]
    assert ocr.calls == [[2]]
    assert reads[1].blank is True
    assert reads[1].text == ""
    # strona z atramentem nadal przechodzi przez OCR i nie jest pusta
    assert reads[2].blank is False
    assert reads[2].text == "TEKST Z OCR"


def test_without_detector_no_page_is_marked_blank():
    composite = TextLayerWithOcrFallback(
        page_ocr=_FakePageOcr({0: ""}),
        text_layer=_FakeTextLayer([""]),
        min_text_chars=25,
    )

    reads = composite.read_pages("scan.pdf")

    assert reads[0].blank is False
