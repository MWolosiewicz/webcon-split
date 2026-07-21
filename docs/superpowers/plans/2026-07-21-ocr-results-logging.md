# Logowanie wynikow OCR / warstwy tekstowej — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Docker logs splittera pokazuja per strona surowy tekst (do 1200 zn.) i znormalizowany tekst (do 300 zn.), zeby dalo sie diagnozowac bledna klasyfikacje (OCR vs slownik).

**Architecture:** Blok diagnostyczny w `api.py` wywolywany po ekstrakcji tekstu, przed klasyfikacja; normalizacja wypromowana do publicznej funkcji `normalize_text` w `rules.py` (ta sama, ktorej uzywa klasyfikator); w `ocr.py` dodatkowy wpis o stronach, ktorych OCR nie poprawil. Wszystko sterowane trzema nowymi ustawieniami `SPLITTER_*`.

**Tech Stack:** Python 3.11+, pydantic-settings, pytest (caplog), logging stdlib.

## Global Constraints

- Prefiks zmiennych srodowiskowych: `SPLITTER_` (konwencja `SplitterSettings`, `env_file=".env"`, `extra="ignore"`).
- Domyslne wartosci: `log_page_text=True`, `log_page_text_raw_chars=1200`, `log_page_text_norm_chars=300`.
- Logi po polsku bez znakow diakrytycznych (konwencja projektu, np. "OCR: uzupelniono tekst...").
- Zadnych zmian w API `/api/split`, kontraktach, akcji WEBCON ani logice klasyfikacji/OCR.
- Testy uruchamiane z katalogu `splitter/`: `python -m pytest tests/... -v`.
- Kazdy commit konczy sie stopka `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Nowe ustawienia konfiguracji

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/config.py`
- Modify: `splitter/.env.example`
- Test: `splitter/tests/test_config_logging.py`

**Interfaces:**
- Consumes: `SplitterSettings` (pydantic BaseSettings, prefiks `SPLITTER_`).
- Produces: pola `settings.log_page_text: bool`, `settings.log_page_text_raw_chars: int`, `settings.log_page_text_norm_chars: int` — uzywane w Task 3.

- [ ] **Step 1: Write the failing tests**

Dopisz na koncu `splitter/tests/test_config_logging.py`:

```python
def test_page_text_logging_defaults():
    settings = SplitterSettings(_env_file=None)
    assert settings.log_page_text is True
    assert settings.log_page_text_raw_chars == 1200
    assert settings.log_page_text_norm_chars == 300


def test_page_text_logging_read_from_env(monkeypatch):
    monkeypatch.setenv("SPLITTER_LOG_PAGE_TEXT", "false")
    monkeypatch.setenv("SPLITTER_LOG_PAGE_TEXT_RAW_CHARS", "500")
    monkeypatch.setenv("SPLITTER_LOG_PAGE_TEXT_NORM_CHARS", "100")
    settings = SplitterSettings(_env_file=None)
    assert settings.log_page_text is False
    assert settings.log_page_text_raw_chars == 500
    assert settings.log_page_text_norm_chars == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run (z katalogu `splitter/`): `python -m pytest tests/test_config_logging.py -v`
Expected: FAIL — `AttributeError: 'SplitterSettings' object has no attribute 'log_page_text'`

- [ ] **Step 3: Write minimal implementation**

W `splitter/src/webcon_pdf_splitter/config.py` dopisz po polu `log_level`:

```python
    log_page_text: bool = Field(default=True)
    log_page_text_raw_chars: int = Field(default=1200)
    log_page_text_norm_chars: int = Field(default=300)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config_logging.py -v`
Expected: PASS (wszystkie, w tym dotychczasowe)

- [ ] **Step 5: Update .env.example**

W `splitter/.env.example`, w sekcji `--- API ---` po `SPLITTER_LOG_LEVEL=INFO` dopisz:

```
# Logowanie tekstu stron (diagnostyka klasyfikacji): per strona surowy
# fragment + fragment znormalizowany (ASCII, wielkie litery) - dokladnie
# w postaci, w jakiej klasyfikator szuka naglowkow i fraz.
SPLITTER_LOG_PAGE_TEXT=true
# Limit znakow surowego fragmentu w logu.
SPLITTER_LOG_PAGE_TEXT_RAW_CHARS=1200
# Limit znakow znormalizowanego fragmentu w logu.
SPLITTER_LOG_PAGE_TEXT_NORM_CHARS=300
```

- [ ] **Step 6: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/config.py splitter/.env.example splitter/tests/test_config_logging.py
git commit -m "feat: ustawienia logowania tekstu stron (SPLITTER_LOG_PAGE_TEXT*)"
```

---

