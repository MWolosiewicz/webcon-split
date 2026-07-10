# WEBCON PDF Splitter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MVP that lets WEBCON send a scanned bundle PDF to a local splitter, detect document boundaries, split the PDF, and create auditable results using SQL Server-backed document patterns and feedback.

**Architecture:** WEBCON remains the workflow and document system. A C# WEBCON Custom Action calls a local Python/FastAPI splitter service. The splitter uses OCR, deterministic rules, SQL Server patterns, and an optional local LLM fallback behind a stable interface.

**Tech Stack:** Python 3.11+, FastAPI, pytest, pydantic, pyodbc or SQLAlchemy with SQL Server, pypdf, local OCR adapter, optional OpenAI-compatible local LLM endpoint, C#/.NET for WEBCON SDK Custom Action.

## Global Constraints

- HR PDFs must not be sent to external services.
- OCR, classification, LLM calls, and PDF splitting run locally.
- The solution uses a dedicated SQL Server database, e.g. `WebconPdfSplitter`, on the same SQL Server infrastructure as WEBCON.
- Do not write custom technical tables into WEBCON system databases.
- The MVP keeps local LLM disabled by default with `LLM_ENABLED=false`.
- The LLM integration must be replaceable and must accept an OpenAI-compatible local endpoint or an adapter for Ollama/vLLM.
- The original bundle PDF must never be deleted or overwritten.
- Low-confidence results must be marked for operator review.
- Logs must not contain full HR document text.

---

## File Structure

Create the Python splitter under `splitter/`:

- `splitter/pyproject.toml`: Python package metadata, dependencies, pytest config.
- `splitter/src/webcon_pdf_splitter/config.py`: environment-based settings.
- `splitter/src/webcon_pdf_splitter/contracts.py`: request/response DTOs shared by API and tests.
- `splitter/src/webcon_pdf_splitter/db/schema.sql`: SQL Server DDL for solution tables.
- `splitter/src/webcon_pdf_splitter/db/repository.py`: SQL access boundary for document types, patterns, jobs, and feedback.
- `splitter/src/webcon_pdf_splitter/classification/rules.py`: deterministic first-page/type classifier.
- `splitter/src/webcon_pdf_splitter/classification/llm.py`: optional local LLM classifier interface and HTTP implementation.
- `splitter/src/webcon_pdf_splitter/classification/pipeline.py`: combines rules, optional LLM, thresholds, and page grouping.
- `splitter/src/webcon_pdf_splitter/pdf_io.py`: PDF validation and split operations.
- `splitter/src/webcon_pdf_splitter/ocr.py`: OCR interface and stub/Tesseract adapter boundary.
- `splitter/src/webcon_pdf_splitter/api.py`: FastAPI endpoints.
- `splitter/tests/`: pytest tests.

Create the WEBCON action under `webcon-action/`:

- `webcon-action/WebconPdfSplitterAction.csproj`: C# project file aligned to the target WEBCON SDK after environment confirmation.
- `webcon-action/SplitPdfAction.cs`: Custom Action entry point.
- `webcon-action/SplitterClient.cs`: HTTP client for local splitter.
- `webcon-action/SplitterContracts.cs`: C# DTOs matching splitter response.

Create deployment docs under `docs/deployment/`:

- `docs/deployment/sql-server.md`: database creation and permissions.
- `docs/deployment/splitter-service.md`: service configuration and local runtime.
- `docs/deployment/webcon-configuration.md`: WEBCON process/action configuration.

---

### Task 1: Python Splitter Scaffold And Contracts

**Files:**
- Create: `splitter/pyproject.toml`
- Create: `splitter/src/webcon_pdf_splitter/__init__.py`
- Create: `splitter/src/webcon_pdf_splitter/config.py`
- Create: `splitter/src/webcon_pdf_splitter/contracts.py`
- Create: `splitter/tests/test_contracts.py`

**Interfaces:**
- Produces: `SplitRequest`, `SplitResult`, `DetectedDocument`, `SplitterSettings`.
- Later tasks consume these DTOs in API, pipeline, and WEBCON client tests.

- [x] **Step 1: Write the contract tests**

Create `splitter/tests/test_contracts.py`:

```python
from webcon_pdf_splitter.contracts import DetectedDocument, SplitResult


def test_split_result_serializes_required_fields():
    result = SplitResult(
        sourceFileName="scan.pdf",
        pageCount=3,
        status="requires_review",
        documents=[
            DetectedDocument(
                documentIndex=1,
                documentType="Umowa o prace",
                confidence=0.91,
                requiresReview=False,
                startPage=1,
                endPage=3,
                outputFileName="001_Umowa_o_prace_strony_001-003.pdf",
                signals=["header_match:UMOWA O PRACE"],
                metadata={"employeeName": "Jan Kowalski"},
            )
        ],
        warnings=[],
    )

    payload = result.model_dump()

    assert payload["sourceFileName"] == "scan.pdf"
    assert payload["documents"][0]["startPage"] == 1
    assert payload["documents"][0]["requiresReview"] is False
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
cd splitter
python -m pytest tests/test_contracts.py -v
```

