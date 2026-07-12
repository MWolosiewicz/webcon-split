# OCR fallback dla skanów — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skany bez warstwy tekstowej dostają tekst z Tesseracta przed
klasyfikacją, a strony puste również po OCR omijają LLM i idą do ręcznej
weryfikacji.

**Architecture:** OCR to etap zdobycia tekstu przed niezmienioną
klasyfikacją. Za istniejącym protokołem `OcrEngine` staje kompozyt
`TextLayerWithOcrFallback` (warstwa tekstowa + fallback per strona przez
wstrzykiwany `TesseractPageOcr`). Pipeline dostaje bramkę: strona pusta
(zero znaków alfanumerycznych) omija LLM.

**Tech Stack:** Python 3.11+, FastAPI, pypdf (jest), pypdfium2 (render),
pytesseract + binarka `tesseract` (OCR), Pillow (obraz). pytest.

## Global Constraints

- Python `>=3.11` (z `pyproject.toml`).
- Prefix zmiennych środowiskowych: `SPLITTER_` (pydantic-settings,
  `env_prefix="SPLITTER_"`, `extra="ignore"`).
- Powody weryzacji i logi po polsku w stylu ASCII (bez diakrytyków), spójnie
  z istniejącym kodem: np. `pewnosc`, `ponizej`, `doklejona`, `rowniez`.
- OCR nigdy nie wywraca żądania: każdy błąd OCR (brak binarki, timeout, błąd
  strony) → strona traktowana jak pusta, żądanie przetwarzane dalej.
- Dwa progi: OCR-trigger `ocr_min_text_chars` (domyślnie 25) w kompozycie;
  bramka LLM = pusta strona iff `alnum_count(text) == 0` (stała, bez env).
- Import lazy ciężkich bibliotek OCR wewnątrz metod (jak istniejący
  `PdfTextOcrEngine`, który importuje `pypdf` w metodzie).
- TDD: test → uruchom (fail) → implementacja → uruchom (pass) → commit.
- Uruchamianie testów z katalogu `splitter/`: `python -m pytest ...`.

---

### Task 1: Helper `alnum_count`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/ocr.py`
- Test: `splitter/tests/test_ocr.py` (create)

**Interfaces:**
- Produces: `alnum_count(text: str) -> int` w module `webcon_pdf_splitter.ocr`
  — liczy znaki alfanumeryczne (Unicode, `str.isalnum()`), używana przez
  kompozyt (Task 2) i pipeline (Task 4).

- [ ] **Step 1: Write the failing test**

Utwórz `splitter/tests/test_ocr.py`:

```python
from webcon_pdf_splitter.ocr import alnum_count


def test_alnum_count_ignores_whitespace_and_punctuation():
    assert alnum_count("   \n\t  ") == 0
    assert alnum_count("... --- ,,, ;") == 0


def test_alnum_count_counts_letters_and_digits():
    # "Umowa 2024" -> U m o w a 2 0 2 4 = 9
    assert alnum_count("Umowa 2024") == 9


def test_alnum_count_counts_polish_letters():
    # str.isalnum() jest swiadome Unicode: polskie litery licza sie
    assert alnum_count("zazolc gesla jazn") == 15
    assert alnum_count("łódź") == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_ocr.py -v`
Expected: FAIL — `ImportError: cannot import name 'alnum_count'`

- [ ] **Step 3: Write minimal implementation**

W `splitter/src/webcon_pdf_splitter/ocr.py` dodaj na górze (pod istniejącym
`from typing import Protocol`):

```python
def alnum_count(text: str) -> int:
    """Liczba znakow alfanumerycznych (Unicode) w tekscie strony.

    Wspolne zrodlo liczenia dla progu OCR (kompozyt) i bramki pustej
    strony (pipeline). Rozne progi, jeden sposob liczenia.
    """
    return sum(1 for ch in text if ch.isalnum())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_ocr.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/ocr.py splitter/tests/test_ocr.py
git commit -m "feat: alnum_count helper for OCR/empty-page thresholds"
```

---

### Task 2: Kompozyt `TextLayerWithOcrFallback`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/ocr.py`
- Test: `splitter/tests/test_ocr.py`

