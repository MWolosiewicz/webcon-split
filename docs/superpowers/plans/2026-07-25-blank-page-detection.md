# Wykrywanie pustych stron po obrazie - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Usuwac z wynikow podzialu wylacznie strony faktycznie puste (biale kartki rozdzielajace), nigdy stron, ktorych OCR nie odczytal (dowody osobiste, rejestracyjne, slabe skany).

**Architecture:** Decyzja przenosi sie z tekstu na obraz. Nowy modul `blank_pages.py` renderuje strone w niskim DPI i mierzy udzial ciemnych pikseli. Detekcja biegnie PRZED Tesseractem (strona wizualnie pusta pomija OCR), a jej wynik plynie przez `PageRead` do pipeline'u, ktory usuwa strone tylko gdy obraz I tekst zgodnie mowia "pusto". Tryby `keep`/`report`/`remove` plus bezpiecznik procentowy.

**Tech Stack:** Python 3.12, pypdfium2 (render), Pillow (histogram), pydantic-settings, pytest. Zero nowych zaleznosci.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-25-blank-page-detection-design.md`.
- Jezyk kodu, komentarzy, logow i komunikatow: **polski bez znakow diakrytycznych** (jak w calym repo).
- **Kazda niepewnosc = strona zostaje.** Blad renderu, brak biblioteki, wyjatek detektora -> strona traktowana jako "ma tresc". Detektor nigdy nie wywraca zadania.
- Warunek usuniecia to **koniunkcja**: wizualnie pusta AND `alnum_count(text) <= SPLITTER_EMPTY_PAGE_MAX_ALNUM`.
- Domyslny tryb to `keep` - po wdrozeniu nic nie znika bez swiadomej zmiany `.env`.
- `SPLITTER_EMPTY_PAGE_MODE` o nieznanej wartosci -> `keep` + `logger.warning` (nigdy crash). Parametry **liczbowe** zostaja fail-fast.
- Bezpiecznik: nigdy nie usuwamy wszystkich stron paczki, niezaleznie od ustawien.
- C# (`webcon-action/`) **bez zmian** - `removedPages` juz jest w kontrakcie. Nowa paczka pluginu nie jest potrzebna.
- Testy uruchamiane z katalogu `splitter/`: `python -m pytest -q`.
- Punkt wyjscia: 164 passed, 2 skipped.

---

### Task 1: Pomiar pokrycia atramentem (`ink_ratio`)

**Files:**
- Create: `splitter/src/webcon_pdf_splitter/blank_pages.py`
- Test: `splitter/tests/test_blank_pages.py`

**Interfaces:**
- Consumes: nic (pierwszy task).
- Produces: `DARK_THRESHOLD: int = 200`, `ink_ratio(image, margin_ratio: float = 0.04, dark_threshold: int = DARK_THRESHOLD) -> float` - przyjmuje obiekt PIL `Image`, zwraca udzial 0.0-1.0.

- [ ] **Step 1: Write the failing tests**

Utworz `splitter/tests/test_blank_pages.py`:

```python
from PIL import Image, ImageDraw

from webcon_pdf_splitter.blank_pages import ink_ratio


def _white(width=500, height=700):
    return Image.new("RGB", (width, height), "white")


def test_ink_ratio_of_white_page_is_zero():
    assert ink_ratio(_white()) == 0.0


def test_ink_ratio_counts_dark_area():
    # po odcieciu 4% marginesu obszar to 460x660 = 303600 px;
    # prostokat 100x100 = 10000 px -> 10000/303600 = 0.0329
    image = _white(500, 700)
    ImageDraw.Draw(image).rectangle([200, 300, 299, 399], fill="black")

    assert 0.032 < ink_ratio(image) < 0.034


def test_ink_ratio_ignores_scanner_edge_after_margin_crop():
    # czarne pasy przy krawedziach (szyba skanera, przekrzywienie) leza
    # w odcinanym marginesie - strona nadal jest pusta
    image = _white(500, 700)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 499, 4], fill="black")
    draw.rectangle([0, 0, 4, 699], fill="black")

    assert ink_ratio(image, margin_ratio=0.04) == 0.0


def test_ink_ratio_treats_light_grey_paper_as_blank():
    # papier kremowy/szary: jasniejszy niz prog ciemnosci -> nie jest atramentem
    assert ink_ratio(Image.new("RGB", (500, 700), (230, 230, 230))) == 0.0


def test_ink_ratio_of_speckle_stays_below_default_threshold():
    # 40 pikseli kurzu -> 40/303600 = 0.00013, ponizej domyslnego progu 0.002
    image = _white(500, 700)
    draw = ImageDraw.Draw(image)
    for x in range(100, 140):
        draw.point((x, 350), fill="black")

    assert 0 < ink_ratio(image) < 0.002
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_blank_pages.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'webcon_pdf_splitter.blank_pages'`

- [ ] **Step 3: Write the implementation**

Utworz `splitter/src/webcon_pdf_splitter/blank_pages.py`:

```python
"""Wykrywanie stron wizualnie pustych (bramka atramentowa).

Kryterium tekstowe (liczba znakow po OCR) NIE odroznia bialej kartki od
strony, ktorej OCR nie odczytal - skan dowodu osobistego i pusta kartka
maja tak samo 0 znakow. Dlatego o pustce decyduje obraz: udzial ciemnych
pikseli na renderze w niskiej rozdzielczosci.

Patrz docs/superpowers/specs/2026-07-25-blank-page-detection-design.md.
"""

import logging

logger = logging.getLogger(__name__)

# Piksel ciemniejszy niz ta wartosc (skala 0-255) liczy sie jako atrament.
# Prog jest luzny, bo papier bywa szary/kremowy - "nie-biel" to za malo.
DARK_THRESHOLD = 200