Expected: FAIL because `webcon_pdf_splitter.contracts` does not exist.

- [x] **Step 3: Add package configuration**

Create `splitter/pyproject.toml`:

```toml
[project]
name = "webcon-pdf-splitter"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "python-multipart>=0.0.9",
  "pypdf>=4.3",
  "requests>=2.32",
  "pyodbc>=5.1",
]

[project.optional-dependencies]
test = [
  "pytest>=8.3",
  "pytest-cov>=5.0",
]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

Create `splitter/src/webcon_pdf_splitter/__init__.py`:

```python
__all__ = ["contracts", "config"]
```

- [x] **Step 4: Add settings and contracts**

Create `splitter/src/webcon_pdf_splitter/config.py`:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SplitterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPLITTER_", env_file=".env")

    database_connection_string: str = Field(default="")
    work_dir: str = Field(default="./work")
    min_auto_accept_confidence: float = Field(default=0.90)
    min_review_confidence: float = Field(default=0.70)
    llm_enabled: bool = Field(default=False)
    llm_endpoint: str = Field(default="")
    llm_model: str = Field(default="")
    api_token: str = Field(default="")
```

Create `splitter/src/webcon_pdf_splitter/contracts.py`:

```python
from typing import Any, Literal

from pydantic import BaseModel, Field


SplitStatus = Literal["completed", "requires_review", "failed"]


class SplitRequest(BaseModel):
    sourceFileName: str
    webconElementId: int | None = None


class DetectedDocument(BaseModel):
    documentIndex: int = Field(ge=1)
    documentType: str
    confidence: float = Field(ge=0.0, le=1.0)
    requiresReview: bool
    startPage: int = Field(ge=1)
    endPage: int = Field(ge=1)
    outputFileName: str
    signals: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SplitResult(BaseModel):
    sourceFileName: str
    pageCount: int = Field(ge=0)
    status: SplitStatus
    documents: list[DetectedDocument]
    warnings: list[str] = Field(default_factory=list)
```

- [x] **Step 5: Run test to verify it passes**

Run:

```powershell
cd splitter
python -m pytest tests/test_contracts.py -v
```

Expected: PASS.

- [x] **Step 6: Commit**

If the workspace has been initialized as a git repo, run:

```powershell
git add splitter/pyproject.toml splitter/src splitter/tests/test_contracts.py
git commit -m "feat: add splitter contracts"
```

---

### Task 2: SQL Server Schema And Repository Boundary

**Files:**
- Create: `splitter/src/webcon_pdf_splitter/db/__init__.py`
- Create: `splitter/src/webcon_pdf_splitter/db/schema.sql`
- Create: `splitter/src/webcon_pdf_splitter/db/repository.py`
- Create: `splitter/tests/test_repository_mapping.py`

**Interfaces:**
- Consumes: `SplitterSettings.database_connection_string`.
- Produces: `DocumentType`, `DocumentPattern`, `InMemoryPatternRepository`, `SqlServerPatternRepository`.
- Later tasks consume repository method `list_active_patterns() -> list[DocumentPattern]`.

- [x] **Step 1: Write repository mapping tests**

Create `splitter/tests/test_repository_mapping.py`:

```python
from webcon_pdf_splitter.db.repository import DocumentPattern, InMemoryPatternRepository


def test_in_memory_repository_returns_only_active_patterns():
    repository = InMemoryPatternRepository(
        patterns=[
            DocumentPattern(
                document_type="Umowa o prace",
                header="UMOWA O PRACE",
                phrases=["pracownik", "pracodawca"],
                excluded_phrases=[],
                weight=1.0,
                active=True,
            ),
            DocumentPattern(
                document_type="Nieaktywny",
                header="NIEAKTYWNY",
                phrases=[],
                excluded_phrases=[],
                weight=1.0,
                active=False,
            ),
        ]
    )

    patterns = repository.list_active_patterns()

    assert len(patterns) == 1
    assert patterns[0].document_type == "Umowa o prace"
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
cd splitter
python -m pytest tests/test_repository_mapping.py -v
```

Expected: FAIL because repository classes do not exist.

- [x] **Step 3: Add SQL Server schema**

Create `splitter/src/webcon_pdf_splitter/db/schema.sql`:

