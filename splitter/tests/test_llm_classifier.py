import pytest

from webcon_pdf_splitter.classification import llm as llm_module
from webcon_pdf_splitter.classification.llm import (
    DisabledLlmClassifier,
    LlmClassification,
    OpenAiCompatibleLlmClassifier,
    extract_json_object,
)


def test_disabled_llm_returns_none():
    classifier = DisabledLlmClassifier()

    result = classifier.classify_uncertain_page(
        current_text="ANEKS DO UMOWY",
        previous_text="",
        next_text="",
        known_document_types=["Umowa o prace", "Aneks"],
    )

    assert result is None


def test_llm_classification_requires_valid_confidence():
    result = LlmClassification(
        isFirstPage=True,
        documentType="Aneks",
        isKnownType=True,
        confidence=0.82,
        reasonCodes=["title_indicates_document_type"],
        suggestedNewPatterns=["ANEKS DO UMOWY"],
    )

    assert result.confidence == 0.82
    assert result.isFirstPage is True


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._payload


def _completion(content):
    return {"choices": [{"message": {"content": content}}]}


_VALID_JSON = (
    '{"isFirstPage": true, "documentType": "Wniosek", "isKnownType": false,'
    ' "confidence": 0.9, "reasonCodes": [], "suggestedNewPatterns": []}'
)


def test_extract_json_object_strips_markdown_fences():
    fenced = "```json\n" + _VALID_JSON + "\n```"

    assert extract_json_object(fenced) == _VALID_JSON


def test_extract_json_object_passes_plain_json_through():
    assert extract_json_object(_VALID_JSON) == _VALID_JSON


def test_extract_json_object_rejects_content_without_json():
    with pytest.raises(ValueError):
        extract_json_object("przepraszam, nie moge pomoc")


def test_retries_without_response_format_on_http_400(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json)
        if "response_format" in json:
            return _FakeResponse(400, text="'response_format.type' must be 'json_schema' or 'text'")
        return _FakeResponse(200, payload=_completion("```json\n" + _VALID_JSON + "\n```"))

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    classifier = OpenAiCompatibleLlmClassifier("http://llm:1234/v1", "model-x")

    result = classifier.classify_uncertain_page("tekst", "", "", ["Umowa o prace"])

    assert result is not None
    assert result.isFirstPage is True
    assert result.documentType == "Wniosek"
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


def test_http_error_message_includes_response_body(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(400, text="model not loaded")

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    classifier = OpenAiCompatibleLlmClassifier("http://llm:1234/v1", "model-x")

    with pytest.raises(RuntimeError) as exc:
        classifier.classify_uncertain_page("tekst", "", "", [])

    assert "model not loaded" in str(exc.value)


def test_percent_confidence_is_normalized_to_fraction(monkeypatch):
    content = (
        '{"isFirstPage": true, "documentType": "Wniosek", "isKnownType": false,'
        ' "confidence": 60, "reasonCodes": [], "suggestedNewPatterns": []}'
    )

    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(200, payload=_completion(content))

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    classifier = OpenAiCompatibleLlmClassifier("http://llm:1234/v1", "model-x")

    result = classifier.classify_uncertain_page("tekst", "", "", [])

    assert result is not None
    assert result.confidence == 0.6


def test_null_document_type_becomes_partial_verdict(monkeypatch):
    # bielik potrafi zwrocic documentType=null wbrew promptowi; taki werdykt
    # nie moze decydowac o podziale, ale isFirstPage i sugerowane frazy
    # sa cenne dla operatora i nie moga przepadac
    content = (
        '{"isFirstPage": true, "documentType": null, "isKnownType": false,'
        ' "confidence": 0.0, "reasonCodes": [],'
        ' "suggestedNewPatterns": ["wniosek o dofinansowanie"]}'
    )

    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(200, payload=_completion(content))

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    classifier = OpenAiCompatibleLlmClassifier("http://llm:1234/v1", "model-x")

    result = classifier.classify_uncertain_page("tekst", "", "", [])

    assert result is not None
    assert result.documentType == ""
    assert result.isFirstPage is True
    assert result.suggestedNewPatterns == ["wniosek o dofinansowanie"]


def test_plain_json_response_still_parses(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(200, payload=_completion(_VALID_JSON))

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    classifier = OpenAiCompatibleLlmClassifier("http://llm:1234/v1", "model-x")

    result = classifier.classify_uncertain_page("tekst", "", "", [])

    assert result is not None
    assert result.confidence == 0.9


def _classification(**overrides):
    kwargs = dict(
        isFirstPage=True,
        documentType="Umowa o prace",
        isKnownType=True,
        confidence=0.9,
    )
    kwargs.update(overrides)
    return LlmClassification(**kwargs)


def test_consistent_first_page_verdict_has_no_inconsistencies():
    verdict = _classification()

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="Swiadectwo pracy",
        known_document_types=["Swiadectwo pracy", "Umowa o prace"],
    )

    assert reasons == []


def test_consistent_continuation_verdict_has_no_inconsistencies():
    verdict = _classification(isFirstPage=False, documentType="Umowa o prace")

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="Umowa o prace",
        known_document_types=["Umowa o prace"],
    )

    assert reasons == []


def test_continuation_with_different_type_is_inconsistent():
    verdict = _classification(isFirstPage=False, documentType="Aneks", isKnownType=False)

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="Umowa o prace",
        known_document_types=["Umowa o prace"],
    )

    assert reasons == [
        "kontynuacja z typem 'Aneks' innym niz biezacy 'Umowa o prace'"
    ]


def test_continuation_without_current_document_is_inconsistent():
    verdict = _classification(isFirstPage=False, documentType="", isKnownType=False)

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="", known_document_types=["Umowa o prace"],
    )

    assert reasons == ["kontynuacja bez biezacego dokumentu"]


def test_known_type_outside_known_list_is_inconsistent():
    verdict = _classification(documentType="Zaswiadczenie", isKnownType=True)

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="Umowa o prace",
        known_document_types=["Umowa o prace"],
    )

    assert reasons == [
        "isKnownType=true dla typu 'Zaswiadczenie' spoza znanych typow"
    ]


def test_partial_continuation_of_current_document_is_not_flagged_as_wrong_type():
    # werdykt czesciowy (documentType="") przy istniejacym biezacym dokumencie:
    # regula 1 nie moze go zglaszac (pusty typ to nie "inny typ")
    verdict = _classification(isFirstPage=False, documentType="", isKnownType=False)

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="Umowa o prace",
        known_document_types=["Umowa o prace"],
    )

    assert reasons == []
