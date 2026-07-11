import pytest

from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.db.repository import (
    WebconDictionaryPatternRepository,
    split_phrases,
)


def test_webcon_dictionary_settings_default_to_disabled():
    settings = SplitterSettings(webcon_db_connection_string="", webcon_dict_form_type_id=0)

    assert settings.webcon_db_connection_string == ""
    assert settings.webcon_dict_form_type_id == 0
    assert settings.webcon_dict_col_type_name == ""
    assert settings.webcon_dict_col_type_active == ""
    assert settings.webcon_dict_col_pattern_header == ""
    assert settings.webcon_dict_col_pattern_phrases == ""
    assert settings.webcon_dict_col_pattern_excluded == ""
    assert settings.webcon_dict_col_pattern_weight == ""
    assert settings.webcon_dict_col_pattern_active == ""


def test_webcon_dictionary_settings_accept_values():
    settings = SplitterSettings(
        webcon_db_connection_string="Driver={ODBC Driver 18 for SQL Server};Server=sql;Database=BPS_Content;",
        webcon_dict_form_type_id=123,
        webcon_dict_col_type_name="WFD_AttText1",
    )

    assert settings.webcon_dict_form_type_id == 123
    assert settings.webcon_dict_col_type_name == "WFD_AttText1"


def test_split_phrases_splits_on_semicolons_and_trims():
    assert split_phrases("pracodawca; pracownik ;wynagrodzenie") == [
        "pracodawca",
        "pracownik",
        "wynagrodzenie",
    ]


def test_split_phrases_drops_empty_entries():
    assert split_phrases("bhp;; ; szkolenie okresowe;") == ["bhp", "szkolenie okresowe"]


def test_split_phrases_handles_none_and_empty():
    assert split_phrases(None) == []
    assert split_phrases("") == []
    assert split_phrases("   ") == []


def test_split_phrases_single_phrase_without_semicolon():
    assert split_phrases("rodo") == ["rodo"]


def _webcon_settings(**overrides):
    values = dict(
        webcon_db_connection_string="Driver={ODBC Driver 18 for SQL Server};Server=sql;Database=BPS_Content;",
        webcon_dict_form_type_id=123,
        webcon_dict_col_type_name="WFD_AttText1",
        webcon_dict_col_type_active="WFD_AttBool1",
        webcon_dict_col_pattern_header="DET_Att1",
        webcon_dict_col_pattern_phrases="DET_Att2",
        webcon_dict_col_pattern_excluded="DET_Att3",
        webcon_dict_col_pattern_weight="DET_Value1",
        webcon_dict_col_pattern_active="DET_Bool1",
    )
    values.update(overrides)
    return SplitterSettings(**values)


def test_repository_accepts_complete_mapping():
    WebconDictionaryPatternRepository(_webcon_settings())


def test_repository_rejects_missing_column_mapping():
    with pytest.raises(ValueError) as exc:
        WebconDictionaryPatternRepository(_webcon_settings(webcon_dict_col_pattern_phrases=""))

    assert "SPLITTER_WEBCON_DICT_COL_PATTERN_PHRASES" in str(exc.value)


def test_repository_rejects_invalid_column_identifier():
    with pytest.raises(ValueError) as exc:
        WebconDictionaryPatternRepository(
            _webcon_settings(webcon_dict_col_type_name="WFD_AttText1; DROP TABLE x")
        )

    assert "SPLITTER_WEBCON_DICT_COL_TYPE_NAME" in str(exc.value)


def test_map_rows_builds_document_patterns():
    repository = WebconDictionaryPatternRepository(_webcon_settings())

    patterns = repository._map_rows(
        [
            ("Umowa o prace", "UMOWA O PRACE", "pracodawca; pracownik", "aneks", 1.2),
        ]
    )

    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.document_type == "Umowa o prace"
    assert pattern.header == "UMOWA O PRACE"
    assert pattern.phrases == ["pracodawca", "pracownik"]
    assert pattern.excluded_phrases == ["aneks"]
    assert pattern.weight == 1.2
    assert pattern.active is True


def test_map_rows_defaults_missing_weight_to_one():
    repository = WebconDictionaryPatternRepository(_webcon_settings())

    patterns = repository._map_rows([("Typ", "NAGLOWEK", None, None, None)])

    assert patterns[0].weight == 1.0
    assert patterns[0].phrases == []
    assert patterns[0].excluded_phrases == []


def test_map_rows_skips_rows_with_empty_header():
    repository = WebconDictionaryPatternRepository(_webcon_settings())

    patterns = repository._map_rows(
        [
            ("Typ", None, "fraza", None, 1.0),
            ("Typ", "   ", "fraza", None, 1.0),
            ("Typ", "PRAWIDLOWY", "fraza", None, 1.0),
        ]
    )

    assert len(patterns) == 1
    assert patterns[0].header == "PRAWIDLOWY"