```sql
CREATE TABLE dbo.document_type (
    document_type_id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_document_type PRIMARY KEY,
    name NVARCHAR(200) NOT NULL,
    is_active BIT NOT NULL CONSTRAINT DF_document_type_is_active DEFAULT (1),
    auto_accept_threshold DECIMAL(5,4) NOT NULL CONSTRAINT DF_document_type_threshold DEFAULT (0.9000),
    target_workflow NVARCHAR(200) NULL,
    target_attachment_category NVARCHAR(200) NULL,
    created_at DATETIME2(0) NOT NULL CONSTRAINT DF_document_type_created_at DEFAULT (SYSUTCDATETIME()),
    updated_at DATETIME2(0) NOT NULL CONSTRAINT DF_document_type_updated_at DEFAULT (SYSUTCDATETIME())
);

CREATE TABLE dbo.document_pattern (
    document_pattern_id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_document_pattern PRIMARY KEY,
    document_type_id INT NOT NULL CONSTRAINT FK_document_pattern_type REFERENCES dbo.document_type(document_type_id),
    header NVARCHAR(500) NOT NULL,
    phrases_json NVARCHAR(MAX) NOT NULL CONSTRAINT DF_document_pattern_phrases DEFAULT (N'[]'),
    excluded_phrases_json NVARCHAR(MAX) NOT NULL CONSTRAINT DF_document_pattern_excluded DEFAULT (N'[]'),
    weight DECIMAL(8,4) NOT NULL CONSTRAINT DF_document_pattern_weight DEFAULT (1.0000),
    source NVARCHAR(50) NOT NULL,
    is_active BIT NOT NULL CONSTRAINT DF_document_pattern_is_active DEFAULT (1),
    created_at DATETIME2(0) NOT NULL CONSTRAINT DF_document_pattern_created_at DEFAULT (SYSUTCDATETIME())
);

CREATE TABLE dbo.splitter_job (
    splitter_job_id UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_splitter_job PRIMARY KEY,
    webcon_element_id INT NULL,
    source_file_name NVARCHAR(500) NOT NULL,
    status NVARCHAR(50) NOT NULL,
    page_count INT NULL,
    detected_document_count INT NULL,
    technical_error NVARCHAR(2000) NULL,
    created_at DATETIME2(0) NOT NULL CONSTRAINT DF_splitter_job_created_at DEFAULT (SYSUTCDATETIME()),
    finished_at DATETIME2(0) NULL
);

CREATE TABLE dbo.classification_feedback (
    classification_feedback_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_classification_feedback PRIMARY KEY,
    splitter_job_id UNIQUEIDENTIFIER NULL CONSTRAINT FK_feedback_job REFERENCES dbo.splitter_job(splitter_job_id),
    webcon_package_element_id INT NULL,
    page_number INT NOT NULL,
    system_document_type NVARCHAR(200) NULL,
    operator_document_type NVARCHAR(200) NULL,
    system_is_first_page BIT NULL,
    operator_is_first_page BIT NULL,
    operator_login NVARCHAR(200) NULL,
    used_for_pattern_update BIT NOT NULL CONSTRAINT DF_feedback_used DEFAULT (0),
    created_at DATETIME2(0) NOT NULL CONSTRAINT DF_feedback_created_at DEFAULT (SYSUTCDATETIME())
);
```

- [x] **Step 4: Add repository boundary**

Create `splitter/src/webcon_pdf_splitter/db/__init__.py`:

```python
__all__ = ["repository"]
```

Create `splitter/src/webcon_pdf_splitter/db/repository.py`:

```python
from dataclasses import dataclass
import json
from typing import Protocol

import pyodbc


@dataclass(frozen=True)
class DocumentPattern:
    document_type: str
    header: str
    phrases: list[str]
    excluded_phrases: list[str]
    weight: float
    active: bool


class PatternRepository(Protocol):
    def list_active_patterns(self) -> list[DocumentPattern]:
        ...


class InMemoryPatternRepository:
    def __init__(self, patterns: list[DocumentPattern]) -> None:
        self._patterns = patterns

    def list_active_patterns(self) -> list[DocumentPattern]:
        return [pattern for pattern in self._patterns if pattern.active]


class SqlServerPatternRepository:
    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string

    def list_active_patterns(self) -> list[DocumentPattern]:
        query = """
            SELECT dt.name, dp.header, dp.phrases_json, dp.excluded_phrases_json, dp.weight, dp.is_active
            FROM dbo.document_pattern dp
            JOIN dbo.document_type dt ON dt.document_type_id = dp.document_type_id
            WHERE dt.is_active = 1 AND dp.is_active = 1
        """
        with pyodbc.connect(self._connection_string) as connection:
            rows = connection.cursor().execute(query).fetchall()

        return [
            DocumentPattern(
                document_type=row[0],
                header=row[1],
                phrases=json.loads(row[2]),
                excluded_phrases=json.loads(row[3]),
                weight=float(row[4]),
                active=bool(row[5]),
            )
            for row in rows
        ]
```

- [x] **Step 5: Run repository tests**

Run:

```powershell
cd splitter
python -m pytest tests/test_repository_mapping.py -v
```

Expected: PASS.

- [x] **Step 6: Commit**

```powershell
git add splitter/src/webcon_pdf_splitter/db splitter/tests/test_repository_mapping.py
git commit -m "feat: add sql server pattern repository"
```

---

### Task 3: Deterministic Document Classifier

**Files:**
- Create: `splitter/src/webcon_pdf_splitter/classification/__init__.py`
- Create: `splitter/src/webcon_pdf_splitter/classification/rules.py`
- Create: `splitter/tests/test_rule_classifier.py`

