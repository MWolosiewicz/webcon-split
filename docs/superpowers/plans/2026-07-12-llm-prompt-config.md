# Konfigurowalny prompt LLM + strażnik spójności — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prompt LLM (system + user) ładowany z plików na wolumenie Dockera z hot-reloadem i wbudowanym fallbackiem; klasyfikator dostaje typ bieżącego dokumentu; werdykty wewnętrznie sprzeczne są degradowane do podpowiedzi; nowy prompt + manual placeholderów + skrypt ewaluacyjny na LM Studio.

**Architecture:** Nowy moduł `classification/prompts.py` (szablony, kontekst placeholderów, `PromptProvider` z hot-reloadem i fallbackami) używany przez `OpenAiCompatibleLlmClassifier`. Strażnik spójności to czysta funkcja w `llm.py` ustawiająca pole `inconsistencyReasons` na werdykcie; pipeline bramkuje na tym polu i pokazuje powód odrzucenia w `reviewReasons`. Skrypt ewaluacyjny w `scripts/` używa produkcyjnego klasyfikatora na przypadkach JSON.

**Tech Stack:** Python ≥3.11, FastAPI, Pydantic v2, pytest; bez nowych zależności.

**Spec:** `docs/superpowers/specs/2026-07-12-llm-prompt-config-design.md`

## Global Constraints

- Bez nowych zależności w `pyproject.toml`.
- Teksty trafiające do LLM (prompty) oraz powody rewizji/logi: polski **bez znaków diakrytycznych** (konwencja repo: "pewnosc", "ponizej").
- Żadnych heurystyk wyglądu strony (np. wielkich liter) w kodzie decyzyjnym — strażnik sprawdza wyłącznie logiczną spójność odpowiedzi modelu (feedback użytkownika 2026-07-12).
- `{format_json}` wstrzykiwany z kodu — szablon nie może rozjechać się z walidacją Pydantic.
- Testy uruchamiane z katalogu `splitter/`: `python -m pytest tests/ -v` (pythonpath=src z pyproject).
- Commity: konwencja `feat:`/`docs:`/`test:` + stopka `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Skrypt ewaluacyjny NIE jest częścią pytest (wymaga żywego LM Studio).

---

### Task 1: Moduł szablonów promptu (`prompts.py`)

**Files:**
- Create: `splitter/src/webcon_pdf_splitter/classification/prompts.py`
- Test: `splitter/tests/test_prompts.py`

**Interfaces:**
- Produces:
  - `build_context(current_text: str, previous_text: str, next_text: str, known_document_types: list[str], current_document_type: str) -> dict[str, str]` — klucze: `znane_typy`, `typ_biezacego_dokumentu`, `poprzednia_strona`, `aktualna_strona`, `nastepna_strona`, `format_json`.
  - `PromptProvider(user_prompt_file: str = "", system_prompt_file: str = "")` z metodami `render_system(context: dict[str, str]) -> str` i `render_user(context: dict[str, str]) -> str`.
  - Stałe: `FORMAT_JSON`, `DEFAULT_SYSTEM_PROMPT`, `DEFAULT_USER_PROMPT`.

- [ ] **Step 1: Write the failing tests**

Utwórz `splitter/tests/test_prompts.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webcon_pdf_splitter.classification.prompts'`

- [ ] **Step 3: Write the implementation**

Utwórz `splitter/src/webcon_pdf_splitter/classification/prompts.py`:

```python
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Wstrzykiwany z kodu jako {format_json}, zeby szablon w pliku nie mogl
# rozjechac sie z walidacja Pydantic w LlmClassification.
FORMAT_JSON = (
    '{"isFirstPage": true|false, "documentType": "<nazwa typu dokumentu>", '
    '"isKnownType": true|false, "confidence": <liczba od 0.0 do 1.0>, '
    '"reasonCodes": ["<krotki_kod_powodu>"], "suggestedNewPatterns": ["<fraza>"]}'
)

DEFAULT_SYSTEM_PROMPT = (
    "Jestes klasyfikatorem stron w paczkach zeskanowanych dokumentow HR. "
    "Oceniasz jedna strone na raz. Odpowiadasz wylacznie jednym poprawnym "
    "obiektem JSON, bez markdown i bez zadnego tekstu poza JSON."
)

DEFAULT_USER_PROMPT = """\
ZADANIE: Ustal, czy AKTUALNA_STRONA to pierwsza strona NOWEGO dokumentu,
czy KONTYNUACJA biezacego dokumentu typu "{typ_biezacego_dokumentu}".

WSKAZOWKI:
- Nowy dokument zwykle zaczyna sie od wyraznego tytulu lub naglowka.
  Tytul moze miec rozna forme: pelna nazwa dokumentu, kod lub symbol
  formularza, naglowek firmowy. NIE zakladaj, ze tytul musi byc
  wielkimi literami.
- Nowy dokument czesto dotyczy innej sprawy, innej osoby lub innej daty
  niz poprzednia strona.
- Kontynuacja zwykle: zaczyna sie w polowie zdania, listy lub tabeli;
  kontynuuje watek z POPRZEDNIA_STRONA; zawiera numeracje stron (np. 2/3).
- Sam fakt, ze strona zawiera slowa typowe dla dokumentow HR
  (np. "pracownik", "wynagrodzenie"), NIE oznacza kontynuacji.

ZASADY ODPOWIEDZI:
- Jesli isFirstPage=false, documentType MUSI byc rowny
  "{typ_biezacego_dokumentu}".
- isKnownType=true tylko wtedy, gdy documentType jest DOKLADNIE jedna
  z pozycji ZNANE_TYPY (uzyj identycznej pisowni).
- documentType nigdy nie moze byc null ani pusty. Jesli nie rozpoznajesz
  typu, opisz go wlasnymi slowami, ustaw isKnownType=false i obniz
  confidence.
- confidence to ulamek od 0.0 do 1.0, nie procent.

FORMAT ODPOWIEDZI: {format_json}

ZNANE_TYPY={znane_typy}
TYP_BIEZACEGO_DOKUMENTU={typ_biezacego_dokumentu}
POPRZEDNIA_STRONA={poprzednia_strona}
AKTUALNA_STRONA={aktualna_strona}
NASTEPNA_STRONA={nastepna_strona}
"""


def build_context(
    current_text: str,
    previous_text: str,
    next_text: str,
    known_document_types: list[str],
    current_document_type: str,
) -> dict[str, str]:
    return {
        "znane_typy": json.dumps(known_document_types, ensure_ascii=False),
        "typ_biezacego_dokumentu": current_document_type or "BRAK",
        "poprzednia_strona": previous_text[:2000],
        "aktualna_strona": current_text[:4000],
        "nastepna_strona": next_text[:2000],
        "format_json": FORMAT_JSON,
    }


class PromptProvider:
    """Laduje szablony promptow z plikow przy kazdym renderze (hot-reload).

    Brak pliku, blad odczytu albo nieznany placeholder w szablonie nigdy nie
    wywracaja zadania — zawsze jest fallback na wbudowany prompt.
    """

    def __init__(self, user_prompt_file: str = "", system_prompt_file: str = "") -> None:
        self._user_prompt_file = user_prompt_file
        self._system_prompt_file = system_prompt_file
        self._last_logged: dict[str, str] = {}

    def render_user(self, context: dict[str, str]) -> str:
        return self._render(self._user_prompt_file, DEFAULT_USER_PROMPT, context, "user")

    def render_system(self, context: dict[str, str]) -> str:
        return self._render(
            self._system_prompt_file, DEFAULT_SYSTEM_PROMPT, context, "system"
        )

    def _render(
        self, file_path: str, default_template: str, context: dict[str, str], kind: str
    ) -> str:
        template = self._load(file_path, default_template, kind)
        try:
            return template.format(**context)
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "Szablon %s promptu z pliku '%s' zawiera nieznany placeholder (%s); "
                "uzywam wbudowanego promptu",
                kind,
                file_path,
                exc,
            )
            return default_template.format(**context)

    def _load(self, file_path: str, default_template: str, kind: str) -> str:
        if not file_path:
            return default_template
        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "Nie mozna odczytac pliku %s promptu '%s' (%s); uzywam wbudowanego promptu",
                kind,
                file_path,
                exc,
            )
            return default_template
        if self._last_logged.get(kind) != content:
            self._last_logged[kind] = content
            logger.info(
                "Prompt %s z pliku '%s' (%s znakow)", kind, file_path, len(content)
            )
        return content
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd splitter && python -m pytest tests/test_prompts.py -v`
Expected: PASS (11 testów)

