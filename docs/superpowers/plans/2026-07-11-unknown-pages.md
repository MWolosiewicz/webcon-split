# Unknown Pages and LLM Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Runs of unrecognized pages become separate "Nieznany typ dokumentu" documents (start, middle, end of a bundle) via phrase affinity, and the local LLM — called only for pages that rules and affinity left unknown — can rescue them into known types or continuations.

**Architecture:** `RuleBasedClassifier` reports per-page `phrase_affinities` (types with ≥1 matched phrase). `ClassificationPipeline.split_pages` is rewritten as a sequential segment builder: rule first-pages open known documents, affine pages extend them, everything else asks the LLM once and otherwise joins an unknown run; every page belongs to exactly one contiguous segment. `api.py` finally honors `SPLITTER_LLM_*` settings when constructing the classifier.

**Tech Stack:** Python 3.11+/FastAPI/pydantic v2/pytest. No plugin, contract, or database changes.

Spec: `docs/superpowers/specs/2026-07-11-unknown-pages-design.md`.

## Global Constraints

- Continuation = non-first page with ≥1 phrase of any pattern of the open known document's type; patterns whose excluded phrase matched contribute no affinity.
- An unknown run lasts until the next first page; a page "returning" to the previous type by affinity or LLM verdict does NOT reattach once a run is open (ranges must stay contiguous).
- Unknown documents: type `"Nieznany typ dokumentu"`, confidence `0.20`, `requiresReview: true`, signal `unknown_run`; one warning per run: `"Strony {start}-{end}: nierozpoznany dokument"`.
- Every page belongs to exactly one document — ranges are contiguous, no gaps, no overlaps.
- LLM is called ONLY for pages that rules + affinity left unknown; multi-page documents with phrase-bearing continuations generate zero LLM calls.
- LLM verdict thresholds: `isFirstPage=true` and confidence ≥ `min_review_confidence` opens a known document (requiresReview decided by `min_auto_accept_confidence`); `isFirstPage=false` + `documentType` equal to the immediately preceding open known segment + confidence ≥ `min_review_confidence` extends it; anything else (None, error, timeout, low confidence) → page stays unknown. LLM errors are logged, never fail the request.
- LLM classifier selection: `llm_enabled=True` AND non-empty `llm_endpoint` AND non-empty `llm_model` → `OpenAiCompatibleLlmClassifier(endpoint, model, timeout_seconds=llm_timeout_seconds)`; otherwise `DisabledLlmClassifier`. New setting `llm_timeout_seconds: int = 30` (`SPLITTER_LLM_TIMEOUT_SECONDS`).
- Tests run from `splitter/`: `python -m pytest tests/ -v`.

---

### Task 1: Phrase affinities and known types in `RuleBasedClassifier`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/rules.py`
- Test: `splitter/tests/test_rule_classifier.py`

