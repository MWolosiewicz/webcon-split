from webcon_pdf_splitter.config import SplitterSettings


def test_drop_empty_pages_defaults_true():
    assert SplitterSettings(_env_file=None).drop_empty_pages is True


def test_empty_page_max_alnum_defaults_zero():
    assert SplitterSettings(_env_file=None).empty_page_max_alnum == 0


def test_empty_page_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("SPLITTER_DROP_EMPTY_PAGES", "false")
    monkeypatch.setenv("SPLITTER_EMPTY_PAGE_MAX_ALNUM", "5")
    settings = SplitterSettings(_env_file=None)
    assert settings.drop_empty_pages is False
    assert settings.empty_page_max_alnum == 5