- [ ] **Step 5: Run the whole suite**

Run: `cd splitter && python -m pytest tests/ -q`
Expected: wszystkie zielone (58 dotychczasowych + 11 nowych)

- [ ] **Step 6: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/prompts.py splitter/tests/test_prompts.py
git commit -m "feat: prompt templates with placeholders, hot-reload and builtin fallback"
```

---

### Task 2: Strażnik spójności werdyktów

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/llm.py` (klasa `LlmClassification`, nowa funkcja)
- Test: `splitter/tests/test_llm_classifier.py` (dopisz testy na końcu pliku)

**Interfaces:**
- Consumes: `LlmClassification` (istniejący model Pydantic w `llm.py`).
- Produces:
  - `LlmClassification.inconsistencyReasons: list[str]` (nowe pole, domyślnie `[]`; niepuste = werdykt zdegradowany, nie może decydować o podziale).
  - `find_inconsistencies(classification: LlmClassification, current_document_type: str, known_document_types: list[str]) -> list[str]` — czysta funkcja, zwraca listę powodów niespójności (pusta = werdykt spójny).

- [ ] **Step 1: Write the failing tests**

Dopisz na końcu `splitter/tests/test_llm_classifier.py`:

```python
def _classification(**overrides):
    kwargs = dict(
        isFirstPage=True,
        documentType="Umowa o prace",
        isKnownType=True,
        confidence=0.9,
    )
    kwargs.update(overrides)
    return LlmClassification(**kwargs)


def test_consistent_first_page_verdict_has_no_inconsistencies():
    verdict = _classification()

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="Swiadectwo pracy",
        known_document_types=["Swiadectwo pracy", "Umowa o prace"],
    )

    assert reasons == []


def test_consistent_continuation_verdict_has_no_inconsistencies():
    verdict = _classification(isFirstPage=False, documentType="Umowa o prace")

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="Umowa o prace",
        known_document_types=["Umowa o prace"],
    )

    assert reasons == []


def test_continuation_with_different_type_is_inconsistent():
    verdict = _classification(isFirstPage=False, documentType="Aneks", isKnownType=False)

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="Umowa o prace",
        known_document_types=["Umowa o prace"],
    )

    assert reasons == [
        "kontynuacja z typem 'Aneks' innym niz biezacy 'Umowa o prace'"
    ]


def test_continuation_without_current_document_is_inconsistent():
    verdict = _classification(isFirstPage=False, documentType="", isKnownType=False)

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="", known_document_types=["Umowa o prace"],
    )

    assert reasons == ["kontynuacja bez biezacego dokumentu"]


def test_known_type_outside_known_list_is_inconsistent():
    verdict = _classification(documentType="Zaswiadczenie", isKnownType=True)

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="Umowa o prace",
        known_document_types=["Umowa o prace"],
    )

    assert reasons == [
        "isKnownType=true dla typu 'Zaswiadczenie' spoza znanych typow"
    ]


def test_partial_continuation_of_current_document_is_not_flagged_as_wrong_type():
    # werdykt czesciowy (documentType="") przy istniejacym biezacym dokumencie:
    # regula 1 nie moze go zglaszac (pusty typ to nie "inny typ")
    verdict = _classification(isFirstPage=False, documentType="", isKnownType=False)

    reasons = llm_module.find_inconsistencies(
        verdict, current_document_type="Umowa o prace",
        known_document_types=["Umowa o prace"],
    )

    assert reasons == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_llm_classifier.py -v -k "inconsisten or consistent or partial_continuation"`
Expected: FAIL — `AttributeError: module ... has no attribute 'find_inconsistencies'`

- [ ] **Step 3: Write the implementation**

W `splitter/src/webcon_pdf_splitter/classification/llm.py`:

Do klasy `LlmClassification` dodaj pole (po `suggestedNewPatterns`):

```python
    # niepuste = werdykt odrzucony jako wewnetrznie sprzeczny; nie moze
    # decydowac o podziale, ale tresc trafia do reviewReasons jako podpowiedz
    inconsistencyReasons: list[str] = Field(default_factory=list)
```

Pod definicją `LlmClassification` dodaj funkcję:

```python
def find_inconsistencies(
    classification: LlmClassification,
    current_document_type: str,
    known_document_types: list[str],
) -> list[str]:
    """Wylacznie logiczna spojnosc odpowiedzi modelu - zero heurystyk
    wygladu strony (tytuly, wielkie litery itp.)."""
    reasons: list[str] = []
    if not classification.isFirstPage:
        if not current_document_type:
            reasons.append("kontynuacja bez biezacego dokumentu")
        elif (
            classification.documentType
            and classification.documentType != current_document_type
        ):
            reasons.append(
                f"kontynuacja z typem '{classification.documentType}' "
                f"innym niz biezacy '{current_document_type}'"
            )
    if classification.isKnownType and classification.documentType not in known_document_types:
        reasons.append(
            f"isKnownType=true dla typu '{classification.documentType}' "
            "spoza znanych typow"
        )
    return reasons
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd splitter && python -m pytest tests/test_llm_classifier.py -v`
Expected: PASS (wszystkie, stare i nowe)

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/llm.py splitter/tests/test_llm_classifier.py
git commit -m "feat: consistency guard for LLM verdicts (pure function + verdict field)"
```

---

### Task 3: Typ bieżącego dokumentu w klasyfikatorze + szablony w kliencie

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/llm.py` (protokół, `DisabledLlmClassifier`, `OpenAiCompatibleLlmClassifier`; usunięcie `_build_prompt`)
- Modify: `splitter/src/webcon_pdf_splitter/classification/pipeline.py` (`_try_llm` i jego wywołanie)
- Modify: `splitter/tests/test_pipeline.py` (`_StubLlm`)
- Test: `splitter/tests/test_llm_classifier.py`, `splitter/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `build_context`, `PromptProvider` z Task 1; `find_inconsistencies`, `LlmClassification.inconsistencyReasons` z Task 2.
- Produces:
  - `classify_uncertain_page(current_text, previous_text, next_text, known_document_types, current_document_type: str = "")` — nowy parametr we wszystkich implementacjach protokołu `LlmClassifier` (domyślna wartość `""` utrzymuje zgodność istniejących wywołań pozycyjnych).
  - `OpenAiCompatibleLlmClassifier.__init__(endpoint, model, timeout_seconds=30, prompts: PromptProvider | None = None)` — Task 5 przekazuje tu provider z configu.
  - Werdykt zwracany przez `OpenAiCompatibleLlmClassifier` ma wypełnione `inconsistencyReasons`, gdy strażnik odrzucił.

- [ ] **Step 1: Write the failing tests**

Dopisz na końcu `splitter/tests/test_llm_classifier.py`:

```python
def test_prompt_contains_current_document_type_and_json_known_types(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(200, payload=_completion(_VALID_JSON))

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    classifier = OpenAiCompatibleLlmClassifier("http://llm:1234/v1", "model-x")

    classifier.classify_uncertain_page(
        "tekst strony",
        "poprzednia",
        "nastepna",
        ["Swiadectwo pracy", "Umowa o prace"],
        current_document_type="Umowa o prace",
    )

    user_message = captured["payload"]["messages"][1]["content"]
    assert 'TYP_BIEZACEGO_DOKUMENTU=Umowa o prace' in user_message
    assert 'ZNANE_TYPY=["Swiadectwo pracy", "Umowa o prace"]' in user_message
    assert "NIE zakladaj, ze tytul musi byc" in user_message


def test_custom_prompt_provider_is_used(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(200, payload=_completion(_VALID_JSON))

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    prompt_file = tmp_path / "user.txt"
    prompt_file.write_text("WLASNY SZABLON: {aktualna_strona}", encoding="utf-8")
    from webcon_pdf_splitter.classification.prompts import PromptProvider

    classifier = OpenAiCompatibleLlmClassifier(
        "http://llm:1234/v1",
        "model-x",
        prompts=PromptProvider(user_prompt_file=str(prompt_file)),
    )
    classifier.classify_uncertain_page("tekst strony", "", "", [])

    assert captured["payload"]["messages"][1]["content"] == "WLASNY SZABLON: tekst strony"


def test_inconsistent_verdict_gets_reasons_attached(monkeypatch):
    content = (
        '{"isFirstPage": false, "documentType": "Aneks", "isKnownType": false,'
        ' "confidence": 0.9, "reasonCodes": [], "suggestedNewPatterns": []}'
    )

    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(200, payload=_completion(content))

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    classifier = OpenAiCompatibleLlmClassifier("http://llm:1234/v1", "model-x")

    result = classifier.classify_uncertain_page(
        "tekst", "", "", ["Umowa o prace"], current_document_type="Umowa o prace"
    )

    assert result is not None
    assert result.inconsistencyReasons == [
        "kontynuacja z typem 'Aneks' innym niz biezacy 'Umowa o prace'"
    ]


def test_consistent_verdict_has_empty_inconsistency_reasons(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(200, payload=_completion(_VALID_JSON))

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    classifier = OpenAiCompatibleLlmClassifier("http://llm:1234/v1", "model-x")

    result = classifier.classify_uncertain_page("tekst", "", "", [])

    assert result is not None
    assert result.inconsistencyReasons == []
```

W `splitter/tests/test_pipeline.py` zaktualizuj `_StubLlm` (sygnatura + rejestracja typu):

```python
class _StubLlm:
    def __init__(self, responses=None, error=None):
        self._responses = responses or {}
        self._error = error
        self.calls = []

    def classify_uncertain_page(
        self,
        current_text,
        previous_text,
        next_text,
        known_document_types,
        current_document_type="",
    ):
        self.calls.append(
            {
                "text": current_text,
                "known_types": known_document_types,
                "current_type": current_document_type,
            }
        )
        if self._error is not None:
            raise self._error
        return self._responses.get(current_text)
```

Dopisz na końcu `splitter/tests/test_pipeline.py`:

```python
def test_pipeline_passes_current_document_type_to_llm():
    stub = _StubLlm()
    _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "strona bez zadnych fraz"],
    )

    assert stub.calls == [
        {
            "text": "strona bez zadnych fraz",
            "known_types": ["Swiadectwo pracy", "Umowa o prace"],
            "current_type": "Umowa o prace",
        }
    ]


def test_pipeline_passes_empty_current_type_at_bundle_start():
    stub = _StubLlm()
    _make_pipeline(llm_classifier=stub).split_pages("scan.pdf", ["obca strona"])

    assert stub.calls[0]["current_type"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_llm_classifier.py tests/test_pipeline.py -v`
Expected: FAIL — nowe testy z `current_document_type` (`TypeError: unexpected keyword argument`) oraz asercje o treści promptu.

- [ ] **Step 3: Write the implementation**

W `splitter/src/webcon_pdf_splitter/classification/llm.py`:

1. Dodaj import na górze:

```python
from webcon_pdf_splitter.classification.prompts import PromptProvider, build_context
```

2. W protokole `LlmClassifier` i w `DisabledLlmClassifier` dodaj parametr
   `current_document_type: str = ""` na końcu sygnatury
   `classify_uncertain_page` (ciała bez zmian).

3. `OpenAiCompatibleLlmClassifier.__init__`:

```python
    def __init__(
        self,
        endpoint: str,
        model: str,
        timeout_seconds: int = 30,
        prompts: PromptProvider | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._prompts = prompts or PromptProvider()
```

4. `classify_uncertain_page` — nowa sygnatura i budowa wiadomości; reszta
   (retry 400, parsowanie, normalizacja confidence, obsługa null documentType)
   bez zmian; na końcu strażnik:

```python
    def classify_uncertain_page(
        self,
        current_text: str,
        previous_text: str,
        next_text: str,
        known_document_types: list[str],
        current_document_type: str = "",
    ) -> LlmClassification | None:
        context = build_context(
            current_text=current_text,
            previous_text=previous_text,
            next_text=next_text,
            known_document_types=known_document_types,
            current_document_type=current_document_type,
        )
        payload = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self._prompts.render_system(context)},
                {"role": "user", "content": self._prompts.render_user(context)},
            ],
        }
        # ... (istniejacy kod: url, post, retry przy 400, raise przy !ok,
        #      extract_json_object, obsluga pustego documentType,
        #      normalizacja confidence) ...
        classification = LlmClassification.model_validate(data)
        inconsistencies = find_inconsistencies(
            classification, current_document_type, known_document_types
        )
        if inconsistencies:
            logger.info(
                "Werdykt LLM odrzucony jako niespojny: %s", "; ".join(inconsistencies)
            )
            classification.inconsistencyReasons = inconsistencies
        return classification
