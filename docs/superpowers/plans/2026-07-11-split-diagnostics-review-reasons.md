# Split Diagnostics + Review Reasons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Docker logs show the full page-by-page split decision path, and every document requiring review carries human-readable reasons — in the API response (`reviewReasons`) and written to form fields on the WEBCON sub-workflows.

**Architecture:** The Python splitter's `ClassificationPipeline` gains INFO logging at each decision branch and a `_review_reasons` helper populating a new `reviewReasons` list on `DetectedDocument`. `api.py` configures root logging (uvicorn does not, so app logs currently never reach `docker logs`). The C# WEBCON action deserializes `ReviewReasons`, appends them to the element comment, and optionally writes two configured form fields on each created sub-workflow before starting it.

**Tech Stack:** Python 3 / FastAPI / pydantic / pytest (splitter); C# netstandard2.0 / WEBCON BPS 2026 SDK 26.1.6.209 / Newtonsoft.Json (plugin).

## Global Constraints

- Reason strings are Polish without diacritics, consistent with existing `warnings` style (spec §2).
- Never log page text content — only decisions, types, confidence, signals (spec: HR personal data).
- `reviewReasons` is empty exactly when `requiresReview` is false; compute reasons only for documents already flagged for review.
- Plugin: new config fields are optional; value 0/empty means "skip writing this field" (backward compatible).
- Splitter tests run from `splitter/` directory: `python -m pytest tests -v`.
- Plugin build runs from `webcon-action/` directory: `dotnet build WebconPdfSplitterAction.csproj -c Release`.

---

### Task 1: `reviewReasons` in contract + pipeline population

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/contracts.py` (class `DetectedDocument`)
- Modify: `splitter/src/webcon_pdf_splitter/classification/pipeline.py` (documents construction, new `_review_reasons` helper)
- Test: `splitter/tests/test_pipeline.py`, `splitter/tests/test_contracts.py`

**Interfaces:**
- Consumes: existing `_Segment` dataclass (`known: bool`, `confidence: float`, `glued_pages: list[int]`), `self._min_auto_accept_confidence: float`.
- Produces: `DetectedDocument.reviewReasons: list[str]` (pydantic field, default `[]`) — Task 2 logs it, Task 4 deserializes it in C# as `ReviewReasons`.

- [ ] **Step 1: Write the failing tests**

Append to `splitter/tests/test_pipeline.py` (uses existing `_make_pipeline` and `_StubLlm` helpers already in that file; add `from webcon_pdf_splitter.classification.llm import LlmClassification` only if not already imported — it is, line 1):

```python
def test_review_reasons_empty_for_auto_accepted_document():
    result = _make_pipeline().split_pages(
        "scan.pdf", ["UMOWA O PRACE zawarta z pracodawca"]
    )

    doc = result.documents[0]
    assert doc.requiresReview is False
    assert doc.reviewReasons == []


def test_review_reasons_for_glued_page():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "obcy zalacznik bez fraz"],
    )

    doc = result.documents[0]
    assert doc.requiresReview is True
    assert doc.reviewReasons == ["strona 2 doklejona bez dopasowania do wzorca"]


def test_review_reasons_for_low_confidence_document():
    stub = _StubLlm(
        responses={
            "PISMO PRZEWODNIE tresc": LlmClassification(
                isFirstPage=True,
                documentType="Pismo przewodnie",
                isKnownType=False,
                confidence=0.85,
                reasonCodes=["layout"],
            )
        }
    )
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "PISMO PRZEWODNIE tresc"],
    )

    pismo = result.documents[1]
    assert pismo.requiresReview is True
    assert pismo.reviewReasons == [
        "pewnosc 0.85 ponizej progu auto-akceptacji 0.90"
    ]


def test_review_reasons_for_unknown_document():
    result = _make_pipeline().split_pages("scan.pdf", ["obca 1", "obca 2"])

    doc = result.documents[0]
    assert doc.requiresReview is True
    assert doc.reviewReasons == [
        "nierozpoznany typ dokumentu (zadna regula nie pasowala)",
        "pewnosc 0.20 ponizej progu auto-akceptacji 0.90",
    ]