**Interfaces:**
- Consumes: `alnum_count` (Task 1); istniejący `PdfTextOcrEngine`
  (`extract_page_texts(pdf_path: str) -> list[str]`).
- Produces:
  - `TextLayerWithOcrFallback(page_ocr, text_layer=None, min_text_chars=25)`
    implementujący `OcrEngine.extract_page_texts(pdf_path) -> list[str]`.
  - Kontrakt wstrzykiwanego `page_ocr`:
    `ocr_pages(pdf_path: str, page_indices: list[int]) -> dict[int, str]`
    (klucz = indeks strony 0-based, wartość = rozpoznany tekst).
    Realizuje go `TesseractPageOcr` w Task 5.

- [ ] **Step 1: Write the failing test**

Dopisz do `splitter/tests/test_ocr.py`:

```python
from webcon_pdf_splitter.ocr import TextLayerWithOcrFallback


class _FakeTextLayer:
    def __init__(self, texts):
        self._texts = texts

    def extract_page_texts(self, pdf_path):
        return list(self._texts)


class _FakePageOcr:
    def __init__(self, results):
        self._results = results  # dict[int, str]
        self.calls = []

    def ocr_pages(self, pdf_path, page_indices):
        self.calls.append(list(page_indices))
        return {i: self._results.get(i, "") for i in page_indices}


class _RaisingPageOcr:
    def ocr_pages(self, pdf_path, page_indices):
        raise RuntimeError("tesseract binary missing")


def test_keeps_text_layer_and_skips_ocr_when_above_threshold():
    ocr = _FakePageOcr({})
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(
            [
                "Pelna umowa o prace z wieloma slowami w warstwie tekstowej",
                "Druga strona umowy rowniez z obszernym tekstem tutaj",
            ]
        ),
        min_text_chars=25,
    )

    result = composite.extract_page_texts("born-digital.pdf")

    assert result == [
        "Pelna umowa o prace z wieloma slowami w warstwie tekstowej",
        "Druga strona umowy rowniez z obszernym tekstem tutaj",
    ]
    assert ocr.calls == []  # OCR nie wolany dla stron z tekstem


def test_ocrs_only_pages_below_threshold_and_substitutes_text():
    ocr = _FakePageOcr({1: "TEKST Z OCR PO ROZPOZNANIU SKANU"})
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(
            ["Strona pierwsza ma duzo tekstu w warstwie tekstowej", ""]
        ),
        min_text_chars=25,
    )

    result = composite.extract_page_texts("mixed.pdf")

    assert result[0].startswith("Strona pierwsza")
    assert result[1] == "TEKST Z OCR PO ROZPOZNANIU SKANU"
    assert ocr.calls == [[1]]  # OCR tylko dla pustej strony, jednym wywolaniem


def test_page_stays_empty_when_ocr_returns_nothing():
    ocr = _FakePageOcr({1: "   "})
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(
            ["Strona pierwsza ma duzo tekstu w warstwie tekstowej", ""]
        ),
        min_text_chars=25,
    )

    result = composite.extract_page_texts("blank-scan.pdf")

    assert result[1] == "   "  # OCR nic nie znalazl -> strona zostaje pusta


def test_ocr_failure_does_not_break_extraction():
    composite = TextLayerWithOcrFallback(
        page_ocr=_RaisingPageOcr(),
        text_layer=_FakeTextLayer(
            ["Strona pierwsza ma duzo tekstu w warstwie tekstowej", ""]
        ),
        min_text_chars=25,
    )

    result = composite.extract_page_texts("scan.pdf")

    # brak binarki tesseract -> zadanie przetwarzane dalej, strona pusta
    assert result[0].startswith("Strona pierwsza")
    assert result[1] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_ocr.py -v`
Expected: FAIL — `ImportError: cannot import name 'TextLayerWithOcrFallback'`

- [ ] **Step 3: Write minimal implementation**

W `splitter/src/webcon_pdf_splitter/ocr.py` dodaj `import logging` na górze
i `logger = logging.getLogger(__name__)`, a poniżej `PdfTextOcrEngine` dopisz:

