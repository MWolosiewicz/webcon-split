# Usuwanie pustych stron z paczki — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Puste strony paczki są usuwane wewnątrz `/api/split` (nie doklejane z wymuszoną weryfikacją), konfigurowalnie i audytowalnie, z zabezpieczeniem przed cichą utratą całej paczki przy awarii OCR.

**Architecture:** Detekcja pustej strony korzysta z tekstu już wyliczonego przez OCR (`alnum_count`) — zerowy narzut. Pipeline pomija puste strony przy grupowaniu i zapisuje ich numery; `split_pdf` wycina je z plików wynikowych. Dwa nowe ustawienia `SPLITTER_*` sterują akcją i progiem. Akcja WEBCON dostaje puste strony w komentarzu dziecka i logu operacji. Zmiany C# są neutralne wobec dwóch linii SDK (2025 R2 / 2026 R1).

**Tech Stack:** Python 3.11, FastAPI, pydantic-settings, pypdf, pytest; C# netstandard2.0 (WEBCON BPS SDK, Newtonsoft.Json).

**Spec:** [`docs/superpowers/specs/2026-07-24-empty-pages-removal-design.md`](../specs/2026-07-24-empty-pages-removal-design.md)

## Global Constraints

- Wszystkie ustawienia mają prefiks `SPLITTER_` i żyją w `SplitterSettings` (`splitter/src/webcon_pdf_splitter/config.py`); `extra="ignore"`.
- Domyślne: `SPLITTER_DROP_EMPTY_PAGES=true`, `SPLITTER_EMPTY_PAGE_MAX_ALNUM=0`.
- Pusta strona = `alnum_count(text) <= empty_page_max_alnum` na tekście PO OCR. To globalna DEFINICJA (używana też do pominięcia LLM); `drop_empty_pages` decyduje tylko o AKCJI (usuń vs doklej).
- Komentarze i logi w kodzie: polski **bez znaków diakrytycznych** (ASCII), zgodnie z resztą repo.
- Testy uruchamiane z katalogu `splitter/` (pyproject: `pythonpath=["src"]`, `testpaths=["tests"]`): `cd splitter && python -m pytest ...`.
- C#: jeden `WebconPdfSplitterAction.csproj`, `netstandard2.0`; **bez** kodu wersjonowanego (`#if`); musi budować się dla `-p:BpsSdk=2025` i `-p:BpsSdk=2026`.
- `SplitResult.pageCount` zawsze = liczba stron oryginału (`len(page_texts)`), niezależnie od usunięć.

---

### Task 1: Ustawienia — przełącznik i próg

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/config.py:29`
- Test: `splitter/tests/test_config_empty_pages.py` (create)

**Interfaces:**
- Produces: `SplitterSettings.drop_empty_pages: bool` (env `SPLITTER_DROP_EMPTY_PAGES`, default `True`), `SplitterSettings.empty_page_max_alnum: int` (env `SPLITTER_EMPTY_PAGE_MAX_ALNUM`, default `0`).

- [ ] **Step 1: Write the failing test**

Create `splitter/tests/test_config_empty_pages.py`:

```python
from webcon_pdf_splitter.config import SplitterSettings


def test_drop_empty_pages_defaults_true():
    assert SplitterSettings(_env_file=None).drop_empty_pages is True


def test_empty_page_max_alnum_defaults_zero():
    assert SplitterSettings(_env_file=None).empty_page_max_alnum == 0