**Interfaces:**
- Produces: `PageClassification.phrase_affinities: set[str]` (default empty set) — document types with ≥1 matched phrase on the page regardless of header; `RuleBasedClassifier.known_document_types` property → `list[str]` (sorted unique types of the classifier's patterns). Both consumed by Task 2/3.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_rule_classifier.py`:

```python
def test_classify_page_reports_phrase_affinities_without_header():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", ["pracodawca"], [], 1.0, True),
            DocumentPattern("Swiadectwo pracy", "SWIADECTWO PRACY", ["okres zatrudnienia"], [], 1.0, True),
        ]
    )

    result = classifier.classify_page("dalszy ciag: pracodawca zapewnia...", page_number=2)

    assert result.document_type == "Nieznany typ dokumentu"
    assert result.phrase_affinities == {"Umowa o prace"}


def test_excluded_phrase_blocks_affinity():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", ["pracodawca"], ["aneks"], 1.0, True),
        ]
    )

    result = classifier.classify_page("aneks: pracodawca zmienia warunki", page_number=2)

    assert result.phrase_affinities == set()


def test_known_document_types_are_sorted_and_unique():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", [], [], 1.0, True),
            DocumentPattern("Umowa o prace", "UMOWA", [], [], 1.0, True),
            DocumentPattern("Aneks", "ANEKS", [], [], 1.0, True),
        ]
    )

    assert classifier.known_document_types == ["Aneks", "Umowa o prace"]
```

(If the file does not already import them, ensure at top: `from webcon_pdf_splitter.classification.rules import RuleBasedClassifier` and `from webcon_pdf_splitter.db.repository import DocumentPattern`.)

- [ ] **Step 2: Run test to verify it fails**

Run (from `splitter/`): `python -m pytest tests/test_rule_classifier.py -v`
Expected: new tests FAIL (`AttributeError: ... 'phrase_affinities'` / `'known_document_types'`); pre-existing tests PASS.

- [ ] **Step 3: Write minimal implementation**

In `splitter/src/webcon_pdf_splitter/classification/rules.py`:

Add the field to the dataclass:

```python
@dataclass(frozen=True)
class PageClassification:
    page_number: int
    is_first_page: bool
    document_type: str
    confidence: float
    signals: list[str] = field(default_factory=list)
    phrase_affinities: set[str] = field(default_factory=set)
```

In `classify_page`, collect affinities in the existing loop and attach them to every returned classification:

```python
    def classify_page(self, text: str, page_number: int) -> PageClassification:
        normalized = self._normalize(text)
        best: PageClassification | None = None
        affinities: set[str] = set()

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

            if phrase_hits:
                affinities.add(pattern.document_type)

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
                phrase_affinities=affinities,
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
                phrase_affinities=affinities,
            )

        return PageClassification(
            page_number=best.page_number,
            is_first_page=best.is_first_page,
            document_type=best.document_type,
            confidence=best.confidence,
            signals=best.signals,
            phrase_affinities=affinities,
        )
```

(The winning candidate is rebuilt with the final `affinities` set so the returned value is complete regardless of pattern order; the `phrase_affinities=affinities` argument inside the candidate construction in the loop may then be omitted.)

Add the property to `RuleBasedClassifier`:

```python
    @property
    def known_document_types(self) -> list[str]:
        return sorted({pattern.document_type for pattern in self._patterns})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_rule_classifier.py -v`
Expected: ALL PASSED

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/rules.py splitter/tests/test_rule_classifier.py
git commit -m "feat: report phrase affinities and known types from rule classifier"
```

---

### Task 2: Sequential grouping with unknown runs (no LLM yet)

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/pipeline.py`
- Test: `splitter/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `PageClassification.phrase_affinities`, `RuleBasedClassifier.known_document_types` (Task 1).
- Produces: rewritten `ClassificationPipeline.split_pages` building contiguous segments; private `_Segment` dataclass; `_try_llm(page_texts, index, known_types) -> LlmClassification | None` hook already wired into the unknown branch (with `DisabledLlmClassifier` it returns None, so Task 3 only adds tests). Warnings per unknown run.

- [ ] **Step 1: Update the existing grouping test and add new failing tests**

Replace the body of `test_pipeline_groups_pages_between_detected_first_pages` in `splitter/tests/test_pipeline.py` (patterns gain phrases; continuation pages contain them):

```python
def test_pipeline_groups_pages_between_detected_first_pages():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", ["umowy"], [], 1.0, True),
            DocumentPattern("Aneks", "ANEKS DO UMOWY", ["aneksu"], [], 1.0, True),
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

Append new tests:

```python
def _make_pipeline(llm_classifier=None):
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                "Umowa o prace", "UMOWA O PRACE", ["pracodawca", "wynagrodzenie"], [], 1.2, True
            ),
            DocumentPattern(
                "Swiadectwo pracy", "SWIADECTWO PRACY", ["okres zatrudnienia"], [], 1.2, True
            ),
        ]
    )
    return ClassificationPipeline(
        rule_classifier=classifier,
        llm_classifier=llm_classifier or DisabledLlmClassifier(),
        min_auto_accept_confidence=0.90,
        min_review_confidence=0.70,
    )


def _assert_full_coverage(result, page_count):
    ranges = sorted((doc.startPage, doc.endPage) for doc in result.documents)
    expected_start = 1
    for start, end in ranges:
        assert start == expected_start
        assert end >= start
        expected_start = end + 1
    assert expected_start == page_count + 1


def test_unknown_run_in_the_middle_becomes_separate_document():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "wynagrodzenie zasadnicze wynosi",
            "zupelnie obce pismo przewodnie",
            "SWIADECTWO PRACY okres zatrudnienia",
        ],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
        ("Nieznany typ dokumentu", 3, 3),
        ("Swiadectwo pracy", 4, 4),
    ]
    unknown = result.documents[1]
    assert unknown.requiresReview is True
    assert unknown.confidence == 0.20
    assert "unknown_run" in unknown.signals
    assert result.warnings == ["Strony 3-3: nierozpoznany dokument"]
    _assert_full_coverage(result, 4)


def test_unknown_pages_at_start_are_not_lost():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "obca strona pierwsza",
            "obca strona druga",
            "UMOWA O PRACE zawarta z pracodawca",
        ],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Nieznany typ dokumentu", 1, 2),
        ("Umowa o prace", 3, 3),
    ]
    _assert_full_coverage(result, 3)


def test_unknown_tail_becomes_separate_document():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "obcy zalacznik bez fraz",
        ],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 1),
        ("Nieznany typ dokumentu", 2, 2),
    ]
    _assert_full_coverage(result, 2)


def test_page_with_foreign_type_phrases_goes_to_unknown_run():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "okres zatrudnienia wynosil trzy lata",
        ],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 1),
        ("Nieznany typ dokumentu", 2, 2),
    ]


def test_fully_unknown_bundle_is_single_unknown_document():
    result = _make_pipeline().split_pages("scan.pdf", ["obca 1", "obca 2"])

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Nieznany typ dokumentu", 1, 2),
    ]
    assert result.status == "requires_review"
    _assert_full_coverage(result, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: the new tests FAIL (unknown pages glued to previous document / start pages missing); the updated grouping test PASSES already if affinity is not required — verify it still passes after Step 3.

- [ ] **Step 3: Rewrite `split_pages`**

Replace the whole of `splitter/src/webcon_pdf_splitter/classification/pipeline.py` with:

```python
from dataclasses import dataclass, field
import logging

from webcon_pdf_splitter.classification.llm import LlmClassification, LlmClassifier
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.contracts import DetectedDocument, SplitResult

logger = logging.getLogger(__name__)

UNKNOWN_DOCUMENT_TYPE = "Nieznany typ dokumentu"


@dataclass
class _Segment:
    document_type: str
    confidence: float
    signals: list[str]
    start_page: int
    end_page: int
    known: bool


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
        known_types = self._rule_classifier.known_document_types
        segments: list[_Segment] = []
        current: _Segment | None = None

        for index, text in enumerate(page_texts):
            page_number = index + 1
            page = self._rule_classifier.classify_page(text, page_number)

            if page.is_first_page:
                current = _Segment(
                    document_type=page.document_type,
                    confidence=page.confidence,
                    signals=page.signals,
                    start_page=page_number,
                    end_page=page_number,
                    known=True,
                )
                segments.append(current)
                continue

            if current is not None and current.known and current.document_type in page.phrase_affinities:
                current.end_page = page_number
                continue

            llm = self._try_llm(page_texts, index, known_types)
            if llm is not None and llm.confidence >= self._min_review_confidence:
                if llm.isFirstPage:
                    current = _Segment(
                        document_type=llm.documentType,
                        confidence=llm.confidence,
                        signals=[f"llm:{code}" for code in llm.reasonCodes],
                        start_page=page_number,
                        end_page=page_number,
                        known=True,
                    )
                    segments.append(current)
                    continue
                if current is not None and current.known and llm.documentType == current.document_type:
                    current.end_page = page_number
                    continue

            if current is not None and not current.known:
                current.end_page = page_number
            else:
                current = _Segment(
                    document_type=UNKNOWN_DOCUMENT_TYPE,
                    confidence=0.20,
                    signals=["unknown_run"],
                    start_page=page_number,
                    end_page=page_number,
                    known=False,
                )
                segments.append(current)

        documents = [
            DetectedDocument(
                documentIndex=document_index,
                documentType=segment.document_type,
                confidence=segment.confidence,
                requiresReview=segment.confidence < self._min_auto_accept_confidence,
                startPage=segment.start_page,
                endPage=segment.end_page,
                outputFileName=self._file_name(
                    document_index, segment.document_type, segment.start_page, segment.end_page
                ),
                signals=segment.signals,
                metadata={},
            )
            for document_index, segment in enumerate(segments, start=1)
        ]
        warnings = [
            f"Strony {segment.start_page}-{segment.end_page}: nierozpoznany dokument"
            for segment in segments
            if not segment.known
        ]

        status = "requires_review" if any(document.requiresReview for document in documents) else "completed"
        return SplitResult(
            sourceFileName=source_file_name,
            pageCount=len(page_texts),
            status=status,
            documents=documents,
            warnings=warnings,
        )

    def _try_llm(
        self, page_texts: list[str], index: int, known_types: list[str]
    ) -> LlmClassification | None:
        try:
            return self._llm_classifier.classify_uncertain_page(
                current_text=page_texts[index],
                previous_text=page_texts[index - 1] if index > 0 else "",
                next_text=page_texts[index + 1] if index + 1 < len(page_texts) else "",
                known_document_types=known_types,
            )
        except Exception:
            logger.warning("LLM classification failed for page %s", index + 1, exc_info=True)
            return None

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

(Note: the unused `field` import may be dropped if the linter complains; `PageClassification` import is no longer needed here.)

- [ ] **Step 4: Run the full splitter suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASSED — including `tests/test_jobs_and_feedback.py` and `tests/test_split_patterns.py` (blank-page uploads now produce a single unknown document covering page 1, same counts as before).

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/tests/test_pipeline.py
git commit -m "feat: emit unknown-page runs as separate review documents"
```

---

### Task 3: LLM rescue of unknown pages (stub tests)

**Files:**
- Test: `splitter/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `_try_llm` wiring from Task 2 (already implemented), `LlmClassification` model from `webcon_pdf_splitter.classification.llm`.
- Produces: verified LLM behavior; no production code expected to change (if a test fails, fix `split_pages` to match the Global Constraints).

- [ ] **Step 1: Write the tests**

Append to `splitter/tests/test_pipeline.py`:

```python
from webcon_pdf_splitter.classification.llm import LlmClassification


class _StubLlm:
    def __init__(self, responses=None, error=None):
        self._responses = responses or {}
        self._error = error
        self.calls = []

    def classify_uncertain_page(self, current_text, previous_text, next_text, known_document_types):
        self.calls.append({"text": current_text, "known_types": known_document_types})
        if self._error is not None:
            raise self._error
        return self._responses.get(current_text)


def test_llm_promotes_unknown_page_to_known_first_page():
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

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 1),
        ("Pismo przewodnie", 2, 2),
    ]
    assert result.documents[1].requiresReview is True
    assert result.documents[1].signals == ["llm:layout"]
    assert stub.calls[0]["known_types"] == ["Swiadectwo pracy", "Umowa o prace"]


def test_llm_confirms_continuation_of_current_document():
    stub = _StubLlm(
        responses={
            "strona bez zadnych fraz": LlmClassification(
                isFirstPage=False,
                documentType="Umowa o prace",
                isKnownType=True,
                confidence=0.80,
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


def test_llm_error_leaves_page_unknown():
    stub = _StubLlm(error=RuntimeError("llm down"))
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "strona bez zadnych fraz"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 1),
        ("Nieznany typ dokumentu", 2, 2),
    ]


def test_llm_low_confidence_leaves_page_unknown():
    stub = _StubLlm(
        responses={
            "strona bez zadnych fraz": LlmClassification(
                isFirstPage=True,
                documentType="Pismo",
                isKnownType=False,
                confidence=0.50,
            )
        }
    )
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "strona bez zadnych fraz"],
    )

    assert result.documents[1].documentType == "Nieznany typ dokumentu"


def test_llm_not_called_for_affine_continuation_pages():
    stub = _StubLlm()
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "wynagrodzenie zasadnicze"],
    )

    assert len(result.documents) == 1
    assert stub.calls == []
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: ALL PASSED (Task 2 already wired `_try_llm`; if any test fails, adjust `split_pages` to the Global Constraints — thresholds, contiguity, unknown fallback).

- [ ] **Step 3: Commit**

```bash
git add splitter/tests/test_pipeline.py
git commit -m "test: cover LLM rescue paths for unknown pages"
```

---

### Task 4: Honor LLM settings in `api.py` + timeout setting

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/config.py`
- Modify: `splitter/src/webcon_pdf_splitter/api.py`
- Test: `splitter/tests/test_llm_wiring.py` (new file)

**Interfaces:**
- Consumes: existing `OpenAiCompatibleLlmClassifier(endpoint, model, timeout_seconds)` and `DisabledLlmClassifier` from `webcon_pdf_splitter.classification.llm`.
- Produces: `SplitterSettings.llm_timeout_seconds: int = 30`; `build_llm_classifier(settings) -> LlmClassifier` in `webcon_pdf_splitter.api`, used inside `_split`.

- [ ] **Step 1: Write the failing test**

Create `splitter/tests/test_llm_wiring.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_wiring.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_llm_classifier'`

- [ ] **Step 3: Write minimal implementation**

In `splitter/src/webcon_pdf_splitter/config.py`, after `llm_model`:

```python
    llm_timeout_seconds: int = Field(default=30)
```

In `splitter/src/webcon_pdf_splitter/api.py`:

Change the llm import line to:

```python
from webcon_pdf_splitter.classification.llm import (
    DisabledLlmClassifier,
    LlmClassifier,
    OpenAiCompatibleLlmClassifier,
)
```

Add after `parse_patterns_field`:

```python
def build_llm_classifier(settings: SplitterSettings) -> LlmClassifier:
    if settings.llm_enabled and settings.llm_endpoint and settings.llm_model:
        return OpenAiCompatibleLlmClassifier(
            endpoint=settings.llm_endpoint,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return DisabledLlmClassifier()
```

In `_split`, replace `llm_classifier=DisabledLlmClassifier(),` with:

```python
        llm_classifier=build_llm_classifier(settings),
```

- [ ] **Step 4: Run the full splitter suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASSED

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/config.py splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_llm_wiring.py
git commit -m "feat: honor LLM settings with configurable timeout"
```

---

### Task 5: Documentation

**Files:**
- Modify: `docs/deployment/splitter-service.md`

- [ ] **Step 1: Update the env var table**

Replace the row:

```markdown
| `SPLITTER_LLM_ENABLED` | nie (false) | Włącza fallback LLM (wymaga endpointu) |
```

with:

```markdown
| `SPLITTER_LLM_ENABLED` | nie (false) | Włącza fallback LLM dla stron nierozpoznanych (wymaga endpointu i modelu) |
| `SPLITTER_LLM_TIMEOUT_SECONDS` | nie (30) | Limit czasu pojedynczego wywołania LLM |
```

- [ ] **Step 2: Add the local-LLM section**

Add after the "Produkcja — zalecenia" list heading area (at the end of the file):

```markdown
## Lokalny LLM (opcjonalny)

Fallback LLM pomaga klasyfikować wyłącznie strony, których nie rozpoznały
reguły i powinowactwo fraz — wielostronicowe dokumenty ze znanymi frazami
nie generują żadnych wywołań. Bez LLM strony nierozpoznane trafiają jako
osobne dokumenty "Nieznany typ dokumentu" do ręcznej weryfikacji.

Wymagany jest lokalny serwer zgodny z OpenAI Chat Completions — splitter go
nie uruchamia. Przykład (Ollama jako kontener na tym samym hoście):

```bash
docker run -d --name ollama -p 11434:11434 ollama/ollama
docker exec ollama ollama pull llama3.1:8b
```

Konfiguracja w `.env` splittera:

```
SPLITTER_LLM_ENABLED=true
SPLITTER_LLM_ENDPOINT=http://host.docker.internal:11434/v1
SPLITTER_LLM_MODEL=llama3.1:8b
SPLITTER_LLM_TIMEOUT_SECONDS=60
```

Dane stron nie opuszczają infrastruktury — żądania idą tylko do wskazanego
lokalnego endpointu. Błąd lub timeout LLM nie przerywa podziału: strona
pozostaje "Nieznany typ dokumentu".
```

- [ ] **Step 3: Commit**

```bash
git add docs/deployment/splitter-service.md
git commit -m "docs: local LLM fallback configuration"
```