def ink_ratio(image, margin_ratio: float = 0.04, dark_threshold: int = DARK_THRESHOLD) -> float:
    """Udzial ciemnych pikseli (0.0-1.0) po odcieciu marginesu.

    Margines odcinamy, bo skan pustej kartki niemal zawsze ma przy
    krawedziach czarne pasy z szyby skanera, dziurki po dziurkaczu albo
    czarne trojkaty w rogach przy przekrzywieniu.
    """
    grayscale = image.convert("L")
    width, height = grayscale.size
    margin_x, margin_y = int(width * margin_ratio), int(height * margin_ratio)
    core = grayscale.crop((margin_x, margin_y, width - margin_x, height - margin_y))
    core_width, core_height = core.size
    total = core_width * core_height
    if total <= 0:
        return 0.0
    histogram = core.histogram()
    dark = sum(histogram[: dark_threshold + 1])
    return dark / total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd splitter && python -m pytest tests/test_blank_pages.py -q`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/blank_pages.py splitter/tests/test_blank_pages.py
git commit -m "feat: pomiar pokrycia atramentem strony (ink_ratio)"
```

---

### Task 2: Detektor pustych stron (render PDF)

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/blank_pages.py`
- Test: `splitter/tests/test_blank_pages.py`

**Interfaces:**
- Consumes: `ink_ratio(image, margin_ratio, dark_threshold)` z Task 1.
- Produces: `BlankPageDetector(dpi: int = 60, max_ink_ratio: float = 0.002, margin_ratio: float = 0.04)` z metoda `detect_blank_pages(pdf_path: str, page_indices: list[int]) -> set[int]`. Indeksy **0-based** (jak w `TesseractPageOcr.ocr_pages`), logi 1-based.

- [ ] **Step 1: Write the failing tests**

Dopisz na koncu `splitter/tests/test_blank_pages.py`:

```python
from webcon_pdf_splitter.blank_pages import BlankPageDetector


def _pdf_with_pages(tmp_path, images, name="scan.pdf"):
    path = tmp_path / name
    images[0].save(str(path), "PDF", save_all=True, append_images=images[1:])
    return str(path)


def test_detects_blank_page_and_keeps_page_with_content(tmp_path):
    blank = _white(500, 700)
    card = _white(500, 700)
    # kartonik dowodu osobistego: ciemny prostokat na srodku strony
    ImageDraw.Draw(card).rectangle([100, 250, 400, 450], fill="black")
    path = _pdf_with_pages(tmp_path, [blank, card])

    detector = BlankPageDetector(dpi=60, max_ink_ratio=0.002)

    assert detector.detect_blank_pages(path, [0, 1]) == {0}


def test_empty_index_list_returns_empty_set():
    assert BlankPageDetector().detect_blank_pages("nieistniejacy.pdf", []) == set()


def test_unreadable_pdf_yields_no_blank_pages(tmp_path):
    # zasada bezpieczenstwa: nie umiemy ocenic -> zadna strona nie jest pusta
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"to nie jest plik pdf")

    assert BlankPageDetector().detect_blank_pages(str(path), [0]) == set()


def test_logs_coverage_for_page_with_content(tmp_path, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="webcon_pdf_splitter.blank_pages")
    card = _white(500, 700)
    ImageDraw.Draw(card).rectangle([100, 250, 400, 450], fill="black")
    path = _pdf_with_pages(tmp_path, [card], name="dowod.pdf")

    BlankPageDetector(dpi=60, max_ink_ratio=0.002).detect_blank_pages(path, [0])

    messages = [record.getMessage() for record in caplog.records]
    assert any("ma tresc (mimo braku tekstu)" in message for message in messages)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_blank_pages.py -q -k "detects or empty_index or unreadable or logs_coverage"`
Expected: FAIL — `ImportError: cannot import name 'BlankPageDetector'`

- [ ] **Step 3: Write the implementation**

Dopisz na koncu `splitter/src/webcon_pdf_splitter/blank_pages.py`:

```python
class BlankPageDetector:
    """Ocenia, czy wskazane strony PDF sa wizualnie puste.

    Render w niskim DPI (domyslnie 60) jest tani - to ulamek kosztu OCR,
    wiec detekcja moze biec PRZED Tesseractem i oszczedzic go na blankach.
    Render jest sekwencyjny, bo PDFium nie jest thread-safe.

    Kazdy blad oznacza "strona ma tresc": nieoceniona strona nigdy nie
    kwalifikuje sie do usuniecia.
    """

    def __init__(
        self,
        dpi: int = 60,
        max_ink_ratio: float = 0.002,
        margin_ratio: float = 0.04,
    ) -> None:
        self._dpi = dpi
        self._max_ink_ratio = max_ink_ratio
        self._margin_ratio = margin_ratio

    def detect_blank_pages(self, pdf_path: str, page_indices: list[int]) -> set[int]:
        if not page_indices:
            return set()
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(pdf_path)
        except Exception:
            logger.warning(
                "Nie udalo sie otworzyc dokumentu do oceny pustych stron - "
                "zadna strona nie zostanie uznana za pusta",
                exc_info=True,
            )
            return set()

        blank: set[int] = set()
        try:
            for index in page_indices:
                try:
                    bitmap = pdf[index].render(scale=self._dpi / 72.0)
                    ratio = ink_ratio(bitmap.to_pil(), self._margin_ratio)
                except Exception:
                    logger.warning(
                        "Nie udalo sie ocenic strony %s - traktowana jako niepusta",
                        index + 1,
                        exc_info=True,
                    )
                    continue
                if ratio <= self._max_ink_ratio:
                    blank.add(index)
                    logger.info(
                        "Strona %s: pokrycie atramentem %.3f%% -> wizualnie pusta",
                        index + 1,
                        ratio * 100,
                    )
                else:
                    logger.info(
                        "Strona %s: pokrycie atramentem %.3f%% -> ma tresc (mimo braku tekstu)",
                        index + 1,
                        ratio * 100,
                    )
        finally:
            pdf.close()
        return blank
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd splitter && python -m pytest tests/test_blank_pages.py -q`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/blank_pages.py splitter/tests/test_blank_pages.py
git commit -m "feat: BlankPageDetector - ocena pustych stron po renderze"
```

---

