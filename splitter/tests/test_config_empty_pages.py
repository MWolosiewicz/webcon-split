import logging

from webcon_pdf_splitter.config import (
    SplitterSettings,
    normalize_empty_page_mode,
)


def test_empty_page_mode_defaults_to_keep():
    assert SplitterSettings(_env_file=None).empty_page_mode == "keep"


def test_blank_detection_defaults():
    settings = SplitterSettings(_env_file=None)
    assert settings.empty_page_max_alnum == 0
    assert settings.empty_page_max_share == 0.5
    assert settings.blank_detect_dpi == 60
    assert settings.blank_max_ink_ratio == 0.002
    assert settings.blank_margin_ratio == 0.04


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("SPLITTER_EMPTY_PAGE_MODE", "remove")
    monkeypatch.setenv("SPLITTER_EMPTY_PAGE_MAX_SHARE", "0.3")
    monkeypatch.setenv("SPLITTER_BLANK_MAX_INK_RATIO", "0.005")
    settings = SplitterSettings(_env_file=None)
    assert settings.empty_page_mode == "remove"
    assert settings.empty_page_max_share == 0.3
    assert settings.blank_max_ink_ratio == 0.005


def test_normalize_accepts_known_modes_case_insensitively():
    assert normalize_empty_page_mode("keep") == "keep"
    assert normalize_empty_page_mode("REPORT") == "report"
    assert normalize_empty_page_mode(" remove ") == "remove"


def test_normalize_falls_back_to_keep_with_warning(caplog):
    # literowka w trybie NIE moze wywrocic serwisu - bezpieczny stan wygrywa
    caplog.set_level(logging.WARNING, logger="webcon_pdf_splitter.config")

    assert normalize_empty_page_mode("remoove") == "keep"

    assert any("remoove" in record.getMessage() for record in caplog.records)


def test_drop_empty_pages_setting_is_gone():
    # zastapione przez SPLITTER_EMPTY_PAGE_MODE; stara zmienna w .env jest
    # ignorowana dzieki extra="ignore"
    assert not hasattr(SplitterSettings(_env_file=None), "drop_empty_pages")
