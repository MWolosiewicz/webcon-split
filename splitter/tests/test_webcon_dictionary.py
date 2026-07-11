from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.db.repository import split_phrases


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