```

Append to `splitter/tests/test_contracts.py`:

```python
def test_detected_document_review_reasons_default_and_serialization():
    document = DetectedDocument(
        documentIndex=1,
        documentType="Nieznany typ dokumentu",
        confidence=0.20,
        requiresReview=True,
        startPage=1,
        endPage=2,
        outputFileName="001_Nieznany_typ_dokumentu_strony_001-002.pdf",
    )
    assert document.reviewReasons == []

    document.reviewReasons = ["nierozpoznany typ dokumentu (zadna regula nie pasowala)"]
    payload = document.model_dump()
    assert payload["reviewReasons"] == [
        "nierozpoznany typ dokumentu (zadna regula nie pasowala)"
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run (in `splitter/`): `python -m pytest tests/test_pipeline.py tests/test_contracts.py -v`
Expected: the 5 new tests FAIL (pydantic `ValidationError`/`AttributeError`: no field `reviewReasons`); all existing tests PASS.

- [ ] **Step 3: Add the contract field**

In `splitter/src/webcon_pdf_splitter/contracts.py`, class `DetectedDocument`, add after the `requiresReview: bool` line:

```python
    reviewReasons: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Populate reasons in the pipeline**

In `splitter/src/webcon_pdf_splitter/classification/pipeline.py`, replace the `documents = [...]` list comprehension (lines 98–114) with an explicit loop:

```python
        documents: list[DetectedDocument] = []
        for document_index, segment in enumerate(segments, start=1):
            requires_review = (
                segment.forced_review
                or segment.confidence < self._min_auto_accept_confidence
            )
            documents.append(
                DetectedDocument(
                    documentIndex=document_index,
                    documentType=segment.document_type,
                    confidence=segment.confidence,
                    requiresReview=requires_review,
                    reviewReasons=self._review_reasons(segment) if requires_review else [],
                    startPage=segment.start_page,
                    endPage=segment.end_page,
                    outputFileName=self._file_name(
                        document_index, segment.document_type, segment.start_page, segment.end_page
                    ),
                    signals=segment.signals,
                    metadata={},
                )
            )
```

Add this method to `ClassificationPipeline` (below `_try_llm`, above `_file_name`):

```python
    def _review_reasons(self, segment: _Segment) -> list[str]:
        reasons: list[str] = []
        if not segment.known:
            reasons.append("nierozpoznany typ dokumentu (zadna regula nie pasowala)")
        for page in segment.glued_pages:
            reasons.append(f"strona {page} doklejona bez dopasowania do wzorca")
        if segment.confidence < self._min_auto_accept_confidence:
            reasons.append(
                f"pewnosc {segment.confidence:.2f} ponizej progu auto-akceptacji "
                f"{self._min_auto_accept_confidence:.2f}"
            )
        return reasons
```

- [ ] **Step 5: Run tests to verify they pass**

Run (in `splitter/`): `python -m pytest tests -v`
Expected: all PASS (including all pre-existing tests — the loop must behave identically to the old comprehension for `requiresReview`).

- [ ] **Step 6: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/contracts.py splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/tests/test_pipeline.py splitter/tests/test_contracts.py
git commit -m "feat: reviewReasons on detected documents"
```

---

### Task 2: Per-page decision logs + summary logs (INFO)

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/pipeline.py` (`split_pages` branches + end of method)
- Test: `splitter/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `logger` already defined in pipeline.py (`logging.getLogger(__name__)` → logger name `webcon_pdf_splitter.classification.pipeline`); `DetectedDocument.reviewReasons` from Task 1.
- Produces: INFO log lines (Polish, no diacritics) — no code consumes them; Task 3 makes them visible in docker logs.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_pipeline.py` (add `import logging` at the top of the file):

```python
def test_logs_page_decisions_and_summary(caplog):
    with caplog.at_level(logging.INFO, logger="webcon_pdf_splitter.classification.pipeline"):
        _make_pipeline().split_pages(
            "scan.pdf",
            ["UMOWA O PRACE zawarta z pracodawca", "obcy zalacznik bez fraz"],
        )

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        m.startswith("Strona 1: pierwsza strona 'Umowa o prace' (regula, confidence")
        for m in messages
    )
    assert (
        "Strona 2: brak dopasowania -> doklejona do 'Umowa o prace', wymuszona weryfikacja"
        in messages
    )
    assert any(
        m.startswith("Dokument 1: 'Umowa o prace', strony 1-2,") and "weryfikacja: TAK" in m
        for m in messages
    )
    assert (
        "Podzial 'scan.pdf' zakonczony: 2 stron, 1 dokumentow, status=requires_review"
        in messages
    )


