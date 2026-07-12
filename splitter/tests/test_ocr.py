from webcon_pdf_splitter.ocr import TextLayerWithOcrFallback, alnum_count


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

    assert result[1] == "   "  # OCR nic nie znalazl -> strona zostaje pusta


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