**Interfaces:**
- Consumes: `DocumentPattern`.
- Produces: `PageClassification`, `RuleBasedClassifier.classify_page(text: str, page_number: int)`.
- Later tasks consume `PageClassification.is_first_page`, `document_type`, `confidence`, `signals`.

- [x] **Step 1: Write classifier tests**

Create `splitter/tests/test_rule_classifier.py`:

```python
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.db.repository import DocumentPattern


def test_classifier_detects_known_header_as_first_page():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                document_type="Umowa o prace",
                header="UMOWA O PRACE",
                phrases=["pracownik", "pracodawca"],
                excluded_phrases=[],
                weight=1.0,
                active=True,
            )
        ]
    )

    result = classifier.classify_page(
        "UMOWA O PRACE zawarta pomiedzy pracodawca i pracownik",
        page_number=1,
    )

    assert result.is_first_page is True
    assert result.document_type == "Umowa o prace"
    assert result.confidence >= 0.90
    assert "header_match:UMOWA O PRACE" in result.signals


def test_classifier_marks_unknown_page_as_continuation_with_low_confidence():
    classifier = RuleBasedClassifier(patterns=[])

    result = classifier.classify_page("dalsza tresc dokumentu bez naglowka", page_number=2)

    assert result.is_first_page is False
    assert result.document_type == "Nieznany typ dokumentu"
    assert result.confidence < 0.70
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd splitter
python -m pytest tests/test_rule_classifier.py -v
```

Expected: FAIL because classifier module does not exist.

- [x] **Step 3: Implement classifier**

Create `splitter/src/webcon_pdf_splitter/classification/__init__.py`:

```python
__all__ = ["rules", "llm", "pipeline"]
```

Create `splitter/src/webcon_pdf_splitter/classification/rules.py`:

```python
from dataclasses import dataclass, field
import re

from webcon_pdf_splitter.db.repository import DocumentPattern


@dataclass(frozen=True)
class PageClassification:
    page_number: int
    is_first_page: bool
    document_type: str
    confidence: float
    signals: list[str] = field(default_factory=list)


class RuleBasedClassifier:
    def __init__(self, patterns: list[DocumentPattern]) -> None:
        self._patterns = patterns

    def classify_page(self, text: str, page_number: int) -> PageClassification:
        normalized = self._normalize(text)
        best: PageClassification | None = None

        for pattern in self._patterns:
            header = self._normalize(pattern.header)
            if not header:
                continue

            header_match = header in normalized[:1200]
            phrase_hits = sum(
                1 for phrase in pattern.phrases if self._normalize(phrase) in normalized
            )
            excluded_hit = any(
                self._normalize(phrase) in normalized for phrase in pattern.excluded_phrases
            )

            if excluded_hit:
                continue

            score = 0.0
            signals: list[str] = []
            if header_match:
                score += 0.78 * pattern.weight
                signals.append(f"header_match:{pattern.header}")
            if phrase_hits:
                score += min(0.18, phrase_hits * 0.06)
                signals.append(f"phrase_hits:{phrase_hits}")

            confidence = max(0.0, min(score, 0.99))
            candidate = PageClassification(
                page_number=page_number,
                is_first_page=confidence >= 0.70,
                document_type=pattern.document_type,
                confidence=confidence,
                signals=signals,
            )
            if best is None or candidate.confidence > best.confidence:
                best = candidate

        if best is None or best.confidence < 0.50:
            return PageClassification(
                page_number=page_number,
                is_first_page=False,
                document_type="Nieznany typ dokumentu",
                confidence=0.20,
                signals=["no_pattern_match"],
            )

        return best

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value.upper()).strip()
```

- [x] **Step 4: Run tests**

Run:

```powershell
cd splitter
python -m pytest tests/test_rule_classifier.py -v
```

Expected: PASS.

- [x] **Step 5: Commit**

```powershell
git add splitter/src/webcon_pdf_splitter/classification splitter/tests/test_rule_classifier.py
git commit -m "feat: add rule based document classifier"
```

---

### Task 4: Local LLM Classifier Adapter

**Files:**
- Create: `splitter/src/webcon_pdf_splitter/classification/llm.py`
- Create: `splitter/tests/test_llm_classifier.py`

**Interfaces:**
- Consumes: current page OCR text, optional neighboring page text, known document types.
- Produces: `LlmClassification`, `DisabledLlmClassifier`, `OpenAiCompatibleLlmClassifier`.
- Later tasks consume `classify_uncertain_page(...) -> LlmClassification | None`.

- [x] **Step 1: Write LLM adapter tests**

Create `splitter/tests/test_llm_classifier.py`:

```python
from webcon_pdf_splitter.classification.llm import DisabledLlmClassifier, LlmClassification


def test_disabled_llm_returns_none():
    classifier = DisabledLlmClassifier()

    result = classifier.classify_uncertain_page(
        current_text="ANEKS DO UMOWY",
        previous_text="",
        next_text="",
        known_document_types=["Umowa o prace", "Aneks"],
    )

    assert result is None


def test_llm_classification_requires_valid_confidence():
    result = LlmClassification(
        isFirstPage=True,
        documentType="Aneks",
        isKnownType=True,
        confidence=0.82,
        reasonCodes=["title_indicates_document_type"],
        suggestedNewPatterns=["ANEKS DO UMOWY"],
    )

    assert result.confidence == 0.82
    assert result.isFirstPage is True
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd splitter
python -m pytest tests/test_llm_classifier.py -v
```

