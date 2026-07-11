# Patterns-in-Request Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The SDK plugin reads recognition patterns from a WEBCON data source and sends them with each `POST /api/split`; the splitter uses request-supplied patterns and loses all access to the WEBCON content database.

**Architecture:** The splitter gains an optional multipart form field `patterns` (JSON array) parsed into `DocumentPattern` objects and served through `InMemoryPatternRepository` per request; the SQL-dictionary mode built earlier (`WebconDictionaryPatternRepository`, `SPLITTER_WEBCON_*` settings) is removed. The C# action gains a "Patterns data source ID" config field, executes the data source via `DataSourcesHelper`, maps rows to `PatternPayload` objects, and `SplitterClient` attaches them as the `patterns` form field.

**Tech Stack:** Python 3.11+/FastAPI/pydantic v2/pytest; C# netstandard2.0, WEBCON.BPS.2026.SDK.Libraries 26.1.6.209 (verified: `WebCon.WorkFlow.SDK.Tools.Data.DataSourcesHelper.GetDataTableFromDataSourceAsync(GetDataTableFromDataSourceParams)` returns `Task<DataTable>`; ctor `GetDataTableFromDataSourceParams(int dataSourceId, int? companyId)`; `ConfigEditableDataSourceID` attribute exists), Newtonsoft.Json 13.

Spec: `docs/superpowers/specs/2026-07-11-patterns-in-request-design.md`.

## Global Constraints

- Contract field names are camelCase: `documentType`, `header`, `phrases`, `excludedPhrases`, `weight`.
- `weight` optional, default `1.0`; `excludedPhrases` optional, default `[]`; `active` never travels in the payload (plugin sends only active patterns).
- Phrases travel as JSON string arrays; the semicolon split happens in the plugin only.
- Invalid `patterns` JSON or schema → HTTP 400; the job is finished as `failed` with the message in `technical_error` (existing endpoint try/except already does this).
- No `patterns` field → behavior identical to before this change (factory: own SQL → in-memory).
- Data source contract columns: `DocumentType`, `Header`, `Phrases`, `ExcludedPhrases`, `Weight` — already filtered to active rows.
- Plugin: data source error or missing columns → action error (no silent fallback); zero rows → continue with warning in `args.LogMessage`.
- Splitter tests run from `splitter/`: `python -m pytest tests/ -v`. Plugin verified by `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release`.
- Standalone splitter mode (`document_type`/`document_pattern` tables, `seed.sql`, `SqlServerPatternRepository`) stays untouched.

---

### Task 1: `PatternPayload` model and `parse_patterns_field`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/contracts.py`
- Modify: `splitter/src/webcon_pdf_splitter/api.py`
- Test: `splitter/tests/test_split_patterns.py` (new file)

**Interfaces:**
- Produces: `PatternPayload(BaseModel)` in `webcon_pdf_splitter.contracts` with fields `documentType: str`, `header: str`, `phrases: list[str] = []`, `excludedPhrases: list[str] = []`, `weight: float = 1.0`.
- Produces: `parse_patterns_field(raw: str) -> list[DocumentPattern]` in `webcon_pdf_splitter.api`, raising `ValueError` on invalid JSON or schema; returned patterns have `active=True`. Used by Task 2.

- [ ] **Step 1: Write the failing test**

Create `splitter/tests/test_split_patterns.py`:

```python
import json

import pytest

from webcon_pdf_splitter.api import parse_patterns_field


def test_parse_patterns_field_builds_document_patterns():
    raw = json.dumps(
        [
            {
                "documentType": "Umowa o prace",
                "header": "UMOWA O PRACE",
                "phrases": ["pracodawca", "pracownik"],
                "excludedPhrases": ["aneks"],
                "weight": 1.2,
            }
        ]
    )

    patterns = parse_patterns_field(raw)

    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.document_type == "Umowa o prace"
    assert pattern.header == "UMOWA O PRACE"
    assert pattern.phrases == ["pracodawca", "pracownik"]
    assert pattern.excluded_phrases == ["aneks"]
    assert pattern.weight == 1.2
    assert pattern.active is True


def test_parse_patterns_field_applies_defaults():
    raw = json.dumps([{"documentType": "Typ", "header": "NAGLOWEK"}])

    patterns = parse_patterns_field(raw)

    assert patterns[0].phrases == []
    assert patterns[0].excluded_phrases == []
    assert patterns[0].weight == 1.0


def test_parse_patterns_field_rejects_invalid_json():
    with pytest.raises(ValueError):
        parse_patterns_field("not a json")


def test_parse_patterns_field_rejects_missing_header():
    with pytest.raises(ValueError):
        parse_patterns_field(json.dumps([{"documentType": "Typ"}]))
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `splitter/`): `python -m pytest tests/test_split_patterns.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_patterns_field'`

