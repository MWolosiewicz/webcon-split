from typing import Protocol


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
