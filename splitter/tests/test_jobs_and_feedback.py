import io

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from webcon_pdf_splitter import api
from webcon_pdf_splitter.api import app
from webcon_pdf_splitter.db.repository import InMemoryFeedbackRepository, InMemoryJobRepository


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_split_records_started_and_finished_job(monkeypatch):
    jobs = InMemoryJobRepository()
    monkeypatch.setattr(api, "build_job_repository", lambda settings: jobs)
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["jobId"] is not None
    assert len(jobs.jobs) == 1
    job = jobs.jobs[0]
    assert job.source_file_name == "scan.pdf"
    assert job.status in ("completed", "requires_review")
    assert job.page_count == 1
    assert job.detected_document_count == 1
    assert job.finished_at is not None


def test_feedback_endpoint_stores_operator_correction(monkeypatch):
    feedback = InMemoryFeedbackRepository()
    monkeypatch.setattr(api, "build_feedback_repository", lambda settings: feedback)
    client = TestClient(app)

    response = client.post(
        "/api/feedback",
        json={
            "webconElementId": 123,
            "pageNumber": 3,
            "systemDocumentType": "Nieznany typ dokumentu",
            "operatorDocumentType": "Aneks do umowy o prace",
            "systemIsFirstPage": False,
            "operatorIsFirstPage": True,
            "operatorLogin": "jan.kowalski",
        },
    )

    assert response.status_code == 200
    assert len(feedback.entries) == 1
    entry = feedback.entries[0]
    assert entry.operator_document_type == "Aneks do umowy o prace"
    assert entry.operator_is_first_page is True
