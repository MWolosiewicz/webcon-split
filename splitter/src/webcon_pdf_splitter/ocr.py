import logging
from typing import Protocol

logger = logging.getLogger(__name__)


def alnum_count(text: str) -> int:
    """Liczba znakow alfanumerycznych (Unicode) w tekscie strony.

    Wspolne zrodlo liczenia dla progu OCR (kompozyt) i bramki pustej
    strony (pipeline). Rozne progi, jeden sposob liczenia.
    """
    return sum(1 for ch in text if ch.isalnum())


class OcrEngine(Protocol):
    def extract_page_texts(self, pdf_path: str) -> list[str]:
        ...


class StubOcrEngine:
    def extract_page_texts(self, pdf_path: str) -> list[str]:
        return ["UMOWA O PRACE"]


class PdfTextOcrEngine:
    """Extracts the embedded text layer page by page.

    Works for born-digital PDFs; scanned bundles need a real OCR engine
    (Tesseract/ABBYY/PaddleOCR) behind the same interface.
    """

    def extract_page_texts(self, pdf_path: str) -> list[str]:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        return [page.extract_text() or "" for page in reader.pages]


class TextLayerWithOcrFallback:
    """Warstwa tekstowa + fallback OCR per strona.

    Czyta osadzony tekst jak PdfTextOcrEngine; dla stron ponizej progu
    `min_text_chars` uruchamia wstrzykniety page-OCR i podmienia tekst.
    OCR nigdy nie wywraca zadania: blad calego wywolania OCR jest lapany,
    dotkniete strony zostaja puste.
    """

    def __init__(self, page_ocr, text_layer=None, min_text_chars: int = 25) -> None:
        self._page_ocr = page_ocr
        self._text_layer = text_layer or PdfTextOcrEngine()
        self._min_text_chars = min_text_chars

    def extract_page_texts(self, pdf_path: str) -> list[str]:
        texts = list(self._text_layer.extract_page_texts(pdf_path))
        empty_indices = [
            index
            for index, text in enumerate(texts)
            if alnum_count(text) < self._min_text_chars
        ]
        if not empty_indices:
            return texts
        try:
            ocr_texts = self._page_ocr.ocr_pages(pdf_path, empty_indices)
        except Exception:
            logger.warning(
                "OCR nie powiodl sie dla stron %s - strony zostaja puste",
                [i + 1 for i in empty_indices],
                exc_info=True,
            )
            return texts
        for index, ocr_text in ocr_texts.items():
            texts[index] = ocr_text
        logger.info(
            "OCR: uzupelniono tekst %s stron (indeksy stron: %s)",
            len(empty_indices),
            [i + 1 for i in empty_indices],
        )
        return texts