Expected: FAIL because `classification.llm` does not exist.

- [x] **Step 3: Implement LLM interface**

Create `splitter/src/webcon_pdf_splitter/classification/llm.py`:

```python
from typing import Protocol

from pydantic import BaseModel, Field
import requests


class LlmClassification(BaseModel):
    isFirstPage: bool
    documentType: str
    isKnownType: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasonCodes: list[str] = Field(default_factory=list)
    suggestedNewPatterns: list[str] = Field(default_factory=list)


class LlmClassifier(Protocol):
    def classify_uncertain_page(
        self,
        current_text: str,
        previous_text: str,
        next_text: str,
        known_document_types: list[str],
    ) -> LlmClassification | None:
        ...


class DisabledLlmClassifier:
    def classify_uncertain_page(
        self,
        current_text: str,
        previous_text: str,
        next_text: str,
        known_document_types: list[str],
    ) -> LlmClassification | None:
        return None


class OpenAiCompatibleLlmClassifier:
    def __init__(self, endpoint: str, model: str, timeout_seconds: int = 30) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    def classify_uncertain_page(
        self,
        current_text: str,
        previous_text: str,
        next_text: str,
        known_document_types: list[str],
    ) -> LlmClassification | None:
        prompt = self._build_prompt(current_text, previous_text, next_text, known_document_types)
        response = requests.post(
            f"{self._endpoint}/chat/completions",
            json={
                "model": self._model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": "Klasyfikujesz strony dokumentow HR. Odpowiadasz tylko poprawnym JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return LlmClassification.model_validate_json(content)

    @staticmethod
    def _build_prompt(
        current_text: str,
        previous_text: str,
        next_text: str,
        known_document_types: list[str],
    ) -> str:
        return (
            "Ustal, czy AKTUALNA_STRONA jest pierwsza strona dokumentu HR. "
            "Zwroc JSON z polami: isFirstPage, documentType, isKnownType, confidence, "
            "reasonCodes, suggestedNewPatterns.\n\n"
            f"ZNANE_TYPY={known_document_types}\n\n"
            f"POPRZEDNIA_STRONA={previous_text[:2000]}\n\n"
            f"AKTUALNA_STRONA={current_text[:4000]}\n\n"
            f"NASTEPNA_STRONA={next_text[:2000]}"
        )
```

- [x] **Step 4: Run tests**

Run:

```powershell
cd splitter
python -m pytest tests/test_llm_classifier.py -v
```

Expected: PASS.

- [x] **Step 5: Commit**

```powershell
git add splitter/src/webcon_pdf_splitter/classification/llm.py splitter/tests/test_llm_classifier.py
git commit -m "feat: add optional local llm classifier"
```

---

### Task 5: Classification Pipeline And Page Grouping

**Files:**
- Create: `splitter/src/webcon_pdf_splitter/classification/pipeline.py`
- Create: `splitter/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `RuleBasedClassifier`, `LlmClassifier`, `SplitResult`, `DetectedDocument`.
- Produces: `ClassificationPipeline.split_pages(source_file_name: str, page_texts: list[str]) -> SplitResult`.

- [x] **Step 1: Write pipeline tests**

Create `splitter/tests/test_pipeline.py`:

```python
from webcon_pdf_splitter.classification.llm import DisabledLlmClassifier
from webcon_pdf_splitter.classification.pipeline import ClassificationPipeline
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.db.repository import DocumentPattern


def test_pipeline_groups_pages_between_detected_first_pages():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", [], [], 1.0, True),
            DocumentPattern("Aneks", "ANEKS DO UMOWY", [], [], 1.0, True),
        ]
    )
    pipeline = ClassificationPipeline(
        rule_classifier=classifier,
        llm_classifier=DisabledLlmClassifier(),
        min_auto_accept_confidence=0.90,
        min_review_confidence=0.70,
    )

    result = pipeline.split_pages(
        source_file_name="scan.pdf",
        page_texts=[
            "UMOWA O PRACE",
            "ciag dalszy umowy",
            "ANEKS DO UMOWY",
            "ciag dalszy aneksu",
        ],
    )

    assert len(result.documents) == 2
    assert result.documents[0].startPage == 1
    assert result.documents[0].endPage == 2
    assert result.documents[1].startPage == 3
    assert result.documents[1].endPage == 4
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
cd splitter
python -m pytest tests/test_pipeline.py -v
```

Expected: FAIL because pipeline module does not exist.

- [x] **Step 3: Implement pipeline**

Create `splitter/src/webcon_pdf_splitter/classification/pipeline.py`:

```python
from webcon_pdf_splitter.classification.llm import LlmClassifier
from webcon_pdf_splitter.classification.rules import PageClassification, RuleBasedClassifier
from webcon_pdf_splitter.contracts import DetectedDocument, SplitResult


