# WEBCON Dictionary Patterns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The splitter reads document types and recognition patterns directly from a WEBCON dictionary process (content database, SQL read-only) instead of its own `document_type`/`document_pattern` tables.

**Architecture:** A new `WebconDictionaryPatternRepository` implements the existing `PatternRepository` protocol by querying `WFElements` (dictionary form headers = document types) joined with `WFElementDetails` (item list rows = patterns) using column names supplied via configuration. The factory `build_pattern_repository` prefers WEBCON dictionary mode when configured; the existing SQL and in-memory modes remain as fallbacks. No classifier or pipeline changes.

**Tech Stack:** Python 3.11+, pydantic-settings v2, pyodbc, pytest. Spec: `docs/superpowers/specs/2026-07-11-webcon-dictionary-patterns-design.md`.

## Global Constraints

- WEBCON content database is **read-only** for the splitter — only `SELECT` on `dbo.WFElements` and `dbo.WFElementDetails`; never write.
- Phrases and excluded phrases are semicolon-separated text (`;`), each phrase trimmed, empty entries dropped.
- All new settings use the existing `SPLITTER_` env prefix (pydantic-settings `env_prefix`).
- Missing pattern weight defaults to `1.0`; per-type auto-accept threshold is NOT read in this iteration (global `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE` applies).
- Pattern rows with an empty header are skipped and logged as a warning.
- Column names from configuration must match `^[A-Za-z0-9_]+$` (they are interpolated into SQL identifiers).
- Existing tests must keep passing; the `PatternRepository` protocol and `DocumentPattern` dataclass do not change.
- Run tests from the `splitter/` directory: `python -m pytest tests/ -v`.

---

### Task 1: WEBCON dictionary settings in `SplitterSettings`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/config.py`
- Test: `splitter/tests/test_webcon_dictionary.py` (new file)

**Interfaces:**
- Consumes: existing `SplitterSettings` (pydantic `BaseSettings`, `env_prefix="SPLITTER_"`).
- Produces: nine new settings fields used by Tasks 3-6:
  `webcon_db_connection_string: str` (default `""`),
  `webcon_dict_form_type_id: int` (default `0`),
  `webcon_dict_col_type_name`, `webcon_dict_col_type_active`,
  `webcon_dict_col_pattern_header`, `webcon_dict_col_pattern_phrases`,
  `webcon_dict_col_pattern_excluded`, `webcon_dict_col_pattern_weight`,
  `webcon_dict_col_pattern_active` (all `str`, default `""`).

- [ ] **Step 1: Write the failing test**

Create `splitter/tests/test_webcon_dictionary.py`:

```python
from webcon_pdf_splitter.config import SplitterSettings


def test_webcon_dictionary_settings_default_to_disabled():
    settings = SplitterSettings(webcon_db_connection_string="", webcon_dict_form_type_id=0)

    assert settings.webcon_db_connection_string == ""
    assert settings.webcon_dict_form_type_id == 0
    assert settings.webcon_dict_col_type_name == ""
    assert settings.webcon_dict_col_type_active == ""
    assert settings.webcon_dict_col_pattern_header == ""
    assert settings.webcon_dict_col_pattern_phrases == ""
    assert settings.webcon_dict_col_pattern_excluded == ""
    assert settings.webcon_dict_col_pattern_weight == ""
    assert settings.webcon_dict_col_pattern_active == ""


def test_webcon_dictionary_settings_accept_values():
    settings = SplitterSettings(
        webcon_db_connection_string="Driver={ODBC Driver 18 for SQL Server};Server=sql;Database=BPS_Content;",
        webcon_dict_form_type_id=123,
        webcon_dict_col_type_name="WFD_AttText1",
    )

    assert settings.webcon_dict_form_type_id == 123
    assert settings.webcon_dict_col_type_name == "WFD_AttText1"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `splitter/`): `python -m pytest tests/test_webcon_dictionary.py -v`
Expected: FAIL — pydantic raises `ValidationError` or the assertion fails with `AttributeError`/unknown field, because the fields do not exist yet.

- [ ] **Step 3: Write minimal implementation**

In `splitter/src/webcon_pdf_splitter/config.py`, add fields to `SplitterSettings` after `api_token`:

```python
    webcon_db_connection_string: str = Field(default="")
    webcon_dict_form_type_id: int = Field(default=0)
    webcon_dict_col_type_name: str = Field(default="")
    webcon_dict_col_type_active: str = Field(default="")
    webcon_dict_col_pattern_header: str = Field(default="")
    webcon_dict_col_pattern_phrases: str = Field(default="")
    webcon_dict_col_pattern_excluded: str = Field(default="")
    webcon_dict_col_pattern_weight: str = Field(default="")
    webcon_dict_col_pattern_active: str = Field(default="")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_webcon_dictionary.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/config.py splitter/tests/test_webcon_dictionary.py
