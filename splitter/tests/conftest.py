import pytest

from webcon_pdf_splitter import api
from webcon_pdf_splitter.config import SplitterSettings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Tests must never read .env or touch a real database."""
    monkeypatch.setattr(api, "get_settings", lambda: SplitterSettings(_env_file=None))
