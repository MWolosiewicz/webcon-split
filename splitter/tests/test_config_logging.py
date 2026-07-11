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