### Task 2: `normalize_text` jako funkcja modulowa

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/rules.py`
- Test: `splitter/tests/test_normalization.py`

**Interfaces:**
- Consumes: dotychczasowa `RuleBasedClassifier._normalize` (staticmethod).
- Produces: `normalize_text(value: str) -> str` w module `webcon_pdf_splitter.classification.rules` — uzywana w Task 3. Zachowanie identyczne z `_normalize` (NFKD, ł→l, ASCII-only, upper, zbite biale znaki).

- [ ] **Step 1: Write the failing test**

Dopisz na koncu `splitter/tests/test_normalization.py`:

```python
def test_normalize_text_module_function_matches_classifier_behavior():
    from webcon_pdf_splitter.classification.rules import normalize_text

    assert normalize_text("Umowa  o\n pracĘ\tłącznie") == "UMOWA O PRACE LACZNIE"
    assert normalize_text("   ") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_normalization.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_text'`

- [ ] **Step 3: Write minimal implementation**

W `splitter/src/webcon_pdf_splitter/classification/rules.py`:

1. Dodaj funkcje modulowa (nad klasa `RuleBasedClassifier`):

```python
def normalize_text(value: str) -> str:
    # OCR output is inconsistent with Polish diacritics, so both the page
    # text and the patterns are folded to plain ASCII before matching.
    decomposed = unicodedata.normalize("NFKD", value.replace("ł", "l").replace("Ł", "L"))
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_only.upper()).strip()
```

2. Zastap staticmethod delegacja (usun cialo, zostaw delegacje — wywolania `self._normalize(...)` w klasie zostaja bez zmian):

```python
    @staticmethod
    def _normalize(value: str) -> str:
        return normalize_text(value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_normalization.py tests/test_split_patterns.py -v`
Expected: PASS (nowy test + wszystkie dotychczasowe testy dopasowania)

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/rules.py splitter/tests/test_normalization.py
git commit -m "refactor: normalize_text jako publiczna funkcja modulowa"
```

---

### Task 3: Blok diagnostyczny `_log_page_texts` w api.py

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/api.py`
- Test: `splitter/tests/test_page_text_logging.py` (nowy plik)

**Interfaces:**
- Consumes: `settings.log_page_text`, `settings.log_page_text_raw_chars`, `settings.log_page_text_norm_chars` (Task 1); `normalize_text` z `webcon_pdf_splitter.classification.rules` (Task 2); `alnum_count` z `webcon_pdf_splitter.ocr` (istnieje).
- Produces: `_log_page_texts(page_texts: list[str], settings: SplitterSettings) -> None` oraz `_preview(value: str, limit: int) -> str` w `webcon_pdf_splitter.api`; wywolanie w `_split` po ekstrakcji tekstu.

- [ ] **Step 1: Write the failing tests**

Utworz `splitter/tests/test_page_text_logging.py`:

```python
import logging

from webcon_pdf_splitter.api import _log_page_texts, _preview
from webcon_pdf_splitter.config import SplitterSettings


def _settings(**overrides) -> SplitterSettings:
    return SplitterSettings(_env_file=None, **overrides)


def test_preview_collapses_whitespace_and_truncates_with_ellipsis():
    assert _preview("Umowa\n  o\tprace", 100) == "Umowa o prace"
    assert _preview("ABCDEF", 4) == "ABCD..."
    assert _preview("ABCD", 4) == "ABCD"  # rowne limitowi -> bez wielokropka


def test_logs_raw_and_normalized_fragment_per_page(caplog):
    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.api")

    _log_page_texts(["Umowa o pracĘ\nzawarta dnia"], _settings())

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert message.startswith("Strona 1:")
    assert 'surowy(1200): "Umowa o pracĘ zawarta dnia"' in message
    assert 'znorm(300): "UMOWA O PRACE ZAWARTA DNIA"' in message


def test_respects_configured_char_limits(caplog):
    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.api")

    _log_page_texts(
        ["Umowa o prace zawarta dnia"],
        _settings(log_page_text_raw_chars=10, log_page_text_norm_chars=5),
    )

    message = caplog.records[0].getMessage()
    assert 'surowy(10): "Umowa o pr..."' in message
    assert 'znorm(5): "UMOWA..."' in message


def test_empty_page_logged_as_pusta(caplog):
    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.api")

    _log_page_texts(["Tekst pierwszej strony", "  \n. ,"], _settings())

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert messages[1] == "Strona 2: 0 znakow (pusta)"


def test_disabled_flag_silences_logging(caplog):
    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.api")

    _log_page_texts(["Umowa o prace"], _settings(log_page_text=False))

    assert caplog.records == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_page_text_logging.py -v`
Expected: FAIL — `ImportError: cannot import name '_log_page_texts'`

- [ ] **Step 3: Write minimal implementation**

W `splitter/src/webcon_pdf_splitter/api.py`:

1. Dodaj `re` do importow stdlib (sekcja importow na gorze pliku):

```python
import re
```

2. Rozszerz import z `classification.rules` i `ocr`:

```python
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier, normalize_text
```

