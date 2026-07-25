from webcon_pdf_splitter.processing import build_llm_classifier
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


def test_prompt_files_from_settings_reach_the_classifier():
    settings = SplitterSettings(
        _env_file=None,
        llm_enabled=True,
        llm_endpoint="http://llm:1234/v1",
        llm_model="model-x",
        llm_prompt_file="/app/prompts/user-prompt.txt",
        llm_system_prompt_file="/app/prompts/system-prompt.txt",
    )

    classifier = build_llm_classifier(settings)

    assert isinstance(classifier, OpenAiCompatibleLlmClassifier)
    assert classifier._prompts._user_prompt_file == "/app/prompts/user-prompt.txt"
    assert classifier._prompts._system_prompt_file == "/app/prompts/system-prompt.txt"


def test_prompt_files_default_to_builtin_prompts():
    settings = SplitterSettings(
        _env_file=None, llm_enabled=True, llm_endpoint="http://llm:1234/v1", llm_model="x"
    )

    classifier = build_llm_classifier(settings)

    assert classifier._prompts._user_prompt_file == ""
    assert classifier._prompts._system_prompt_file == ""