def test_logs_llm_and_unknown_decisions(caplog):
    stub = _StubLlm(
        responses={
            "PISMO PRZEWODNIE tresc": LlmClassification(
                isFirstPage=True,
                documentType="Pismo przewodnie",
                isKnownType=False,
                confidence=0.85,
                reasonCodes=["layout"],
            )
        }
    )
    with caplog.at_level(logging.INFO, logger="webcon_pdf_splitter.classification.pipeline"):
        _make_pipeline(llm_classifier=stub).split_pages(
            "scan.pdf",
            ["obca strona", "UMOWA O PRACE zawarta z pracodawca", "PISMO PRZEWODNIE tresc"],
        )

    messages = [record.getMessage() for record in caplog.records]
    assert "Strona 1: brak dopasowania -> nowy nieznany segment" in messages
    assert (
        "Strona 3: LLM -> pierwsza strona 'Pismo przewodnie' (confidence 0.85, reasonCodes: layout)"
        in messages
    )
```

Note: in the second test page 1 is unknown, so the pipeline calls the LLM stub for it too; the stub returns `None` for unseen texts, which falls through to the unknown-segment branch — exactly the path being asserted.

- [ ] **Step 2: Run tests to verify they fail**

Run (in `splitter/`): `python -m pytest tests/test_pipeline.py -k "logs" -v`
Expected: both FAIL (no log records captured).

- [ ] **Step 3: Add the log statements**

In `splitter/src/webcon_pdf_splitter/classification/pipeline.py`, modify `split_pages`:

In the `if page.is_first_page:` branch, right before `segments.append(current)`:

```python
                logger.info(
                    "Strona %s: pierwsza strona '%s' (regula, confidence %.2f, sygnaly: %s)",
                    page_number,
                    page.document_type,
                    page.confidence,
                    ", ".join(page.signals),
                )
```

In the phrase-affinity continuation branch (`if current is not None and current.known and current.document_type in page.phrase_affinities:`), before `continue`:

```python
                logger.info(
                    "Strona %s: kontynuacja '%s' (dopasowanie fraz)",
                    page_number,
                    current.document_type,
                )
```

In the LLM block, in the `if llm.isFirstPage:` branch right before `segments.append(current)`:

```python
                    logger.info(
                        "Strona %s: LLM -> pierwsza strona '%s' (confidence %.2f, reasonCodes: %s)",
                        page_number,
                        llm.documentType,
                        llm.confidence,
                        ", ".join(llm.reasonCodes),
                    )
```

In the LLM continuation branch (`if current is not None and current.known and llm.documentType == current.document_type:`), before `continue`:

```python
                    logger.info(
                        "Strona %s: LLM -> kontynuacja '%s' (confidence %.2f)",
                        page_number,
                        llm.documentType,
                        llm.confidence,
                    )
```

In the glue branch (`if current is not None and current.known:` at the bottom of the loop), after `current.signals.append(...)`:

```python
                logger.info(
                    "Strona %s: brak dopasowania -> doklejona do '%s', wymuszona weryfikacja",
                    page_number,
                    current.document_type,
                )
```

In the unknown-continuation branch (`elif current is not None and not current.known:`), after `current.end_page = page_number`:

```python
                logger.info(
                    "Strona %s: brak dopasowania -> kontynuacja nieznanego segmentu", page_number
                )
```

In the new-unknown-segment `else:` branch, after `segments.append(current)`:

```python
                logger.info(
                    "Strona %s: brak dopasowania -> nowy nieznany segment", page_number
                )
