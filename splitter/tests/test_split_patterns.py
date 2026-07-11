import json

import pytest

from webcon_pdf_splitter.api import parse_patterns_field


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