```python
class TextLayerWithOcrFallback:
    """Warstwa tekstowa + fallback OCR per strona.

    Czyta osadzony tekst jak PdfTextOcrEngine; dla stron ponizej progu
    `min_text_chars` uruchamia wstrzykniety page-OCR i podmienia tekst.
    OCR nigdy nie wywraca zadania: blad calego wywolania OCR jest lapany,
    dotkniete strony zostaja puste.
    """

    def __init__(self, page_ocr, text_layer=None, min_text_chars: int = 25) -> None:
        self._page_ocr = page_ocr
        self._text_layer = text_layer or PdfTextOcrEngine()
        self._min_text_chars = min_text_chars

    def extract_page_texts(self, pdf_path: str) -> list[str]:
        texts = list(self._text_layer.extract_page_texts(pdf_path))
        empty_indices = [
            index
            for index, text in enumerate(texts)
            if alnum_count(text) < self._min_text_chars
        ]
        if not empty_indices:
            return texts
        try:
            ocr_texts = self._page_ocr.ocr_pages(pdf_path, empty_indices)
        except Exception:
            logger.warning(
                "OCR nie powiodl sie dla stron %s - strony zostaja puste",
                [i + 1 for i in empty_indices],
                exc_info=True,
            )
            return texts
        for index, ocr_text in ocr_texts.items():
            texts[index] = ocr_text
        logger.info(
            "OCR: uzupelniono tekst %s stron (indeksy stron: %s)",
            len(empty_indices),
            [i + 1 for i in empty_indices],
        )
        return texts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_ocr.py -v`
Expected: PASS (7 passed — 3 z Task 1 + 4 nowe)

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/ocr.py splitter/tests/test_ocr.py
git commit -m "feat: TextLayerWithOcrFallback composite behind OcrEngine"
```

---

### Task 3: Ustawienia OCR w `SplitterSettings`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/config.py`
- Test: `splitter/tests/test_config_logging.py`

**Interfaces:**
- Produces: pola `SplitterSettings`: `ocr_enabled: bool = True`,
  `ocr_min_text_chars: int = 25`, `ocr_languages: str = "pol+eng"`,
  `ocr_dpi: int = 300`, `ocr_timeout_seconds: int = 30`. Czytane w Task 6.

- [ ] **Step 1: Write the failing test**

Dopisz do `splitter/tests/test_config_logging.py`:

```python
def test_ocr_settings_defaults():
    settings = SplitterSettings(_env_file=None)
    assert settings.ocr_enabled is True
    assert settings.ocr_min_text_chars == 25
    assert settings.ocr_languages == "pol+eng"
    assert settings.ocr_dpi == 300
    assert settings.ocr_timeout_seconds == 30


def test_ocr_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("SPLITTER_OCR_ENABLED", "false")
    monkeypatch.setenv("SPLITTER_OCR_MIN_TEXT_CHARS", "40")
    monkeypatch.setenv("SPLITTER_OCR_LANGUAGES", "pol")
    settings = SplitterSettings(_env_file=None)
    assert settings.ocr_enabled is False
    assert settings.ocr_min_text_chars == 40
    assert settings.ocr_languages == "pol"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_config_logging.py -v`
Expected: FAIL — `AttributeError: 'SplitterSettings' object has no attribute 'ocr_enabled'`

- [ ] **Step 3: Write minimal implementation**

W `splitter/src/webcon_pdf_splitter/config.py`, po polu `log_level`, dodaj:

```python
    ocr_enabled: bool = Field(default=True)
    ocr_min_text_chars: int = Field(default=25)
    ocr_languages: str = Field(default="pol+eng")
    ocr_dpi: int = Field(default=300)
    ocr_timeout_seconds: int = Field(default=30)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_config_logging.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/config.py splitter/tests/test_config_logging.py
git commit -m "feat: OCR settings (enabled, threshold, languages, dpi, timeout)"
```

---

### Task 4: Bramka "pusta strona omija LLM" w pipeline

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/pipeline.py`
- Test: `splitter/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `alnum_count` (Task 1).
- Produces: zmiana zachowania `ClassificationPipeline.split_pages` — strona
  z `alnum_count(text) == 0` nie woła LLM, jest doklejana z `requiresReview`
  i powodem `"strona N bez tekstu (rowniez po OCR) - dolaczona automatycznie"`.
