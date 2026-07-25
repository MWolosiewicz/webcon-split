import base64
import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from webcon_pdf_splitter import api
from webcon_pdf_splitter.api import app
from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.processing import build_blank_detector


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


def test_default_configuration_removes_nothing():
    # REGRESJA INCYDENTU: domyslna konfiguracja (tryb keep) nie moze usunac
    # zadnej strony, nawet gdy caly PDF to biale kartki
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes(3)), "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pageCount"] == 3
    assert all(document["removedPages"] == [] for document in payload["documents"])
    covered = sum(
        document["endPage"] - document["startPage"] + 1
        for document in payload["documents"]
    )
    assert covered == 3


def test_blank_detector_built_from_settings(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SplitterSettings(
            _env_file=None, blank_detect_dpi=72, blank_max_ink_ratio=0.01
        ),
    )

    detector = build_blank_detector(api.get_settings())

    assert detector._dpi == 72
    assert detector._max_ink_ratio == 0.01