```

5. Usuń metodę `_build_prompt` (zastąpiona przez `prompts.py`).

W `splitter/src/webcon_pdf_splitter/classification/pipeline.py`:

1. Wywołanie w `split_pages` (linia `llm = self._try_llm(...)`):

```python
            llm = self._try_llm(page_texts, index, known_types, current)
```

2. `_try_llm`:

```python
    def _try_llm(
        self,
        page_texts: list[str],
        index: int,
        known_types: list[str],
        current: _Segment | None,
    ) -> LlmClassification | None:
        try:
            return self._llm_classifier.classify_uncertain_page(
                current_text=page_texts[index],
                previous_text=page_texts[index - 1] if index > 0 else "",
                next_text=page_texts[index + 1] if index + 1 < len(page_texts) else "",
                known_document_types=known_types,
                current_document_type=(
                    current.document_type if current is not None and current.known else ""
                ),
            )
        except Exception:
            logger.warning("LLM classification failed for page %s", index + 1, exc_info=True)
            return None
```

- [ ] **Step 4: Run the whole suite**

Run: `cd splitter && python -m pytest tests/ -q`
Expected: wszystkie zielone.

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/llm.py splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/tests/test_llm_classifier.py splitter/tests/test_pipeline.py
git commit -m "feat: pass current document type to LLM and render prompts from templates"
```

---

### Task 4: Bramka pipeline na werdyktach niespójnych + powody rewizji

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/pipeline.py` (bramka decyzyjna, `_unmatched_details`)
- Test: `splitter/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `LlmClassification.inconsistencyReasons` z Task 2.
- Produces: powód rewizji z prefiksem `werdykt LLM odrzucony jako niespojny (<powody>); ` przed dotychczasowym opisem propozycji LLM.

- [ ] **Step 1: Write the failing tests**

Dopisz na końcu `splitter/tests/test_pipeline.py`:

```python
def test_inconsistent_llm_verdict_never_decides_split():
    # halucynacja: model twierdzi, ze zna typ spoza slownika, z wysoka pewnoscia
    stub = _StubLlm(
        responses={
            "strona bez zadnych fraz": LlmClassification(
                isFirstPage=True,
                documentType="Zaswiadczenie o zatrudnieniu",
                isKnownType=True,
                confidence=0.95,
                inconsistencyReasons=[
                    "isKnownType=true dla typu 'Zaswiadczenie o zatrudnieniu' "
                    "spoza znanych typow"
                ],
            )
        }
    )
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "strona bez zadnych fraz"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]
    assert result.documents[0].requiresReview is True


def test_review_reasons_include_inconsistency_note():
    stub = _StubLlm(
        responses={
            "strona bez zadnych fraz": LlmClassification(
                isFirstPage=True,
                documentType="Zaswiadczenie o zatrudnieniu",
                isKnownType=True,
                confidence=0.95,
                inconsistencyReasons=[
                    "isKnownType=true dla typu 'Zaswiadczenie o zatrudnieniu' "
                    "spoza znanych typow"
                ],
            )
        }
    )
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "strona bez zadnych fraz"],
    )

    doc = result.documents[0]
    assert doc.reviewReasons == [
        "strona 2 doklejona bez dopasowania do wzorca "
        "(zadna fraza nie pasuje; werdykt LLM odrzucony jako niespojny "
        "(isKnownType=true dla typu 'Zaswiadczenie o zatrudnieniu' spoza "
        "znanych typow); LLM proponuje typ: 'Zaswiadczenie o zatrudnieniu' "
        "(pewnosc 0.95))"
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_pipeline.py -v -k inconsistent`
Expected: FAIL — pierwszy test tworzy dziś segment `Zaswiadczenie o zatrudnieniu` (bramka nie sprawdza `inconsistencyReasons`).

- [ ] **Step 3: Write the implementation**

W `splitter/src/webcon_pdf_splitter/classification/pipeline.py`:

1. Bramka decyzyjna (dziś: `if llm is not None and llm.documentType and llm.confidence >= ...`):

```python
            if (
                llm is not None
                and llm.documentType
                and not llm.inconsistencyReasons
                and llm.confidence >= self._min_review_confidence
            ):
```

2. W `_unmatched_details`, w gałęzi `if page.llm is not None:` — po zbudowaniu
   `detail` (wraz z doklejeniem sugerowanych fraz), a przed `parts.append(detail)`:

```python
            if page.llm.inconsistencyReasons:
                detail = (
                    "werdykt LLM odrzucony jako niespojny ("
                    + "; ".join(page.llm.inconsistencyReasons)
                    + "); "
                    + detail
                )
```

- [ ] **Step 4: Run the whole suite**

Run: `cd splitter && python -m pytest tests/ -q`
Expected: wszystkie zielone.

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/tests/test_pipeline.py
git commit -m "feat: gate pipeline on verdict consistency and surface rejection in review reasons"
```

---

### Task 5: Konfiguracja plików promptów + wiring w API

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/config.py`
- Modify: `splitter/src/webcon_pdf_splitter/api.py` (`build_llm_classifier`)
- Test: `splitter/tests/test_llm_wiring.py`

**Interfaces:**
- Consumes: `PromptProvider` z Task 1; `OpenAiCompatibleLlmClassifier(..., prompts=...)` z Task 3.
- Produces: `SplitterSettings.llm_prompt_file: str` i `SplitterSettings.llm_system_prompt_file: str` (env: `SPLITTER_LLM_PROMPT_FILE`, `SPLITTER_LLM_SYSTEM_PROMPT_FILE`, domyślnie `""`).

- [ ] **Step 1: Write the failing test**

Dopisz na końcu `splitter/tests/test_llm_wiring.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_llm_wiring.py -v`
Expected: FAIL — `ValidationError`/`AttributeError` (brak pól w settings, brak `_prompts` przekazanego z configu).

- [ ] **Step 3: Write the implementation**

W `splitter/src/webcon_pdf_splitter/config.py` dodaj po `llm_timeout_seconds`:

```python
    llm_prompt_file: str = Field(default="")
    llm_system_prompt_file: str = Field(default="")
```

W `splitter/src/webcon_pdf_splitter/api.py`:

1. Import:

```python
from webcon_pdf_splitter.classification.prompts import PromptProvider
```

2. `build_llm_classifier`:

```python
def build_llm_classifier(settings: SplitterSettings) -> LlmClassifier:
    if settings.llm_enabled and settings.llm_endpoint and settings.llm_model:
        return OpenAiCompatibleLlmClassifier(
            endpoint=settings.llm_endpoint,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            prompts=PromptProvider(
                user_prompt_file=settings.llm_prompt_file,
                system_prompt_file=settings.llm_system_prompt_file,
            ),
        )
    return DisabledLlmClassifier()
```

- [ ] **Step 4: Run the whole suite**