class ClassificationPipeline:
    def __init__(
        self,
        rule_classifier: RuleBasedClassifier,
        llm_classifier: LlmClassifier,
        min_auto_accept_confidence: float,
        min_review_confidence: float,
    ) -> None:
        self._rule_classifier = rule_classifier
        self._llm_classifier = llm_classifier
        self._min_auto_accept_confidence = min_auto_accept_confidence
        self._min_review_confidence = min_review_confidence

    def split_pages(self, source_file_name: str, page_texts: list[str]) -> SplitResult:
        classifications = [
            self._classify_with_fallback(page_texts, index)
            for index in range(len(page_texts))
        ]
        first_pages = [
            classification
            for classification in classifications
            if classification.is_first_page
        ]
        if not first_pages and page_texts:
            first_pages = [
                PageClassification(
                    page_number=1,
                    is_first_page=True,
                    document_type="Nieznany typ dokumentu",
                    confidence=0.20,
                    signals=["forced_first_page"],
                )
            ]

        documents: list[DetectedDocument] = []
        for document_index, first_page in enumerate(first_pages, start=1):
            next_first_page = first_pages[document_index] if document_index < len(first_pages) else None
            end_page = (next_first_page.page_number - 1) if next_first_page else len(page_texts)
            requires_review = first_page.confidence < self._min_auto_accept_confidence
            documents.append(
                DetectedDocument(
                    documentIndex=document_index,
                    documentType=first_page.document_type,
                    confidence=first_page.confidence,
                    requiresReview=requires_review,
                    startPage=first_page.page_number,
                    endPage=end_page,
                    outputFileName=self._file_name(document_index, first_page.document_type, first_page.page_number, end_page),
                    signals=first_page.signals,
                    metadata={},
                )
            )

        status = "requires_review" if any(document.requiresReview for document in documents) else "completed"
        return SplitResult(
            sourceFileName=source_file_name,
            pageCount=len(page_texts),
            status=status,
            documents=documents,
            warnings=[],
        )

    def _classify_with_fallback(self, page_texts: list[str], index: int) -> PageClassification:
        page_number = index + 1
        rule_result = self._rule_classifier.classify_page(page_texts[index], page_number)
        if rule_result.confidence >= self._min_auto_accept_confidence:
            return rule_result

        llm_result = self._llm_classifier.classify_uncertain_page(
            current_text=page_texts[index],
            previous_text=page_texts[index - 1] if index > 0 else "",
            next_text=page_texts[index + 1] if index + 1 < len(page_texts) else "",
            known_document_types=[],
        )
        if llm_result is None or llm_result.confidence <= rule_result.confidence:
            return rule_result

        return PageClassification(
            page_number=page_number,
            is_first_page=llm_result.isFirstPage,
            document_type=llm_result.documentType,
            confidence=llm_result.confidence,
            signals=[f"llm:{code}" for code in llm_result.reasonCodes],
        )

    @staticmethod
    def _file_name(index: int, document_type: str, start_page: int, end_page: int) -> str:
        safe_type = (
            document_type.replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
        )
        return f"{index:03d}_{safe_type}_strony_{start_page:03d}-{end_page:03d}.pdf"
```

- [x] **Step 4: Run tests**

Run:

```powershell
cd splitter
python -m pytest tests/test_pipeline.py -v
```

Expected: PASS.

- [x] **Step 5: Commit**

```powershell
git add splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/tests/test_pipeline.py
git commit -m "feat: group classified pages into documents"
```

---

### Task 6: PDF IO And API Endpoint

**Files:**
- Create: `splitter/src/webcon_pdf_splitter/pdf_io.py`
- Create: `splitter/src/webcon_pdf_splitter/ocr.py`
- Create: `splitter/src/webcon_pdf_splitter/api.py`
- Create: `splitter/tests/test_api.py`

**Interfaces:**
- Consumes: `ClassificationPipeline`.
- Produces: FastAPI endpoint `POST /api/split` with multipart PDF upload and JSON `SplitResult`.

- [x] **Step 1: Write API smoke test**

Create `splitter/tests/test_api.py`:

```python
from fastapi.testclient import TestClient

from webcon_pdf_splitter.api import app


def test_health_endpoint_returns_ok():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
cd splitter
python -m pytest tests/test_api.py -v
```

Expected: FAIL because `api.py` does not exist.

- [x] **Step 3: Add OCR and PDF boundaries**

Create `splitter/src/webcon_pdf_splitter/ocr.py`:

```python
from typing import Protocol


class OcrEngine(Protocol):
    def extract_page_texts(self, pdf_path: str) -> list[str]:
        ...


class StubOcrEngine:
    def extract_page_texts(self, pdf_path: str) -> list[str]:
        return ["UMOWA O PRACE"]
```

Create `splitter/src/webcon_pdf_splitter/pdf_io.py`:

```python
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from webcon_pdf_splitter.contracts import DetectedDocument