```

After the `documents` loop (from Task 1) and after `status` is computed — i.e. right before `return SplitResult(...)` — add the summary block (move the existing `status = ...` line above it if needed):

```python
        for document in documents:
            if document.requiresReview:
                logger.info(
                    "Dokument %s: '%s', strony %s-%s, confidence %.2f, weryfikacja: TAK (powody: %s)",
                    document.documentIndex,
                    document.documentType,
                    document.startPage,
                    document.endPage,
                    document.confidence,
                    "; ".join(document.reviewReasons),
                )
            else:
                logger.info(
                    "Dokument %s: '%s', strony %s-%s, confidence %.2f, weryfikacja: NIE",
                    document.documentIndex,
                    document.documentType,
                    document.startPage,
                    document.endPage,
                    document.confidence,
                )
        logger.info(
            "Podzial '%s' zakonczony: %s stron, %s dokumentow, status=%s",
            source_file_name,
            len(page_texts),
            len(documents),
            status,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run (in `splitter/`): `python -m pytest tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/tests/test_pipeline.py
git commit -m "feat: log split decisions per page and result summary"
```

---

### Task 3: Logging configuration (make app logs reach docker logs)

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/config.py` (new `log_level` setting)
- Modify: `splitter/src/webcon_pdf_splitter/api.py` (new `configure_logging`, called at import)
- Modify: `docs/deployment/splitter-service.md` (env var table row)
- Test: `splitter/tests/test_config_logging.py` (new file)

**Interfaces:**
- Consumes: `SplitterSettings` (pydantic-settings, env prefix `SPLITTER_`), `get_settings()` in api.py.
- Produces: `SplitterSettings.log_level: str = "INFO"` (env: `SPLITTER_LOG_LEVEL`); `configure_logging(settings: SplitterSettings) -> None` in `api.py`.

- [ ] **Step 1: Write the failing tests**

Create `splitter/tests/test_config_logging.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run (in `splitter/`): `python -m pytest tests/test_config_logging.py -v`
Expected: FAIL (`log_level` unknown / `configure_logging` not defined).

- [ ] **Step 3: Implement**

In `splitter/src/webcon_pdf_splitter/config.py`, add to `SplitterSettings` (after `api_token`):

```python
    log_level: str = Field(default="INFO")
```

In `splitter/src/webcon_pdf_splitter/api.py`:

Add `import logging` to the imports (first import block).

Add after the `get_settings` function definition and replace the bare `app = FastAPI(...)` line so ordering is: settings → logging → app:

```python
def configure_logging(settings: SplitterSettings) -> None:
    # uvicorn configures only its own loggers; without this, application
    # logger.info(...) calls never reach docker logs.
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


configure_logging(get_settings())

app = FastAPI(title="WEBCON PDF Splitter")
```

(`force=True` is required: repeated calls — e.g. in tests — must reconfigure the root logger; without it `basicConfig` is a no-op once handlers exist.)

- [ ] **Step 4: Run tests to verify they pass**

Run (in `splitter/`): `python -m pytest tests -v`
Expected: all PASS.

- [ ] **Step 5: Document the env var**

In `docs/deployment/splitter-service.md`, add a row to the env var table (after the `SPLITTER_LLM_ENDPOINT`/`SPLITTER_LLM_MODEL` row, matching the table's existing style):

```markdown
| `SPLITTER_LOG_LEVEL` | nie (INFO) | Poziom logów aplikacji widocznych w `docker logs` (`DEBUG`/`INFO`/`WARNING`/`ERROR`); na INFO serwis loguje decyzję klasyfikacji dla każdej strony i podsumowanie podziału z powodami weryfikacji |
```

- [ ] **Step 6: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/config.py splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_config_logging.py docs/deployment/splitter-service.md
git commit -m "fix: configure root logging so app logs reach docker logs"
```

---

### Task 4: Plugin — `ReviewReasons` contract + extended comment

**Files:**
- Modify: `webcon-action/SplitterContracts.cs` (class `DetectedDocument`)
- Modify: `webcon-action/SplitPdfAction.cs` (`FormatDetectionComment`)

**Interfaces:**
- Consumes: splitter JSON response field `reviewReasons` (Task 1). Newtonsoft.Json matches C# `ReviewReasons` to `reviewReasons` case-insensitively — no attribute needed (same as existing properties).
- Produces: `DetectedDocument.ReviewReasons: List<string>` (default empty — old splitter responses without the field must deserialize to an empty list, hence the `= new()` initializer). Task 5 writes it to form fields.

There are no unit tests in the plugin project; the verification step is a Release build.

- [ ] **Step 1: Add the contract property**

In `webcon-action/SplitterContracts.cs`, class `DetectedDocument`, add after `public bool RequiresReview { get; set; }`:

```csharp
    public List<string> ReviewReasons { get; set; } = new();
```

- [ ] **Step 2: Extend the comment**

In `webcon-action/SplitPdfAction.cs`, replace `FormatDetectionComment` (expression-bodied method at the bottom of the class):

```csharp
    private static string FormatDetectionComment(DetectedDocument detected)
    {
        var comment =
            $"Type: {detected.DocumentType}; pages {detected.StartPage}-{detected.EndPage}; " +
            $"confidence {detected.Confidence:0.00}; requires review: {detected.RequiresReview}";
        if (detected.ReviewReasons.Count > 0)
            comment += $"; review reasons: {string.Join("; ", detected.ReviewReasons)}";
        return comment;
    }
```

- [ ] **Step 3: Build to verify**

Run (in `webcon-action/`): `dotnet build WebconPdfSplitterAction.csproj -c Release`
Expected: `Build succeeded. 0 Warning(s). 0 Error(s)` (nullable warnings would fail the expectation — fix them, don't suppress).

- [ ] **Step 4: Commit**

```bash
git add webcon-action/SplitterContracts.cs webcon-action/SplitPdfAction.cs
git commit -m "feat(plugin): deserialize review reasons and include them in element comment"
```

---

### Task 5: Plugin — optional form field mappings + docs

**Files:**
- Modify: `webcon-action/SplitPdfActionConfig.cs` (two new properties)
- Modify: `webcon-action/SplitPdfAction.cs` (`RunAsync` loop)
- Modify: `docs/deployment/webcon-configuration.md` (config table rows)

**Interfaces:**
- Consumes: `DetectedDocument.ReviewReasons` (Task 4); SDK `NewDocumentData.SetFieldValueAsync(int fieldID, object value, CultureInfo culture = null)` (verified against WEBCON BPS 2026 SDK 26.1.6.209); `ConfigEditableFormFieldID` attribute from `WebCon.WorkFlow.SDK.ConfigAttributes`.
- Produces: `SplitPdfActionConfig.RequiresReviewFieldId: int`, `SplitPdfActionConfig.ReviewReasonsFieldId: int` (0 = not configured = skip).

- [ ] **Step 1: Add the config properties**

In `webcon-action/SplitPdfActionConfig.cs`, add after the `PatternsDataSourceId` property (keep the existing attribute style; note descriptions are ASCII-only like the rest of the file):

```csharp
    [ConfigEditableFormFieldID(
        DisplayName = "Requires review field ID",
        Description = "Opcjonalne: pole formularza typu tak/nie w obiegu docelowym, w ktore akcja " +
                      "zapisze, czy dokument wymaga weryfikacji operatora. " +
                      "Zostaw puste, aby nie zapisywac.",
        Order = 8)]
    public int RequiresReviewFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Review reasons field ID",
        Description = "Opcjonalne: pole tekstowe (najlepiej wieloliniowe) w obiegu docelowym, " +
                      "w ktore akcja zapisze powody weryfikacji, jeden na linie. " +
                      "Zostaw puste, aby nie zapisywac.",
        Order = 9)]
    public int ReviewReasonsFieldId { get; set; }