Run: `cd splitter && python -m pytest tests/ -q`
Expected: wszystkie zielone.

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/config.py splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_llm_wiring.py
git commit -m "feat: SPLITTER_LLM_PROMPT_FILE and SPLITTER_LLM_SYSTEM_PROMPT_FILE settings"
```

---

### Task 6: Manual placeholderów, przykłady, docker-compose, docs wdrożeniowe

**Files:**
- Create: `splitter/docs/llm-prompt.md`
- Create: `splitter/examples/prompts/user-prompt.txt`
- Create: `splitter/examples/prompts/system-prompt.txt`
- Modify: `splitter/docker-compose.yml`
- Modify: `docs/deployment/splitter-service.md`

**Interfaces:**
- Consumes: treść `DEFAULT_USER_PROMPT` / `DEFAULT_SYSTEM_PROMPT` z Task 1 (pliki przykładowe = dokładnie ta treść).

- [ ] **Step 1: Utwórz pliki przykładowe**

`splitter/examples/prompts/system-prompt.txt` — dokładnie treść
`DEFAULT_SYSTEM_PROMPT` (jedna linia, bez placeholderów):

```
Jestes klasyfikatorem stron w paczkach zeskanowanych dokumentow HR. Oceniasz jedna strone na raz. Odpowiadasz wylacznie jednym poprawnym obiektem JSON, bez markdown i bez zadnego tekstu poza JSON.
```

`splitter/examples/prompts/user-prompt.txt` — dokładnie treść
`DEFAULT_USER_PROMPT` z Task 1 (od `ZADANIE:` do `NASTEPNA_STRONA={nastepna_strona}`,
skopiuj 1:1 z `prompts.py`, bez cudzysłowów Pythona).

- [ ] **Step 2: Napisz manual**

Utwórz `splitter/docs/llm-prompt.md`:

````markdown
# Konfiguracja promptu LLM

Prompt, ktorym splitter odpytuje lokalny LLM o strony nierozpoznane przez
reguly, mozna podmienic bez przebudowy obrazu. Sluza do tego dwa szablony:
user prompt (tresc zadania) i system prompt (rola modelu).

## Zmienne srodowiskowe

| Zmienna | Opis |
|---|---|
| `SPLITTER_LLM_PROMPT_FILE` | Sciezka do pliku szablonu user promptu |
| `SPLITTER_LLM_SYSTEM_PROMPT_FILE` | Sciezka do pliku szablonu system promptu |

Obie sa opcjonalne i domyslnie puste — wtedy dziala prompt wbudowany w kod
(identyczny z plikami w `examples/prompts/`).

## Placeholdery

W szablonach uzywasz placeholderow w formacie `{nazwa}`:

| Placeholder | Za co odpowiada |
|---|---|
| `{znane_typy}` | Nazwy typow dokumentow ze slownika WEBCON (kolumna DocumentType zrodla danych, przysylane w polu `patterns` kazdego zadania `/api/split`), bez duplikatow, posortowane alfabetycznie, jako tablica JSON, np. `["Aneks do umowy", "Umowa o prace"]`. Tylko nazwy — bez fraz i wag. Punkt odniesienia dla `isKnownType` |
| `{typ_biezacego_dokumentu}` | Typ dokumentu, ktorego kontynuacja moglaby byc oceniana strona; `BRAK`, gdy nie ma poprzednika (poczatek paczki albo segment nieznany) |
| `{poprzednia_strona}` | Tekst poprzedniej strony (obciety do 2000 znakow) |
| `{aktualna_strona}` | Tekst ocenianej strony (obciety do 4000 znakow) |
| `{nastepna_strona}` | Tekst nastepnej strony (obciety do 2000 znakow) |
| `{format_json}` | Wymagany format odpowiedzi JSON — wstrzykiwany z kodu, zeby szablon nie mogl rozjechac sie z walidacja odpowiedzi |

Placeholdery dzialaja w obu szablonach (w system prompcie zwykle przydaje
sie najwyzej `{znane_typy}`).

Zasady:

- Literalny nawias klamrowy w szablonie zapisuj podwojnie: `{{` i `}}`.
- Nieznany placeholder (np. literowka `{aktualna_stron}`) nie wywraca
  zadania: serwis loguje WARNING i uzywa wbudowanego promptu.
- Brakujacy/nieczytelny plik: WARNING + wbudowany prompt.

## Hot-reload

Pliki sa czytane przy kazdym zadaniu. Edycja pliku na wolumenie dziala od
nastepnego splitu — bez restartu kontenera. Kazda zmiana tresci jest
logowana na poziomie INFO ("Prompt user z pliku '...' (N znakow)").

## Wdrozenie w Dockerze

1. Obok `docker-compose.yml` utworz katalog `prompts/`.
2. Skopiuj do niego pliki startowe:
   `cp examples/prompts/user-prompt.txt examples/prompts/system-prompt.txt prompts/`
3. W `.env` dopisz sciezki **z perspektywy kontenera** (nie hosta!):

   ```
   SPLITTER_LLM_PROMPT_FILE=/app/prompts/user-prompt.txt
   SPLITTER_LLM_SYSTEM_PROMPT_FILE=/app/prompts/system-prompt.txt
   ```

4. W `docker-compose.yml` odkomentuj sekcje `volumes` montujaca
   `./prompts:/app/prompts`.
5. Raz uruchom `docker compose up -d`. Od tego momentu edycja plikow
   w `prompts/` dziala bez restartu.

## Iteracja tresci promptu

Do porownywania wariantow promptu sluzy skrypt ewaluacyjny
`scripts/llm_eval.py` (syntetyczne przypadki, wymaga zywego endpointu LLM):

```bash
python scripts/llm_eval.py --endpoint http://192.168.1.147:1234/v1 --model qwen2.5-7b-instruct-1m
python scripts/llm_eval.py --prompt-file prompts/user-prompt.txt   # wariant z pliku
```
````

- [ ] **Step 3: Odkomentowana-gotowa sekcja wolumenu w compose**

W `splitter/docker-compose.yml`, po bloku `env_file:`, dodaj:

```yaml
    # Szablony promptow LLM z hosta (opcjonalne) - patrz docs/llm-prompt.md.
    # Po odkomentowaniu ustaw w .env:
    #   SPLITTER_LLM_PROMPT_FILE=/app/prompts/user-prompt.txt
    #   SPLITTER_LLM_SYSTEM_PROMPT_FILE=/app/prompts/system-prompt.txt
    # volumes:
    #   - ./prompts:/app/prompts
