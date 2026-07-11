import io
import json

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from webcon_pdf_splitter import api
from webcon_pdf_splitter.api import app, parse_patterns_field
from webcon_pdf_splitter.db.repository import InMemoryPatternRepository


def test_parse_patterns_field_builds_document_patterns():
    raw = json.dumps(
        [
            {
                "documentType": "Umowa o prace",
                "header": "UMOWA O PRACE",
                "phrases": ["pracodawca", "pracownik"],
                "excludedPhrases": ["aneks"],
                "weight": 1.2,
            }
        ]
    )

    patterns = parse_patterns_field(raw)

    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.document_type == "Umowa o prace"
    assert pattern.header == "UMOWA O PRACE"
    assert pattern.phrases == ["pracodawca", "pracownik"]
    assert pattern.excluded_phrases == ["aneks"]
    assert pattern.weight == 1.2
    assert pattern.active is True


def test_parse_patterns_field_applies_defaults():
    raw = json.dumps([{"documentType": "Typ", "header": "NAGLOWEK"}])

    patterns = parse_patterns_field(raw)

    assert patterns[0].phrases == []
    assert patterns[0].excluded_phrases == []
    assert patterns[0].weight == 1.0


def test_parse_patterns_field_rejects_invalid_json():
    with pytest.raises(ValueError):
        parse_patterns_field("not a json")


def test_parse_patterns_field_rejects_missing_header():
    with pytest.raises(ValueError):
        parse_patterns_field(json.dumps([{"documentType": "Typ"}]))


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class _StubOcr:
    def __init__(self, texts):
        self._texts = texts

    def extract_page_texts(self, path):
        return self._texts


def _umowa_patterns_json() -> str:
    return json.dumps(
        [
            {
                "documentType": "Umowa o prace",
                "header": "UMOWA O PRACE",
                "phrases": ["pracodawca", "pracownik"],
                "weight": 1.2,
            }
        ]
    )


def test_split_uses_patterns_from_request(monkeypatch):
    monkeypatch.setattr(
        api,
        "PdfTextOcrEngine",
        lambda: _StubOcr(["UMOWA O PRACE zawarta pomiedzy pracodawca a pracownikiem"]),
    )
    monkeypatch.setattr(
        api,
        "build_pattern_repository",
        lambda settings: (_ for _ in ()).throw(AssertionError("factory must not be called")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
        data={"patterns": _umowa_patterns_json()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["documents"][0]["documentType"] == "Umowa o prace"


def test_split_without_patterns_falls_back_to_factory(monkeypatch):
    calls = []

    def factory(settings):
        calls.append(settings)
        return InMemoryPatternRepository(patterns=[])

    monkeypatch.setattr(api, "build_pattern_repository", factory)
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert response.json()["documents"][0]["documentType"] == "Nieznany typ dokumentu"


def test_split_rejects_invalid_patterns_json():
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
        data={"patterns": "not a json"},
    )

    assert response.status_code == 400


def test_split_rejects_patterns_with_wrong_schema():
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
        data={"patterns": json.dumps([{"documentType": "Typ"}])},
    )

    assert response.status_code == 400