def validate_pdf(path: Path) -> int:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("PDF is encrypted")
    return len(reader.pages)


def split_pdf(source_path: Path, output_dir: Path, documents: list[DetectedDocument]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(source_path))
    output_paths: list[Path] = []
    for document in documents:
        writer = PdfWriter()
        for page_index in range(document.startPage - 1, document.endPage):
            writer.add_page(reader.pages[page_index])
        output_path = output_dir / document.outputFileName
        with output_path.open("wb") as handle:
            writer.write(handle)
        output_paths.append(output_path)
    return output_paths
```

- [x] **Step 4: Add FastAPI app**

Create `splitter/src/webcon_pdf_splitter/api.py`:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, HTTPException, UploadFile

from webcon_pdf_splitter.classification.llm import DisabledLlmClassifier
from webcon_pdf_splitter.classification.pipeline import ClassificationPipeline
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.contracts import SplitResult
from webcon_pdf_splitter.db.repository import InMemoryPatternRepository
from webcon_pdf_splitter.ocr import StubOcrEngine
from webcon_pdf_splitter.pdf_io import validate_pdf


app = FastAPI(title="WEBCON PDF Splitter")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/split", response_model=SplitResult)
async def split_pdf_endpoint(file: UploadFile = File(...)) -> SplitResult:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    settings = SplitterSettings()
    repository = InMemoryPatternRepository(patterns=[])
    pipeline = ClassificationPipeline(
        rule_classifier=RuleBasedClassifier(repository.list_active_patterns()),
        llm_classifier=DisabledLlmClassifier(),
        min_auto_accept_confidence=settings.min_auto_accept_confidence,
        min_review_confidence=settings.min_review_confidence,
    )
    ocr = StubOcrEngine()

    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / file.filename
        source_path.write_bytes(await file.read())
        try:
            validate_pdf(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        page_texts = ocr.extract_page_texts(str(source_path))
        return pipeline.split_pages(file.filename, page_texts)
```

- [x] **Step 5: Run API tests**

Run:

```powershell
cd splitter
python -m pytest tests/test_api.py -v
```

Expected: PASS.

- [x] **Step 6: Commit**

```powershell
git add splitter/src/webcon_pdf_splitter/api.py splitter/src/webcon_pdf_splitter/ocr.py splitter/src/webcon_pdf_splitter/pdf_io.py splitter/tests/test_api.py
git commit -m "feat: expose splitter api"
```

---

### Task 7: WEBCON Custom Action Client Scaffold

**Files:**
- Create: `webcon-action/WebconPdfSplitterAction.csproj`
- Create: `webcon-action/SplitterContracts.cs`
- Create: `webcon-action/SplitterClient.cs`
- Create: `webcon-action/SplitPdfAction.cs`

**Interfaces:**
- Consumes: splitter endpoint `POST /api/split`.
- Produces: C# DTOs and client that the WEBCON SDK action can call.

- [x] **Step 1: Create C# project**

Create `webcon-action/WebconPdfSplitterAction.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net472</TargetFramework>
    <LangVersion>latest</LangVersion>
    <Nullable>enable</Nullable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
  </ItemGroup>
</Project>
```

- [x] **Step 2: Add splitter DTOs**

Create `webcon-action/SplitterContracts.cs`:

```csharp
using System.Collections.Generic;

namespace WebconPdfSplitterAction;

public sealed class SplitResult
{
    public string SourceFileName { get; set; } = "";
    public int PageCount { get; set; }
    public string Status { get; set; } = "";
    public List<DetectedDocument> Documents { get; set; } = new();
    public List<string> Warnings { get; set; } = new();
}

public sealed class DetectedDocument
{
    public int DocumentIndex { get; set; }
    public string DocumentType { get; set; } = "";
    public double Confidence { get; set; }
    public bool RequiresReview { get; set; }
    public int StartPage { get; set; }
    public int EndPage { get; set; }
    public string OutputFileName { get; set; } = "";
    public List<string> Signals { get; set; } = new();
    public Dictionary<string, object> Metadata { get; set; } = new();
}
```

- [x] **Step 3: Add splitter HTTP client**

Create `webcon-action/SplitterClient.cs`:

```csharp
using System;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace WebconPdfSplitterAction;

public sealed class SplitterClient
{
    private readonly HttpClient _httpClient;
    private readonly string _baseUrl;

    public SplitterClient(HttpClient httpClient, string baseUrl)
    {
        _httpClient = httpClient;
        _baseUrl = baseUrl.TrimEnd('/');
    }

    public async Task<SplitResult> SplitAsync(string fileName, Stream pdfStream)
    {
        using var content = new MultipartFormDataContent();
        using var fileContent = new StreamContent(pdfStream);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        content.Add(fileContent, "file", fileName);

        using var response = await _httpClient.PostAsync($"{_baseUrl}/api/split", content);
        var body = await response.Content.ReadAsStringAsync();
        response.EnsureSuccessStatusCode();

        return JsonConvert.DeserializeObject<SplitResult>(body)
            ?? throw new InvalidOperationException("Splitter returned empty response.");
    }
}
```