### Task 3: `PageRead` i `read_pages` w silnikach OCR (refaktor zachowawczy)

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/ocr.py`
- Test: `splitter/tests/test_ocr.py`

**Interfaces:**
- Consumes: nic nowego.
- Produces: `@dataclass PageRead(text: str, blank: bool = False)`; metoda `read_pages(pdf_path: str) -> list[PageRead]` na `StubOcrEngine`, `PdfTextOcrEngine`, `TextLayerWithOcrFallback`. `extract_page_texts` zostaje jako nakladka i **musi dzialac tak jak dotad** (istniejace testy bez zmian).

- [ ] **Step 1: Write the failing test**

Dopisz na koncu `splitter/tests/test_ocr.py`:

```python
def test_read_pages_returns_text_and_blank_flag():
    from webcon_pdf_splitter.ocr import PageRead, PdfTextOcrEngine

    composite = TextLayerWithOcrFallback(
        page_ocr=_FakePageOcr({}),
        text_layer=_FakeTextLayer(["Pelna umowa o prace z wieloma slowami w warstwie"]),
        min_text_chars=25,
    )

    reads = composite.read_pages("born-digital.pdf")

    assert reads == [
        PageRead(text="Pelna umowa o prace z wieloma slowami w warstwie", blank=False)
    ]
    # nakladka zachowuje dotychczasowy interfejs
    assert composite.extract_page_texts("born-digital.pdf") == [
        "Pelna umowa o prace z wieloma slowami w warstwie"
    ]
    assert PdfTextOcrEngine().read_pages.__name__ == "read_pages"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python -m pytest tests/test_ocr.py::test_read_pages_returns_text_and_blank_flag -q`
Expected: FAIL — `ImportError: cannot import name 'PageRead'`

- [ ] **Step 3: Write the implementation**

W `splitter/src/webcon_pdf_splitter/ocr.py` zamien naglowek pliku (importy + protokol + dwa proste silniki):

```python
import logging
from dataclasses import dataclass
from typing import Protocol

from webcon_pdf_splitter import metrics

logger = logging.getLogger(__name__)


def alnum_count(text: str) -> int:
    """Liczba znakow alfanumerycznych (Unicode) w tekscie strony.

    Wspolne zrodlo liczenia dla progu OCR (kompozyt) i bramki pustej
    strony (pipeline). Rozne progi, jeden sposob liczenia.
    """
    return sum(1 for ch in text if ch.isalnum())


@dataclass
class PageRead:
    """Wynik odczytu jednej strony.

    `blank=True` znaczy "potwierdzona pustka wizualna" - obraz strony nie
    zawiera atramentu. Brak tekstu SAM W SOBIE nie ustawia tej flagi:
    strona, ktorej OCR nie odczytal, ma pusty tekst i `blank=False`.
    """

    text: str
    blank: bool = False


class OcrEngine(Protocol):
    def read_pages(self, pdf_path: str) -> list[PageRead]:
        ...


class StubOcrEngine:
    def read_pages(self, pdf_path: str) -> list[PageRead]:
        return [PageRead(text="UMOWA O PRACE")]

    def extract_page_texts(self, pdf_path: str) -> list[str]:
        return [read.text for read in self.read_pages(pdf_path)]


class PdfTextOcrEngine:
    """Extracts the embedded text layer page by page.

    Works for born-digital PDFs; scanned bundles need a real OCR engine
    (Tesseract/ABBYY/PaddleOCR) behind the same interface.
    """

    def extract_page_texts(self, pdf_path: str) -> list[str]:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        return [page.extract_text() or "" for page in reader.pages]

    def read_pages(self, pdf_path: str) -> list[PageRead]:
        # sama warstwa tekstowa nie ocenia obrazu - zadna strona nie jest
        # oznaczana jako wizualnie pusta
        return [PageRead(text=text) for text in self.extract_page_texts(pdf_path)]
```

Nastepnie w klasie `TextLayerWithOcrFallback` zamien metode `extract_page_texts` na pare `read_pages` + nakladka. Zmien sygnature:

```python
    def read_pages(self, pdf_path: str) -> list[PageRead]:
        texts = list(self._text_layer.extract_page_texts(pdf_path))
        empty_indices = [
            index
            for index, text in enumerate(texts)
            if alnum_count(text) < self._min_text_chars
        ]
        if not empty_indices:
            return [PageRead(text=text) for text in texts]
        try:
            ocr_texts = self._page_ocr.ocr_pages(pdf_path, empty_indices)
        except Exception:
            logger.warning(
                "OCR nie powiodl sie dla stron %s - strony zostaja puste",
                [i + 1 for i in empty_indices],
                exc_info=True,
            )
            return [PageRead(text=text) for text in texts]
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
            metrics.add_ocr_pages(len(filled))
            logger.info("OCR: uzupelniono tekst %s stron (strony: %s)", len(filled), filled)
        if not_improved:
            logger.info(
                "OCR nie poprawil stron %s - zachowano tekst warstwy",
                not_improved,
            )
        return [PageRead(text=text) for text in texts]

    def extract_page_texts(self, pdf_path: str) -> list[str]:
        return [read.text for read in self.read_pages(pdf_path)]
```

- [ ] **Step 4: Run the whole suite to verify no regression**

Run: `cd splitter && python -m pytest -q`
Expected: PASS — 174 passed, 2 skipped (165 dotychczasowych + 9 z Task 1-2 + 1 nowy... zweryfikuj, ze liczba rosnie i **zero FAILED**)

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/ocr.py splitter/tests/test_ocr.py
git commit -m "refactor: PageRead i read_pages w silnikach OCR (bez zmiany zachowania)"
```

---

### Task 4: Pominiecie OCR dla stron wizualnie pustych

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/ocr.py`
- Test: `splitter/tests/test_ocr.py`

**Interfaces:**
- Consumes: `PageRead` (Task 3), `BlankPageDetector.detect_blank_pages(pdf_path, page_indices) -> set[int]` (Task 2).
- Produces: `TextLayerWithOcrFallback(page_ocr, text_layer=None, min_text_chars=25, blank_detector=None)` - strona wykryta jako pusta nie trafia do `ocr_pages` i wraca z `blank=True`.

- [ ] **Step 1: Write the failing tests**

Dopisz na koncu `splitter/tests/test_ocr.py`:

```python
class _FakeBlankDetector:
    def __init__(self, blank_indices):
        self._blank = set(blank_indices)
        self.calls = []

    def detect_blank_pages(self, pdf_path, page_indices):
        self.calls.append(list(page_indices))
        return {i for i in page_indices if i in self._blank}


