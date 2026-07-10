from typing import Protocol


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