- [x] **Step 4: Add WEBCON action entry scaffold**

Create `webcon-action/SplitPdfAction.cs`:

```csharp
using System;
using System.Net.Http;
using System.Threading.Tasks;

namespace WebconPdfSplitterAction;

public sealed class SplitPdfAction
{
    public string SplitterBaseUrl { get; set; } = "http://localhost:8000";

    public async Task<SplitResult> ExecuteForPdfStreamAsync(string fileName, System.IO.Stream pdfStream)
    {
        using var httpClient = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(5)
        };
        var client = new SplitterClient(httpClient, SplitterBaseUrl);
        return await client.SplitAsync(fileName, pdfStream);
    }
}
```

- [x] **Step 5: Build C# project**

Run:

```powershell
dotnet build webcon-action/WebconPdfSplitterAction.csproj
```

Expected: build succeeds. If the target WEBCON SDK requires a different target framework, update `TargetFramework` to the version confirmed in the environment.

- [x] **Step 6: Commit**

```powershell
git add webcon-action
git commit -m "feat: add webcon splitter action scaffold"
```

---

### Task 8: Deployment Notes And Operator Flow

**Files:**
- Create: `docs/deployment/sql-server.md`
- Create: `docs/deployment/splitter-service.md`
- Create: `docs/deployment/webcon-configuration.md`

**Interfaces:**
- Consumes: SQL schema, API endpoint, WEBCON action scaffold.
- Produces: deployment checklist for the pilot environment.

- [x] **Step 1: Add SQL Server deployment notes**

Create `docs/deployment/sql-server.md`:

```markdown
# SQL Server Setup

Create a dedicated database named `WebconPdfSplitter` on the SQL Server infrastructure used by WEBCON.

Do not add splitter tables to WEBCON system databases.

Minimum permissions:

- splitter service account: read/write on `WebconPdfSplitter`;
- WEBCON service account: no direct access required unless WEBCON forms read splitter audit tables;
- DBA/admin: schema deployment and maintenance.

Apply schema from:

`splitter/src/webcon_pdf_splitter/db/schema.sql`
```

- [x] **Step 2: Add splitter service notes**

Create `docs/deployment/splitter-service.md`:

```markdown
# Splitter Service

The splitter runs as a local internal service.

Required environment:

- `SPLITTER_DATABASE_CONNECTION_STRING`
- `SPLITTER_WORK_DIR`
- `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE=0.90`
- `SPLITTER_MIN_REVIEW_CONFIDENCE=0.70`
- `SPLITTER_LLM_ENABLED=false`
- `SPLITTER_LLM_ENDPOINT`
- `SPLITTER_LLM_MODEL`
- `SPLITTER_API_TOKEN`

Local development command:

```powershell
cd splitter
python -m uvicorn webcon_pdf_splitter.api:app --host 127.0.0.1 --port 8000
```

Production should run behind an internal service account and HTTPS or a protected local network channel.
```

- [x] **Step 3: Add WEBCON configuration notes**

Create `docs/deployment/webcon-configuration.md`:

```markdown
# WEBCON Configuration

Create a process for scan bundles with:

- original PDF attachment;
- processing status;
- page count;
- detected document count;
- technical log reference;
- relation to created HR document elements.

Create a process for HR documents with:

- single split PDF attachment;
- document type;
- source page range;
- confidence;
- review status;
- source scan bundle reference.

Configure the custom action "Podziel PDF" to:

1. read the selected bundle PDF;
2. call the local splitter service;
3. create HR document elements;
4. attach split PDFs;
5. route low-confidence documents to review.
```

- [x] **Step 4: Verify docs contain no unresolved placeholder markers**

Run:

```powershell
rg -n ('TB'+'D|TO'+'DO|FIX'+'ME') docs splitter webcon-action
```

Expected: no matches.

- [x] **Step 5: Commit**

```powershell
git add docs/deployment
git commit -m "docs: add deployment notes"
```

---

## Self-Review

- Spec coverage: covered WEBCON action, local splitter API, SQL Server solution database, deterministic classification, optional local LLM fallback, review thresholds, and deployment notes.
- Intentional MVP limitation: real OCR engine integration is behind `OcrEngine`; first executable slice uses `StubOcrEngine` so API and workflow can be tested before choosing Tesseract/ABBYY/PaddleOCR.
- Intentional WEBCON limitation: `SplitPdfAction.cs` is an SDK entry scaffold. The final base class and attachment APIs must be aligned to the exact WEBCON BPS SDK version in the target environment.
- Placeholder scan: no unresolved placeholder markers should remain after the verification command in Task 8.
- Type consistency: Python DTO fields use the same names as JSON returned to C# DTOs: `sourceFileName`, `pageCount`, `documents`, `documentIndex`, `documentType`, `confidence`, `requiresReview`, `startPage`, `endPage`, `outputFileName`, `signals`, `metadata`.
