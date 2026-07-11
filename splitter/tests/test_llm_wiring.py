from webcon_pdf_splitter.api import build_llm_classifier
from webcon_pdf_splitter.classification.llm import (
    DisabledLlmClassifier,
    OpenAiCompatibleLlmClassifier,
)
from webcon_pdf_splitter.config import SplitterSettings


def test_llm_disabled_by_default():
    settings = SplitterSettings(_env_file=None)

    assert isinstance(build_llm_classifier(settings), DisabledLlmClassifier)


def test_llm_enabled_with_endpoint_and_model():
    settings = SplitterSettings(
        _env_file=None,
        llm_enabled=True,
        llm_endpoint="http://ollama:11434/v1",
        llm_model="llama3.1:8b",
        llm_timeout_seconds=60,
    )

    classifier = build_llm_classifier(settings)

    assert isinstance(classifier, OpenAiCompatibleLlmClassifier)
    assert classifier._timeout_seconds == 60


def test_llm_flag_without_endpoint_stays_disabled():
    settings = SplitterSettings(_env_file=None, llm_enabled=True, llm_endpoint="", llm_model="x")

    assert isinstance(build_llm_classifier(settings), DisabledLlmClassifier)