```python
from webcon_pdf_splitter.ocr import (
    PdfTextOcrEngine,
    TesseractPageOcr,
    TextLayerWithOcrFallback,
    alnum_count,
)
```

3. Dodaj funkcje pomocnicze (np. po `_page_count_of`):

```python
def _preview(value: str, limit: int) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."


def _log_page_texts(page_texts: list[str], settings: SplitterSettings) -> None:
    """Diagnostyka klasyfikacji: co faktycznie odczytano z kazdej strony.

    Surowy fragment pokazuje jakosc odczytu (warstwa/OCR), znormalizowany
    fragment jest w postaci, w ktorej klasyfikator szuka naglowkow i fraz
    ze slownika - porownywalny 1:1 z konfiguracja wzorcow.
    """
    if not settings.log_page_text:
        return
    for index, text in enumerate(page_texts):
        chars = alnum_count(text)
        if chars == 0:
            logger.info("Strona %s: 0 znakow (pusta)", index + 1)
            continue
        logger.info(
            'Strona %s: %s znakow alnum | surowy(%s): "%s" | znorm(%s): "%s"',
            index + 1,
            chars,
            settings.log_page_text_raw_chars,
            _preview(text, settings.log_page_text_raw_chars),
            settings.log_page_text_norm_chars,
            _preview(normalize_text(text), settings.log_page_text_norm_chars),
        )
```

4. W `_split`, po linii `page_texts = ocr.extract_page_texts(str(source_path))` dodaj:

```python
        _log_page_texts(page_texts, settings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_page_text_logging.py tests/test_api.py -v`
Expected: PASS (nowe testy + testy API bez regresji)

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_page_text_logging.py
git commit -m "feat: log tekstu stron (surowy + znormalizowany) po ekstrakcji"
```

---

### Task 4: Wpis "OCR nie poprawil stron" w ocr.py

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/ocr.py:76-82` (petla nadpisywania w `TextLayerWithOcrFallback.extract_page_texts`)
- Test: `splitter/tests/test_ocr.py`

**Interfaces:**
- Consumes: istniejaca petla `for index, ocr_text in ocr_texts.items()` w `TextLayerWithOcrFallback`.
- Produces: dodatkowy wpis INFO loggera `webcon_pdf_splitter.ocr`, gdy OCR uruchomil sie dla strony, ale nie dostarczyl wiecej tresci niz warstwa tekstowa. Zadnych zmian w zwracanych danych.

- [ ] **Step 1: Write the failing test**

Dopisz w `splitter/tests/test_ocr.py` (po `test_ocr_result_ignored_when_shorter_than_text_layer`):

```python
def test_logs_pages_where_ocr_did_not_improve_text(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.ocr")
    ocr = _FakePageOcr({0: "", 1: "TEKST Z OCR PO ROZPOZNANIU SKANU"})
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(["Zalacznik nr 3 podpisany", ""]),  # obie < prog
        min_text_chars=25,
    )

    composite.extract_page_texts("mixed.pdf")

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "OCR nie poprawil stron [1] - zachowano tekst warstwy" == message
        for message in messages
    )
    # strona 2 zostala uzupelniona -> raportowana w dotychczasowym wpisie
    assert any("uzupelniono" in message for message in messages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ocr.py::test_logs_pages_where_ocr_did_not_improve_text -v`
Expected: FAIL — assercja "OCR nie poprawil stron" (wpis nie istnieje)

- [ ] **Step 3: Write minimal implementation**

W `splitter/src/webcon_pdf_splitter/ocr.py` zastap petle nadpisywania (linie 75-81, od komentarza "Nadpisuj warstwe..." do `logger.info("OCR: uzupelniono...")` wlacznie):

```python
        # Nadpisuj warstwe tekstowa tylko gdy OCR dostarczyl WIECEJ tresci -
        # inaczej krotki, ale realny tekst (albo pusty OCR przy braku binarki)
        # skasowalby oryginal (utrata danych).
        filled = []
        not_improved = []
        for index, ocr_text in ocr_texts.items():
            if alnum_count(ocr_text) > alnum_count(texts[index]):
                texts[index] = ocr_text
                filled.append(index + 1)
            else:
                not_improved.append(index + 1)
        if filled:
            logger.info("OCR: uzupelniono tekst %s stron (strony: %s)", len(filled), filled)
        if not_improved:
            logger.info(
                "OCR nie poprawil stron %s - zachowano tekst warstwy",
                not_improved,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ocr.py -v`
Expected: PASS (nowy test + wszystkie dotychczasowe)

- [ ] **Step 5: Run full test suite**

Run (z katalogu `splitter/`): `python -m pytest -v`
Expected: PASS — komplet testow splittera bez regresji

- [ ] **Step 6: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/ocr.py splitter/tests/test_ocr.py
git commit -m "feat: log stron, ktorych OCR nie poprawil"
```
