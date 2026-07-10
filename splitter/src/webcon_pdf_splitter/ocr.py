from typing import Protocol


class OcrEngine(Protocol):
    def extract_page_texts(self, pdf_path: str) -> list[str]:
        ...


class StubOcrEngine:
    def extract_page_texts(self, pdf_path: str) -> list[str]:
        return ["UMOWA O PRACE"]
