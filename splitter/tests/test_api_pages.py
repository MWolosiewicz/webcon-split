import base64
import io

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from webcon_pdf_splitter import api
from webcon_pdf_splitter.api import app
from webcon_pdf_splitter.config import SplitterSettings


def _pdf_bytes(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _decode_pages(payload) -> int:
    content = base64.b64decode(payload["fileContentBase64"])
    return len(PdfReader(io.BytesIO(content)).pages)


def test_remove_pages_endpoint_drops_pages():
    client = TestClient(app)
    response = client.post(
        "/api/pages/remove",
        data={"pages": "2,4"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(5)), "application/pdf")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageCount"] == 3
    assert _decode_pages(payload) == 3


def test_remove_pages_endpoint_rejects_bad_range():
    client = TestClient(app)
    response = client.post(
        "/api/pages/remove",
        data={"pages": "9-10"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(5)), "application/pdf")},
    )
    assert response.status_code == 400


def test_extract_pages_endpoint_keeps_pages():
    client = TestClient(app)
    response = client.post(
        "/api/pages/extract",
        data={"pages": "2-3"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(6)), "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["pageCount"] == 2


def test_pages_endpoint_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr(
        api, "get_settings", lambda: SplitterSettings(_env_file=None, api_token="sekret")
    )
    client = TestClient(app)
    response = client.post(
        "/api/pages/remove",
        data={"pages": "1"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(2)), "application/pdf")},
    )
    assert response.status_code == 401