def test_visually_blank_page_skips_ocr_and_is_marked():
    ocr = _FakePageOcr({1: "NIE POWINNO ZOSTAC UZYTE", 2: "TEKST Z OCR"})
    detector = _FakeBlankDetector([1])
    composite = TextLayerWithOcrFallback(
        page_ocr=ocr,
        text_layer=_FakeTextLayer(
            ["Pelna umowa o prace z wieloma slowami w warstwie tekstowej", "", ""]
        ),
        min_text_chars=25,
        blank_detector=detector,
    )

    reads = composite.read_pages("scan.pdf")

    # detektor dostal kandydatow (strony ubogie w tekst), OCR tylko niepustych
    assert detector.calls == [[1, 2]]
    assert ocr.calls == [[2]]
    assert reads[1].blank is True
    assert reads[1].text == ""
    # strona z atramentem nadal przechodzi przez OCR i nie jest pusta
    assert reads[2].blank is False
    assert reads[2].text == "TEKST Z OCR"


def test_without_detector_no_page_is_marked_blank():
    composite = TextLayerWithOcrFallback(
        page_ocr=_FakePageOcr({0: ""}),
        text_layer=_FakeTextLayer([""]),
        min_text_chars=25,
    )

    reads = composite.read_pages("scan.pdf")

    assert reads[0].blank is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_ocr.py -q -k "visually_blank or without_detector"`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'blank_detector'`

- [ ] **Step 3: Write the implementation**

W `splitter/src/webcon_pdf_splitter/ocr.py`, w klasie `TextLayerWithOcrFallback`, zamien `__init__` i poczatek `read_pages`:

```python
    def __init__(
        self,
        page_ocr,
        text_layer=None,
        min_text_chars: int = 25,
        blank_detector=None,
    ) -> None:
        self._page_ocr = page_ocr
        self._text_layer = text_layer or PdfTextOcrEngine()
        self._min_text_chars = min_text_chars
        self._blank_detector = blank_detector

    def read_pages(self, pdf_path: str) -> list[PageRead]:
        texts = list(self._text_layer.extract_page_texts(pdf_path))
        candidates = [
            index
            for index, text in enumerate(texts)
            if alnum_count(text) < self._min_text_chars
        ]
        # Strony wizualnie puste odsiewamy PRZED Tesseractem: biala kartka
        # nie ma czego oddac, a kosztuje pelny cykl OCR (w skrajnym wypadku
        # timeout). Zysk dziala niezaleznie od tego, czy cokolwiek usuwamy.
        blank_indices: set[int] = set()
        if self._blank_detector is not None and candidates:
            blank_indices = self._blank_detector.detect_blank_pages(pdf_path, candidates)
            if blank_indices:
                logger.info(
                    "Pominieto OCR dla %s wizualnie pustych stron: %s",
                    len(blank_indices),
                    sorted(index + 1 for index in blank_indices),
                )
        empty_indices = [index for index in candidates if index not in blank_indices]
        if not empty_indices:
            return [
                PageRead(text=text, blank=index in blank_indices)
                for index, text in enumerate(texts)
            ]
```

W dalszej czesci `read_pages` zamien **oba** pozostale `return` na wariant z flaga:

```python
        try:
            ocr_texts = self._page_ocr.ocr_pages(pdf_path, empty_indices)
        except Exception:
            logger.warning(
                "OCR nie powiodl sie dla stron %s - strony zostaja puste",
                [i + 1 for i in empty_indices],
                exc_info=True,
            )
            return [
                PageRead(text=text, blank=index in blank_indices)
                for index, text in enumerate(texts)
            ]
```

oraz koncowy:

```python
        return [
            PageRead(text=text, blank=index in blank_indices)
            for index, text in enumerate(texts)
        ]
```

- [ ] **Step 4: Run the whole suite**

Run: `cd splitter && python -m pytest -q`
Expected: PASS — zero FAILED, liczba testow rosnie o 2

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/ocr.py splitter/tests/test_ocr.py
git commit -m "feat: strony wizualnie puste pomijaja OCR i sa oznaczane"
```

---

### Task 5: Ustawienia - tryby i progi

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/config.py`
- Delete (pole): `drop_empty_pages`
- Test: `splitter/tests/test_config_empty_pages.py`

**Interfaces:**
- Consumes: nic.
- Produces: pola `empty_page_mode: str = "keep"`, `empty_page_max_share: float = 0.5`, `blank_detect_dpi: int = 60`, `blank_max_ink_ratio: float = 0.002`, `blank_margin_ratio: float = 0.04`; stala `EMPTY_PAGE_MODES: tuple[str, ...]`; funkcja `normalize_empty_page_mode(value: str) -> str`. Pole `empty_page_max_alnum: int = 0` zostaje bez zmian.

- [ ] **Step 1: Write the failing tests**

Zastap cala zawartosc `splitter/tests/test_config_empty_pages.py`:

```python
import logging

from webcon_pdf_splitter.config import (
    SplitterSettings,
    normalize_empty_page_mode,
)


def test_empty_page_mode_defaults_to_keep():
    assert SplitterSettings(_env_file=None).empty_page_mode == "keep"


def test_blank_detection_defaults():
    settings = SplitterSettings(_env_file=None)
    assert settings.empty_page_max_alnum == 0
    assert settings.empty_page_max_share == 0.5
    assert settings.blank_detect_dpi == 60
    assert settings.blank_max_ink_ratio == 0.002
    assert settings.blank_margin_ratio == 0.04


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("SPLITTER_EMPTY_PAGE_MODE", "remove")
    monkeypatch.setenv("SPLITTER_EMPTY_PAGE_MAX_SHARE", "0.3")
    monkeypatch.setenv("SPLITTER_BLANK_MAX_INK_RATIO", "0.005")
    settings = SplitterSettings(_env_file=None)
    assert settings.empty_page_mode == "remove"
    assert settings.empty_page_max_share == 0.3
    assert settings.blank_max_ink_ratio == 0.005


def test_normalize_accepts_known_modes_case_insensitively():
    assert normalize_empty_page_mode("keep") == "keep"
    assert normalize_empty_page_mode("REPORT") == "report"
    assert normalize_empty_page_mode(" remove ") == "remove"


def test_normalize_falls_back_to_keep_with_warning(caplog):
    # literowka w trybie NIE moze wywrocic serwisu - bezpieczny stan wygrywa
    caplog.set_level(logging.WARNING, logger="webcon_pdf_splitter.config")

    assert normalize_empty_page_mode("remoove") == "keep"

    assert any("remoove" in record.getMessage() for record in caplog.records)


def test_drop_empty_pages_setting_is_gone():
    # zastapione przez SPLITTER_EMPTY_PAGE_MODE; stara zmienna w .env jest
    # ignorowana dzieki extra="ignore"
    assert not hasattr(SplitterSettings(_env_file=None), "drop_empty_pages")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_config_empty_pages.py -q`
Expected: FAIL — `ImportError: cannot import name 'normalize_empty_page_mode'`

- [ ] **Step 3: Write the implementation**

W `splitter/src/webcon_pdf_splitter/config.py` zamien naglowek importow na:

```python
import logging

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

EMPTY_PAGE_MODES = ("keep", "report", "remove")


def normalize_empty_page_mode(value: str) -> str:
    """Nieznana wartosc trybu -> 'keep' (bezpieczny stan) + ostrzezenie.

    Swiadome odstepstwo od fail-fast: dla parametru decydujacego o USUWANIU
    stron lepszy jest bezpieczny stan niz zatrzymany serwis. Parametry
    liczbowe zostaja fail-fast (walidacja pydantic).
    """
    mode = (value or "").strip().lower()
    if mode in EMPTY_PAGE_MODES:
        return mode
    logger.warning(
        "Nieznany tryb SPLITTER_EMPTY_PAGE_MODE='%s' - uzywam 'keep' "
        "(nic nie bedzie usuwane). Dozwolone: %s",
        value,
        ", ".join(EMPTY_PAGE_MODES),
    )
    return "keep"
```

W klasie `SplitterSettings` **usun** linie `drop_empty_pages: bool = Field(default=True)` i zamien blok pustych stron na:

```python
    empty_page_mode: str = Field(default="keep")
    empty_page_max_alnum: int = Field(default=0)
    empty_page_max_share: float = Field(default=0.5)
    blank_detect_dpi: int = Field(default=60)
    blank_max_ink_ratio: float = Field(default=0.002)
    blank_margin_ratio: float = Field(default=0.04)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd splitter && python -m pytest tests/test_config_empty_pages.py -q`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/config.py splitter/tests/test_config_empty_pages.py
git commit -m "feat: SPLITTER_EMPTY_PAGE_MODE i progi bramki atramentowej"
```

---

### Task 6: Pipeline - tryby, koniunkcja i bezpiecznik

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/classification/pipeline.py`
- Test: `splitter/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `alnum_count` z `ocr.py`; zbior `blank_pages` (indeksy **0-based**) od `api.py`.
- Produces: `ClassificationPipeline(rule_classifier, llm_classifier, min_auto_accept_confidence, min_review_confidence, empty_page_mode="keep", empty_page_max_alnum=0, empty_page_max_share=0.5)` oraz `split_pages(source_file_name: str, page_texts: list[str], blank_pages: set[int] | None = None) -> SplitResult`.

- [ ] **Step 1: Write the failing tests**

W `splitter/tests/test_pipeline.py` zamien helper `_make_pipeline` na wersje z trybem:

```python
def _make_pipeline(
    llm_classifier=None,
    empty_page_mode="keep",
    empty_page_max_alnum=0,
    empty_page_max_share=0.5,
):
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
        empty_page_mode=empty_page_mode,
        empty_page_max_alnum=empty_page_max_alnum,
        empty_page_max_share=empty_page_max_share,
    )
```

Usun testy oparte na starym przelaczniku: `test_empty_page_dropped_by_default`, `test_leading_empty_pages_dropped`, `test_empty_page_inside_document_attributed_to_child`, `test_separator_empty_page_reported_only_at_bundle_level`, `test_empty_page_glued_with_review_when_drop_disabled`, `test_threshold_treats_ocr_noise_as_empty`, `test_sparse_real_content_above_threshold_not_dropped`, `test_all_empty_bundle_falls_back_to_unknown_document`. Zastap je nowym zestawem (dopisz na koncu pliku):

```python
def test_keep_mode_glues_empty_page_with_review():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "   "],
        blank_pages={1},
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]
    doc = result.documents[0]
    assert doc.requiresReview is True
    assert doc.removedPages == []
    assert "glued_unknown_page:2" in doc.signals


def test_remove_mode_drops_confirmed_blank_page_inside_document():
    result = _make_pipeline(empty_page_mode="remove").split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "   ", "wynagrodzenie zasadnicze wynosi"],
        blank_pages={1},
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 3),
    ]
    assert result.documents[0].removedPages == [2]
    assert result.warnings == ["Usunieto 1 pustych stron: 2 (z 3)"]


def test_remove_mode_keeps_unreadable_page_that_has_ink():
    # REGRESJA INCYDENTU 2026-07-24: skan dowodu osobistego - OCR nic nie
    # odczytal (0 znakow), ale obraz ma atrament -> strona MUSI zostac
    result = _make_pipeline(empty_page_mode="remove").split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "   "],
        blank_pages=set(),
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]
    assert result.documents[0].removedPages == []
    assert result.documents[0].requiresReview is True