- [ ] **Step 3: Write minimal implementation**

In `splitter/src/webcon_pdf_splitter/contracts.py`, add after `SplitRequest`:

```python
class PatternPayload(BaseModel):
    documentType: str
    header: str
    phrases: list[str] = Field(default_factory=list)
    excludedPhrases: list[str] = Field(default_factory=list)
    weight: float = 1.0
```

In `splitter/src/webcon_pdf_splitter/api.py`:

Extend the contracts import and add `TypeAdapter`/`ValidationError`:

```python
from pydantic import TypeAdapter, ValidationError

from webcon_pdf_splitter.contracts import FeedbackRequest, PatternPayload, SplitResult
```

Extend the repository import with `DocumentPattern` and `InMemoryPatternRepository`:

```python
from webcon_pdf_splitter.db.repository import (
    DocumentPattern,
    FeedbackEntry,
    InMemoryPatternRepository,
    SplitterJob,
    build_feedback_repository,
    build_job_repository,
    build_pattern_repository,
)
```

Add after `_require_token`:

```python
_PATTERNS_ADAPTER = TypeAdapter(list[PatternPayload])


def parse_patterns_field(raw: str) -> list[DocumentPattern]:
    try:
        payloads = _PATTERNS_ADAPTER.validate_json(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid patterns payload: {exc}") from exc
    return [
        DocumentPattern(
            document_type=payload.documentType,
            header=payload.header,
            phrases=payload.phrases,
            excluded_phrases=payload.excludedPhrases,
            weight=payload.weight,
            active=True,
        )
        for payload in payloads
    ]
```

