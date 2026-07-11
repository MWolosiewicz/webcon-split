import base64
import io

import pytest
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


def test_split_returns_documents_with_file_content():
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes(2)), "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pageCount"] == 2
    assert len(payload["documents"]) >= 1
    content = base64.b64decode(payload["documents"][0]["fileContentBase64"])
    assert len(PdfReader(io.BytesIO(content)).pages) >= 1


def test_split_rejects_missing_token_when_token_configured(monkeypatch):
    monkeypatch.setattr(
        api, "get_settings", lambda: SplitterSettings(_env_file=None, api_token="sekret")
    )
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes(1)), "application/pdf")},
    )

    assert response.status_code == 401


def test_split_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(
        api, "get_settings", lambda: SplitterSettings(_env_file=None, api_token="sekret")
    )
    client = TestClient(app)

    response = client.post(
        "/api/split",
        headers={"Authorization": "Bearer sekret"},
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes(1)), "application/pdf")},
    )

    assert response.status_code == 200