- Zmiana wewnętrzna: `_UnmatchedPage` zyskuje pole `empty: bool = False`.

- [ ] **Step 1: Write the failing test**

Dopisz do `splitter/tests/test_pipeline.py` (używa istniejących helperów
`_make_pipeline` i `_StubLlm` z tego pliku):

```python
def test_empty_page_skips_llm_and_glues_with_review():
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

    # pusta strona 2 nie trafia do LLM mimo skonfigurowanej odpowiedzi
    assert stub.calls == []
    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]
    doc = result.documents[0]
    assert doc.requiresReview is True
    assert "glued_unknown_page:2" in doc.signals
    assert doc.reviewReasons == [
        "strona 2 bez tekstu (rowniez po OCR) - dolaczona automatycznie"
    ]


def test_leading_empty_pages_form_unknown_document():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        ["", "   ", "UMOWA O PRACE zawarta z pracodawca"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Nieznany typ dokumentu", 1, 2),
        ("Umowa o prace", 3, 3),
    ]
    unknown = result.documents[0]
    assert unknown.requiresReview is True
    assert (
        "strona 1 bez tekstu (rowniez po OCR) - dolaczona automatycznie"
        in unknown.reviewReasons
    )
    assert (
        "strona 2 bez tekstu (rowniez po OCR) - dolaczona automatycznie"
        in unknown.reviewReasons
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_pipeline.py -k "empty" -v`
Expected: FAIL — LLM jest wołany (stub.calls niepuste) i/lub reviewReasons
mają starą treść.

- [ ] **Step 3: Write minimal implementation**

W `splitter/src/webcon_pdf_splitter/classification/pipeline.py`:

(a) dodaj import na górze (pod istniejącymi importami):

```python
from webcon_pdf_splitter.ocr import alnum_count
```

(b) dodaj pole `empty` do `_UnmatchedPage`:

```python
@dataclass
class _UnmatchedPage:
    page_number: int
    phrase_affinities: list[str]
    llm: LlmClassification | None
    empty: bool = False
```

(c) w `split_pages`, zamień istniejącą linię:

```python
            llm = self._try_llm(page_texts, index, known_types, current)
```

na:

```python
            page_is_empty = alnum_count(text) == 0
            llm = (
                None
                if page_is_empty
                else self._try_llm(page_texts, index, known_types, current)
            )
```

(d) w tej samej pętli, w budowaniu `_UnmatchedPage`, ustaw flagę `empty`:

```python
            unmatched = _UnmatchedPage(
                page_number=page_number,
                phrase_affinities=sorted(page.phrase_affinities),
                llm=llm,
                empty=page_is_empty,
            )
```

(e) w `_unmatched_details`, na samym początku metody, przed obecnym kodem:

```python
    @staticmethod
    def _unmatched_details(page: _UnmatchedPage) -> str:
        if page.empty:
            return "strona bez tekstu (rowniez po OCR) - dolaczona automatycznie"
        if page.phrase_affinities:
```

(reszta metody bez zmian).

(f) w `_review_reasons` ujednolić formatowanie powodu per strona przez nowy
helper, tak aby pusta strona dawała identyczny powód w segmencie znanym
i nieznanym. Zamień całe pętle po `segment.unmatched_pages` (obie gałęzie)
tak, by wołały helper. Obecny fragment:

```python
        if not segment.known:
            reasons.append("nierozpoznany typ dokumentu (zadna regula nie pasowala)")
            for page in segment.unmatched_pages:
                reasons.append(f"strona {page.page_number}: {self._unmatched_details(page)}")
        else:
            for page in segment.unmatched_pages:
                reasons.append(
                    f"strona {page.page_number} doklejona bez dopasowania do wzorca "
                    f"({self._unmatched_details(page)})"
                )
```

zamień na:

```python
        if not segment.known:
            reasons.append("nierozpoznany typ dokumentu (zadna regula nie pasowala)")
            for page in segment.unmatched_pages:
                reasons.append(self._page_review_reason(page, known=False))
        else:
            for page in segment.unmatched_pages:
                reasons.append(self._page_review_reason(page, known=True))
```

