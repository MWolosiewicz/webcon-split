# Ręczne akcje podziału/sklejania PDF — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dać operatorowi trzy ręczne akcje SDK — usunięcie stron z załącznika, wycięcie stron do nowego (surowego) elementu weryfikacyjnego, sklejenie wybranych załączników PDF w jeden wg kolejności listy pozycji.

**Architecture:** Cała logika PDF trafia do istniejącego serwisu Python (FastAPI + `pypdf`) jako trzy nowe endpointy bez OCR/LLM. Trzy nowe akcje C# (`CustomAction`) pozostają cienkimi orkiestratorami: pobierają bajty załączników, wołają serwis, wykonują operacje WEBCON (dodanie/podmiana załącznika, utworzenie elementu potomnego). Wspólna konfiguracja połączenia (URL/token/timeout) wydzielona do klasy bazowej.

**Tech Stack:** Python 3.11+, FastAPI, pypdf, pytest, FastAPI `TestClient`; C# .NET Standard 2.0, WEBCON.BPS.2026.SDK.Libraries 26.1.6.209, Newtonsoft.Json 13.0.3.

## Global Constraints

- Serwis PDF: format zakresu stron **1-based, inclusive**, np. `"2-4,7,9-11"`.
- Endpointy chronione tym samym tokenem co `/api/split` (`Authorization: Bearer <token>`; brak/zły token → HTTP 401 tylko gdy token skonfigurowany).
- Błędy walidacji (zły zakres, pusty wynik, PDF zaszyfrowany, plik nie-PDF) → HTTP 400 z czytelnym `detail`.
- C# identyfikatory po angielsku; `DisplayName`/`Description` konfiguracji po polsku (jak w istniejącym kodzie). Komentarze po polsku bez polskich znaków diakrytycznych (spójnie z repo).
- Kategoria załącznika w SDK = `AttachmentData.FileGroup` (`AttachmentsGroup` z `.ID` i `.DisplayName`).
- Każda paczka pluginu musi mieć nową wersję assembly (WEBCON cache'uje po wersji) — bump `webcon-action/version.txt` przez `package.ps1`.
- Testy nie mogą czytać `.env` ani dotykać bazy — `conftest.py` już wstrzykuje izolowane `SplitterSettings`.

---

## CZĘŚĆ A — Serwis Python (TDD)

### Task 1: `parse_page_range` — parser i walidacja zakresu stron

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/pdf_io.py`
- Test: `splitter/tests/test_pdf_io.py` (create)

**Interfaces:**
- Produces: `parse_page_range(spec: str, page_count: int) -> list[int]` — zwraca posortowaną rosnąco listę unikalnych stron 1-based; rzuca `ValueError` dla pustego/nieparsowalnego/poza zakresem.

- [ ] **Step 1: Write the failing test**

Create `splitter/tests/test_pdf_io.py`:

```python
import io

import pytest
from pypdf import PdfReader, PdfWriter

from webcon_pdf_splitter.pdf_io import (
    parse_page_range,
)


def test_parse_page_range_single_and_ranges():
    assert parse_page_range("2-4,7", 10) == [2, 3, 4, 7]


def test_parse_page_range_deduplicates_and_sorts():
    assert parse_page_range("7,2-3,3", 10) == [2, 3, 7]


def test_parse_page_range_rejects_empty():
    with pytest.raises(ValueError):
        parse_page_range("   ", 10)


def test_parse_page_range_rejects_out_of_bounds():
    with pytest.raises(ValueError):
        parse_page_range("5-8", 6)


def test_parse_page_range_rejects_reversed():
    with pytest.raises(ValueError):
        parse_page_range("5-2", 10)


def test_parse_page_range_rejects_garbage():
    with pytest.raises(ValueError):
        parse_page_range("2-x", 10)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_pdf_io.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_page_range'`.

- [ ] **Step 3: Write minimal implementation**

Add to the top of `splitter/src/webcon_pdf_splitter/pdf_io.py` (after existing imports; add `import io`):

```python
import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from webcon_pdf_splitter.contracts import DetectedDocument


def parse_page_range(spec: str, page_count: int) -> list[int]:
    """Parsuje zakres stron 1-based, np. '2-4,7'. Zwraca posortowane, unikalne."""
    if spec is None or not spec.strip():
        raise ValueError("Zakres stron jest pusty")
    pages: set[int] = set()
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_s, _, end_s = token.partition("-")
            try:
                start, end = int(start_s.strip()), int(end_s.strip())
            except ValueError as exc:
                raise ValueError(f"Nieprawidlowy fragment zakresu: '{token}'") from exc
            if start > end:
                raise ValueError(f"Odwrocony zakres: '{token}'")
            pages.update(range(start, end + 1))
        else:
            try:
                pages.add(int(token))
            except ValueError as exc:
                raise ValueError(f"Nieprawidlowy numer strony: '{token}'") from exc
    if not pages:
        raise ValueError("Zakres stron jest pusty")
    for page in sorted(pages):
        if page < 1 or page > page_count:
            raise ValueError(f"Strona {page} poza dokumentem (1-{page_count})")
    return sorted(pages)
```

(Keep the existing `validate_pdf` and `split_pdf` functions below.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_pdf_io.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/pdf_io.py splitter/tests/test_pdf_io.py
git commit -m "feat: parse_page_range - parser zakresu stron 1-based z walidacja"
```

---

### Task 2: `remove_pages`, `extract_pages`, `merge_pdfs`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/pdf_io.py`
- Test: `splitter/tests/test_pdf_io.py`

**Interfaces:**
- Consumes: `parse_page_range` (Task 1).
- Produces:
  - `remove_pages(source_path: Path, pages: list[int]) -> bytes` — PDF bez wskazanych stron (1-based); `ValueError` gdy usuwa wszystkie.
  - `extract_pages(source_path: Path, pages: list[int]) -> bytes` — PDF tylko ze wskazanymi stronami, w kolejności rosnącej.
  - `merge_pdfs(source_paths: list[Path]) -> bytes` — skleja w podanej kolejności; `ValueError` gdy lista pusta.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_pdf_io.py`:

```python
def _pdf_path(tmp_path, name, page_count):
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    path = tmp_path / name
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _page_count(pdf_bytes):
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def test_remove_pages_drops_selected(tmp_path):
    from webcon_pdf_splitter.pdf_io import remove_pages

    source = _pdf_path(tmp_path, "src.pdf", 5)
    out = remove_pages(source, [2, 4])
    assert _page_count(out) == 3


def test_remove_pages_rejects_removing_all(tmp_path):
    from webcon_pdf_splitter.pdf_io import remove_pages

    source = _pdf_path(tmp_path, "src.pdf", 2)
    with pytest.raises(ValueError):
        remove_pages(source, [1, 2])


def test_extract_pages_keeps_only_selected(tmp_path):
    from webcon_pdf_splitter.pdf_io import extract_pages

    source = _pdf_path(tmp_path, "src.pdf", 6)
    out = extract_pages(source, [2, 3, 5])
    assert _page_count(out) == 3


def test_merge_pdfs_sums_pages_in_order(tmp_path):
    from webcon_pdf_splitter.pdf_io import merge_pdfs

    a = _pdf_path(tmp_path, "a.pdf", 2)
    b = _pdf_path(tmp_path, "b.pdf", 3)
    out = merge_pdfs([b, a])
    assert _page_count(out) == 5


def test_merge_pdfs_rejects_empty():
    from webcon_pdf_splitter.pdf_io import merge_pdfs

    with pytest.raises(ValueError):
        merge_pdfs([])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_pdf_io.py -v`
Expected: FAIL — `ImportError: cannot import name 'remove_pages'`.

- [ ] **Step 3: Write minimal implementation**

Add to `splitter/src/webcon_pdf_splitter/pdf_io.py` (below `parse_page_range`):

```python
def remove_pages(source_path: Path, pages: list[int]) -> bytes:
    reader = PdfReader(str(source_path))
    to_remove = set(pages)
    keep = [i for i in range(len(reader.pages)) if (i + 1) not in to_remove]
    if not keep:
        raise ValueError("Usuniecie tych stron zostawiloby pusty dokument")
    writer = PdfWriter()
    for index in keep:
        writer.add_page(reader.pages[index])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def extract_pages(source_path: Path, pages: list[int]) -> bytes:
    reader = PdfReader(str(source_path))
    writer = PdfWriter()
    for page in sorted(set(pages)):
        writer.add_page(reader.pages[page - 1])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def merge_pdfs(source_paths: list[Path]) -> bytes:
    if not source_paths:
        raise ValueError("Brak plikow PDF do sklejenia")
    writer = PdfWriter()
    for path in source_paths:
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_pdf_io.py -v`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/pdf_io.py splitter/tests/test_pdf_io.py
git commit -m "feat: remove_pages/extract_pages/merge_pdfs w pdf_io"
```

---

### Task 3: Kontrakt `PageOpResult`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/contracts.py`
- Test: `splitter/tests/test_contracts.py`

**Interfaces:**
- Produces: `PageOpResult(BaseModel)` z polami `outputFileName: str`, `pageCount: int (ge=0)`, `fileContentBase64: str`, `warnings: list[str]`.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_contracts.py`:

```python
def test_page_op_result_roundtrip():
    from webcon_pdf_splitter.contracts import PageOpResult

    result = PageOpResult(
        outputFileName="out.pdf",
        pageCount=3,
        fileContentBase64="QUJD",
    )
    dumped = result.model_dump()
    assert dumped["outputFileName"] == "out.pdf"
    assert dumped["pageCount"] == 3
    assert dumped["warnings"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_contracts.py::test_page_op_result_roundtrip -v`
Expected: FAIL — `ImportError: cannot import name 'PageOpResult'`.

- [ ] **Step 3: Write minimal implementation**

Append to `splitter/src/webcon_pdf_splitter/contracts.py`:

```python
class PageOpResult(BaseModel):
    outputFileName: str
    pageCount: int = Field(ge=0)
    fileContentBase64: str
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_contracts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/contracts.py splitter/tests/test_contracts.py
git commit -m "feat: kontrakt PageOpResult dla operacji na stronach"
```

---

### Task 4: Endpointy `/api/pages/remove` i `/api/pages/extract`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/api.py`
- Test: `splitter/tests/test_api_pages.py` (create)

**Interfaces:**
- Consumes: `parse_page_range`, `remove_pages`, `extract_pages`, `validate_pdf` (pdf_io); `PageOpResult` (contracts).
- Produces: `POST /api/pages/remove` i `POST /api/pages/extract`, każdy: multipart `file` (PDF) + `pages` (Form str) → `PageOpResult`; helper `_derive_name(original: str, suffix: str) -> str`.

- [ ] **Step 1: Write the failing test**

Create `splitter/tests/test_api_pages.py`:

```python
import base64
import io

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from webcon_pdf_splitter import api
from webcon_pdf_splitter.api import app
from webcon_pdf_splitter.config import SplitterSettings


def _pdf_bytes(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _decode_pages(payload) -> int:
    content = base64.b64decode(payload["fileContentBase64"])
    return len(PdfReader(io.BytesIO(content)).pages)


def test_remove_pages_endpoint_drops_pages():
    client = TestClient(app)
    response = client.post(
        "/api/pages/remove",
        data={"pages": "2,4"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(5)), "application/pdf")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageCount"] == 3
    assert _decode_pages(payload) == 3


def test_remove_pages_endpoint_rejects_bad_range():
    client = TestClient(app)
    response = client.post(
        "/api/pages/remove",
        data={"pages": "9-10"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(5)), "application/pdf")},
    )
    assert response.status_code == 400


def test_extract_pages_endpoint_keeps_pages():
    client = TestClient(app)
    response = client.post(
        "/api/pages/extract",
        data={"pages": "2-3"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(6)), "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["pageCount"] == 2


def test_pages_endpoint_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr(
        api, "get_settings", lambda: SplitterSettings(_env_file=None, api_token="sekret")
    )
    client = TestClient(app)
    response = client.post(
        "/api/pages/remove",
        data={"pages": "1"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(2)), "application/pdf")},
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_api_pages.py -v`
Expected: FAIL — 404 Not Found (endpoints not defined).

- [ ] **Step 3: Write minimal implementation**

In `splitter/src/webcon_pdf_splitter/api.py`, extend the pdf_io import:

```python
from webcon_pdf_splitter.pdf_io import (
    extract_pages,
    merge_pdfs,
    parse_page_range,
    remove_pages,
    split_pdf,
    validate_pdf,
)
```

Extend the contracts import:

```python
from webcon_pdf_splitter.contracts import PageOpResult, PatternPayload, SplitResult
```

Add near the top (after `_PATTERNS_ADAPTER`):

```python
def _derive_name(original: str, suffix: str) -> str:
    stem = original[:-4] if original.lower().endswith(".pdf") else original
    return f"{stem}{suffix}.pdf"


def _page_count_of(pdf_bytes: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
```

Add `import base64` and `import io` if not already imported at the top (`base64` is already imported; add `import io`).

Add the two endpoints (below `/api/split`):

```python
@app.post("/api/pages/remove", response_model=PageOpResult)
async def remove_pages_endpoint(
    file: UploadFile = File(...),
    pages: str = Form(...),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> PageOpResult:
    settings = get_settings()
    _require_token(settings, authorization)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / file.filename
        source_path.write_bytes(await file.read())
        try:
            page_count = validate_pdf(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            selected = parse_page_range(pages, page_count)
            output = remove_pages(source_path, selected)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PageOpResult(
        outputFileName=_derive_name(file.filename, "_bez-stron"),
        pageCount=_page_count_of(output),
        fileContentBase64=base64.b64encode(output).decode("ascii"),
    )


@app.post("/api/pages/extract", response_model=PageOpResult)
async def extract_pages_endpoint(
    file: UploadFile = File(...),
    pages: str = Form(...),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> PageOpResult:
    settings = get_settings()
    _require_token(settings, authorization)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / file.filename
        source_path.write_bytes(await file.read())
        try:
            page_count = validate_pdf(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            selected = parse_page_range(pages, page_count)
            output = extract_pages(source_path, selected)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PageOpResult(
        outputFileName=_derive_name(file.filename, "_strony"),
        pageCount=_page_count_of(output),
        fileContentBase64=base64.b64encode(output).decode("ascii"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_api_pages.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_api_pages.py
git commit -m "feat: endpointy /api/pages/remove i /api/pages/extract"
```

---

### Task 5: Endpoint `/api/merge`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/api.py`
- Test: `splitter/tests/test_api_pages.py`

**Interfaces:**
- Consumes: `merge_pdfs`, `validate_pdf`, `PageOpResult`.
- Produces: `POST /api/merge` — multipart wiele `files` (PDF) w kolejności + `output_file_name` (Form, domyślnie `"merged.pdf"`) → `PageOpResult`.

- [ ] **Step 1: Write the failing test**

Append to `splitter/tests/test_api_pages.py`:

```python
def test_merge_endpoint_concatenates_in_order():
    client = TestClient(app)
    response = client.post(
        "/api/merge",
        data={"output_file_name": "scalony.pdf"},
        files=[
            ("files", ("b.pdf", io.BytesIO(_pdf_bytes(3)), "application/pdf")),
            ("files", ("a.pdf", io.BytesIO(_pdf_bytes(2)), "application/pdf")),
        ],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["outputFileName"] == "scalony.pdf"
    assert payload["pageCount"] == 5
    assert _decode_pages(payload) == 5


def test_merge_endpoint_rejects_non_pdf():
    client = TestClient(app)
    response = client.post(
        "/api/merge",
        files=[("files", ("note.txt", io.BytesIO(b"hello"), "text/plain"))],
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_api_pages.py -k merge -v`
Expected: FAIL — 404 Not Found.

- [ ] **Step 3: Write minimal implementation**

Add to `splitter/src/webcon_pdf_splitter/api.py`:

```python
@app.post("/api/merge", response_model=PageOpResult)
async def merge_endpoint(
    files: list[UploadFile] = File(...),
    output_file_name: str = Form(default="merged.pdf"),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> PageOpResult:
    settings = get_settings()
    _require_token(settings, authorization)
    if not files:
        raise HTTPException(status_code=400, detail="No files to merge")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        paths: list[Path] = []
        for index, upload in enumerate(files):
            if not upload.filename or not upload.filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="Only PDF files are supported")
            path = Path(tmp) / f"{index:03d}_{upload.filename}"
            path.write_bytes(await upload.read())
            try:
                validate_pdf(path)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            paths.append(path)
        try:
            output = merge_pdfs(paths)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PageOpResult(
        outputFileName=output_file_name,
        pageCount=_page_count_of(output),
        fileContentBase64=base64.b64encode(output).decode("ascii"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_api_pages.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_api_pages.py
git commit -m "feat: endpoint /api/merge - sklejanie PDF w kolejnosci"
```

---

### Task 6: Pełny przebieg testów serwisu + dokumentacja API

**Files:**
- Modify: `README.md`

**Interfaces:** brak nowych.

- [ ] **Step 1: Run the full Python suite**

Run: `cd splitter && python -m pytest -q`
Expected: PASS — wszystkie dotychczasowe + nowe testy zielone.

- [ ] **Step 2: Dopisz opis nowych endpointow do README**

W `README.md`, w sekcji opisującej API serwisu (obok `/api/split`), dodaj akapit:

```markdown
### Ręczne operacje na PDF (dla akcji operatora)

- `POST /api/pages/remove` — multipart `file` (PDF) + `pages` (zakres 1-based, np. `2-4,7`) → `PageOpResult` z PDF bez tych stron.
- `POST /api/pages/extract` — jak wyżej, zwraca PDF tylko ze wskazanymi stronami.
- `POST /api/merge` — wiele pól `files` (PDF) w kolejności + `output_file_name` → jeden sklejony PDF.

`PageOpResult`: `{ outputFileName, pageCount, fileContentBase64, warnings }`.
Błędny zakres / pusty wynik / plik nie-PDF → HTTP 400 z komunikatem w `detail`.
Uwierzytelnianie: `Authorization: Bearer <token>` jak w `/api/split`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: opis endpointow pages/remove, pages/extract, merge"
```

---

## CZĘŚĆ B — Plugin C# (weryfikacja przez build)

> C# akcji nie testujemy jednostkowo (brak hosta WEBCON); każdy task kończy się `dotnet build` bez błędów. Logika PDF jest pokryta testami Pythona.

### Task 7: Bazowa konfiguracja połączenia + migracja `SplitPdfActionConfig`

**Files:**
- Create: `webcon-action/SplitterConnectionConfig.cs`
- Modify: `webcon-action/SplitPdfActionConfig.cs`

**Interfaces:**
- Produces: `SplitterConnectionConfig : PluginConfiguration` z `string SplitterBaseUrl`, `string ApiToken`, `int TimeoutSeconds` (Order 1-3).
- `SplitPdfActionConfig : SplitterConnectionConfig` — dziedziczy trójkę, własne pola Order 10+.

- [ ] **Step 1: Utwórz bazową klasę konfiguracji**

Create `webcon-action/SplitterConnectionConfig.cs`:

```csharp
using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

// Wspolna konfiguracja polaczenia z serwisem PDF Splitter dla wszystkich akcji.
public class SplitterConnectionConfig : PluginConfiguration
{
    [ConfigEditableText(
        DisplayName = "Splitter base URL",
        Description = "Adres lokalnego serwisu PDF Splitter, np. http://localhost:8000. " +
                      "Musi byc osiagalny z serwera WEBCON BPS (WorkflowService).",
        DefaultText = "http://localhost:8000",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 1)]
    public string SplitterBaseUrl { get; set; } = "http://localhost:8000";

    [ConfigEditableText(
        DisplayName = "Splitter API token",
        Description = "Token wysylany jako 'Authorization: Bearer ...'. Identyczny z SPLITTER_API_TOKEN. " +
                      "Zostaw puste tylko, jesli serwis dziala bez tokenu (niezalecane).",
        IsPasswordField = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 2)]
    public string ApiToken { get; set; } = "";

    [ConfigEditableInteger(
        DisplayName = "Timeout in seconds",
        Description = "Maksymalny czas oczekiwania na odpowiedz serwisu; domyslnie 300 s.",
        DefaultValue = 300,
        MinValue = 10,
        MaxValue = 3600,
        Order = 3)]
    public int TimeoutSeconds { get; set; } = 300;
}
```

- [ ] **Step 2: Przenieś wspólne pola z `SplitPdfActionConfig`**

Replace the full contents of `webcon-action/SplitPdfActionConfig.cs` with:

```csharp
using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class SplitPdfActionConfig : SplitterConnectionConfig
{
    [ConfigEditableText(
        DisplayName = "Target workflow ID (HR document)",
        Description = "ID obiegu, w ktorym maja powstawac elementy dokumentow HR. " +
                      "Wpisz liczbe albo przeciagnij tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 10)]
    public string TargetWorkflowId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Target document type ID (HR document)",
        Description = "ID typu formularza dla elementow dokumentow HR. " +
                      "Wpisz liczbe albo przeciagnij tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 11)]
    public string TargetDocTypeId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Start path ID (HR document workflow)",
        Description = "ID sciezki przejscia, ktora nowy element ma wystartowac. " +
                      "Wpisz liczbe albo przeciagnij tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 12)]
    public string StartPathId { get; set; } = "";

    [ConfigEditableDataSourceID(
        DisplayName = "Patterns data source ID",
        Description = "Zrodlo danych zwracajace aktywne wzorce rozpoznawania. " +
                      "Wymagane kolumny: DocumentType, Header, Phrases, ExcludedPhrases, Weight.",
        IsRequired = true,
        Order = 13)]
    public int PatternsDataSourceId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Requires review field ID",
        Description = "Opcjonalne: pole tak/nie w obiegu docelowym na flage weryfikacji. Puste = nie zapisuj.",
        Order = 14)]
    public int RequiresReviewFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Review reasons field ID",
        Description = "Opcjonalne: pole tekstowe na powody weryfikacji (jeden na linie). " +
                      "Ustawione = powody nie dubluja sie w komentarzu. Puste = powody do komentarza.",
        Order = 15)]
    public int ReviewReasonsFieldId { get; set; }
}
```

- [ ] **Step 3: Build**

Run: `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release`
Expected: Build succeeded, 0 errors. (Potwierdza, ze dziedziczone pola konfiguracji sa akceptowane.)

- [ ] **Step 4: Commit**

```bash
git add webcon-action/SplitterConnectionConfig.cs webcon-action/SplitPdfActionConfig.cs
git commit -m "refactor: wspolna baza SplitterConnectionConfig dla akcji"
```

---

### Task 8: Kontrakty i metody klienta dla operacji na stronach

**Files:**
- Modify: `webcon-action/SplitterContracts.cs`
- Modify: `webcon-action/SplitterClient.cs`

**Interfaces:**
- Produces:
  - `PageOpResult { string OutputFileName; int PageCount; string FileContentBase64; List<string> Warnings; }`
  - `MergeInput { string FileName; byte[] Content; }`
  - `SplitterClient.RemovePagesAsync(string fileName, Stream pdf, string pageRange, int? webconElementId=null) -> Task<PageOpResult>`
  - `SplitterClient.ExtractPagesAsync(...) -> Task<PageOpResult>` (ta sama sygnatura)
  - `SplitterClient.MergeAsync(IReadOnlyList<MergeInput> files, int? webconElementId=null) -> Task<PageOpResult>`

- [ ] **Step 1: Dodaj kontrakty**

Append to `webcon-action/SplitterContracts.cs`:

```csharp
public sealed class PageOpResult
{
    public string OutputFileName { get; set; } = "";
    public int PageCount { get; set; }
    public string FileContentBase64 { get; set; } = "";
    public List<string> Warnings { get; set; } = new();
}

public sealed class MergeInput
{
    public string FileName { get; set; } = "";
    public byte[] Content { get; set; } = System.Array.Empty<byte>();
}
```

- [ ] **Step 2: Dodaj metody klienta**

Add to the `SplitterClient` class in `webcon-action/SplitterClient.cs` (inside the class, after `SplitAsync`):

```csharp
    public Task<PageOpResult> RemovePagesAsync(
        string fileName, Stream pdfStream, string pageRange, int? webconElementId = null)
        => PostPagesAsync("/api/pages/remove", fileName, pdfStream, pageRange, webconElementId);

    public Task<PageOpResult> ExtractPagesAsync(
        string fileName, Stream pdfStream, string pageRange, int? webconElementId = null)
        => PostPagesAsync("/api/pages/extract", fileName, pdfStream, pageRange, webconElementId);

    private async Task<PageOpResult> PostPagesAsync(
        string path, string fileName, Stream pdfStream, string pageRange, int? webconElementId)
    {
        using var content = new MultipartFormDataContent();
        var fileContent = new StreamContent(pdfStream);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        content.Add(fileContent, "file", fileName);
        content.Add(new StringContent(pageRange), "pages");
        return await PostAsync<PageOpResult>(path, content, webconElementId);
    }

    public async Task<PageOpResult> MergeAsync(
        IReadOnlyList<MergeInput> files, int? webconElementId = null)
    {
        using var content = new MultipartFormDataContent();
        foreach (var file in files)
        {
            var part = new ByteArrayContent(file.Content);
            part.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
            content.Add(part, "files", file.FileName);
        }
        return await PostAsync<PageOpResult>("/api/merge", content, webconElementId);
    }

    private async Task<T> PostAsync<T>(
        string path, MultipartFormDataContent content, int? webconElementId)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, $"{_baseUrl}{path}") { Content = content };
        if (!string.IsNullOrEmpty(_apiToken))
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiToken);
        if (webconElementId.HasValue)
            request.Headers.Add("X-Webcon-Element-Id", webconElementId.Value.ToString());

        using var response = await _httpClient.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();
        // przekaz tresc bledu serwisu (HTTP 400 detail) do gornej warstwy, zeby operator wiedzial co poprawic
        if (!response.IsSuccessStatusCode)
            throw new InvalidOperationException($"Splitter returned {(int)response.StatusCode}: {body}");

        return JsonConvert.DeserializeObject<T>(body)
            ?? throw new InvalidOperationException("Splitter returned empty response.");
    }
```

- [ ] **Step 3: Build**

Run: `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release`
Expected: Build succeeded, 0 errors.

- [ ] **Step 4: Commit**

```bash
git add webcon-action/SplitterContracts.cs webcon-action/SplitterClient.cs
git commit -m "feat: klient SplitterClient - RemovePages/ExtractPages/Merge"
```

---

### Task 9: Helper wyboru źródła po kategorii + `RemovePagesAction`

**Files:**
- Create: `webcon-action/AttachmentSourceHelper.cs`
- Create: `webcon-action/RemovePagesActionConfig.cs`
- Create: `webcon-action/RemovePagesAction.cs`

**Interfaces:**
- Consumes: `SplitterConnectionConfig`, `SplitterClient`, `PageOpResult`.
- Produces:
  - `AttachmentSourceHelper.GetSinglePdfInCategoriesAsync(RunCustomActionParams args, string allowedCategoriesRaw) -> Task<AttachmentData>` — dokładnie jeden PDF w kategoriach; inaczej `InvalidOperationException`.
  - `RemovePagesAction : CustomAction<RemovePagesActionConfig>`.

- [ ] **Step 1: Utwórz helper wyboru źródła**

Create `webcon-action/AttachmentSourceHelper.cs`:

```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

internal static class AttachmentSourceHelper
{
    // Zwraca dokladnie jeden zalacznik PDF nalezacy do dozwolonych kategorii (FileGroup).
    // Kategorie z konfiguracji rozdzielone srednikami; dopasowanie po ID lub nazwie grupy.
    public static async Task<AttachmentData> GetSinglePdfInCategoriesAsync(
        RunCustomActionParams args, string allowedCategoriesRaw)
    {
        var allowed = (allowedCategoriesRaw ?? "")
            .Split(';')
            .Select(value => value.Trim())
            .Where(value => value.Length > 0)
            .ToList();
        if (allowed.Count == 0)
            throw new InvalidOperationException(
                "Nie skonfigurowano dozwolonych kategorii zalacznikow dla tej akcji.");

        var manager = new DocumentAttachmentsManager(args.Context);
        var attachments = await manager.GetAttachmentsAsync(
            new GetAttachmentsParams { DocumentId = args.Context.CurrentDocument.ID });

        bool InAllowed(AttachmentData attachment) =>
            attachment.FileGroup != null &&
            allowed.Any(category =>
                string.Equals(category, attachment.FileGroup.ID, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(category, attachment.FileGroup.DisplayName, StringComparison.OrdinalIgnoreCase));

        var pdfs = attachments
            .Where(a => string.Equals(a.FileExtension?.TrimStart('.'), "pdf", StringComparison.OrdinalIgnoreCase))
            .Where(InAllowed)
            .ToList();

        if (pdfs.Count == 0)
            throw new InvalidOperationException(
                $"Brak zalacznika PDF w dozwolonych kategoriach ({string.Join(", ", allowed)}).");
        if (pdfs.Count > 1)
            throw new InvalidOperationException(
                $"Wiecej niz jeden PDF w dozwolonych kategoriach ({string.Join(", ", allowed)}); zrodlo niejednoznaczne.");
        return pdfs[0];
    }
}
```

- [ ] **Step 2: Utwórz konfigurację akcji**

Create `webcon-action/RemovePagesActionConfig.cs`:

```csharp
using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class RemovePagesActionConfig : SplitterConnectionConfig
{
    [ConfigEditableText(
        DisplayName = "Dozwolone kategorie zalacznikow",
        Description = "Nazwy lub ID kategorii (grup) zalacznikow, na ktorych akcja moze dzialac. " +
                      "Kilka rozdziel srednikiem. Akcja wymaga dokladnie jednego PDF w tych kategoriach.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 10)]
    public string AllowedCategories { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Zakres stron do usuniecia",
        Description = "Strony 1-based, inclusive, np. '2-4,7'. Mozna przeciagnac tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 11)]
    public string PageRange { get; set; } = "";

    [ConfigEditableBool(
        DisplayName = "Podmien zawartosc w miejscu",
        Description = "Wlaczone: usuwa strony z istniejacego zalacznika (nadpisuje). " +
                      "Wylaczone: dodaje nowy zalacznik z wynikiem, oryginal zostaje.",
        Order = 12)]
    public bool ReplaceInPlace { get; set; }
}
```

- [ ] **Step 3: Utwórz akcję**

Create `webcon-action/RemovePagesAction.cs`:

```csharp
using System;
using System.IO;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

public class RemovePagesAction : CustomAction<RemovePagesActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        var pluginVersion = typeof(RemovePagesAction).Assembly.GetName().Version?.ToString(3) ?? "?";
        try
        {
            var source = await AttachmentSourceHelper.GetSinglePdfInCategoriesAsync(
                args, Configuration.AllowedCategories);
            var pdfContent = await source.GetContentAsync();

            PageOpResult result;
            using (var httpClient = new System.Net.Http.HttpClient
                   { Timeout = TimeSpan.FromSeconds(Configuration.TimeoutSeconds) })
            {
                var client = new SplitterClient(httpClient, Configuration.SplitterBaseUrl, Configuration.ApiToken);
                result = await client.RemovePagesAsync(
                    source.FileName,
                    new MemoryStream(pdfContent),
                    Configuration.PageRange,
                    args.Context.CurrentDocument.ID);
            }

            var outputBytes = Convert.FromBase64String(result.FileContentBase64);
            var manager = new DocumentAttachmentsManager(args.Context);

            if (Configuration.ReplaceInPlace)
            {
                source.SetContent(outputBytes);
                await manager.UpdateAttachmentAsync(new UpdateAttachmentParams { Attachment = source });
            }
            else
            {
                var newAttachment = await manager.GetNewAttachmentAsync(result.OutputFileName, outputBytes);
                if (source.FileGroup != null)
                    await newAttachment.SetFileGroupAsync(source.FileGroup.ID);
                await manager.AddAttachmentAsync(new AddAttachmentParams
                {
                    DocumentId = args.Context.CurrentDocument.ID,
                    Attachment = newAttachment,
                });
            }

            args.LogMessage =
                $"RemovePagesAction v{pluginVersion}. Zrodlo '{source.FileName}' (ID {source.ID}); " +
                $"usunieto strony '{Configuration.PageRange}'; wynik {result.PageCount} stron; " +
                $"tryb: {(Configuration.ReplaceInPlace ? "podmiana w miejscu" : "nowy zalacznik")}.";
        }
        catch (Exception ex)
        {
            args.HasErrors = true;
            args.Message = $"Usuwanie stron nie powiodlo sie: {ex.Message}";
            args.LogMessage = $"RemovePagesAction v{pluginVersion}. {ex}";
        }
    }
}
```

- [ ] **Step 4: Build**

Run: `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release`
Expected: Build succeeded, 0 errors.

- [ ] **Step 5: Commit**

```bash
git add webcon-action/AttachmentSourceHelper.cs webcon-action/RemovePagesActionConfig.cs webcon-action/RemovePagesAction.cs
git commit -m "feat: RemovePagesAction - reczne usuwanie stron z zalacznika"
```

---

### Task 10: `ExtractPagesToNewFormAction`

**Files:**
- Create: `webcon-action/ExtractPagesToNewFormActionConfig.cs`
- Create: `webcon-action/ExtractPagesToNewFormAction.cs`

**Interfaces:**
- Consumes: `AttachmentSourceHelper`, `SplitterClient`, `PageOpResult`.
- Produces: `ExtractPagesToNewFormAction : CustomAction<ExtractPagesToNewFormActionConfig>` — tworzy surowy element potomny z wyciętymi stronami; opcjonalnie usuwa je ze źródła.

- [ ] **Step 1: Utwórz konfigurację**

Create `webcon-action/ExtractPagesToNewFormActionConfig.cs`:

```csharp
using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class ExtractPagesToNewFormActionConfig : SplitterConnectionConfig
{
    [ConfigEditableText(
        DisplayName = "Dozwolone kategorie zalacznikow",
        Description = "Nazwy lub ID kategorii (grup) zalacznikow zrodlowych. Kilka rozdziel srednikiem. " +
                      "Akcja wymaga dokladnie jednego PDF w tych kategoriach.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 10)]
    public string AllowedCategories { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Zakres stron do wyciecia",
        Description = "Strony 1-based, inclusive, np. '3-5'. Mozna przeciagnac tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 11)]
    public string PageRange { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Target workflow ID",
        Description = "ID obiegu, w ktorym ma powstac nowy element weryfikacyjny. Liczba lub tag/stala.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 12)]
    public string TargetWorkflowId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Target document type ID",
        Description = "ID typu formularza nowego elementu. Liczba lub tag/stala.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 13)]
    public string TargetDocTypeId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Start path ID",
        Description = "ID sciezki, ktora nowy element ma wystartowac. Liczba lub tag/stala.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 14)]
    public string StartPathId { get; set; } = "";

    [ConfigEditableBool(
        DisplayName = "Usun wyciete strony ze zrodla",
        Description = "Wlaczone: po wycieciu usuwa te strony z zalacznika zrodlowego (przenoszenie). " +
                      "Wylaczone: zrodlo zostaje nietkniete (kopiowanie).",
        Order = 15)]
    public bool RemoveFromSource { get; set; }
}
```

- [ ] **Step 2: Utwórz akcję**

Create `webcon-action/ExtractPagesToNewFormAction.cs`:

```csharp
using System;
using System.Globalization;
using System.IO;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

public class ExtractPagesToNewFormAction : CustomAction<ExtractPagesToNewFormActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        var pluginVersion = typeof(ExtractPagesToNewFormAction).Assembly.GetName().Version?.ToString(3) ?? "?";
        try
        {
            var targetWorkflowId = ParseId(Configuration.TargetWorkflowId, "Target workflow ID");
            var targetDocTypeId = ParseId(Configuration.TargetDocTypeId, "Target document type ID");
            var startPathId = ParseId(Configuration.StartPathId, "Start path ID");

            var source = await AttachmentSourceHelper.GetSinglePdfInCategoriesAsync(
                args, Configuration.AllowedCategories);
            var pdfContent = await source.GetContentAsync();

            PageOpResult extractResult;
            PageOpResult removeResult = null;
            using (var httpClient = new System.Net.Http.HttpClient
                   { Timeout = TimeSpan.FromSeconds(Configuration.TimeoutSeconds) })
            {
                var client = new SplitterClient(httpClient, Configuration.SplitterBaseUrl, Configuration.ApiToken);
                extractResult = await client.ExtractPagesAsync(
                    source.FileName, new MemoryStream(pdfContent), Configuration.PageRange,
                    args.Context.CurrentDocument.ID);

                if (Configuration.RemoveFromSource)
                    removeResult = await client.RemovePagesAsync(
                        source.FileName, new MemoryStream(pdfContent), Configuration.PageRange,
                        args.Context.CurrentDocument.ID);
            }

            var documentsManager = new DocumentsManager(args.Context);
            var newDocument = await documentsManager.GetNewDocumentAsync(
                new GetNewDocumentParams(targetWorkflowId, targetDocTypeId)
                {
                    ParentDocumentID = args.Context.CurrentDocument.ID,
                });

            await newDocument.Attachments.AddNewAsync(
                extractResult.OutputFileName,
                Convert.FromBase64String(extractResult.FileContentBase64));
            await newDocument.Comment.AddCommentAsync(
                $"Wyciete ze zrodla '{source.FileName}', strony '{Configuration.PageRange}'.");

            var started = await documentsManager.StartNewWorkFlowAsync(
                new StartNewWorkFlowParams(newDocument, startPathId));

            if (removeResult != null)
            {
                var manager = new DocumentAttachmentsManager(args.Context);
                source.SetContent(Convert.FromBase64String(removeResult.FileContentBase64));
                await manager.UpdateAttachmentAsync(new UpdateAttachmentParams { Attachment = source });
            }

            args.LogMessage =
                $"ExtractPagesToNewFormAction v{pluginVersion}. Zrodlo '{source.FileName}' (ID {source.ID}); " +
                $"wyciete strony '{Configuration.PageRange}' ({extractResult.PageCount} stron); " +
                $"utworzono element {started.CreatedDocumentID}; " +
                $"zrodlo: {(Configuration.RemoveFromSource ? "strony usuniete" : "nietkniete")}.";
        }
        catch (Exception ex)
        {
            args.HasErrors = true;
            args.Message = $"Wyciecie stron do nowego elementu nie powiodlo sie: {ex.Message}";
            args.LogMessage = $"ExtractPagesToNewFormAction v{pluginVersion}. {ex}";
        }
    }

    private static int ParseId(string configuredValue, string fieldName)
    {
        if (int.TryParse(configuredValue?.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var id) && id > 0)
            return id;
        throw new InvalidOperationException(
            $"Pole konfiguracji '{fieldName}' musi byc dodatnia liczba calkowita, otrzymano: '{configuredValue}'.");
    }
}
```

- [ ] **Step 3: Build**

Run: `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release`
Expected: Build succeeded, 0 errors.

- [ ] **Step 4: Commit**

```bash
git add webcon-action/ExtractPagesToNewFormActionConfig.cs webcon-action/ExtractPagesToNewFormAction.cs
git commit -m "feat: ExtractPagesToNewFormAction - wyciecie stron do surowego elementu"
```

---

### Task 11: `MergeAttachmentsAction`

**Files:**
- Create: `webcon-action/MergeAttachmentsActionConfig.cs`
- Create: `webcon-action/MergeAttachmentsAction.cs`

**Interfaces:**
- Consumes: `SplitterClient`, `MergeInput`, `PageOpResult`.
- Produces: `MergeAttachmentsAction : CustomAction<MergeAttachmentsActionConfig>` — czyta listę pozycji w kolejności wierszy, skleja wskazane załączniki, dodaje wynik jako nowy załącznik.

- [ ] **Step 1: Utwórz konfigurację**

Create `webcon-action/MergeAttachmentsActionConfig.cs`:

```csharp
using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class MergeAttachmentsActionConfig : SplitterConnectionConfig, IConfigEditableItemList
{
    [ConfigEditableItemList(
        DisplayName = "Lista pozycji z zalacznikami",
        Description = "Lista pozycji, w ktorej kazdy wiersz wskazuje jeden zalacznik do sklejenia. " +
                      "Kolejnosc wierszy = kolejnosc sklejania.")]
    public int ItemListId { get; set; }

    [ConfigEditableItemListColumnID(
        DisplayName = "Kolumna z ID zalacznika",
        Description = "Kolumna typu picker (zrodlo danych zwracajace ID i nazwy zalacznikow formularza). " +
                      "Akcja czyta zapisane ID zalacznika z kazdego wiersza.",
        IsRequired = true,
        ItemListColumnTypes = ItemListColumnTypes.Picker)]
    public int AttachmentIdColumnId { get; set; }

    [ConfigEditableText(
        DisplayName = "Nazwa pliku wynikowego",
        Description = "Nazwa sklejonego PDF dodawanego do biezacego elementu, np. 'scalony.pdf'.",
        DefaultText = "scalony.pdf",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 13)]
    public string OutputFileName { get; set; } = "scalony.pdf";
}
```

- [ ] **Step 2: Utwórz akcję**

Create `webcon-action/MergeAttachmentsAction.cs`:

```csharp
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

public class MergeAttachmentsAction : CustomAction<MergeAttachmentsActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        var pluginVersion = typeof(MergeAttachmentsAction).Assembly.GetName().Version?.ToString(3) ?? "?";
        try
        {
            var itemList = args.Context.CurrentDocument.ItemsLists.GetByID(Configuration.ItemListId);
            if (itemList == null)
                throw new InvalidOperationException(
                    $"Nie znaleziono listy pozycji o ID {Configuration.ItemListId}.");

            var manager = new DocumentAttachmentsManager(args.Context);
            var inputs = new List<MergeInput>();
            foreach (var row in itemList.Rows)
            {
                var rawValue = row.GetCellValue(Configuration.AttachmentIdColumnId, EntityValueFormat.PairID);
                var idText = rawValue?.ToString()?.Trim();
                if (string.IsNullOrEmpty(idText))
                    continue; // pomijamy puste wiersze (niewybrany zalacznik)
                if (!int.TryParse(idText, NumberStyles.Integer, CultureInfo.InvariantCulture, out var attachmentId))
                    throw new InvalidOperationException(
                        $"Wartosc '{idText}' w wierszu listy pozycji nie jest poprawnym ID zalacznika.");

                var attachment = await manager.GetAttachmentAsync(attachmentId, false);
                var content = await attachment.GetContentAsync();
                inputs.Add(new MergeInput { FileName = attachment.FileName, Content = content });
            }

            if (inputs.Count == 0)
                throw new InvalidOperationException(
                    "Lista pozycji nie wskazuje zadnego zalacznika do sklejenia.");

            PageOpResult result;
            using (var httpClient = new System.Net.Http.HttpClient
                   { Timeout = TimeSpan.FromSeconds(Configuration.TimeoutSeconds) })
            {
                var client = new SplitterClient(httpClient, Configuration.SplitterBaseUrl, Configuration.ApiToken);
                result = await client.MergeAsync(inputs, args.Context.CurrentDocument.ID);
            }

            var outputBytes = Convert.FromBase64String(result.FileContentBase64);
            var newAttachment = await manager.GetNewAttachmentAsync(Configuration.OutputFileName, outputBytes);
            await manager.AddAttachmentAsync(new AddAttachmentParams
            {
                DocumentId = args.Context.CurrentDocument.ID,
                Attachment = newAttachment,
            });

            args.LogMessage =
                $"MergeAttachmentsAction v{pluginVersion}. Sklejono {inputs.Count} zalacznikow " +
                $"w '{Configuration.OutputFileName}' ({result.PageCount} stron).";
        }
        catch (Exception ex)
        {
            args.HasErrors = true;
            args.Message = $"Sklejanie zalacznikow nie powiodlo sie: {ex.Message}";
            args.LogMessage = $"MergeAttachmentsAction v{pluginVersion}. {ex}";
        }
    }
}
```

- [ ] **Step 3: Build**

Run: `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release`
Expected: Build succeeded, 0 errors.

> Jeśli build zgłosi, że `EntityValueFormat` jest nierozpoznany, dodaj `using WebCon.WorkFlow.SDK.Documents.Model;` (już jest) — enum żyje w tej przestrzeni nazw (`WebCon.WorkFlow.SDK.Documents.Model.EntityValueFormat`).

- [ ] **Step 4: Commit**

```bash
git add webcon-action/MergeAttachmentsActionConfig.cs webcon-action/MergeAttachmentsAction.cs
git commit -m "feat: MergeAttachmentsAction - sklejanie zalacznikow wg listy pozycji"
```

---

### Task 12: Rejestracja akcji w manifeście + dokumentacja

**Files:**
- Modify: `webcon-action/WebconPdfSplitterAction.json`
- Modify: `README.md`

**Interfaces:** brak nowych.

- [ ] **Step 1: Dodaj trzy wpisy do manifestu**

Replace `webcon-action/WebconPdfSplitterAction.json` with:

```json
{
  "extensions": [
    {
      "guid": "5a984326-8f99-464a-b6ae-fb673055938c",
      "name": "SplitPdfAction",
      "description": "Dzieli zbiorczy PDF paczki skanu na osobne dokumenty HR przez lokalny serwis PDF Splitter i tworzy elementy potomne.",
      "assembly": "WebconPdfSplitterAction",
      "class": "WebconPdfSplitterAction.SplitPdfAction",
      "type": "CustomAction"
    },
    {
      "guid": "b3158154-3836-42a7-abe1-13712729486d",
      "name": "RemovePagesAction",
      "description": "Usuwa wskazany zakres stron z zalacznika PDF (jednego w dozwolonych kategoriach); podmienia w miejscu lub tworzy nowy zalacznik.",
      "assembly": "WebconPdfSplitterAction",
      "class": "WebconPdfSplitterAction.RemovePagesAction",
      "type": "CustomAction"
    },
    {
      "guid": "d707e16e-80df-4395-8f68-76000f90d838",
      "name": "ExtractPagesToNewFormAction",
      "description": "Wycina wskazane strony z zalacznika PDF i tworzy nowy (surowy) element weryfikacyjny; opcjonalnie usuwa strony ze zrodla.",
      "assembly": "WebconPdfSplitterAction",
      "class": "WebconPdfSplitterAction.ExtractPagesToNewFormAction",
      "type": "CustomAction"
    },
    {
      "guid": "b9bfe1d9-07ca-4cd7-bc6f-002f75ed3a9e",
      "name": "MergeAttachmentsAction",
      "description": "Skleja wybrane zalaczniki PDF w jeden wg kolejnosci wierszy listy pozycji i dodaje wynik do biezacego elementu.",
      "assembly": "WebconPdfSplitterAction",
      "class": "WebconPdfSplitterAction.MergeAttachmentsAction",
      "type": "CustomAction"
    }
  ],
  "dependencies": [
    "WebconPdfSplitterAction",
    "Newtonsoft.Json"
  ]
}
```

- [ ] **Step 2: Opisz akcje w README**

W `README.md`, w sekcji o akcjach WEBCON (obok `SplitPdfAction`), dodaj:

```markdown
### Ręczne akcje operatora

- **RemovePagesAction** — usuwa zakres stron (np. `2-4,7`) z jedynego PDF-a w dozwolonych kategoriach załącznika. Przełącznik „Podmień w miejscu" (nadpisz) lub dodanie nowego załącznika.
- **ExtractPagesToNewFormAction** — wycina strony do nowego, surowego elementu (bez klasyfikacji) w obiegu docelowym; przełącznik „Usuń wycięte strony ze źródła".
- **MergeAttachmentsAction** — skleja załączniki wskazane w liście pozycji (wiersz = załącznik, kolejność wierszy = kolejność) w jeden PDF dodawany do bieżącego elementu.

Wszystkie trzy dzielą konfigurację połączenia (URL/token/timeout) z `SplitPdfAction`.
Kategorie załączników w konfiguracji podaje się nazwami lub ID grup, rozdzielone średnikami.
```

- [ ] **Step 3: Build kontrolny + commit**

Run: `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release`
Expected: Build succeeded, 0 errors.

```bash
git add webcon-action/WebconPdfSplitterAction.json README.md
git commit -m "feat: rejestracja trzech recznych akcji w manifescie + README"
```

---

### Task 13: Pełny build serwisu i pluginu + paczka

**Files:** brak zmian kodu (weryfikacja końcowa).

- [ ] **Step 1: Testy serwisu**

Run: `cd splitter && python -m pytest -q`
Expected: PASS — cała bateria testów zielona.

- [ ] **Step 2: Zbuduj paczkę pluginu**

Run: `powershell -File webcon-action/package.ps1`
Expected: `Pakiet gotowy: ...WebconPdfSplitterAction-1.0.9.zip` (wersja bumpnięta o 1 z 1.0.8), build bez błędów, ZIP zawiera `WebconPdfSplitterAction.dll`, `Newtonsoft.Json.dll`, `WebconPdfSplitterAction.json`.

- [ ] **Step 3: Commit bumpu wersji**

```bash
git add webcon-action/version.txt
git commit -m "build: paczka pluginu 1.0.9 z recznymi akcjami PDF"
```

---

## Self-Review

**Spec coverage:**
- Endpoint remove/extract/merge → Tasks 4, 5. ✅
- `parse_page_range` walidacja → Task 1. ✅
- `remove/extract/merge` w pdf_io → Task 2. ✅
- Kontrakt `PageOpResult` → Task 3. ✅
- Wybór źródła po kategorii, dokładnie jeden PDF → Task 9 (`AttachmentSourceHelper`). ✅
- Los źródła konfigurowalny per akcja: `ReplaceInPlace` (Task 9), `RemoveFromSource` (Task 10). ✅
- Surowy element bez klasyfikacji → Task 10 (brak wywołania `/api/split`). ✅
- Sklejanie: lista pozycji, kolejność wierszy, ID załącznika, wynik jako nowy załącznik, źródła zostają → Task 11. ✅
- Wspólna baza konfiguracji + migracja `SplitPdfActionConfig` → Task 7. ✅
- `SplitterClient` metody + auth/deserializacja → Task 8. ✅
- Obsługa błędów (HTTP 400 detail → `args.Message`) → Task 8 (`PostAsync` rzuca z treścią), akcje mapują na `args.Message`. ✅
- Testy pytest → Tasks 1-5. ✅
- Rejestracja akcji + wersja → Tasks 12, 13. ✅

**Type consistency:** `PageOpResult` (Python i C#) — pola `outputFileName/pageCount/fileContentBase64/warnings`. `RemovePagesAsync/ExtractPagesAsync` sygnatura `(string, Stream, string, int?)`. `MergeAsync(IReadOnlyList<MergeInput>, int?)`. `GetSinglePdfInCategoriesAsync(RunCustomActionParams, string)`. `EntityValueFormat.PairID`, `ItemListColumnTypes.Picker`, `IConfigEditableItemList.ItemListId` — zgodne z API SDK 26.1.6.209. Spójne między taskami.

**Placeholder scan:** brak TBD/TODO; każdy krok zawiera kod i komendy z oczekiwanym wynikiem.

## Ryzyka i weryfikacja przy pierwszym uruchomieniu w WEBCON

Zweryfikowane w assembly SDK 26.1.6.209 (refleksja + `WebCon.WorkFlow.SDK.xml`):
`AttachmentData.FileGroup/GetContentAsync/SetContent`, `DocumentAttachmentsManager.{GetAttachmentsAsync,GetAttachmentAsync,GetNewAttachmentAsync,AddAttachmentAsync,UpdateAttachmentAsync}`, `CurrentDocumentData.ItemsLists`, `ItemsList.Rows`, `ItemRowData.GetCellValue(int, EntityValueFormat)`, atrybuty `ConfigEditableBool/ConfigEditableItemList/ConfigEditableItemListColumnID`, `IConfigEditableItemList`.

Do potwierdzenia dopiero na środowisku WEBCON (nie blokuje implementacji):
- Czy designer konfiguracji renderuje pola dziedziczone z `SplitterConnectionConfig` (Task 7). Jeśli nie — cofnąć migrację `SplitPdfActionConfig` i zduplikować trójkę pól w nowych configach.
- Czy `row.GetCellValue(columnId, EntityValueFormat.PairID)` dla kolumny picker zwraca ID załącznika jako string (zależy od konfiguracji źródła danych kolumny w procesie).