def test_report_mode_reports_without_removing():
    result = _make_pipeline(empty_page_mode="report").split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "   ", "wynagrodzenie zasadnicze wynosi"],
        blank_pages={1},
    )

    assert result.documents[0].removedPages == []
    assert result.documents[0].endPage == 3
    assert (
        "Tryb report: 1 stron wyglada na puste (nie usunieto): 2 (z 3)"
        in result.warnings
    )


def test_circuit_breaker_blocks_mass_removal():
    result = _make_pipeline(empty_page_mode="remove", empty_page_max_share=0.5).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "  ", "  ", "  "],
        blank_pages={1, 2, 3},
    )

    assert result.documents[0].removedPages == []
    assert result.documents[0].endPage == 4
    assert any("Bezpiecznik" in warning for warning in result.warnings)


def test_never_removes_every_page_even_with_permissive_share():
    result = _make_pipeline(empty_page_mode="remove", empty_page_max_share=1.0).split_pages(
        "scan.pdf",
        ["   ", "  "],
        blank_pages={0, 1},
    )

    assert len(result.documents) == 1
    assert result.documents[0].removedPages == []
    assert result.status == "requires_review"


def test_text_above_threshold_is_never_removed_even_if_visually_blank():
    result = _make_pipeline(empty_page_mode="remove").split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "Zalacznik nr 1"],
        blank_pages={1},
    )

    assert result.documents[0].removedPages == []
    assert result.documents[0].endPage == 2


def test_unknown_mode_behaves_like_keep():
    result = _make_pipeline(empty_page_mode="cokolwiek").split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "   "],
        blank_pages={1},
    )

    assert result.documents[0].removedPages == []
    assert result.documents[0].endPage == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_pipeline.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'empty_page_mode'`

- [ ] **Step 3: Write the implementation**

W `splitter/src/webcon_pdf_splitter/classification/pipeline.py` zamien konstruktor:

```python
    def __init__(
        self,
        rule_classifier: RuleBasedClassifier,
        llm_classifier: LlmClassifier,
        min_auto_accept_confidence: float,
        min_review_confidence: float,
        empty_page_mode: str = "keep",
        empty_page_max_alnum: int = 0,
        empty_page_max_share: float = 0.5,
    ) -> None:
        self._rule_classifier = rule_classifier
        self._llm_classifier = llm_classifier
        self._min_auto_accept_confidence = min_auto_accept_confidence
        self._min_review_confidence = min_review_confidence
        self._empty_page_mode = empty_page_mode
        self._empty_page_max_alnum = empty_page_max_alnum
        self._empty_page_max_share = empty_page_max_share
```

Dodaj metode pomocnicza (nad `split_pages`):

```python
    def _confirmed_empty_pages(
        self, page_texts: list[str], blank_pages: set[int]
    ) -> list[int]:
        """Numery stron (1-based) pustych wedlug OBU kryteriow naraz.

        Koniunkcja jest istota poprawki: sam brak tekstu oznacza rownie
        dobrze biala kartke, co strone, ktorej OCR nie odczytal.
        """
        return [
            index + 1
            for index, text in enumerate(page_texts)
            if index in blank_pages
            and alnum_count(text) <= self._empty_page_max_alnum
        ]
```

Zamien sygnature i poczatek `split_pages` (linie 51-57):

```python
    def split_pages(
        self,
        source_file_name: str,
        page_texts: list[str],
        blank_pages: set[int] | None = None,
    ) -> SplitResult:
        known_types = self._rule_classifier.known_document_types
        segments: list[_Segment] = []
        current: _Segment | None = None
        removed_pages: list[int] = []

        # Zbior do usuniecia wyznaczamy PRZED petla segmentacji: bezpiecznik
        # musi znac pelna liste, zanim cokolwiek zostanie pominiete.
        candidates = self._confirmed_empty_pages(page_texts, set(blank_pages or ()))
        removable: set[int] = set()
        breaker_tripped = False
        if self._empty_page_mode == "remove" and candidates:
            share = len(candidates) / len(page_texts) if page_texts else 0.0
            # `>=` na liczbie stron: nigdy nie usuwamy calej paczki, nawet
            # gdy operator ustawil max_share na 1.0
            if share > self._empty_page_max_share or len(candidates) >= len(page_texts):
                breaker_tripped = True
                logger.warning(
                    "Bezpiecznik: %s z %s stron (%.0f%%) uznano za puste - "
                    "nie usuwam nic, sprawdz OCR/render",
                    len(candidates),
                    len(page_texts),
                    share * 100,
                )
            else:
                removable = set(candidates)
```

W petli, **przed** linia `page_is_empty = ...`, wstaw:

```python
            if page_number in removable:
                removed_pages.append(page_number)
                logger.info(
                    "Strona %s: pusta (potwierdzona obrazem) - usunieta", page_number
                )
                continue
```

Usun stary blok usuwania (`if page_is_empty and self._drop_empty_pages:` wraz z jego cialem) - zostaje samo:

```python
            page_is_empty = alnum_count(text) <= self._empty_page_max_alnum
            llm = (
                None
                if page_is_empty
                else self._try_llm(page_texts, index, known_types, current)
            )
```

Usun caly blok zabezpieczenia `if not segments and removed_pages:` (zastapiony przez bezpiecznik) oraz zmienna `all_empty_fallback`. W sekcji `warnings` zamien dwa wpisy o pustych stronach na:

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
        if self._empty_page_mode == "report" and candidates:
            warnings.append(
                "Tryb report: %s stron wyglada na puste (nie usunieto): %s (z %s)"
                % (
                    len(candidates),
                    ", ".join(str(page) for page in candidates),
                    len(page_texts),
                )
            )
        if breaker_tripped:
            warnings.append(
                "Bezpiecznik: %s z %s stron uznano za puste - nie usunieto nic, "
                "sprawdz OCR/render" % (len(candidates), len(page_texts))
            )
```

- [ ] **Step 4: Run the whole suite**