oraz dodaj nowy helper obok `_unmatched_details`:

```python
    def _page_review_reason(self, page: _UnmatchedPage, known: bool) -> str:
        if page.empty:
            return (
                f"strona {page.page_number} bez tekstu (rowniez po OCR) "
                "- dolaczona automatycznie"
            )
        if known:
            return (
                f"strona {page.page_number} doklejona bez dopasowania do wzorca "
                f"({self._unmatched_details(page)})"
            )
        return f"strona {page.page_number}: {self._unmatched_details(page)}"
```

(Dla stron niepustych helper zwraca dokładnie te same napisy co dotychczas,
więc istniejące testy `test_review_reasons_*` pozostają zielone.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_pipeline.py -v`
Expected: PASS (nowe testy + wszystkie dotychczasowe — żaden istniejący
przypadek nie używa strony z zerem znaków alfanumerycznych, więc pozostają
zielone).

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/tests/test_pipeline.py
git commit -m "feat: empty pages skip LLM, glued with review reason"
```

---

### Task 5: Silnik `TesseractPageOcr` + zależności runtime

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/ocr.py`
- Modify: `splitter/pyproject.toml`
- Test: `splitter/tests/test_ocr.py`

**Interfaces:**
- Produces: `TesseractPageOcr(languages="pol+eng", dpi=300, timeout_seconds=30)`
  z metodą `ocr_pages(pdf_path: str, page_indices: list[int]) -> dict[int, str]`
  — kontrakt wstrzykiwany do kompozytu (Task 2). Ładuje dokument PDFium raz na
  wywołanie; per strona łapie błędy (timeout/render) i zwraca `""`.

- [ ] **Step 1: Dodaj zależności i przeinstaluj pakiet**

W `splitter/pyproject.toml`, w tablicy `dependencies`, dodaj trzy pozycje:

```toml
  "pypdfium2>=4.30",
  "pytesseract>=0.3.10",
  "Pillow>=10.0",
```

Zainstaluj do środowiska deweloperskiego:

Run: `cd splitter && pip install -e .`
Expected: instalacja pypdfium2, pytesseract, Pillow zakończona sukcesem.

- [ ] **Step 2: Write the failing integration test**

Dopisz do `splitter/tests/test_ocr.py` (na górze pliku dodaj importy
`import shutil` i `import pytest`):

```python
import shutil
import pytest

from webcon_pdf_splitter.ocr import TesseractPageOcr

_TESSERACT_MISSING = shutil.which("tesseract") is None


@pytest.mark.skipif(_TESSERACT_MISSING, reason="brak binarki tesseract")
def test_tesseract_ocr_recognizes_rendered_text(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (700, 220), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=64)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((30, 70), "UMOWA", fill="black", font=font)
    pdf_path = tmp_path / "scan.pdf"
    image.save(str(pdf_path), "PDF")

    engine = TesseractPageOcr(languages="eng", dpi=200)
    result = engine.ocr_pages(str(pdf_path), [0])

    assert "UMOWA" in result[0].upper()


@pytest.mark.skipif(_TESSERACT_MISSING, reason="brak binarki tesseract")
def test_tesseract_ocr_empty_index_list_returns_empty_dict(tmp_path):
    from PIL import Image

    pdf_path = tmp_path / "scan.pdf"
    Image.new("RGB", (200, 200), "white").save(str(pdf_path), "PDF")

    engine = TesseractPageOcr()
    assert engine.ocr_pages(str(pdf_path), []) == {}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_ocr.py -k tesseract -v`
Expected: FAIL — `ImportError: cannot import name 'TesseractPageOcr'`
(jeśli binarka tesseract jest zainstalowana). Gdy binarki brak: testy
oznaczone SKIPPED, ale import `TesseractPageOcr` i tak musi się powieść —
wtedy uruchom cały plik: `python -m pytest tests/test_ocr.py -v` i sprawdź,
że kolekcja pliku nie wywala się na imporcie (obecnie wywali się na braku
klasy).

- [ ] **Step 4: Write minimal implementation**

W `splitter/src/webcon_pdf_splitter/ocr.py`, poniżej `TextLayerWithOcrFallback`,
dodaj:

```python
class TesseractPageOcr:
    """OCR wybranych stron przez Tesseract (pypdfium2 render -> pytesseract).

    Laduje dokument PDFium raz na wywolanie. Per strona lapie bledy
    (timeout/render/brak binarki) i zwraca pusty tekst dla tej strony,
    aby OCR nigdy nie wywracal calego zadania.
    """

    def __init__(
        self,
        languages: str = "pol+eng",
        dpi: int = 300,
        timeout_seconds: int = 30,
    ) -> None:
        self._languages = languages
        self._dpi = dpi
        self._timeout_seconds = timeout_seconds

    def ocr_pages(self, pdf_path: str, page_indices: list[int]) -> dict[int, str]:
        if not page_indices:
            return {}
        import pypdfium2 as pdfium
        import pytesseract

        results: dict[int, str] = {}
        pdf = pdfium.PdfDocument(pdf_path)
        try:
            for index in page_indices:
                try:
                    page = pdf[index]
                    bitmap = page.render(scale=self._dpi / 72.0)
                    image = bitmap.to_pil()
                    results[index] = pytesseract.image_to_string(
                        image,
                        lang=self._languages,
                        timeout=self._timeout_seconds,
                    )
                except Exception:
                    logger.warning(
                        "OCR strony %s nie powiodl sie - strona pusta",
                        index + 1,
                        exc_info=True,
                    )
                    results[index] = ""
        finally:
            pdf.close()
        return results
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_ocr.py -v`
Expected: PASS lub SKIPPED dla testów `tesseract` (zależnie od obecności
binarki); pozostałe testy `test_ocr.py` PASS. Kolekcja pliku bez błędu
importu.

- [ ] **Step 6: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/ocr.py splitter/pyproject.toml splitter/tests/test_ocr.py
git commit -m "feat: TesseractPageOcr engine (pypdfium2 + pytesseract) and deps"
```

---

### Task 6: Wpięcie wyboru silnika OCR w API

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/api.py`
- Test: `splitter/tests/test_api.py`

**Interfaces:**
- Consumes: `SplitterSettings` OCR fields (Task 3), `TextLayerWithOcrFallback`
  + `TesseractPageOcr` (Task 2, 5), `PdfTextOcrEngine` (istnieje),
  `ocr_min_text_chars` do pipeline.
- Produces: `build_ocr_engine(settings: SplitterSettings) -> OcrEngine`
  w `api.py`; `_split` używa `build_ocr_engine(settings)` zamiast
  `PdfTextOcrEngine()`. Pipeline bez zmian (bramka pustej strony to stała
  `== 0`, nie potrzebuje progu z ustawień).

- [ ] **Step 1: Write the failing test**

Dopisz do `splitter/tests/test_api.py`:

```python
def test_build_ocr_engine_selects_fallback_when_enabled():
    from webcon_pdf_splitter.api import build_ocr_engine
    from webcon_pdf_splitter.config import SplitterSettings
    from webcon_pdf_splitter.ocr import PdfTextOcrEngine, TextLayerWithOcrFallback

    enabled = SplitterSettings(_env_file=None, ocr_enabled=True)
    assert isinstance(build_ocr_engine(enabled), TextLayerWithOcrFallback)

    disabled = SplitterSettings(_env_file=None, ocr_enabled=False)
    assert isinstance(build_ocr_engine(disabled), PdfTextOcrEngine)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_api.py -k build_ocr_engine -v`
Expected: FAIL — `ImportError: cannot import name 'build_ocr_engine'`

- [ ] **Step 3: Write minimal implementation**

W `splitter/src/webcon_pdf_splitter/api.py`:

(a) rozszerz import z `ocr` (zamień istniejącą linię
`from webcon_pdf_splitter.ocr import PdfTextOcrEngine`):

```python
from webcon_pdf_splitter.ocr import (
    PdfTextOcrEngine,
    TesseractPageOcr,
    TextLayerWithOcrFallback,
)
```

(b) dodaj funkcję fabryki obok `build_llm_classifier`:

```python
def build_ocr_engine(settings: SplitterSettings):
    if settings.ocr_enabled:
        return TextLayerWithOcrFallback(
            page_ocr=TesseractPageOcr(
                languages=settings.ocr_languages,
                dpi=settings.ocr_dpi,
                timeout_seconds=settings.ocr_timeout_seconds,
            ),
            min_text_chars=settings.ocr_min_text_chars,
        )
    return PdfTextOcrEngine()
```

(c) w `_split`, zamień jedną linię:

```python
    ocr = PdfTextOcrEngine()
```

na:

```python
    ocr = build_ocr_engine(settings)
```

Konstrukcja `ClassificationPipeline` pozostaje bez zmian — bramka pustej
strony (Task 4) używa stałej `alnum_count(text) == 0`, więc pipeline nie
potrzebuje progu z ustawień.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Uruchom pełny zestaw testów**

Run: `cd splitter && python -m pytest -v`
Expected: wszystkie PASS (testy `tesseract` SKIPPED jeśli brak binarki).

- [ ] **Step 6: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_api.py
git commit -m "feat: wire OCR engine selection into split endpoint"
```

---

### Task 7: Obraz Dockera i dokumentacja zmiennych

**Files:**
- Modify: `splitter/Dockerfile`
- Modify: `splitter/docker-compose.yml`
- Modify: `splitter/docs/deployment/splitter-service.md` (jeśli istnieje;
  w innym wypadku pomiń ten plik)

**Interfaces:** brak nowego kodu; zmiana obrazu (binarka tesseract) i
dokumentacja. Weryfikacja przez build kontenera, nie pytest.

- [ ] **Step 1: Dodaj warstwę apt z Tesseractem**

W `splitter/Dockerfile`, między `WORKDIR /app` a `COPY pyproject.toml ./`,
wstaw:

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-pol \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Udokumentuj zmienne OCR w compose**

W `splitter/docker-compose.yml`, w bloku komentarza przy `env_file`, dopisz
(komentarz, wartości domyślne — nie trzeba ich ustawiać):

```yaml
    # Zmienne OCR (opcjonalne, wartosci domyslne w nawiasach):
    #   SPLITTER_OCR_ENABLED (true)          - fallback Tesseract dla skanow
    #   SPLITTER_OCR_MIN_TEXT_CHARS (25)     - ponizej -> strona idzie do OCR
    #   SPLITTER_OCR_LANGUAGES (pol+eng)     - jezyki Tesseracta
    #   SPLITTER_OCR_DPI (300)               - rozdzielczosc renderu strony
    #   SPLITTER_OCR_TIMEOUT_SECONDS (30)    - limit OCR jednej strony
```

- [ ] **Step 3: Zbuduj obraz i zweryfikuj obecność binarki**

Run: `cd splitter && docker compose build`
Expected: build kończy się sukcesem.

Run: `docker compose run --rm --entrypoint tesseract splitter --list-langs`
Expected: lista języków zawiera `pol` i `eng`.

- [ ] **Step 4: Weryfikacja end-to-end w kontenerze (dymna)**

Run: `cd splitter && docker compose run --rm --entrypoint python splitter -m pytest -v`
Expected: wszystkie testy PASS — w tym testy `tesseract` (już NIE skipped,
bo binarka jest w obrazie).

- [ ] **Step 5: Commit**

```bash
git add splitter/Dockerfile splitter/docker-compose.yml
git commit -m "build: install tesseract-ocr + pol data, document OCR env vars"
```

Jeśli edytowano `splitter/docs/deployment/splitter-service.md`, dołącz go do
tego commita.

---

## Notatki po wdrożeniu (do wykonania po zmergowaniu)

Zaktualizuj pamięć projektu (nie w tym planie, ręcznie po merge):
- `open-topics-backlog`: punkt 1 (OCR) → zrobiony.
- `project-status`: nowe zależności, zmienne `SPLITTER_OCR_*`, bramka pustych
  stron, kompozyt `TextLayerWithOcrFallback`.
- Rebuild kontenera dochodzi do listy "czeka na wdrożenie" (już tam jest
  rebuild — teraz obejmuje też binarkę tesseract).
