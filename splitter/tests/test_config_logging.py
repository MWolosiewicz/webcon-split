import logging

from webcon_pdf_splitter import api
from webcon_pdf_splitter.config import SplitterSettings


def test_log_level_defaults_to_info():
    assert SplitterSettings(_env_file=None).log_level == "INFO"


def test_configure_logging_sets_root_level():
    api.configure_logging(SplitterSettings(_env_file=None, log_level="debug"))
    assert logging.getLogger().level == logging.DEBUG

    api.configure_logging(SplitterSettings(_env_file=None))
    assert logging.getLogger().level == logging.INFO


def test_ocr_settings_defaults():
    settings = SplitterSettings(_env_file=None)
    assert settings.ocr_enabled is True
    assert settings.ocr_min_text_chars == 25
    assert settings.ocr_languages == "pol+eng"
    assert settings.ocr_dpi == 300
    assert settings.ocr_timeout_seconds == 30


def test_ocr_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("SPLITTER_OCR_ENABLED", "false")
    monkeypatch.setenv("SPLITTER_OCR_MIN_TEXT_CHARS", "40")
    monkeypatch.setenv("SPLITTER_OCR_LANGUAGES", "pol")
    settings = SplitterSettings(_env_file=None)
    assert settings.ocr_enabled is False
    assert settings.ocr_min_text_chars == 40
    assert settings.ocr_languages == "pol"
