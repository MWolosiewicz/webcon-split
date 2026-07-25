import logging

from webcon_pdf_splitter.processing import _log_page_texts, _preview
from webcon_pdf_splitter.config import SplitterSettings


def _settings(**overrides) -> SplitterSettings:
    return SplitterSettings(_env_file=None, **overrides)


def test_preview_collapses_whitespace_and_truncates_with_ellipsis():
    assert _preview("Umowa\n  o\tprace", 100) == "Umowa o prace"
    assert _preview("ABCDEF", 4) == "ABCD..."
    assert _preview("ABCD", 4) == "ABCD"  # rowne limitowi -> bez wielokropka


def test_logs_raw_and_normalized_fragment_per_page(caplog):
    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.processing")

    _log_page_texts(["Umowa o pracĘ\nzawarta dnia"], _settings())

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert message.startswith("Strona 1:")
    assert 'surowy(1200): "Umowa o pracĘ zawarta dnia"' in message
    assert 'znorm(300): "UMOWA O PRACE ZAWARTA DNIA"' in message


def test_respects_configured_char_limits(caplog):
    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.processing")

    _log_page_texts(
        ["Umowa o prace zawarta dnia"],
        _settings(log_page_text_raw_chars=10, log_page_text_norm_chars=5),
    )

    message = caplog.records[0].getMessage()
    assert 'surowy(10): "Umowa o pr..."' in message
    assert 'znorm(5): "UMOWA..."' in message


def test_empty_page_logged_as_pusta(caplog):
    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.processing")

    _log_page_texts(["Tekst pierwszej strony", "  \n. ,"], _settings())

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert messages[1] == "Strona 2: 0 znakow (pusta)"


def test_disabled_flag_silences_logging(caplog):
    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.processing")

    _log_page_texts(["Umowa o prace"], _settings(log_page_text=False))

    assert caplog.records == []
