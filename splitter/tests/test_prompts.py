import logging

from webcon_pdf_splitter.classification.prompts import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_USER_PROMPT,
    PromptProvider,
    build_context,
)


def _context(**overrides):
    kwargs = {
        "current_text": "tekst aktualnej strony",
        "previous_text": "tekst poprzedniej strony",
        "next_text": "tekst nastepnej strony",
        "known_document_types": ["Swiadectwo pracy", "Umowa o prace"],
        "current_document_type": "Umowa o prace",
    }
    kwargs.update(overrides)
    return build_context(**kwargs)


def test_context_renders_known_types_as_json_array():
    context = _context()

    assert context["znane_typy"] == '["Swiadectwo pracy", "Umowa o prace"]'


def test_context_uses_brak_for_empty_current_document_type():
    context = _context(current_document_type="")

    assert context["typ_biezacego_dokumentu"] == "BRAK"


def test_context_truncates_page_texts():
    context = _context(
        current_text="a" * 5000, previous_text="b" * 3000, next_text="c" * 3000
    )

    assert len(context["aktualna_strona"]) == 4000
    assert len(context["poprzednia_strona"]) == 2000
    assert len(context["nastepna_strona"]) == 2000


def test_default_user_prompt_renders_all_placeholders():
    rendered = PromptProvider().render_user(_context())

    assert "Umowa o prace" in rendered
    assert "tekst aktualnej strony" in rendered
    assert '"isFirstPage"' in rendered  # format_json wstrzykniety


def test_default_user_prompt_has_no_unresolved_placeholders():
    rendered = PromptProvider().render_user(_context())

    # jedyne nawiasy klamrowe pochodza z format_json (przyklad odpowiedzi)
    assert "{znane_typy}" not in rendered
    assert "{typ_biezacego_dokumentu}" not in rendered
    assert "{aktualna_strona}" not in rendered


def test_default_system_prompt_used_without_file():
    rendered = PromptProvider().render_system(_context())

    assert rendered == DEFAULT_SYSTEM_PROMPT


def test_file_template_overrides_default(tmp_path):
    prompt_file = tmp_path / "user.txt"
    prompt_file.write_text("MOJ SZABLON: {aktualna_strona}", encoding="utf-8")
    provider = PromptProvider(user_prompt_file=str(prompt_file))

    rendered = provider.render_user(_context())

    assert rendered == "MOJ SZABLON: tekst aktualnej strony"


def test_file_change_is_picked_up_without_restart(tmp_path, caplog):
    prompt_file = tmp_path / "user.txt"
    prompt_file.write_text("WERSJA 1: {aktualna_strona}", encoding="utf-8")
    provider = PromptProvider(user_prompt_file=str(prompt_file))
    provider.render_user(_context())

    prompt_file.write_text("WERSJA 2: {aktualna_strona}", encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="webcon_pdf_splitter.classification.prompts"):
        rendered = provider.render_user(_context())

    assert rendered.startswith("WERSJA 2")
    assert any("Prompt user z pliku" in r.getMessage() for r in caplog.records)


def test_missing_file_falls_back_to_default_with_warning(tmp_path, caplog):
    provider = PromptProvider(user_prompt_file=str(tmp_path / "nie-ma.txt"))

    with caplog.at_level(logging.WARNING):
        rendered = provider.render_user(_context())

    assert "ZADANIE:" in rendered  # wbudowany prompt
    assert any("Nie mozna odczytac pliku" in r.getMessage() for r in caplog.records)


def test_unknown_placeholder_falls_back_to_default_with_warning(tmp_path, caplog):
    prompt_file = tmp_path / "user.txt"
    prompt_file.write_text("literowka: {aktualna_stron}", encoding="utf-8")
    provider = PromptProvider(user_prompt_file=str(prompt_file))

    with caplog.at_level(logging.WARNING):
        rendered = provider.render_user(_context())

    assert "ZADANIE:" in rendered
    assert any("nieznany placeholder" in r.getMessage() for r in caplog.records)


def test_system_prompt_file_supports_placeholders(tmp_path):
    prompt_file = tmp_path / "system.txt"
    prompt_file.write_text("Znasz typy: {znane_typy}", encoding="utf-8")
    provider = PromptProvider(system_prompt_file=str(prompt_file))

    rendered = provider.render_system(_context())

    assert rendered == 'Znasz typy: ["Swiadectwo pracy", "Umowa o prace"]'
