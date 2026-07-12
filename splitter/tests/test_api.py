from fastapi.testclient import TestClient

from webcon_pdf_splitter.api import app


def test_health_endpoint_returns_ok():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_build_ocr_engine_selects_fallback_when_enabled():
    from webcon_pdf_splitter.api import build_ocr_engine
    from webcon_pdf_splitter.config import SplitterSettings
    from webcon_pdf_splitter.ocr import PdfTextOcrEngine, TextLayerWithOcrFallback

    enabled = SplitterSettings(_env_file=None, ocr_enabled=True)
    assert isinstance(build_ocr_engine(enabled), TextLayerWithOcrFallback)

    disabled = SplitterSettings(_env_file=None, ocr_enabled=False)
    assert isinstance(build_ocr_engine(disabled), PdfTextOcrEngine)
