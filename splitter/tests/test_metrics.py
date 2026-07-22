import io
import logging

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from webcon_pdf_splitter import api, metrics
from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.metrics import RequestMetrics
from webcon_pdf_splitter.ocr import TextLayerWithOcrFallback


@pytest.fixture(autouse=True)
def reset_registry():
    metrics.registry.reset()


def _single_blank_page_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_registry_accumulates_requests_and_computes_review_rate():
    metrics.registry.record(
        RequestMetrics(
            pages=10,
            ocr_pages=4,
            llm_calls=2,
            documents=3,
            documents_requiring_review=1,
            duration_seconds=2.5,
        )
    )
    metrics.registry.record(
        RequestMetrics(pages=2, documents=1, duration_seconds=0.5)
    )

    snapshot = metrics.registry.snapshot()

    assert snapshot["split_requests_total"] == 2
    assert snapshot["pages_total"] == 12
    assert snapshot["ocr_pages_total"] == 4
    assert snapshot["llm_calls_total"] == 2
    assert snapshot["documents_total"] == 4
    assert snapshot["documents_requiring_review_total"] == 1
    assert snapshot["review_rate"] == 0.25
    assert snapshot["processing_seconds_total"] == 3.0


def test_review_rate_is_zero_without_documents():
    assert metrics.registry.snapshot()["review_rate"] == 0.0


def test_collector_receives_increments_only_inside_context():
    metrics.add_ocr_pages(5)  # poza zadaniem: no-op, bez bledu
    metrics.add_llm_call()

    with metrics.request_collector() as collected:
        metrics.add_ocr_pages(3)
        metrics.add_llm_call()
        metrics.add_llm_call()

    assert collected.ocr_pages == 3
    assert collected.llm_calls == 2


def test_ocr_composite_reports_filled_pages_to_collector():
    class _FakeTextLayer:
        def extract_page_texts(self, pdf_path):
            return ["Strona pierwsza ma duzo tekstu w warstwie tekstowej", "", ""]

    class _FakePageOcr:
        def ocr_pages(self, pdf_path, page_indices):
            # strona 2 uzupelniona, strona 3 bez poprawy
            return {1: "TEKST Z OCR PO ROZPOZNANIU SKANU", 2: ""}

    composite = TextLayerWithOcrFallback(
        page_ocr=_FakePageOcr(), text_layer=_FakeTextLayer(), min_text_chars=25
    )

    with metrics.request_collector() as collected:
        composite.extract_page_texts("mixed.pdf")

    assert collected.ocr_pages == 1


def test_llm_classifier_counts_calls(monkeypatch):
    import requests

    class _FakeResponse:
        status_code = 200
        ok = True

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"isFirstPage": true, "documentType": "Umowa",'
                            ' "isKnownType": false, "confidence": 0.9}'
                        }
                    }
                ]
            }

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: _FakeResponse())
    from webcon_pdf_splitter.classification.llm import OpenAiCompatibleLlmClassifier

    classifier = OpenAiCompatibleLlmClassifier(endpoint="http://x/v1", model="m")
    with metrics.request_collector() as collected:
        classifier.classify_uncertain_page("tekst", "", "", [], "")

    assert collected.llm_calls == 1


def test_split_updates_metrics_endpoint_and_logs_summary(caplog):
    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.api")
    client = TestClient(api.app)

    response = client.post(
        "/api/split",
        files={"file": ("paczka.pdf", _single_blank_page_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 200

    snapshot = client.get("/metrics").json()
    assert snapshot["split_requests_total"] == 1
    assert snapshot["pages_total"] == 1
    assert snapshot["documents_total"] == 1
    assert snapshot["documents_requiring_review_total"] == 1
    assert snapshot["review_rate"] == 1.0
    assert snapshot["processing_seconds_total"] > 0

    assert any("Metryki zadania" in record.getMessage() for record in caplog.records)


def test_metrics_endpoint_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr(
        api, "get_settings", lambda: SplitterSettings(_env_file=None, api_token="sekret")
    )
    client = TestClient(api.app)

    assert client.get("/metrics").status_code == 401
    assert (
        client.get("/metrics", headers={"Authorization": "Bearer sekret"}).status_code
        == 200
    )