(`InMemoryPatternRepository` becomes used in Task 2; the import is added now so both tasks compile.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_split_patterns.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/contracts.py splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_split_patterns.py
git commit -m "feat: parse patterns payload into document patterns"
```

---

### Task 2: `/api/split` accepts the `patterns` form field

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/api.py`
- Test: `splitter/tests/test_split_patterns.py`

**Interfaces:**
- Consumes: `parse_patterns_field` from Task 1.
- Produces: `/api/split` with `patterns: str | None = Form(default=None)`; `_split(settings, file, patterns_field)` selects `InMemoryPatternRepository(parsed)` when the field is present, `build_pattern_repository(settings)` otherwise. The C# client (Task 5) sends this field.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_split_patterns.py`:

```python
import io

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from webcon_pdf_splitter import api
from webcon_pdf_splitter.api import app
from webcon_pdf_splitter.db.repository import InMemoryPatternRepository


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class _StubOcr:
    def __init__(self, texts):
        self._texts = texts

    def extract_page_texts(self, path):
        return self._texts


def _umowa_patterns_json() -> str:
    return json.dumps(
        [
            {
                "documentType": "Umowa o prace",
                "header": "UMOWA O PRACE",
                "phrases": ["pracodawca", "pracownik"],
                "weight": 1.2,
            }
        ]
    )


def test_split_uses_patterns_from_request(monkeypatch):
    monkeypatch.setattr(
        api,
        "PdfTextOcrEngine",
        lambda: _StubOcr(["UMOWA O PRACE zawarta pomiedzy pracodawca a pracownikiem"]),
    )
    monkeypatch.setattr(
        api,
        "build_pattern_repository",
        lambda settings: (_ for _ in ()).throw(AssertionError("factory must not be called")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
        data={"patterns": _umowa_patterns_json()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["documents"][0]["documentType"] == "Umowa o prace"


def test_split_without_patterns_falls_back_to_factory(monkeypatch):
    calls = []

    def factory(settings):
        calls.append(settings)
        return InMemoryPatternRepository(patterns=[])

    monkeypatch.setattr(api, "build_pattern_repository", factory)
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert response.json()["documents"][0]["documentType"] == "Nieznany typ dokumentu"


def test_split_rejects_invalid_patterns_json():
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
        data={"patterns": "not a json"},
    )

    assert response.status_code == 400


def test_split_rejects_patterns_with_wrong_schema():
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
        data={"patterns": json.dumps([{"documentType": "Typ"}])},
    )

    assert response.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_split_patterns.py -v`
Expected: the 4 Task-1 tests PASS; `test_split_uses_patterns_from_request` FAILS (factory called → AssertionError → 500) and `test_split_rejects_*` FAIL (200 instead of 400), because the endpoint ignores the `patterns` field.

- [ ] **Step 3: Write minimal implementation**

In `splitter/src/webcon_pdf_splitter/api.py`:

Add `Form` to the fastapi import:

```python
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
```

Change the endpoint signature and the `_split` call:

```python
@app.post("/api/split", response_model=SplitResult)
async def split_pdf_endpoint(
    file: UploadFile = File(...),
    patterns: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> SplitResult:
```

and inside the existing `try` block:

```python
        result = await _split(settings, file, patterns)
```

Change `_split` to select the repository:

```python
async def _split(
    settings: SplitterSettings, file: UploadFile, patterns_field: str | None
) -> SplitResult:
    if patterns_field is not None:
        try:
            provided = parse_patterns_field(patterns_field)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repository = InMemoryPatternRepository(provided)
    else:
        repository = build_pattern_repository(settings)
    pipeline = ClassificationPipeline(
        rule_classifier=RuleBasedClassifier(repository.list_active_patterns()),
        llm_classifier=DisabledLlmClassifier(),
        min_auto_accept_confidence=settings.min_auto_accept_confidence,
        min_review_confidence=settings.min_review_confidence,
    )
```

(The rest of `_split` — OCR, validation, splitting — stays unchanged; only the `repository = build_pattern_repository(settings)` line is replaced by the branch above.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_split_patterns.py -v`
Expected: 8 PASSED

- [ ] **Step 5: Run the full splitter suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASSED (existing `/api/split` tests unaffected — the new field is optional)

- [ ] **Step 6: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_split_patterns.py
git commit -m "feat: accept recognition patterns in split request"
```

---

### Task 3: Remove the SQL-dictionary mode from the splitter

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/config.py`
- Modify: `splitter/src/webcon_pdf_splitter/db/repository.py`
- Modify: `splitter/tests/test_repository_factory.py`
- Delete: `splitter/tests/test_webcon_dictionary.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `build_pattern_repository` back to two branches (own SQL → in-memory); `SplitterSettings` without `webcon_*` fields. No other module references the removed names after Tasks 1-2 (verify with grep in Step 3).

- [ ] **Step 1: Delete the dictionary-mode tests**

```bash
git rm splitter/tests/test_webcon_dictionary.py
```

In `splitter/tests/test_repository_factory.py`: remove `WebconDictionaryPatternRepository` from the import list, and delete `_webcon_kwargs`, `test_factory_prefers_webcon_dictionary_when_configured`, `test_factory_prefers_webcon_dictionary_over_own_database`, `test_factory_ignores_webcon_mode_without_form_type_id`. The file keeps only the two original tests (in-memory without connection string, SQL with connection string).

- [ ] **Step 2: Remove the implementation**

In `splitter/src/webcon_pdf_splitter/config.py` delete the nine fields:

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

In `splitter/src/webcon_pdf_splitter/db/repository.py` delete:

- the `split_phrases` function;
- `logger = logging.getLogger(__name__)` and `_SQL_IDENTIFIER = re.compile(...)`;
- the entire `WebconDictionaryPatternRepository` class;
- `import logging` and `import re`;
- the first branch of the factory, restoring:

```python
def build_pattern_repository(settings: "SplitterSettings") -> PatternRepository:
    if settings.database_connection_string:
        return SqlServerPatternRepository(settings.database_connection_string)
    return InMemoryPatternRepository(patterns=[])
```

- [ ] **Step 3: Verify nothing references the removed names**

Run: `git grep -n "webcon_dict\|WebconDictionaryPatternRepository\|split_phrases\|webcon_db_connection_string" -- splitter/`
Expected: no matches.

- [ ] **Step 4: Run the full splitter suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASSED

- [ ] **Step 5: Commit**

```bash
git add -A splitter/
git commit -m "refactor: remove splitter-side WEBCON dictionary SQL mode"
```

---

### Task 4: `PatternPayload` in plugin contracts and `SplitterClient`

**Files:**
- Modify: `webcon-action/SplitterContracts.cs`
- Modify: `webcon-action/SplitterClient.cs`

**Interfaces:**
- Produces: `PatternPayload` class (`DocumentType`, `Header`, `Phrases`, `ExcludedPhrases`, `Weight`) serialized with camelCase `JsonProperty` names matching the splitter contract; `SplitterClient.SplitAsync(string fileName, Stream pdfStream, int? webconElementId = null, IReadOnlyList<PatternPayload>? patterns = null)`. Task 5 builds the list and passes it.

- [ ] **Step 1: Add `PatternPayload` to `webcon-action/SplitterContracts.cs`**

Append at the end of the file (inside the namespace):

```csharp
public sealed class PatternPayload
{
    [Newtonsoft.Json.JsonProperty("documentType")]
    public string DocumentType { get; set; } = "";

    [Newtonsoft.Json.JsonProperty("header")]
    public string Header { get; set; } = "";

    [Newtonsoft.Json.JsonProperty("phrases")]
    public List<string> Phrases { get; set; } = new();

    [Newtonsoft.Json.JsonProperty("excludedPhrases")]
    public List<string> ExcludedPhrases { get; set; } = new();

    [Newtonsoft.Json.JsonProperty("weight")]
    public double Weight { get; set; } = 1.0;
}
```

- [ ] **Step 2: Extend `SplitterClient.SplitAsync`**

In `webcon-action/SplitterClient.cs`, add `using System.Collections.Generic;` to the usings, change the signature to:

```csharp
    public async Task<SplitResult> SplitAsync(
        string fileName,
        Stream pdfStream,
        int? webconElementId = null,
        IReadOnlyList<PatternPayload>? patterns = null)
```

and after `content.Add(fileContent, "file", fileName);` add:

```csharp
        if (patterns != null)
            content.Add(new StringContent(JsonConvert.SerializeObject(patterns)), "patterns");
```

- [ ] **Step 3: Build to verify**

Run: `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release`
Expected: Build succeeded, 0 errors.

- [ ] **Step 4: Commit**

```bash
git add webcon-action/SplitterContracts.cs webcon-action/SplitterClient.cs
git commit -m "feat: send recognition patterns in splitter client request"
```

---

### Task 5: Action reads the data source and passes patterns

**Files:**
- Modify: `webcon-action/SplitPdfActionConfig.cs`
- Modify: `webcon-action/SplitPdfAction.cs`

**Interfaces:**
- Consumes: `PatternPayload` and the extended `SplitAsync` from Task 4; SDK `DataSourcesHelper` (`WebCon.WorkFlow.SDK.Tools.Data`), `GetDataTableFromDataSourceParams(int, int?)` (`WebCon.WorkFlow.SDK.Tools.Data.Model`).
- Produces: config property `PatternsDataSourceId` (int); private `LoadPatternsAsync(RunCustomActionParams) -> Task<List<PatternPayload>>` in the action.

- [ ] **Step 1: Add the config field**

In `webcon-action/SplitPdfActionConfig.cs`, add after `TimeoutSeconds`:

```csharp
    [ConfigEditableDataSourceID(
        DisplayName = "Patterns data source ID",
        Description = "Zrodlo danych zwracajace aktywne wzorce rozpoznawania ze slownika typow dokumentow. " +
                      "Wymagane kolumny: DocumentType, Header, Phrases, ExcludedPhrases, Weight. " +
                      "Frazy rozdzielane srednikami. Szczegoly: docs/deployment/webcon-dictionary.md.",
        IsRequired = true,
        Order = 7)]
    public int PatternsDataSourceId { get; set; }
```

If the build in Step 3 reports that `ConfigEditableDataSourceID` lacks one of these named properties, fall back to the same shape as the other ID fields:

```csharp
    [ConfigEditableInteger(
        DisplayName = "Patterns data source ID",
        Description = "Zrodlo danych zwracajace aktywne wzorce rozpoznawania ze slownika typow dokumentow. " +
                      "Wymagane kolumny: DocumentType, Header, Phrases, ExcludedPhrases, Weight. " +
                      "Frazy rozdzielane srednikami. Szczegoly: docs/deployment/webcon-dictionary.md.",
        Order = 7)]
    public int PatternsDataSourceId { get; set; }
```

- [ ] **Step 2: Load patterns in the action**

In `webcon-action/SplitPdfAction.cs`:

Add usings:

```csharp
using System.Data;
using System.Globalization;
using WebCon.WorkFlow.SDK.Tools.Data;
using WebCon.WorkFlow.SDK.Tools.Data.Model;
```

In `RunAsync`, after the three `ParseId` lines, add:

```csharp
            var patterns = await LoadPatternsAsync(args);
            var patternsWarning = patterns.Count == 0
                ? "Warning: patterns data source returned no rows; every page will be classified as unknown. "
                : "";
```

Pass patterns to the client (the `SplitAsync` call becomes):

```csharp
                result = await client.SplitAsync(
                    sourceAttachment.FileName,
                    new MemoryStream(pdfContent),
                    args.Context.CurrentDocument.ID,
                    patterns);
```

Prepend the warning to the final log line:

```csharp
            args.LogMessage =
                patternsWarning +
                $"Splitter job {result.JobId}: {result.Status}, pages: {result.PageCount}, " +
                $"documents: {result.Documents.Count}, created elements: {string.Join(", ", createdIds)}";
```

Add the private methods at the end of the class:

```csharp
    private async Task<List<PatternPayload>> LoadPatternsAsync(RunCustomActionParams args)
    {
        var helper = new DataSourcesHelper(args.Context);
        var table = await helper.GetDataTableFromDataSourceAsync(
            new GetDataTableFromDataSourceParams(Configuration.PatternsDataSourceId, null));

        var required = new[] { "DocumentType", "Header", "Phrases", "ExcludedPhrases", "Weight" };
        var missing = required.Where(column => !table.Columns.Contains(column)).ToList();
        if (missing.Count > 0)
            throw new InvalidOperationException(
                $"Patterns data source {Configuration.PatternsDataSourceId} is missing required columns: " +
                $"{string.Join(", ", missing)}. Expected columns: {string.Join(", ", required)}.");

        var patterns = new List<PatternPayload>();
        foreach (DataRow row in table.Rows)
        {
            var header = (row["Header"] as string)?.Trim();
            if (string.IsNullOrEmpty(header))
                continue;

            patterns.Add(new PatternPayload
            {
                DocumentType = (row["DocumentType"] as string)?.Trim() ?? "",
                Header = header!,
                Phrases = SplitPhrases(row["Phrases"]),
                ExcludedPhrases = SplitPhrases(row["ExcludedPhrases"]),
                Weight = row["Weight"] == DBNull.Value || row["Weight"] == null
                    ? 1.0
                    : Convert.ToDouble(row["Weight"], CultureInfo.InvariantCulture),
            });
        }
        return patterns;
    }

    private static List<string> SplitPhrases(object? value) =>
        value is string text
            ? text.Split(';').Select(phrase => phrase.Trim()).Where(phrase => phrase.Length > 0).ToList()
            : new List<string>();
```

- [ ] **Step 3: Build to verify**

Run: `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release`
Expected: Build succeeded, 0 errors. (If `ConfigEditableDataSourceID` property names fail to compile, apply the fallback from Step 1 and rebuild.)

- [ ] **Step 4: Build the deployable package (bumps version.txt)**

Run: `powershell -File webcon-action/package.ps1`
Expected: `Pakiet gotowy: ...\Publish\WebconPdfSplitterAction.zip`; `version.txt` bumped by the script.

- [ ] **Step 5: Commit**

```bash
git add webcon-action/SplitPdfActionConfig.cs webcon-action/SplitPdfAction.cs webcon-action/version.txt
git commit -m "feat: action loads patterns from WEBCON data source"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/deployment/webcon-dictionary.md`
- Modify: `docs/deployment/splitter-service.md`
- Modify: `docs/deployment/webcon-configuration.md`
- Modify: `docs/deployment/sql-server.md`

- [ ] **Step 1: Rework `docs/deployment/webcon-dictionary.md`**

Replace the intro paragraph with:

```markdown
Wzorce rozpoznawania są utrzymywane w procesie słownikowym WEBCON.
Akcja SDK odczytuje je poprzez źródło danych (Designer Studio) i wysyła
razem z PDF-em w każdym wywołaniu `/api/split` — splitter nie ma żadnego
dostępu do bazy treści WEBCON. Zmiany w słowniku działają od następnego
wywołania akcji, bez restartów.
```

Replace the sections "Odczyt ID i nazw kolumn" and "Uprawnienia SQL" with:

```markdown
## Źródło danych wzorców

W Designer Studio utwórz źródło danych (zapytanie SQL do bazy treści),
które zwraca **wyłącznie aktywne** wzorce w kolumnach o dokładnie tych
nazwach:

| Kolumna | Znaczenie |
|---|---|
| `DocumentType` | nazwa typu dokumentu |
| `Header` | nagłówek wzorca (wiersz z pustym nagłówkiem jest pomijany) |
| `Phrases` | frazy rozdzielane średnikami |
| `ExcludedPhrases` | frazy wykluczające rozdzielane średnikami |
| `Weight` | waga wzorca (puste = 1,0) |

Szablon zapytania — dostosuj ID typu formularza i nazwy kolumn atrybutów
(znajdziesz je we właściwościach atrybutów w Designer Studio):

```sql
SELECT
    el.WFD_AttText1  AS DocumentType,
    det.DET_Att1     AS Header,
    det.DET_Att2     AS Phrases,
    det.DET_Att3     AS ExcludedPhrases,
    det.DET_Value1   AS Weight
FROM dbo.WFElements el
JOIN dbo.WFElementDetails det ON det.DET_WFDID = el.WFD_ID
WHERE el.WFD_DTYPEID = 123          -- ID typu formularza slownika
  AND el.WFD_IsDeleted = 0
  AND el.WFD_AttBool1 = 1           -- typ aktywny
  AND det.DET_Bool1 = 1             -- wzorzec aktywny
```

ID tego źródła danych wpisz w konfiguracji akcji SplitPdfAction
(pole "Patterns data source ID").
```

Update the troubleshooting section to:

```markdown
## Rozwiązywanie problemów

- Błąd akcji o brakujących kolumnach → nazwy kolumn w zapytaniu źródła
  muszą brzmieć dokładnie: DocumentType, Header, Phrases, ExcludedPhrases,
  Weight (aliasy `AS`).
- Ostrzeżenie "patterns data source returned no rows" w logu akcji →
  słownik pusty albo wszystkie wpisy nieaktywne; wszystko będzie
  klasyfikowane jako "Nieznany typ dokumentu".
- HTTP 400 od splittera z opisem "Invalid patterns payload" → źródło
  zwraca wartości w złych typach (np. tekst w kolumnie Weight);
  szczegóły w `splitter_job.technical_error`.
```

The dictionary-process section and the seed-data table stay unchanged.

- [ ] **Step 2: Update `docs/deployment/splitter-service.md`**

Delete the nine `SPLITTER_WEBCON_*` rows from the env var table and the paragraph:

```markdown
Konfiguracja słownika WEBCON: patrz `docs/deployment/webcon-dictionary.md`.
Tryb słownika WEBCON ma pierwszeństwo przed `SPLITTER_DATABASE_CONNECTION_STRING`
przy odczycie wzorców; tabele własne pozostają używane dla jobów i feedbacku.
```

Replace that paragraph with:

```markdown
Wzorce rozpoznawania przychodzą w żądaniu z akcji WEBCON (pole `patterns`);
patrz `docs/deployment/webcon-dictionary.md`. Gdy żądanie nie zawiera wzorców,
serwis używa tabel własnych (`SPLITTER_DATABASE_CONNECTION_STRING`) albo pustej
listy.
```

- [ ] **Step 3: Update `docs/deployment/webcon-configuration.md`**

Add a row to the action-configuration table after "Start path ID":

```markdown
| Patterns data source ID | tak | Źródło danych zwracające aktywne wzorce (kolumny: DocumentType, Header, Phrases, ExcludedPhrases, Weight) | Designer Studio → Źródła danych → właściwości → ID; szablon zapytania w `docs/deployment/webcon-dictionary.md` |
```

- [ ] **Step 4: Update `docs/deployment/sql-server.md`**

Replace the "Tryb słownika WEBCON" section with:

```markdown
## Wzorce ze słownika WEBCON

Wzorce rozpoznawania dostarcza akcja SDK w każdym żądaniu (odczyt przez
źródło danych — `docs/deployment/webcon-dictionary.md`); splitter nie
potrzebuje żadnych uprawnień do bazy treści WEBCON. Tabele `document_type`
i `document_pattern` oraz `seed.sql` służą wyłącznie do pracy standalone
(bez WEBCON-a). Tabele `splitter_job` i `classification_feedback` są
używane zawsze.
```

- [ ] **Step 5: Commit**

```bash
git add docs/deployment/webcon-dictionary.md docs/deployment/splitter-service.md docs/deployment/webcon-configuration.md docs/deployment/sql-server.md
git commit -m "docs: patterns delivered by SDK action via data source"
```