git commit -m "feat: add WEBCON dictionary settings to splitter config"
```

---

### Task 2: Phrase splitting helper

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/db/repository.py`
- Test: `splitter/tests/test_webcon_dictionary.py`

**Interfaces:**
- Produces: module-level function `split_phrases(value: str | None) -> list[str]` in `webcon_pdf_splitter.db.repository`, used by Task 4.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_webcon_dictionary.py`:

```python
from webcon_pdf_splitter.db.repository import split_phrases


def test_split_phrases_splits_on_semicolons_and_trims():
    assert split_phrases("pracodawca; pracownik ;wynagrodzenie") == [
        "pracodawca",
        "pracownik",
        "wynagrodzenie",
    ]


def test_split_phrases_drops_empty_entries():
    assert split_phrases("bhp;; ; szkolenie okresowe;") == ["bhp", "szkolenie okresowe"]


def test_split_phrases_handles_none_and_empty():
    assert split_phrases(None) == []
    assert split_phrases("") == []
    assert split_phrases("   ") == []


def test_split_phrases_single_phrase_without_semicolon():
    assert split_phrases("rodo") == ["rodo"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_webcon_dictionary.py -v`
Expected: FAIL with `ImportError: cannot import name 'split_phrases'`

- [ ] **Step 3: Write minimal implementation**

In `splitter/src/webcon_pdf_splitter/db/repository.py`, add after the imports:

```python
def split_phrases(value: str | None) -> list[str]:
    if not value:
        return []
    return [phrase.strip() for phrase in value.split(";") if phrase.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_webcon_dictionary.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/db/repository.py splitter/tests/test_webcon_dictionary.py
git commit -m "feat: add semicolon phrase splitting helper"
```

---

### Task 3: `WebconDictionaryPatternRepository` constructor with mapping validation

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/db/repository.py`
- Test: `splitter/tests/test_webcon_dictionary.py`

**Interfaces:**
- Consumes: `SplitterSettings` fields from Task 1.
- Produces: class `WebconDictionaryPatternRepository` with `__init__(self, settings: "SplitterSettings") -> None` raising `ValueError` on incomplete or invalid mapping. Tasks 4-6 extend/instantiate this class.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_webcon_dictionary.py`:

```python
import pytest

from webcon_pdf_splitter.db.repository import WebconDictionaryPatternRepository


def _webcon_settings(**overrides):
    values = dict(
        webcon_db_connection_string="Driver={ODBC Driver 18 for SQL Server};Server=sql;Database=BPS_Content;",
        webcon_dict_form_type_id=123,
        webcon_dict_col_type_name="WFD_AttText1",
        webcon_dict_col_type_active="WFD_AttBool1",
        webcon_dict_col_pattern_header="DET_Att1",
        webcon_dict_col_pattern_phrases="DET_Att2",
        webcon_dict_col_pattern_excluded="DET_Att3",
        webcon_dict_col_pattern_weight="DET_Value1",
        webcon_dict_col_pattern_active="DET_Bool1",
    )
    values.update(overrides)
    return SplitterSettings(**values)


def test_repository_accepts_complete_mapping():
    WebconDictionaryPatternRepository(_webcon_settings())


def test_repository_rejects_missing_column_mapping():
    with pytest.raises(ValueError) as exc:
        WebconDictionaryPatternRepository(_webcon_settings(webcon_dict_col_pattern_phrases=""))

    assert "SPLITTER_WEBCON_DICT_COL_PATTERN_PHRASES" in str(exc.value)


def test_repository_rejects_invalid_column_identifier():
    with pytest.raises(ValueError) as exc:
        WebconDictionaryPatternRepository(
            _webcon_settings(webcon_dict_col_type_name="WFD_AttText1; DROP TABLE x")
        )

    assert "SPLITTER_WEBCON_DICT_COL_TYPE_NAME" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_webcon_dictionary.py -v`
Expected: FAIL with `ImportError: cannot import name 'WebconDictionaryPatternRepository'`

- [ ] **Step 3: Write minimal implementation**

In `splitter/src/webcon_pdf_splitter/db/repository.py`:

Add to the imports at the top:

```python
import logging
import re
```

Add after `split_phrases`:

```python
logger = logging.getLogger(__name__)

_SQL_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


class WebconDictionaryPatternRepository:
    _COLUMN_SETTINGS = (
        "webcon_dict_col_type_name",
        "webcon_dict_col_type_active",
        "webcon_dict_col_pattern_header",
        "webcon_dict_col_pattern_phrases",
        "webcon_dict_col_pattern_excluded",
        "webcon_dict_col_pattern_weight",
        "webcon_dict_col_pattern_active",
    )

    def __init__(self, settings: "SplitterSettings") -> None:
        missing = [name for name in self._COLUMN_SETTINGS if not getattr(settings, name)]
        if missing:
            raise ValueError(
                "Incomplete WEBCON dictionary mapping, set: "
                + ", ".join(f"SPLITTER_{name.upper()}" for name in missing)
            )
        invalid = [
            name
            for name in self._COLUMN_SETTINGS
            if not _SQL_IDENTIFIER.match(getattr(settings, name))
        ]
        if invalid:
            raise ValueError(
                "Invalid WEBCON dictionary column names (letters, digits, underscore only): "
                + ", ".join(f"SPLITTER_{name.upper()}" for name in invalid)
            )
        self._settings = settings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_webcon_dictionary.py -v`
Expected: 9 PASSED

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/db/repository.py splitter/tests/test_webcon_dictionary.py
git commit -m "feat: add WEBCON dictionary repository with mapping validation"
```

---

### Task 4: Row mapping to `DocumentPattern`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/db/repository.py`
- Test: `splitter/tests/test_webcon_dictionary.py`

**Interfaces:**
- Consumes: `WebconDictionaryPatternRepository` from Task 3, `split_phrases` from Task 2, existing `DocumentPattern` dataclass.
- Produces: method `_map_rows(self, rows) -> list[DocumentPattern]` where each row is a sequence `(type_name, header, phrases, excluded_phrases, weight)`. Used by `list_active_patterns` in Task 5.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_webcon_dictionary.py`:

```python
def test_map_rows_builds_document_patterns():
    repository = WebconDictionaryPatternRepository(_webcon_settings())

    patterns = repository._map_rows(
        [
            ("Umowa o prace", "UMOWA O PRACE", "pracodawca; pracownik", "aneks", 1.2),
        ]
    )

    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.document_type == "Umowa o prace"
    assert pattern.header == "UMOWA O PRACE"
    assert pattern.phrases == ["pracodawca", "pracownik"]
    assert pattern.excluded_phrases == ["aneks"]
    assert pattern.weight == 1.2
    assert pattern.active is True


def test_map_rows_defaults_missing_weight_to_one():
    repository = WebconDictionaryPatternRepository(_webcon_settings())

    patterns = repository._map_rows([("Typ", "NAGLOWEK", None, None, None)])

    assert patterns[0].weight == 1.0
    assert patterns[0].phrases == []
    assert patterns[0].excluded_phrases == []


def test_map_rows_skips_rows_with_empty_header():
    repository = WebconDictionaryPatternRepository(_webcon_settings())

    patterns = repository._map_rows(
        [
            ("Typ", None, "fraza", None, 1.0),
            ("Typ", "   ", "fraza", None, 1.0),
            ("Typ", "PRAWIDLOWY", "fraza", None, 1.0),
        ]
    )

    assert len(patterns) == 1
    assert patterns[0].header == "PRAWIDLOWY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_webcon_dictionary.py -v`
Expected: FAIL with `AttributeError: ... has no attribute '_map_rows'`

- [ ] **Step 3: Write minimal implementation**

Add to `WebconDictionaryPatternRepository`:

```python
    def _map_rows(self, rows) -> list[DocumentPattern]:
        patterns: list[DocumentPattern] = []
        for row in rows:
            header = (row[1] or "").strip()
            if not header:
                logger.warning(
                    "Skipping WEBCON dictionary pattern row with empty header (type: %s)", row[0]
                )
                continue
            patterns.append(
                DocumentPattern(
                    document_type=row[0],
                    header=header,
                    phrases=split_phrases(row[2]),
                    excluded_phrases=split_phrases(row[3]),
                    weight=float(row[4]) if row[4] is not None else 1.0,
                    active=True,
                )
            )
        return patterns
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_webcon_dictionary.py -v`
Expected: 12 PASSED

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/db/repository.py splitter/tests/test_webcon_dictionary.py
git commit -m "feat: map WEBCON dictionary rows to document patterns"
```

---

### Task 5: Query builder and `list_active_patterns`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/db/repository.py`
- Test: `splitter/tests/test_webcon_dictionary.py`

**Interfaces:**
- Consumes: `_map_rows` from Task 4, validated settings from Task 3.
- Produces: `_build_query(self) -> str` and `list_active_patterns(self) -> list[DocumentPattern]` — completes the `PatternRepository` protocol. Task 6 plugs the class into the factory.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_webcon_dictionary.py`:

```python
def test_build_query_uses_mapped_columns_and_fixed_filters():
    repository = WebconDictionaryPatternRepository(_webcon_settings())

    query = repository._build_query()

    assert "el.[WFD_AttText1]" in query
    assert "det.[DET_Att1]" in query
    assert "det.[DET_Att2]" in query
    assert "det.[DET_Att3]" in query
    assert "det.[DET_Value1]" in query
    assert "el.[WFD_AttBool1] = 1" in query
    assert "det.[DET_Bool1] = 1" in query
    assert "WFD_DTYPEID = ?" in query
    assert "WFD_IsDeleted = 0" in query
    assert "JOIN dbo.WFElementDetails det ON det.DET_WFDID = el.WFD_ID" in query
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_webcon_dictionary.py -v`
Expected: FAIL with `AttributeError: ... has no attribute '_build_query'`

- [ ] **Step 3: Write minimal implementation**

Add to `WebconDictionaryPatternRepository`:

```python
    def _build_query(self) -> str:
        s = self._settings
        return f"""
            SELECT el.[{s.webcon_dict_col_type_name}],
                   det.[{s.webcon_dict_col_pattern_header}],
                   det.[{s.webcon_dict_col_pattern_phrases}],
                   det.[{s.webcon_dict_col_pattern_excluded}],
                   det.[{s.webcon_dict_col_pattern_weight}]
            FROM dbo.WFElements el
            JOIN dbo.WFElementDetails det ON det.DET_WFDID = el.WFD_ID
            WHERE el.WFD_DTYPEID = ?
              AND el.WFD_IsDeleted = 0
              AND el.[{s.webcon_dict_col_type_active}] = 1
              AND det.[{s.webcon_dict_col_pattern_active}] = 1
        """

    def list_active_patterns(self) -> list[DocumentPattern]:
        settings = self._settings
        with pyodbc.connect(settings.webcon_db_connection_string) as connection:
            rows = (
                connection.cursor()
                .execute(self._build_query(), settings.webcon_dict_form_type_id)
                .fetchall()
            )
        return self._map_rows(rows)
```

Note: column names are interpolated as `[bracketed]` identifiers — safe because Task 3 validated them against `^[A-Za-z0-9_]+$`. The form type ID stays a `?` parameter. Unchecked checkboxes stored as `NULL` are excluded by `= 1`, which is the intended behavior (active means explicitly checked).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_webcon_dictionary.py -v`
Expected: 13 PASSED

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/db/repository.py splitter/tests/test_webcon_dictionary.py
git commit -m "feat: read active patterns from WEBCON dictionary process"
```

---

### Task 6: Factory selects WEBCON dictionary mode

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/db/repository.py:35-38` (function `build_pattern_repository`)
- Test: `splitter/tests/test_repository_factory.py`

**Interfaces:**
- Consumes: `WebconDictionaryPatternRepository` (Tasks 3-5), existing `SqlServerPatternRepository` and `InMemoryPatternRepository`.
- Produces: updated `build_pattern_repository(settings) -> PatternRepository` with priority: WEBCON dictionary > own SQL tables > in-memory. `api.py` needs no changes.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_repository_factory.py`:

```python
from webcon_pdf_splitter.db.repository import WebconDictionaryPatternRepository


def _webcon_kwargs():
    return dict(
        webcon_db_connection_string="Driver={ODBC Driver 18 for SQL Server};Server=sql;Database=BPS_Content;",
        webcon_dict_form_type_id=123,
        webcon_dict_col_type_name="WFD_AttText1",
        webcon_dict_col_type_active="WFD_AttBool1",
        webcon_dict_col_pattern_header="DET_Att1",
        webcon_dict_col_pattern_phrases="DET_Att2",
        webcon_dict_col_pattern_excluded="DET_Att3",
        webcon_dict_col_pattern_weight="DET_Value1",
        webcon_dict_col_pattern_active="DET_Bool1",
    )


def test_factory_prefers_webcon_dictionary_when_configured():
    settings = SplitterSettings(database_connection_string="", **_webcon_kwargs())

    repository = build_pattern_repository(settings)

    assert isinstance(repository, WebconDictionaryPatternRepository)


def test_factory_prefers_webcon_dictionary_over_own_database():
    settings = SplitterSettings(
        database_connection_string="Driver={ODBC Driver 18 for SQL Server};Server=sql;Database=WebconPdfSplitter;",
        **_webcon_kwargs(),
    )

    repository = build_pattern_repository(settings)

    assert isinstance(repository, WebconDictionaryPatternRepository)


def test_factory_ignores_webcon_mode_without_form_type_id():
    kwargs = _webcon_kwargs()
    kwargs["webcon_dict_form_type_id"] = 0
    settings = SplitterSettings(database_connection_string="", **kwargs)

    repository = build_pattern_repository(settings)

    assert isinstance(repository, InMemoryPatternRepository)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repository_factory.py -v`
Expected: 2 PASSED (existing), 2 FAILED with `AssertionError` (factory returns `InMemoryPatternRepository`), 1 PASSED (`test_factory_ignores_webcon_mode_without_form_type_id` may pass already — that is fine; the two preference tests must fail)

- [ ] **Step 3: Write minimal implementation**

Replace `build_pattern_repository` in `splitter/src/webcon_pdf_splitter/db/repository.py`:

```python
def build_pattern_repository(settings: "SplitterSettings") -> PatternRepository:
    if settings.webcon_db_connection_string and settings.webcon_dict_form_type_id:
        return WebconDictionaryPatternRepository(settings)
    if settings.database_connection_string:
        return SqlServerPatternRepository(settings.database_connection_string)
    return InMemoryPatternRepository(patterns=[])
```

Note: `WebconDictionaryPatternRepository` must be defined above `build_pattern_repository` in the module, or the factory will raise `NameError`. Move the class definition (Tasks 3-5) above the factory if needed.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASSED (including all pre-existing tests — the protocol did not change)

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/db/repository.py splitter/tests/test_repository_factory.py
git commit -m "feat: prefer WEBCON dictionary patterns in repository factory"
```

---

### Task 7: Deployment documentation

**Files:**
- Create: `docs/deployment/webcon-dictionary.md`
- Modify: `docs/deployment/splitter-service.md` (env var table, after the `SPLITTER_DATABASE_CONNECTION_STRING` row)
- Modify: `docs/deployment/sql-server.md` (standalone-mode note at the end)

**Interfaces:**
- Consumes: settings names from Task 1, query behavior from Task 5.
- Produces: operator-facing setup guide; no code.

- [ ] **Step 1: Create `docs/deployment/webcon-dictionary.md`**

```markdown
# Słownik typów dokumentów w WEBCON

Splitter czyta typy dokumentów i wzorce rozpoznawania bezpośrednio z bazy
treści WEBCON (tylko odczyt). Edycja odbywa się wyłącznie w WEBCON —
w procesie słownikowym opisanym niżej. Zmiany działają od następnego
wywołania `/api/split`, bez restartu serwisu.

## Proces słownikowy w Designer Studio

Utwórz proces słownikowy **"Typ dokumentu"** (jeden formularz = jeden typ):

Atrybuty nagłówka:

| Atrybut | Typ atrybutu | Uwagi |
|---|---|---|
| Nazwa typu | Wiersz tekstu | polskie znaki dozwolone — klasyfikator normalizuje do ASCII |
| Aktywny | Pole wyboru (checkbox) | odznaczony = cały typ wyłączony |
| Próg auto-akceptacji | Liczba zmiennoprzecinkowa | pole rezerwowe — obecnie splitter stosuje próg globalny |

Lista pozycji **"Wzorce"** (jeden wiersz = jeden wzorzec) — formularz powinien
mieć dokładnie jedną listę pozycji:

| Kolumna | Typ | Uwagi |
|---|---|---|
| Nagłówek dokumentu | Wiersz tekstu | np. `UMOWA O PRACE`; wiersz z pustym nagłówkiem jest pomijany |
| Frazy | Wiersz tekstu | rozdzielane średnikami, np. `pracodawca; pracownik` |
| Frazy wykluczające | Wiersz tekstu | rozdzielane średnikami, może być puste |
| Waga | Liczba zmiennoprzecinkowa | puste = 1,0 |
| Aktywny | Pole wyboru | odznaczony = wzorzec wyłączony |

## Odczyt ID i nazw kolumn

1. W Designer Studio włącz "Pokaż identyfikatory obiektów".
2. ID typu formularza słownika → właściwości typu formularza
   (`SPLITTER_WEBCON_DICT_FORM_TYPE_ID`).
3. Nazwę kolumny bazodanowej każdego atrybutu znajdziesz we właściwościach
   atrybutu (np. `WFD_AttText1` dla nagłówka, `DET_Att1` dla kolumn listy
   pozycji). Wpisz je do zmiennych `SPLITTER_WEBCON_DICT_COL_*`
   (tabela w `splitter-service.md`).

## Uprawnienia SQL

Konto splittera potrzebuje w bazie treści WEBCON wyłącznie:

```sql
GRANT SELECT ON dbo.WFElements TO splitter_svc;
GRANT SELECT ON dbo.WFElementDetails TO splitter_svc;
```

Splitter nigdy nie pisze do bazy treści. Tabele operacyjne
(`splitter_job`, `classification_feedback`) pozostają w bazie
`WebconPdfSplitter`.

## Dane startowe (typy HR i wzorce)

Wprowadź ręcznie w słowniku (jednorazowo, ok. 15 minut). Wszystkie typy:
Aktywny = tak, Próg = 0,90. Wszystkie wzorce: Aktywny = tak.

| Typ dokumentu | Nagłówek wzorca | Frazy | Frazy wykluczające | Waga |
|---|---|---|---|---|
| Umowa o pracę | UMOWA O PRACE | pracodawca; pracownik; wynagrodzenie; wymiar czasu pracy | aneks; wypowiedzenie; rozwiazanie umowy | 1,2 |
| Aneks do umowy o pracę | ANEKS DO UMOWY O PRACE | zmienia sie; pozostale warunki; porozumienie stron | | 1,2 |
| Aneks do umowy o pracę | ANEKS DO UMOWY | umowy o prace; zmienia sie | | 1,0 |
| Umowa zlecenie | UMOWA ZLECENIE | zleceniodawca; zleceniobiorca | | 1,2 |
| Umowa zlecenie | UMOWA ZLECENIA | zleceniodawca; zleceniobiorca | | 1,2 |
| Wypowiedzenie umowy o pracę | WYPOWIEDZENIE UMOWY O PRACE | okres wypowiedzenia; rozwiazanie umowy | | 1,2 |
| Wypowiedzenie umowy o pracę | ROZWIAZANIE UMOWY O PRACE | za wypowiedzeniem; bez wypowiedzenia; porozumienie stron | | 1,1 |
| Świadectwo pracy | SWIADECTWO PRACY | stosunek pracy; okres zatrudnienia; urlop wypoczynkowy | | 1,2 |
| Kwestionariusz osobowy | KWESTIONARIUSZ OSOBOWY | imie i nazwisko; data urodzenia; adres zamieszkania | | 1,2 |
| Orzeczenie lekarskie | ORZECZENIE LEKARSKIE | zdolny do pracy; badania profilaktyczne; medycyna pracy | | 1,2 |
| Orzeczenie lekarskie | ZASWIADCZENIE LEKARSKIE | zdolny do pracy; przeciwwskazania | | 1,0 |
| Zaświadczenie o ukończeniu szkolenia BHP | ZASWIADCZENIE O UKONCZENIU SZKOLENIA | bezpieczenstwa i higieny pracy; bhp; szkolenie okresowe | | 1,1 |
| Zaświadczenie o ukończeniu szkolenia BHP | KARTA SZKOLENIA WSTEPNEGO | instruktaz ogolny; instruktaz stanowiskowy; bhp | | 1,2 |
| Oświadczenie PIT-2 | PIT-2 | oswiadczenie; zaliczek na podatek; kwoty zmniejszajacej | | 1,2 |
| Zgoda na przetwarzanie danych osobowych | ZGODA NA PRZETWARZANIE DANYCH | danych osobowych; rodo; administratorem danych | | 1,2 |

Nagłówki i frazy wpisuj bez polskich znaków (jak w tabeli) — dopasowanie
i tak odbywa się po normalizacji do ASCII, ale ułatwia to diagnostykę.

## Rozwiązywanie problemów

- Błąd 500 przy `/api/split` z komunikatem o mapowaniu → sprawdź zmienne
  `SPLITTER_WEBCON_DICT_COL_*` (komunikat wskazuje brakującą/błędną zmienną);
  szczegóły w `splitter_job.technical_error`.
- Wszystko klasyfikowane jako "Nieznany typ dokumentu" → słownik pusty,
  wpisy nieaktywne albo złe `SPLITTER_WEBCON_DICT_FORM_TYPE_ID`.
- Ostrzeżenie o pustym nagłówku w logu → wiersz listy pozycji bez
  nagłówka dokumentu (jest pomijany).
```

- [ ] **Step 2: Update `docs/deployment/splitter-service.md`**

In the env var table, directly after the `SPLITTER_DATABASE_CONNECTION_STRING` row, add:

```markdown
| `SPLITTER_WEBCON_DB_CONNECTION_STRING` | dla trybu słownika WEBCON | ODBC do bazy treści WEBCON (konto tylko-odczyt); razem z ID typu formularza włącza odczyt wzorców ze słownika WEBCON zamiast tabel własnych |
| `SPLITTER_WEBCON_DICT_FORM_TYPE_ID` | dla trybu słownika WEBCON | ID typu formularza procesu słownikowego (`WFD_DTYPEID`) |
| `SPLITTER_WEBCON_DICT_COL_TYPE_NAME` | dla trybu słownika WEBCON | kolumna nagłówka z nazwą typu, np. `WFD_AttText1` |
| `SPLITTER_WEBCON_DICT_COL_TYPE_ACTIVE` | dla trybu słownika WEBCON | kolumna nagłówka z flagą aktywności typu, np. `WFD_AttBool1` |
| `SPLITTER_WEBCON_DICT_COL_PATTERN_HEADER` | dla trybu słownika WEBCON | kolumna listy pozycji z nagłówkiem wzorca, np. `DET_Att1` |
| `SPLITTER_WEBCON_DICT_COL_PATTERN_PHRASES` | dla trybu słownika WEBCON | kolumna listy pozycji z frazami (średniki), np. `DET_Att2` |
| `SPLITTER_WEBCON_DICT_COL_PATTERN_EXCLUDED` | dla trybu słownika WEBCON | kolumna listy pozycji z frazami wykluczającymi, np. `DET_Att3` |
| `SPLITTER_WEBCON_DICT_COL_PATTERN_WEIGHT` | dla trybu słownika WEBCON | kolumna listy pozycji z wagą, np. `DET_Value1` |
| `SPLITTER_WEBCON_DICT_COL_PATTERN_ACTIVE` | dla trybu słownika WEBCON | kolumna listy pozycji z flagą aktywności wzorca, np. `DET_Bool1` |
```

Below the table add one sentence:

```markdown
Konfiguracja słownika WEBCON: patrz `docs/deployment/webcon-dictionary.md`.
Tryb słownika WEBCON ma pierwszeństwo przed `SPLITTER_DATABASE_CONNECTION_STRING`
przy odczycie wzorców; tabele własne pozostają używane dla jobów i feedbacku.
```

- [ ] **Step 3: Update `docs/deployment/sql-server.md`**

Append at the end:

```markdown
## Tryb słownika WEBCON

Gdy skonfigurowano odczyt słowników z procesu WEBCON
(`docs/deployment/webcon-dictionary.md`), tabele `document_type`
i `document_pattern` oraz `seed.sql` są używane wyłącznie w trybie
standalone (praca bez WEBCON-a). Tabele `splitter_job`
i `classification_feedback` są używane zawsze.
```

- [ ] **Step 4: Commit**

```bash
git add docs/deployment/webcon-dictionary.md docs/deployment/splitter-service.md docs/deployment/sql-server.md
git commit -m "docs: WEBCON dictionary setup guide and config reference"
```