Run: `cd splitter && python -m pytest -q`
Expected: PASS — zero FAILED

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/classification/pipeline.py splitter/tests/test_pipeline.py
git commit -m "feat: tryby keep/report/remove, koniunkcja obraz+tekst, bezpiecznik"
```

---

### Task 7: Spiecie w `api.py`

**Files:**
- Modify: `splitter/src/webcon_pdf_splitter/api.py`
- Test: `splitter/tests/test_api_split.py`

**Interfaces:**
- Consumes: `BlankPageDetector` (Task 2), `read_pages`/`PageRead` (Task 3-4), `normalize_empty_page_mode` (Task 5), `ClassificationPipeline(..., empty_page_mode=..., empty_page_max_share=...)` i `split_pages(..., blank_pages=...)` (Task 6).
- Produces: `build_blank_detector(settings) -> BlankPageDetector`; `/api/split` przekazuje `blank_pages` do pipeline'u.

- [ ] **Step 1: Write the failing tests**

Zamien w `splitter/tests/test_api_split.py` test `test_split_all_empty_bundle_flags_for_review` na:

```python
def test_default_configuration_removes_nothing():
    # REGRESJA INCYDENTU: domyslna konfiguracja (tryb keep) nie moze usunac
    # zadnej strony, nawet gdy caly PDF to biale kartki
    client = TestClient(app)

    response = client.post(
        "/api/split",
        files={"file": ("scan.pdf", io.BytesIO(_pdf_bytes(3)), "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pageCount"] == 3
    assert all(document["removedPages"] == [] for document in payload["documents"])
    covered = sum(
        document["endPage"] - document["startPage"] + 1
        for document in payload["documents"]
    )
    assert covered == 3


def test_blank_detector_built_from_settings(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SplitterSettings(
            _env_file=None, blank_detect_dpi=72, blank_max_ink_ratio=0.01
        ),
    )

    detector = api.build_blank_detector(api.get_settings())

    assert detector._dpi == 72
    assert detector._max_ink_ratio == 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd splitter && python -m pytest tests/test_api_split.py -q`
Expected: FAIL — `AttributeError: module 'webcon_pdf_splitter.api' has no attribute 'build_blank_detector'`

- [ ] **Step 3: Write the implementation**

W `splitter/src/webcon_pdf_splitter/api.py` dodaj import:

```python
from webcon_pdf_splitter.blank_pages import BlankPageDetector
```

oraz rozszerz import z `config`:

```python
from webcon_pdf_splitter.config import SplitterSettings, normalize_empty_page_mode
```

Dodaj fabryke tuz nad `build_ocr_engine`:

```python
def build_blank_detector(settings: SplitterSettings) -> BlankPageDetector:
    return BlankPageDetector(
        dpi=settings.blank_detect_dpi,
        max_ink_ratio=settings.blank_max_ink_ratio,
        margin_ratio=settings.blank_margin_ratio,
    )
```

Zamien `build_ocr_engine`:

```python
def build_ocr_engine(settings: SplitterSettings):
    if settings.ocr_enabled:
        return TextLayerWithOcrFallback(
            page_ocr=TesseractPageOcr(
                languages=settings.ocr_languages,
                dpi=settings.ocr_dpi,
                timeout_seconds=settings.ocr_timeout_seconds,
                workers=settings.ocr_workers,
            ),
            min_text_chars=settings.ocr_min_text_chars,
            blank_detector=build_blank_detector(settings),
        )
    # bez OCR nie ma renderu, wiec nie ma tez oceny obrazu - zadna strona
    # nie zostanie uznana za pusta (patrz README)
    return PdfTextOcrEngine()
```

W `_split` zamien budowe pipeline'u:

```python
    mode = normalize_empty_page_mode(settings.empty_page_mode)
    if mode != "keep" and not settings.ocr_enabled:
        logger.warning(
            "SPLITTER_EMPTY_PAGE_MODE=%s wymaga wlaczonego OCR "
            "(SPLITTER_OCR_ENABLED=true) - bez niego nic nie bedzie usuwane",
            mode,
        )
    pipeline = ClassificationPipeline(
        rule_classifier=RuleBasedClassifier(repository.list_active_patterns()),
        llm_classifier=build_llm_classifier(settings),
        min_auto_accept_confidence=settings.min_auto_accept_confidence,
        min_review_confidence=settings.min_review_confidence,
        empty_page_mode=mode,
        empty_page_max_alnum=settings.empty_page_max_alnum,
        empty_page_max_share=settings.empty_page_max_share,
    )
```

oraz odczyt stron:

```python
        page_reads = ocr.read_pages(str(source_path))
        page_texts = [read.text for read in page_reads]
        blank_pages = {index for index, read in enumerate(page_reads) if read.blank}
        _log_page_texts(page_texts, settings)
        result = pipeline.split_pages(filename, page_texts, blank_pages=blank_pages)
```

- [ ] **Step 4: Run the whole suite**

Run: `cd splitter && python -m pytest -q`
Expected: PASS — zero FAILED

- [ ] **Step 5: Commit**

```bash
git add splitter/src/webcon_pdf_splitter/api.py splitter/tests/test_api_split.py
git commit -m "feat: wpiecie detektora pustych stron w /api/split"
```

---

### Task 8: Dokumentacja i migracja

**Files:**
- Modify: `README.md`
- Modify: `splitter/.env.example`

**Interfaces:**
- Consumes: nazwy zmiennych z Task 5.
- Produces: dokumentacja (bez kodu).

- [ ] **Step 1: Zaktualizuj tabele zmiennych w README**

W `README.md` **usun** wiersze `SPLITTER_DROP_EMPTY_PAGES` i `SPLITTER_EMPTY_PAGE_MAX_ALNUM`, wstawiajac w ich miejsce:

```markdown
| `SPLITTER_EMPTY_PAGE_MODE` | `keep` | `keep` = nic nie usuwa (puste strony doklejane z `requiresReview`); `report` = wykrywa i raportuje, nie usuwa; `remove` = usuwa potwierdzone puste. Nieznana wartość → `keep` + ostrzeżenie |
| `SPLITTER_EMPTY_PAGE_MAX_ALNUM` | `0` | Do ilu znaków alfanum. strona jest „tekstowo pusta". Warunek usunięcia to **koniunkcja** z oceną obrazu |
| `SPLITTER_EMPTY_PAGE_MAX_SHARE` | `0.5` | Bezpiecznik: powyżej tego udziału „pustych" stron nie usuwaj nic. Całej paczki nie usuwa nigdy |
| `SPLITTER_BLANK_DETECT_DPI` | `60` | Rozdzielczość renderu do pomiaru pokrycia atramentem |
| `SPLITTER_BLANK_MAX_INK_RATIO` | `0.002` | Udział ciemnych pikseli, poniżej którego strona jest wizualnie pusta (0,2%) |
| `SPLITTER_BLANK_MARGIN_RATIO` | `0.04` | Odcinany margines (krawędzie skanera, dziurki, przekrzywienie) |
```

- [ ] **Step 2: Zaktualizuj opis pustych stron w sekcji „Grupowanie stron"**

Zamień punkt 3 (zaczynający się od „**Strona pusta**") na:

```markdown
3. **Strona pusta** → o pustce decyduje **obraz**, nie tekst. Strona jest
   usuwana wyłącznie gdy jednocześnie (a) render wykazał pokrycie atramentem
   poniżej `SPLITTER_BLANK_MAX_INK_RATIO` i (b) ma ≤ `SPLITTER_EMPTY_PAGE_MAX_ALNUM`
   znaków. Sam brak tekstu **nie wystarczy** — skan dowodu osobistego czy
   rejestracyjnego bywa dla OCR nieczytelny, a strona jest pełna treści.
   Zachowanie zależy od `SPLITTER_EMPTY_PAGE_MODE`: `keep` (domyślnie) dokleja
   z `requiresReview`, `report` tylko raportuje, `remove` usuwa. Bezpiecznik
   `SPLITTER_EMPTY_PAGE_MAX_SHARE` blokuje masowe usunięcia (np. przy awarii
   OCR), a cała paczka nigdy nie zostaje usunięta.
```

- [ ] **Step 3: Dodaj sekcję o kalibracji i migracji**

Pod tabelą zmiennych (przed „Diagnostyka klasyfikacji w logach") dodaj:

```markdown
**Kalibracja usuwania pustych stron** — nie włączaj `remove` w ciemno:

1. Zostaw `SPLITTER_EMPTY_PAGE_MODE=keep`. Detekcja i tak działa: puste
   strony pomijają Tesseract (oszczędność czasu), a log pokazuje pokrycie.
2. Przełącz na `report` i przepuść realne paczki. W logu zobaczysz wpisy
   `Strona 6: pokrycie atramentem 0.031% -> wizualnie pusta` oraz
   `Strona 2: pokrycie atramentem 7.204% -> ma tresc (mimo braku tekstu)`,
   a w `warnings` podsumowanie „co by zostało usunięte".
3. Gdy wyniki się zgadzają — dopiero wtedy `remove`.

**Migracja:** `SPLITTER_DROP_EMPTY_PAGES` **już nie istnieje** — zastąpiony
przez `SPLITTER_EMPTY_PAGE_MODE`. Zmienna pozostawiona w `.env` nie wywróci
serwisu (`extra="ignore"`), ale przestaje cokolwiek znaczyć — usuń ją.

Usuwanie pustych stron wymaga `SPLITTER_OCR_ENABLED=true` (ocena obrazu
korzysta z tego samego renderu). Przy wyłączonym OCR serwis loguje
ostrzeżenie i nic nie usuwa.
```

- [ ] **Step 4: Zaktualizuj `.env.example`**

W `splitter/.env.example` zamień cały blok `# --- Puste strony ---` na:

```bash
# --- Puste strony (biale kartki rozdzielajace skany) ---
# UWAGA: separator dziesietny to KROPKA, nie przecinek (0.002, nie 0,002).
# Bledna wartosc liczbowa zatrzyma start serwisu.
#
# O pustce decyduje OBRAZ (pokrycie atramentem), nie liczba znakow po OCR:
# skan dowodu osobistego czy rejestracyjnego bywa dla OCR nieczytelny,
# ale strona jest pelna tresci i NIE moze zostac usunieta.
#
# keep   = nic nie usuwaj (puste strony doklejane z requiresReview) - domyslne
# report = wykryj i zaraportuj w logu/warnings, ale nie usuwaj (kalibracja)
# remove = usuwaj potwierdzone puste strony
SPLITTER_EMPTY_PAGE_MODE=keep
# Do ilu znakow alfanum. strona jest "tekstowo pusta" (warunek konieczny,
# ale niewystarczajacy - obraz musi potwierdzic).
SPLITTER_EMPTY_PAGE_MAX_ALNUM=0
# Bezpiecznik: powyzej tego udzialu "pustych" stron nie usuwaj nic
# (0.5 = polowa paczki). Calej paczki nie usuwamy nigdy.
SPLITTER_EMPTY_PAGE_MAX_SHARE=0.5
# Rozdzielczosc renderu do pomiaru pokrycia atramentem.
SPLITTER_BLANK_DETECT_DPI=60
# Udzial ciemnych pikseli, ponizej ktorego strona jest wizualnie pusta
# (0.002 = 0,2%). Dobierz na podstawie logow z trybu report.
SPLITTER_BLANK_MAX_INK_RATIO=0.002
# Odcinany margines strony: krawedzie szyby skanera, dziurki po dziurkaczu,
# czarne rogi przy przekrzywieniu (0.04 = 4% z kazdej strony).
SPLITTER_BLANK_MARGIN_RATIO=0.04
```

- [ ] **Step 5: Commit**

```bash
git add README.md splitter/.env.example
git commit -m "docs: tryby pustych stron, kalibracja i migracja z SPLITTER_DROP_EMPTY_PAGES"
```

---

## Weryfikacja koncowa

- [ ] `cd splitter && python -m pytest -q` — zero FAILED
- [ ] `grep -rn "drop_empty_pages" splitter/ README.md` — brak trafien (poza specami w `docs/`)
- [ ] C# **nie wymaga** przebudowy: `git status` nie pokazuje zmian w `webcon-action/`