```

- [ ] **Step 2: Write the fields on each new sub-workflow**

In `webcon-action/SplitPdfAction.cs`, in `RunAsync`, inside the `foreach (var detected in result.Documents)` loop, after the `await newDocument.Comment.AddCommentAsync(...)` line and before `StartNewWorkFlowAsync`:

```csharp
                if (Configuration.RequiresReviewFieldId > 0)
                    await newDocument.SetFieldValueAsync(
                        Configuration.RequiresReviewFieldId, detected.RequiresReview);

                if (Configuration.ReviewReasonsFieldId > 0)
                    await newDocument.SetFieldValueAsync(
                        Configuration.ReviewReasonsFieldId,
                        string.Join(Environment.NewLine, detected.ReviewReasons));
```

- [ ] **Step 3: Build to verify**

Run (in `webcon-action/`): `dotnet build WebconPdfSplitterAction.csproj -c Release`
Expected: `Build succeeded. 0 Warning(s). 0 Error(s)`.

- [ ] **Step 4: Document the new config fields**

In `docs/deployment/webcon-configuration.md`, add two rows at the end of the action config table (after the `Timeout in seconds` row, same style):

```markdown
| Requires review field ID | nie | Pole tak/nie w obiegu Dokument HR, w które akcja zapisuje `requiresReview` splittera | Designer Studio → atrybuty obiegu docelowego → właściwości pola → ID; puste = pomijane |
| Review reasons field ID | nie | Pole tekstowe (wieloliniowe) w obiegu Dokument HR na powody weryfikacji (jeden na linię) | Designer Studio → atrybuty obiegu docelowego → właściwości pola → ID; puste = pomijane |
```

- [ ] **Step 5: Commit**

```bash
git add webcon-action/SplitPdfActionConfig.cs webcon-action/SplitPdfAction.cs docs/deployment/webcon-configuration.md
git commit -m "feat(plugin): write review flag and reasons to sub-workflow form fields"
```

---

### Task 6: Package the plugin (auto-bumps version to 1.0.6)

**Files:**
- Modify: `webcon-action/version.txt` (auto-incremented by the script)

**Interfaces:**
- Consumes: `webcon-action/package.ps1` — reads `version.txt` (currently `1.0.5`), increments the last segment, rebuilds in Release with that version, produces the plugin package.
- Produces: plugin package for WEBCON Designer Studio import, `version.txt` = `1.0.6`.

- [ ] **Step 1: Run the packaging script**

Run (in `webcon-action/`, PowerShell): `./package.ps1`
Expected: output contains `Wersja pakietu: 1.0.6` and the build succeeds; a package file is produced (same location as previous releases).

- [ ] **Step 2: Commit the version bump**

```bash
git add webcon-action/version.txt
git commit -m "chore(plugin): release 1.0.6"
```

Manual follow-up (deployment, not part of this plan): import the 1.0.6 package in Designer Studio, create the two form fields in the target HR workflow, and set their IDs in the action configuration.
