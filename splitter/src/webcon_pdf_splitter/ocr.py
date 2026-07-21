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
        # Nadpisuj warstwe tekstowa tylko gdy OCR dostarczyl WIECEJ tresci -
        # inaczej krotki, ale realny tekst (albo pusty OCR przy braku binarki)
        # skasowalby oryginal (utrata danych).
        filled = []
        not_improved = []
        for index, ocr_text in ocr_texts.items():
            if alnum_count(ocr_text) > alnum_count(texts[index]):
                texts[index] = ocr_text
                filled.append(index + 1)
            else:
                not_improved.append(index + 1)
        if filled:
            logger.info("OCR: uzupelniono tekst %s stron (strony: %s)", len(filled), filled)
        if not_improved:
            logger.info(
                "OCR nie poprawil stron %s - zachowano tekst warstwy",
                not_improved,
            )
        return texts


class TesseractPageOcr:
    """OCR wybranych stron przez Tesseract (pypdfium2 render -> pytesseract).

    Laduje dokument PDFium raz na wywolanie. Per strona lapie bledy
    (timeout/render/brak binarki) i zwraca pusty tekst dla tej strony,
    aby OCR nigdy nie wywracal calego zadania.
    """

    def __init__(
        self,
        languages: str = "pol+eng",
        dpi: int = 300,
        timeout_seconds: int = 30,
    ) -> None:
        self._languages = languages
        self._dpi = dpi
        self._timeout_seconds = timeout_seconds

    def ocr_pages(self, pdf_path: str, page_indices: list[int]) -> dict[int, str]:
        if not page_indices:
            return {}
        import pypdfium2 as pdfium
        import pytesseract

        results: dict[int, str] = {}
        pdf = pdfium.PdfDocument(pdf_path)
        try:
            for index in page_indices:
                try:
                    page = pdf[index]
                    bitmap = page.render(scale=self._dpi / 72.0)
                    image = bitmap.to_pil()
                    results[index] = pytesseract.image_to_string(
                        image,
                        lang=self._languages,
                        timeout=self._timeout_seconds,
                    )
                except Exception:
                    logger.warning(
                        "OCR strony %s nie powiodl sie - strona pusta",
                        index + 1,
                        exc_info=True,
                    )
                    results[index] = ""
        finally:
            pdf.close()
        return results