```

- [ ] **Step 4: Uzupełnij docs wdrożeniowe**

W `docs/deployment/splitter-service.md`:

1. Do tabeli zmiennych środowiskowych dodaj dwa wiersze (po
   `SPLITTER_LLM_ENDPOINT, SPLITTER_LLM_MODEL`):

```markdown
| `SPLITTER_LLM_PROMPT_FILE` | nie | Plik szablonu user promptu LLM (wolumen); pusty = prompt wbudowany. Patrz `splitter/docs/llm-prompt.md` |
| `SPLITTER_LLM_SYSTEM_PROMPT_FILE` | nie | Plik szablonu system promptu LLM (wolumen); pusty = prompt wbudowany |
```

2. Na końcu sekcji "Lokalny LLM (opcjonalny)" dodaj akapit:

```markdown
Tresc promptu (system + user) mozna podmienic plikami na wolumenie bez
przebudowy obrazu — instrukcja krok po kroku i lista placeholderow:
`splitter/docs/llm-prompt.md`.
```

- [ ] **Step 5: Weryfikacja**

Run: `cd splitter && docker compose config -q`
Expected: brak błędów (poprawny YAML). Jeśli Docker niedostępny w środowisku:
`python -c "import yaml,io;yaml.safe_load(open('docker-compose.yml',encoding='utf-8'))"`
(jeśli brak PyYAML, wystarczy wizualna kontrola wcięć — sekcja jest w całości komentarzem).

Run: `cd splitter && python -m pytest tests/ -q`
Expected: wszystkie zielone (nic w kodzie się nie zmieniło).

- [ ] **Step 6: Commit**

```bash
git add splitter/docs/llm-prompt.md splitter/examples/prompts/ splitter/docker-compose.yml docs/deployment/splitter-service.md
git commit -m "docs: LLM prompt template manual, example templates and compose volume"
```

---

### Task 7: Skrypt ewaluacyjny + syntetyczne przypadki

**Files:**
- Create: `splitter/scripts/llm_eval.py`
- Create: `splitter/scripts/eval_cases/*.json` (12 plików, treści niżej)
- Create: `splitter/scripts/prompts_baseline/user-prompt.txt` (stary prompt do porównań przed/po)

**Interfaces:**
- Consumes: `OpenAiCompatibleLlmClassifier` (Task 3, sygnatura z `current_document_type`), `PromptProvider` (Task 1).

- [ ] **Step 1: Zapisz stary prompt jako baseline**

Utwórz `splitter/scripts/prompts_baseline/user-prompt.txt` — treść dokładnie
odtwarza usunięty `_build_prompt` (do uruchamiania porównania "przed"):

```
Ustal, czy AKTUALNA_STRONA jest pierwsza strona nowego dokumentu HR, czy kontynuacja poprzedniego dokumentu. Zwroc TYLKO jeden obiekt JSON, bez zadnego innego tekstu, dokladnie w formacie: {format_json}. Jesli typ pasuje do ktoregos ze ZNANE_TYPY, uzyj dokladnie tej nazwy i ustaw isKnownType=true. documentType nigdy nie moze byc null.

ZNANE_TYPY={znane_typy}

POPRZEDNIA_STRONA={poprzednia_strona}

AKTUALNA_STRONA={aktualna_strona}

NASTEPNA_STRONA={nastepna_strona}
```

- [ ] **Step 2: Utwórz przypadki testowe**

Wspólna konwencja: `znane_typy` = `["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"]`
o ile przypadek nie mówi inaczej. Utwórz 12 plików w `splitter/scripts/eval_cases/`:

`01-tytul-wielkimi-literami.json`:

```json
{
  "id": "tytul-wielkimi-literami",
  "opis": "Nowy dokument znanego typu, tytul wielkimi literami",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Umowa o prace",
  "poprzednia_strona": "W sprawach nieuregulowanych stosuje sie przepisy Kodeksu pracy. Umowe sporzadzono w dwoch egzemplarzach. Podpis pracodawcy: Jan Kowalski. Podpis pracownika: Adam Nowak.",
  "aktualna_strona": "SWIADECTWO PRACY\n1. Stwierdza sie, ze Pan Adam Nowak, urodzony 12.05.1988, byl zatrudniony w ACME Sp. z o.o. w okresie od 01.02.2020 do 31.05.2026 w pelnym wymiarze czasu pracy.",
  "nastepna_strona": "4. Stosunek pracy ustal w wyniku rozwiazania umowy za porozumieniem stron. 5. Wykorzystano urlop wypoczynkowy w wymiarze 12 dni.",
  "oczekiwane": { "isFirstPage": true, "documentType": "Swiadectwo pracy", "isKnownType": true }
}
```

`02-tytul-normalna-pisownia.json`:

```json
{
  "id": "tytul-normalna-pisownia",
  "opis": "Nowy dokument znanego typu, tytul zwykla pisownia (nie wielkimi literami)",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Swiadectwo pracy",
  "poprzednia_strona": "Pouczenie: pracownik moze w ciagu 14 dni wystapic o sprostowanie swiadectwa pracy. Data i podpis: 31.05.2026, Anna Wisniewska.",
  "aktualna_strona": "Umowa o prace\nzawarta w dniu 1 czerwca 2026 r. w Warszawie pomiedzy ACME Sp. z o.o., zwana dalej Pracodawca, a Panem Piotrem Zielinskim, zwanym dalej Pracownikiem.",
  "nastepna_strona": "2. Wynagrodzenie zasadnicze wynosi 9 200 zl brutto miesiecznie, platne do 10. dnia nastepnego miesiaca.",
  "oczekiwane": { "isFirstPage": true, "documentType": "Umowa o prace", "isKnownType": true }
}
```

`03-kod-formularza-w-naglowku.json`:

```json
{
  "id": "kod-formularza-w-naglowku",
  "opis": "Nowy dokument nieznanego typu rozpoznawalny po kodzie formularza w naglowku",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Umowa o prace",
  "poprzednia_strona": "Umowe sporzadzono w dwoch jednobrzmiacych egzemplarzach, po jednym dla kazdej ze stron. Podpisy stron.",
  "aktualna_strona": "KW-3/2026\nKarta obiegowa pracownika\nImie i nazwisko: Adam Nowak\nDzial: Ksiegowosc\nData rozpoczecia obiegu: 02.06.2026\nPotwierdzenia dzialow: IT [ ], Kadry [ ], Magazyn [ ]",
  "nastepna_strona": "Uwagi dzialow: brak zastrzezen. Podpis kierownika dzialu kadr.",
  "oczekiwane": { "isFirstPage": true, "isKnownType": false }
}
```

`04-naglowek-firmowy.json`:

```json
{
  "id": "naglowek-firmowy",
  "opis": "Nowy dokument nieznanego typu zaczynajacy sie naglowkiem firmowym",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Umowa o prace",
  "poprzednia_strona": "W sprawach nieuregulowanych stosuje sie Kodeks pracy. Podpis pracodawcy, podpis pracownika.",
  "aktualna_strona": "ACME Sp. z o.o., ul. Prosta 1, 00-001 Warszawa, NIP 525-000-11-22\nZaswiadczenie o zatrudnieniu i wynagrodzeniu\nNiniejszym zaswiadcza sie, ze Pan Adam Nowak jest zatrudniony w naszej firmie od 01.02.2020 na stanowisku ksiegowego.",
  "nastepna_strona": "Srednie miesieczne wynagrodzenie z ostatnich 3 miesiecy wynosi 8 750 zl brutto. Zaswiadczenie wydaje sie na prosbe pracownika.",
  "oczekiwane": { "isFirstPage": true, "isKnownType": false }
}
```

`05-kontynuacja-srodek-zdania.json`:

```json
{
  "id": "kontynuacja-srodek-zdania",
  "opis": "Kontynuacja zaczynajaca sie w polowie zdania",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Umowa o prace",
  "poprzednia_strona": "UMOWA O PRACE zawarta 1 czerwca 2026 r. pomiedzy ACME Sp. z o.o. a Piotrem Zielinskim. 1. Pracodawca zatrudnia Pracownika na stanowisku analityka. 2. Wynagrodzenie zasadnicze,",
  "aktualna_strona": "ktore strony ustalily w drodze negocjacji, wynosi 8 500 zl brutto miesiecznie i jest platne do 10. dnia kazdego miesiaca na rachunek bankowy wskazany przez Pracownika.",
  "nastepna_strona": "3. Wymiar czasu pracy: pelny etat. 4. Miejsce wykonywania pracy: Warszawa.",
  "oczekiwane": { "isFirstPage": false, "documentType": "Umowa o prace" }
}
```

`06-kontynuacja-tabela.json`:

```json
{
  "id": "kontynuacja-tabela",
  "opis": "Kontynuacja - dalszy ciag tabeli z poprzedniej strony",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Swiadectwo pracy",
  "poprzednia_strona": "SWIADECTWO PRACY. Okresy zatrudnienia:\n| Od | Do | Stanowisko |\n| 01.02.2020 | 31.12.2022 | Mlodszy ksiegowy |",
  "aktualna_strona": "| 01.01.2023 | 31.05.2026 | Ksiegowy |\n| - | - | - |\nLacznie: 6 lat i 4 miesiace zatrudnienia.",
  "nastepna_strona": "Pouczenie o mozliwosci sprostowania swiadectwa w terminie 14 dni.",
  "oczekiwane": { "isFirstPage": false, "documentType": "Swiadectwo pracy" }
}
```

`07-kontynuacja-numeracja.json`:

```json
{
  "id": "kontynuacja-numeracja",
  "opis": "Kontynuacja z widoczna numeracja stron",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Umowa o prace",
  "poprzednia_strona": "UMOWA O PRACE. 1. Strony umowy. 2. Rodzaj pracy: specjalista ds. logistyki.\nStrona 1/3",
  "aktualna_strona": "5. Pracownikowi przysluguje urlop zgodnie z Kodeksem pracy. 6. Okres wypowiedzenia wynosi jeden miesiac.\nStrona 2/3",
  "nastepna_strona": "7. Umowa wchodzi w zycie z dniem podpisania. Podpisy stron.\nStrona 3/3",
  "oczekiwane": { "isFirstPage": false, "documentType": "Umowa o prace" }
}
```

`08-kontynuacja-bez-fraz.json`:

```json
{
  "id": "kontynuacja-bez-fraz",
  "opis": "Kontynuacja bez zadnej frazy typu - tylko formuly koncowe i podpisy",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Aneks do umowy",
  "poprzednia_strona": "ANEKS DO UMOWY O PRACE z dnia 01.02.2020. Strony zgodnie postanawiaja, ze od 01.07.2026 wynagrodzenie zasadnicze ulega podwyzszeniu do kwoty 9 800 zl brutto.",
  "aktualna_strona": "Pozostale postanowienia pozostaja bez zmian. Sporzadzono w dwoch jednobrzmiacych egzemplarzach.\n\nData i podpis: 15.06.2026\nJan Kowalski                    Adam Nowak",
  "nastepna_strona": "",
  "oczekiwane": { "isFirstPage": false, "documentType": "Aneks do umowy" }
}
```

`09-wniosek-po-swiadectwie.json`:

```json
{
  "id": "wniosek-po-swiadectwie",
  "opis": "PULAPKA: nowy dokument nieznanego typu z generycznymi frazami HR po swiadectwie (klasa realnego bledu z 2026-07-11)",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Swiadectwo pracy",
  "poprzednia_strona": "6. Informacja o zajeciu wynagrodzenia: brak. 7. Pouczenie: pracownik moze wystapic o sprostowanie swiadectwa pracy w ciagu 14 dni. Podpis pracodawcy.",
  "aktualna_strona": "Wniosek o dofinansowanie zakupu okularow korygujacych\nZwracam sie z prosba o dofinansowanie zakupu okularow korygujacych do pracy przy monitorze. Jestem pracownikiem dzialu ksiegowosci, moje wynagrodzenie pomniejszane jest o skladki zgodnie z przepisami.\nW zalaczeniu faktura na kwote 450 zl.",
  "nastepna_strona": "Opinia lekarza medycyny pracy: zalecane okulary korygujace do pracy z monitorem ekranowym.",
  "oczekiwane": { "isFirstPage": true, "isKnownType": false }
}
```

`10-malo-tekstu-zalacznik.json`:

```json
{
  "id": "malo-tekstu-zalacznik",
  "opis": "Strona z bardzo mala iloscia tekstu - zalacznik do biezacego dokumentu",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Umowa o prace",
  "poprzednia_strona": "Integralna czescia umowy jest zalacznik nr 1 - zakres obowiazkow. Podpisy stron.",
  "aktualna_strona": "Zalacznik nr 1 do umowy o prace\nZakres obowiazkow: prowadzenie ksiag rachunkowych, sporzadzanie deklaracji.",
  "nastepna_strona": "",
  "oczekiwane": { "isFirstPage": false, "documentType": "Umowa o prace" }
}
```

`11-poczatek-paczki.json`:

```json
{
  "id": "poczatek-paczki",
  "opis": "Pierwsza strona paczki - brak biezacego dokumentu (typ = BRAK)",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "",
  "poprzednia_strona": "",
  "aktualna_strona": "UMOWA O PRACE zawarta w dniu 1 czerwca 2026 r. pomiedzy ACME Sp. z o.o. (Pracodawca) a Piotrem Zielinskim (Pracownik). 1. Stanowisko: analityk danych.",
  "nastepna_strona": "2. Wynagrodzenie zasadnicze: 8 500 zl brutto miesiecznie.",
  "oczekiwane": { "isFirstPage": true, "documentType": "Umowa o prace", "isKnownType": true }
}
```

`12-aneks-po-umowie.json`:

```json
{
  "id": "aneks-po-umowie",
  "opis": "Nowy dokument znanego typu z frazami nakladajacymi sie na typ poprzedni (aneks po umowie)",
  "znane_typy": ["Aneks do umowy", "Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Umowa o prace",
  "poprzednia_strona": "Umowa wchodzi w zycie z dniem podpisania. Sporzadzono w dwoch egzemplarzach. Podpisy stron: Jan Kowalski, Piotr Zielinski.",
  "aktualna_strona": "ANEKS DO UMOWY O PRACE\nzawartej w dniu 1 czerwca 2026 r. Strony zgodnie postanawiaja, ze od dnia 1 sierpnia 2026 r. stanowisko Pracownika ulega zmianie na: starszy analityk danych.",
  "nastepna_strona": "Pozostale warunki umowy o prace pozostaja bez zmian. Podpisy stron.",
  "oczekiwane": { "isFirstPage": true, "documentType": "Aneks do umowy", "isKnownType": true }
}
```

- [ ] **Step 3: Napisz runner**

Utwórz `splitter/scripts/llm_eval.py`:

```python
"""Ewaluacja promptu LLM na syntetycznych przypadkach.

Wymaga zywego endpointu zgodnego z OpenAI Chat Completions (np. LM Studio).
Nie jest czescia pytest. Przyklady:

    python scripts/llm_eval.py                          # domyslny endpoint/model
    python scripts/llm_eval.py --list                   # wypisz przypadki bez wolania LLM
    python scripts/llm_eval.py --prompt-file prompts_baseline/user-prompt.txt
    python scripts/llm_eval.py --cases wniosek-po-swiadectwie --out wyniki.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from webcon_pdf_splitter.classification.llm import OpenAiCompatibleLlmClassifier
from webcon_pdf_splitter.classification.prompts import PromptProvider

CASES_DIR = Path(__file__).resolve().parent / "eval_cases"


def load_cases(only_ids: list[str]) -> list[dict]:
    cases = []
    for path in sorted(CASES_DIR.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        if only_ids and case["id"] not in only_ids:
            continue
        cases.append(case)
    return cases


def run_case(classifier: OpenAiCompatibleLlmClassifier, case: dict) -> dict:
    start = time.monotonic()
    try:
        verdict = classifier.classify_uncertain_page(
            current_text=case["aktualna_strona"],
            previous_text=case["poprzednia_strona"],
            next_text=case["nastepna_strona"],
            known_document_types=case["znane_typy"],
            current_document_type=case["typ_biezacego_dokumentu"],
        )
    except Exception as exc:  # blad HTTP/parsowania = FAIL z opisem
        return {
            "id": case["id"],
            "pass": False,
            "seconds": round(time.monotonic() - start, 1),
            "error": str(exc),
            "mismatches": [],
            "guard": [],
        }
    seconds = round(time.monotonic() - start, 1)
    mismatches = []
    for key, expected in case["oczekiwane"].items():
        got = getattr(verdict, key)
        if got != expected:
            mismatches.append(f"{key}: oczekiwano {expected!r}, otrzymano {got!r}")
    guard = list(verdict.inconsistencyReasons)
    return {
        "id": case["id"],
        "pass": not mismatches and not guard,
        "seconds": seconds,
        "error": None,
        "mismatches": mismatches,
        "guard": guard,
        "verdict": verdict.model_dump(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://192.168.1.147:1234/v1")
    parser.add_argument("--model", default="qwen2.5-7b-instruct-1m")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--prompt-file", default="")
    parser.add_argument("--system-prompt-file", default="")
    parser.add_argument("--cases", nargs="*", default=[], help="filtr po id przypadkow")
    parser.add_argument("--out", default="", help="zapisz szczegolowe wyniki do JSON")
    parser.add_argument("--list", action="store_true", help="wypisz przypadki i zakoncz")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if not cases:
        print("Brak przypadkow (sprawdz --cases / katalog eval_cases)")
        return 2
    if args.list:
        for case in cases:
            print(f"{case['id']}: {case['opis']}")
        return 0

    classifier = OpenAiCompatibleLlmClassifier(
        endpoint=args.endpoint,
        model=args.model,
        timeout_seconds=args.timeout,
        prompts=PromptProvider(
            user_prompt_file=args.prompt_file,
            system_prompt_file=args.system_prompt_file,
        ),
    )

    results = []
    for case in cases:
        result = run_case(classifier, case)
        results.append(result)
        status = "PASS" if result["pass"] else "FAIL"
        print(f"[{status}] {result['id']} ({result['seconds']}s)")
        if result["error"]:
            print(f"       blad: {result['error']}")
        for mismatch in result["mismatches"]:
            print(f"       {mismatch}")
        for reason in result["guard"]:
            print(f"       straznik odrzucil: {reason}")

    passed = sum(1 for r in results if r["pass"])
    total_seconds = round(sum(r["seconds"] for r in results), 1)
    print(f"\nWynik: {passed}/{len(results)} PASS, laczny czas {total_seconds}s")

    if args.out:
        Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Szczegoly zapisane do {args.out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Weryfikacja bez LLM**

Run: `cd splitter && python scripts/llm_eval.py --list`
Expected: 12 linii `id: opis`, exit code 0.

Run: `cd splitter && python scripts/llm_eval.py --cases nie-istnieje`
Expected: komunikat "Brak przypadkow...", exit code 2.

- [ ] **Step 5: Commit**

```bash
git add splitter/scripts/llm_eval.py splitter/scripts/eval_cases/ splitter/scripts/prompts_baseline/
git commit -m "feat: LLM prompt eval harness with synthetic multi-paradigm cases"
```

---

### Task 8: Ewaluacja na LM Studio (krok ręczny / na żywo)

**Files:** brak zmian w kodzie (ewentualnie iteracje treści `DEFAULT_USER_PROMPT` w `prompts.py` + `examples/prompts/user-prompt.txt`).

Wymaga dostępu do LM Studio użytkownika (`http://192.168.1.147:1234/v1`,
model `qwen2.5-7b-instruct-1m`). Jeśli endpoint nieosiągalny ze środowiska
wykonania — zgłoś to i przekaż użytkownikowi komendy do samodzielnego
uruchomienia.

- [ ] **Step 1: Baseline (stary prompt)**

Run: `cd splitter && python scripts/llm_eval.py --prompt-file scripts/prompts_baseline/user-prompt.txt --out baseline.json`
Zanotuj wynik X/12. Uwaga: stary prompt nie zna `{typ_biezacego_dokumentu}`
— to celowe (tak wyglądała produkcja przed zmianą).

- [ ] **Step 2: Nowy prompt (wbudowany)**

Run: `cd splitter && python scripts/llm_eval.py --out nowy.json`
Zanotuj wynik Y/12 i porównaj z baseline. Oczekiwanie: Y > X, w szczególności
przypadek `wniosek-po-swiadectwie` PASS.

- [ ] **Step 3: Raport i ewentualna iteracja**

Przedstaw użytkownikowi porównanie (per przypadek: baseline vs nowy, czasy).
Jeśli nowy prompt nie poprawia pułapek — iteruj treść `DEFAULT_USER_PROMPT`
(pamiętając o synchronizacji `examples/prompts/user-prompt.txt`), commit po
każdej udanej iteracji:

```bash
git add splitter/src/webcon_pdf_splitter/classification/prompts.py splitter/examples/prompts/user-prompt.txt
git commit -m "feat: tune LLM prompt based on eval results"
```

Pliki `baseline.json` / `nowy.json` NIE trafiają do gita (wyniki lokalne).

---

## Self-review (wykonany)

- **Pokrycie specu:** szablony+hot-reload+fallbacki (Task 1), strażnik 3 reguł (Task 2), typ bieżącego dokumentu + integracja szablonów (Task 3), bramka+reviewReasons (Task 4), config+wiring (Task 5), manual+przykłady+compose+docs (Task 6), skrypt+12 przypadków (Task 7), przebieg baseline→nowy (Task 8). Wszystkie testy jednostkowe ze specu mają zadania.
- **Spójność typów:** `classify_uncertain_page(..., current_document_type: str = "")` jednolicie w Tasks 3/4/7; `PromptProvider(user_prompt_file, system_prompt_file)` jednolicie w Tasks 1/3/5/7; `inconsistencyReasons` jednolicie w Tasks 2/3/4/7.
- **Zależności między zadaniami:** 1→3→4, 2→3, 1+3→5, 1→6 (treść przykładów), 3→7, 7→8. Kolejność wykonania = numeracja.