def test_empty_page_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("SPLITTER_DROP_EMPTY_PAGES", "false")
    monkeypatch.setenv("SPLITTER_EMPTY_PAGE_MAX_ALNUM", "5")
    settings = SplitterSettings(_env_file=None)
    assert settings.drop_empty_pages is False
    assert settings.empty_page_max_alnum == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_config_empty_pages.py -v`
Expected: FAIL — `AttributeError: 'SplitterSettings' object has no attribute 'drop_empty_pages'`.

- [ ] **Step 3: Add the settings fields**

In `config.py`, after the `ocr_workers` line (`config.py:29`), add:

```python
    ocr_workers: int = Field(default=2)
    drop_empty_pages: bool = Field(default=True)
    empty_page_max_alnum: int = Field(default=0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_config_empty_pages.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/config.py splitter/tests/test_config_empty_pages.py
git commit -m "feat: ustawienia SPLITTER_DROP_EMPTY_PAGES i SPLITTER_EMPTY_PAGE_MAX_ALNUM"
```

---

### Task 2: Kontrakt — `removedPages` w `DetectedDocument`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/contracts.py:32`
- Test: `splitter/tests/test_contracts.py` (append)

**Interfaces:**
- Produces: `DetectedDocument.removedPages: list[int]` (default `[]`) — puste strony usunięte ze środka zakresu tego dokumentu, w numeracji oryginału.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_contracts.py`:

```python
def test_detected_document_removed_pages_defaults_empty():
    from webcon_pdf_splitter.contracts import DetectedDocument

    doc = DetectedDocument(
        documentIndex=1,
        documentType="X",
        confidence=0.5,
        requiresReview=False,
        startPage=1,
        endPage=1,
        outputFileName="x.pdf",
    )
    assert doc.removedPages == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_contracts.py::test_detected_document_removed_pages_defaults_empty -v`
Expected: FAIL — `AttributeError: 'DetectedDocument' object has no attribute 'removedPages'`.

- [ ] **Step 3: Add the contract field**

In `contracts.py`, in `DetectedDocument`, add `removedPages` after `signals` (`contracts.py:32`):

```python
    signals: list[str] = Field(default_factory=list)
    removedPages: list[int] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_contracts.py -v`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/contracts.py splitter/tests/test_contracts.py
git commit -m "feat: pole removedPages w kontrakcie DetectedDocument"
```

---

### Task 3: `split_pdf` pomija `removedPages`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/pdf_io.py:84-96`
- Test: `splitter/tests/test_pdf_io.py` (append)

**Interfaces:**
- Consumes: `DetectedDocument.removedPages` (Task 2).
- Produces: `split_pdf(source_path: Path, output_dir: Path, documents: list[DetectedDocument]) -> list[Path]` — dla każdego dokumentu pomija strony z `document.removedPages` (1-based) przy zapisie.

- [ ] **Step 1: Write the failing tests**

Append to `splitter/tests/test_pdf_io.py` (używa istniejących helperów `_pdf_path` i `_page_count`):

```python
def test_split_pdf_skips_removed_pages(tmp_path):
    from webcon_pdf_splitter.pdf_io import split_pdf
    from webcon_pdf_splitter.contracts import DetectedDocument

    source = _pdf_path(tmp_path, "src.pdf", 5)
    doc = DetectedDocument(
        documentIndex=1, documentType="X", confidence=0.9, requiresReview=False,
        startPage=1, endPage=5, outputFileName="out.pdf", removedPages=[2, 4],
    )
    out_paths = split_pdf(source, tmp_path / "out", [doc])
    assert _page_count(out_paths[0].read_bytes()) == 3


def test_split_pdf_without_removed_pages_keeps_all(tmp_path):
    from webcon_pdf_splitter.pdf_io import split_pdf
    from webcon_pdf_splitter.contracts import DetectedDocument

    source = _pdf_path(tmp_path, "src.pdf", 3)
    doc = DetectedDocument(
        documentIndex=1, documentType="X", confidence=0.9, requiresReview=False,
        startPage=1, endPage=3, outputFileName="out.pdf",
    )
    out_paths = split_pdf(source, tmp_path / "out", [doc])
    assert _page_count(out_paths[0].read_bytes()) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_pdf_io.py::test_split_pdf_skips_removed_pages -v`
Expected: FAIL — plik ma 5 stron zamiast 3 (`removedPages` jeszcze nieuwzględniane).

- [ ] **Step 3: Implement page skipping**

Replace the body of `split_pdf` in `pdf_io.py:84-96` with:

```python
def split_pdf(source_path: Path, output_dir: Path, documents: list[DetectedDocument]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(source_path))
    output_paths: list[Path] = []
    for document in documents:
        writer = PdfWriter()
        removed = set(document.removedPages)
        for page_index in range(document.startPage - 1, document.endPage):
            if (page_index + 1) in removed:
                continue
            writer.add_page(reader.pages[page_index])
        output_path = output_dir / document.outputFileName
        with output_path.open("wb") as handle:
            writer.write(handle)
        output_paths.append(output_path)
    return output_paths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd splitter && python -m pytest tests/test_pdf_io.py -v`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/pdf_io.py splitter/tests/test_pdf_io.py
git commit -m "feat: split_pdf pomija strony z removedPages"
```

---

### Task 4: Pipeline — parametry i próg (refaktor zachowawczy)

Behavior-preserving: dodajemy parametry konstruktora i próg, ale JESZCZE bez usuwania. Wszystkie istniejące testy zostają zielone (domyślny próg 0 == dzisiejsze `== 0`; brak gałęzi usuwania).

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/pipeline.py:34-45` (konstruktor), `pipeline.py:84` (próg)
- Modify: `splitter/src/webcon_pdf_splitter/api.py:284-289` (przekazanie ustawień)
- Modify: `splitter/tests/test_pipeline.py:98-114` (helper `_make_pipeline`)

**Interfaces:**
- Consumes: `SplitterSettings.drop_empty_pages`, `SplitterSettings.empty_page_max_alnum` (Task 1).
- Produces: `ClassificationPipeline.__init__(self, rule_classifier, llm_classifier, min_auto_accept_confidence, min_review_confidence, drop_empty_pages: bool = True, empty_page_max_alnum: int = 0)`; atrybuty `self._drop_empty_pages`, `self._empty_page_max_alnum`.

- [ ] **Step 1: Extend the constructor**

In `pipeline.py`, update `__init__` (`pipeline.py:34-45`):

```python
    def __init__(
        self,
        rule_classifier: RuleBasedClassifier,
        llm_classifier: LlmClassifier,
        min_auto_accept_confidence: float,
        min_review_confidence: float,
        drop_empty_pages: bool = True,
        empty_page_max_alnum: int = 0,
    ) -> None:
        self._rule_classifier = rule_classifier
        self._llm_classifier = llm_classifier
        self._min_auto_accept_confidence = min_auto_accept_confidence
        self._min_review_confidence = min_review_confidence
        self._drop_empty_pages = drop_empty_pages
        self._empty_page_max_alnum = empty_page_max_alnum
```

- [ ] **Step 2: Use the threshold for the empty gate**

In `pipeline.py:84`, change:

```python
            page_is_empty = alnum_count(text) <= self._empty_page_max_alnum
```

- [ ] **Step 3: Wire settings through the API**

In `api.py`, update the pipeline construction (`api.py:284-289`):

```python
    pipeline = ClassificationPipeline(
        rule_classifier=RuleBasedClassifier(repository.list_active_patterns()),
        llm_classifier=build_llm_classifier(settings),
        min_auto_accept_confidence=settings.min_auto_accept_confidence,
        min_review_confidence=settings.min_review_confidence,
        drop_empty_pages=settings.drop_empty_pages,
        empty_page_max_alnum=settings.empty_page_max_alnum,
    )
```

- [ ] **Step 4: Let the test helper forward the new params**

In `test_pipeline.py`, update `_make_pipeline` (`test_pipeline.py:98-114`):

```python
def _make_pipeline(llm_classifier=None, drop_empty_pages=True, empty_page_max_alnum=0):
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
        drop_empty_pages=drop_empty_pages,
        empty_page_max_alnum=empty_page_max_alnum,
    )
```

- [ ] **Step 5: Run the full suite — everything stays green**

Run: `cd splitter && python -m pytest -q`
Expected: PASS — brak regresji (to refaktor bez zmiany zachowania; puste strony wciąż doklejane, bo gałęzi usuwania jeszcze nie ma).

- [ ] **Step 6: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_pipeline.py
git commit -m "refactor: pipeline przyjmuje ustawienia pustych stron (zachowawczo)"
```

---

### Task 5: Pipeline — usuwanie, atrybucja, warningi, zabezpieczenie

To sedno funkcji. Domyślnie `drop_empty_pages=True`, więc dwa istniejące testy starego zachowania zostają PRZEPISANE na nowe, a stare zachowanie jest chronione osobnym testem z `drop_empty_pages=False`.

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/pipeline.py` (metoda `split_pages`)
- Modify: `splitter/tests/test_pipeline.py` (przepisz 2 testy, dodaj nowe)

**Interfaces:**
- Consumes: `self._drop_empty_pages`, `self._empty_page_max_alnum` (Task 4); `DetectedDocument.removedPages` (Task 2).
- Produces: puste strony usuwane (numeracja oryginału), `removedPages` per dokument (strony ze środka zakresu), warning podsumowujący, zabezpieczenie „cała paczka pusta".

- [ ] **Step 1: Rewrite the two legacy empty-page tests to the new default**

In `test_pipeline.py`, REPLACE `test_empty_page_skips_llm_and_glues_with_review` (`test_pipeline.py:49-73`) with:

```python
def test_empty_page_dropped_by_default():
    stub = _StubLlm(
        responses={
            "": LlmClassification(
                isFirstPage=True, documentType="Cokolwiek",
                isKnownType=False, confidence=0.99,
            )
        }
    )
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "    \n  "],
    )

    assert stub.calls == []
    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 1),
    ]
    doc = result.documents[0]
    assert doc.requiresReview is False
    assert doc.removedPages == []
    assert "glued_unknown_page:2" not in doc.signals
    assert result.warnings == ["Usunieto 1 pustych stron: 2 (z 2)"]
```

REPLACE `test_leading_empty_pages_form_unknown_document` (`test_pipeline.py:76-95`) with:

```python
def test_leading_empty_pages_dropped():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        ["", "   ", "UMOWA O PRACE zawarta z pracodawca"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 3, 3),
    ]
    assert result.documents[0].removedPages == []
    assert result.warnings == ["Usunieto 2 pustych stron: 1, 2 (z 3)"]
```

- [ ] **Step 2: Add the new behavior tests**

Append to `test_pipeline.py`:

```python
def test_empty_page_inside_document_attributed_to_child():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "    ", "wynagrodzenie zasadnicze wynosi"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 3),
    ]
    assert result.documents[0].removedPages == [2]
    assert result.warnings == ["Usunieto 1 pustych stron: 2 (z 3)"]


def test_separator_empty_page_reported_only_at_bundle_level():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "   ", "SWIADECTWO PRACY okres zatrudnienia"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 1),
        ("Swiadectwo pracy", 3, 3),
    ]
    assert result.documents[0].removedPages == []
    assert result.documents[1].removedPages == []
    assert result.warnings == ["Usunieto 1 pustych stron: 2 (z 3)"]


def test_empty_page_glued_with_review_when_drop_disabled():
    result = _make_pipeline(drop_empty_pages=False).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "    \n  "],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]
    doc = result.documents[0]
    assert doc.requiresReview is True
    assert "glued_unknown_page:2" in doc.signals
    assert doc.reviewReasons == [
        "strona 2 bez tekstu (rowniez po OCR) - dolaczona automatycznie"
    ]
    assert doc.removedPages == []


def test_threshold_treats_ocr_noise_as_empty():
    result = _make_pipeline(empty_page_max_alnum=3).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "x y"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 1),
    ]
    assert result.warnings == ["Usunieto 1 pustych stron: 2 (z 2)"]


def test_sparse_real_content_above_threshold_not_dropped():
    result = _make_pipeline(empty_page_max_alnum=3).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "Zalacznik nr 1"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]
    assert result.documents[0].removedPages == []
    assert result.documents[0].requiresReview is True


def test_all_empty_bundle_falls_back_to_unknown_document():
    result = _make_pipeline().split_pages("scan.pdf", ["", "   ", "  \n "])

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Nieznany typ dokumentu", 1, 3),
    ]
    doc = result.documents[0]
    assert doc.requiresReview is True
    assert doc.removedPages == []
    assert "all_empty_fallback" in doc.signals
    assert "Wszystkie strony rozpoznane jako puste - sprawdz OCR" in result.warnings
    assert result.status == "requires_review"
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_pipeline.py -k "dropped or attributed or separator or drop_disabled or threshold or sparse or all_empty" -v`
Expected: FAIL — puste strony wciąż doklejane; brak `removedPages`, warningów podsumowujących i zabezpieczenia.

- [ ] **Step 4: Implement the drop branch**

In `split_pages`, initialize the removed list next to `segments` (`pipeline.py:49-50`):

```python
        segments: list[_Segment] = []
        current: _Segment | None = None
        removed_pages: list[int] = []
        all_empty_fallback = False
```

Insert the drop branch right where `page_is_empty` is computed (`pipeline.py:84`), before the `llm = ...` line:

```python
            page_is_empty = alnum_count(text) <= self._empty_page_max_alnum
            if page_is_empty and self._drop_empty_pages:
                removed_pages.append(page_number)
                logger.info(
                    "Strona %s: pusta (%s znakow alnum) - usunieta",
                    page_number,
                    alnum_count(text),
                )
                continue
            llm = (
                None
                if page_is_empty
                else self._try_llm(page_texts, index, known_types, current)
            )
```

- [ ] **Step 5: Implement the all-empty safety guard**

Immediately after the main `for index, text in enumerate(page_texts):` loop ends and before `documents: list[DetectedDocument] = []` (`pipeline.py:166`), add:

```python
        if not segments and removed_pages:
            # ZABEZPIECZENIE: cala paczka pusta (np. awaria OCR) - nie gub jej po cichu
            logger.warning(
                "Wszystkie %s stron rozpoznane jako puste - mozliwa awaria OCR; "
                "paczka trafia do weryfikacji jako nieznana",
                len(page_texts),
            )
            segments.append(
                _Segment(
                    document_type=UNKNOWN_DOCUMENT_TYPE,
                    confidence=0.20,
                    signals=["all_empty_fallback"],
                    start_page=1,
                    end_page=len(page_texts),
                    known=False,
                )
            )
            removed_pages = []
            all_empty_fallback = True
```

- [ ] **Step 6: Attribute removed pages to their document**

In the documents-building loop (`pipeline.py:167-187`), pass `removedPages` per segment:

```python
        for document_index, segment in enumerate(segments, start=1):
            requires_review = (
                segment.forced_review
                or segment.confidence < self._min_auto_accept_confidence
            )
            segment_removed = [
                p for p in removed_pages if segment.start_page <= p <= segment.end_page
            ]
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
                        segment.document_type, segment.start_page, segment.end_page
                    ),
                    signals=segment.signals,
                    removedPages=segment_removed,
                    metadata={},
                )
            )
```

- [ ] **Step 7: Add the bundle-level warnings**

After the existing per-segment `warnings` loop (`pipeline.py:189-199`), before `status = ...` (`pipeline.py:201`), add:

```python
        if removed_pages:
            warnings.append(
                "Usunieto %s pustych stron: %s (z %s)"
                % (
                    len(removed_pages),
                    ", ".join(str(page) for page in removed_pages),
                    len(page_texts),
                )
            )
        if all_empty_fallback:
            warnings.append("Wszystkie strony rozpoznane jako puste - sprawdz OCR")
```

- [ ] **Step 8: Run the full suite to verify green**

Run: `cd splitter && python -m pytest -q`
Expected: PASS — nowe testy przechodzą, reszta bez regresji.

- [ ] **Step 9: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/tests/test_pipeline.py
git commit -m "feat: usuwanie pustych stron w pipeline + removedPages, warningi, zabezpieczenie OCR"
```

---

### Task 6: API — pokrycie zabezpieczenia i regresji

**Files:**
- Modify: `splitter/tests/test_api_split.py` (append)

**Interfaces:**
- Consumes: pełny przepływ `/api/split` (Tasks 1–5).

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_api_split.py` (paczka samych blanków → zabezpieczenie → 1 dokument nieznany):

```python
def test_split_all_empty_bundle_flags_for_review():
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes(2)), "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pageCount"] == 2
    assert payload["status"] == "requires_review"
    assert len(payload["documents"]) == 1
    assert payload["documents"][0]["documentType"] == "Nieznany typ dokumentu"
    # pole removedPages serializuje sie w odpowiedzi (tu puste - zabezpieczenie nic nie usuwa)
    assert payload["documents"][0]["removedPages"] == []
    assert any("sprawdz OCR" in warning for warning in payload["warnings"])
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_api_split.py -v`
Expected: PASS — zabezpieczenie z Task 5 obsługuje paczkę samych blanków (żaden tekst → wszystkie puste → fallback). Wszystkie istniejące testy API również zielone (paczka blanków nadal daje ≥ 1 dokument z treścią).

> Uwaga dla wykonawcy: jeśli ten test padnie z 0 dokumentów, to znaczy, że zabezpieczenie z Task 5 nie działa — wróć do Task 5 Step 5, NIE osłabiaj tego testu.

- [ ] **Step 3: Commit**

```bash
git add splitter/tests/test_api_split.py
git commit -m "test: API - paczka samych pustych stron trafia do weryfikacji"
```

---

### Task 7: Akcja WEBCON — `RemovedPages` w kontrakcie, komentarzu i logu

Zmiany neutralne wobec dwóch linii SDK (tylko DTO + `args.LogMessage` + `Comment.AddCommentAsync`). Brak projektu testów C# — weryfikacja przez budowę obu linii i przegląd.

**Files:**
- Modify: `webcon-action/SplitterContracts.cs:15-28` (`DetectedDocument`)
- Modify: `webcon-action/SplitPdfAction.cs:93-97` (`args.LogMessage`), `SplitPdfAction.cs:134-143` (`FormatDetectionComment`)

**Interfaces:**
- Consumes: JSON `removedPages` (z Task 2/5) i `warnings` (z Task 5).
- Produces: komentarz dziecka z usuniętymi stronami; `warnings` w logu operacji elementu-źródła.

- [ ] **Step 1: Add the contract property**

In `SplitterContracts.cs`, in `DetectedDocument` (after `Signals`, `SplitterContracts.cs:26`), add:

```csharp
    public List<string> Signals { get; set; } = new();
    public List<int> RemovedPages { get; set; } = new();
    public Dictionary<string, object> Metadata { get; set; } = new();
```

(Newtonsoft dopasowuje camelCase `removedPages` do `RemovedPages` case-insensitive, jak pozostałe pola tej klasy — bez atrybutu `JsonProperty`.)

- [ ] **Step 2: Surface removed pages in the child comment**

In `SplitPdfAction.cs`, update `FormatDetectionComment` (`SplitPdfAction.cs:134-143`):

```csharp
    private string FormatDetectionComment(DetectedDocument detected)
    {
        var comment =
            $"Type: {detected.DocumentType}; pages {detected.StartPage}-{detected.EndPage}; " +
            $"confidence {detected.Confidence:0.00}; requires review: {detected.RequiresReview}";
        if (detected.RemovedPages.Count > 0)
            comment += $"; usunieto puste strony: {string.Join(", ", detected.RemovedPages)}";
        // powody trafiaja do komentarza tylko, gdy nie sa zapisywane w dedykowanym polu
        if (Configuration.ReviewReasonsFieldId <= 0 && detected.ReviewReasons.Count > 0)
            comment += $"; review reasons: {string.Join("; ", detected.ReviewReasons)}";
        return comment;
    }
```

- [ ] **Step 3: Surface bundle warnings in the operation log**

In `SplitPdfAction.cs`, update the `args.LogMessage` assignment (`SplitPdfAction.cs:93-97`):

```csharp
            var warningsText = result.Warnings.Count > 0
                ? " Warnings: " + string.Join(" | ", result.Warnings) + "."
                : "";
            args.LogMessage =
                $"SplitPdfAction v{pluginVersion}. " +
                patternsWarning +
                $"Splitter job {result.JobId}: {result.Status}, pages: {result.PageCount}, " +
                $"documents: {result.Documents.Count}, created elements: {string.Join(", ", createdIds)}" +
                warningsText;
```

- [ ] **Step 4: Build both SDK lines**

Run (środowisko z dostępem do pakietów SDK WEBCON — licencja):

```bash
dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release -p:BpsSdk=2026
dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release -p:BpsSdk=2025
```

Expected: oba `Build succeeded`. Jeśli pakiety SDK są niedostępne lokalnie, weryfikację budowy wykonuje operator przez `package.ps1 -Sdk 2026` i `package.ps1 -Sdk 2025`; kod zmian używa wyłącznie stabilnych API obecnych w obu liniach.

- [ ] **Step 5: Commit**

```bash
git add webcon-action/SplitterContracts.cs webcon-action/SplitPdfAction.cs
git commit -m "feat: akcja WEBCON pokazuje usuniete puste strony (komentarz + log)"
```

---

### Task 8: Dokumentacja — README i `.env.example`

**Files:**
- Modify: `README.md` (tabela zmiennych ~235; opis pustych stron ~111-113 i ~154-156)
- Modify: `splitter/.env.example`

**Interfaces:**
- Consumes: nazwy i domyślne z Task 1.

- [ ] **Step 1: Add the env-var rows**

In `README.md`, after the `SPLITTER_OCR_WORKERS` row (`README.md:235`), add two rows:

```markdown
| `SPLITTER_DROP_EMPTY_PAGES` | `true` | Puste strony są usuwane z wyników zamiast doklejania z `requiresReview`. `false` = stare zachowanie (doklejanie + flaga). Gdy usunięcie zostawiłoby 0 dokumentów (np. awaria OCR), cała paczka trafia jako jeden „Nieznany typ dokumentu" do weryfikacji |
| `SPLITTER_EMPTY_PAGE_MAX_ALNUM` | `0` | Do ilu znaków alfanum. po OCR strona jest uznawana za pustą (0 = tylko całkiem bez tekstu; >0 łapie szum OCR na blankach). Trzymać małe — wysokie ryzykuje utratę stron ze skąpą treścią |
```

- [ ] **Step 2: Update the "Omiń LLM (pusta strona)" bullet**

In `README.md:111-113`, replace:

```markdown
- **Omiń LLM (pusta strona)** — strona jest „pusta", gdy ma **zero** znaków
  alfanumerycznych, również po OCR (stała, nie env). Krótka, ale realna strona
  nie jest uznawana za pustą i idzie normalnie do LLM.
```

with:

```markdown
- **Omiń LLM / usuń (pusta strona)** — strona jest „pusta", gdy ma **≤
  `SPLITTER_EMPTY_PAGE_MAX_ALNUM`** znaków alfanumerycznych, również po OCR
  (domyślnie 0). Krótka, ale realna strona nie jest uznawana za pustą i idzie
  normalnie do LLM. Puste strony przy `SPLITTER_DROP_EMPTY_PAGES=true`
  (domyślnie) są usuwane z wyników — patrz „Grupowanie stron".
```

- [ ] **Step 3: Update grouping rule 3**

In `README.md:154-156`, replace:

```markdown
3. **Strona pusta** (0 znaków, też po OCR) → **omija LLM**, doklejana do bieżącego
   dokumentu z wymuszonym `requiresReview` i powodem
   „strona N bez tekstu (rowniez po OCR) - dolaczona automatycznie".
```

with:

```markdown
3. **Strona pusta** (≤ `SPLITTER_EMPTY_PAGE_MAX_ALNUM` znaków, też po OCR) →
   **omija LLM**; przy `SPLITTER_DROP_EMPTY_PAGES=true` (domyślnie) jest
   **usuwana** z wyników (nie trafia do żadnego pliku, nie wymusza weryfikacji);
   puste strony ze środka dokumentu lądują w `removedPages` i w komentarzu
   dziecka, a podsumowanie usunięć w `warnings` + logu operacji. Przy `false` —
   doklejana do bieżącego dokumentu z wymuszonym `requiresReview` i powodem
   „strona N bez tekstu (rowniez po OCR) - dolaczona automatycznie". **Gdy
   usunięcie zostawiłoby 0 dokumentów (np. awaria OCR), cała paczka trafia jako
   jeden „Nieznany typ dokumentu" do weryfikacji** — funkcja nigdy nie gubi
   paczki po cichu.
```

- [ ] **Step 4: Update `.env.example`**

Open `splitter/.env.example`, and near the OCR settings append (matching the file's existing comment style):

```
# Puste strony: usuwaj z wynikow (true, domyslnie) zamiast doklejac z weryfikacja
SPLITTER_DROP_EMPTY_PAGES=true
# Do ilu znakow alfanum. po OCR strona = pusta (0 = tylko bez tekstu; >0 lapie szum OCR)
SPLITTER_EMPTY_PAGE_MAX_ALNUM=0
```

- [ ] **Step 5: Commit**

```bash
git add README.md splitter/.env.example
git commit -m "docs: SPLITTER_DROP_EMPTY_PAGES i SPLITTER_EMPTY_PAGE_MAX_ALNUM w README i .env.example"
```

---

## Verification (po wszystkich zadaniach)

- [ ] `cd splitter && python -m pytest -q` — cała bateria zielona.
- [ ] `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release -p:BpsSdk=2026` — Build succeeded.
- [ ] `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release -p:BpsSdk=2025` — Build succeeded.
- [ ] Przegląd: `SPLITTER_DROP_EMPTY_PAGES=false` odtwarza dokładnie stare zachowanie (test `test_empty_page_glued_with_review_when_drop_disabled`).
