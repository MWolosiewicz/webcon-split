# OCR fallback dla skanów bez warstwy tekstowej — projekt

Data: 2026-07-12
Status: zaakceptowany przez użytkownika (brainstorming 2026-07-12)
Zakres: punkt 1 backlogu (OCR dla skanów). Fallback Tesseract za istniejącym
protokołem `OcrEngine` + bramka "pusta strona omija LLM" w pipeline.

## Cel

Skany bez osadzonej warstwy tekstowej dziś dają puste strony —
`PdfTextOcrEngine` czyta wyłącznie osadzony tekst. Skutek: wszystkie strony
skanu są puste, każda idzie do LLM z pustym wejściem (płatne/wolne wywołanie
bez sensu), a całość ląduje jako jeden "Nieznany typ dokumentu". Cel:
uzupełnić brakujący tekst przez Tesseract **przed** klasyfikacją, tak aby
istniejący pipeline (słownik → LLM) działał na skanach identycznie jak na
PDF-ach born-digital, oraz odciąć puste strony od LLM.

## Zasada nadrzędna (feedback użytkownika 2026-07-12)

OCR to wyłącznie etap **zdobycia tekstu**, umieszczony przed klasyfikacją.
Klasyfikacja pozostaje jedną i tą samą ścieżką (słownik → LLM) niezależnie od
tego, czy tekst pochodzi z warstwy tekstowej, czy z Tesseracta — nie ma
osobnej gałęzi "dla skanów". Żaden mechanizm podziału nie zyskuje nowych
heurystyk wyglądu strony. Spójne z [[testy-syntetyczne-nie-realne]]:
brak założeń o jednym paradygmacie nagłówka.

## Przepływ (dwa etapy, dla każdej strony)

**Etap 1 — zdobycie tekstu (moduł OCR):**

- strona ma warstwę tekstową o liczbie znaków alfanumerycznych ≥ progu →
  bierzemy tę warstwę (jak dziś),
- strona poniżej progu → render + Tesseract; jego wynik staje się tekstem
  strony,
- strona nadal poniżej progu po Tesseract (czysta kartka, rewers, nieczytelny
  skan) → tekst pozostaje pusty.

**Etap 2 — klasyfikacja (istniejący kod, bez zmian logiki), na tekście z etapu 1:**

- nagłówek pasuje do słownika → nowy dokument,
- ≥1 fraza typu bieżącego dokumentu → kontynuacja,
- niedopasowana, ale **ma jakikolwiek tekst** → LLM (jak dziś),
- niedopasowana i **pusta** (nowa bramka) → **nie** idzie do LLM; doklejana
  do bieżącego dokumentu z `requiresReview` i powodem po polsku.

**Dwa różne progi (decyzja użytkownika 2026-07-12, korekta pierwotnego specu):**
próg "uruchom OCR" i próg "omiń LLM" mają różny sens i nie są tą samą liczbą.

- **Uruchom OCR** (etap 1): tekst warstwy < `ocr_min_text_chars`
  (domyślnie 25). Próg wysoki celowo — strona z samą stopką skanera
  (np. "Skan 2024-01-01 str.1", ~15 znaków) ma trafić do OCR.
- **Omiń LLM** (etap 2): strona jest "pusta" tylko gdy **nie ma żadnego znaku
  alfanumerycznego** (`alnum_count(text) == 0`) — również po OCR. To stała
  logiczna, bez zmiennej środowiskowej. Krótka, ale realna strona tekstu nie
  jest uznawana za pustą i normalnie idzie do LLM. Zgodne z backlogiem
  ("strona z pustym tekstem nie powinna iść do LLM").

Wspólny jest tylko *sposób* liczenia — funkcja `alnum_count` używana przez
oba etapy; różnią się progiem.

## Sekcja 1: Silniki OCR (`ocr.py`)

Nowe klasy za istniejącym protokołem `OcrEngine.extract_page_texts(pdf_path) -> list[str]`.
`api.py` dalej woła jedno `extract_page_texts()` — nie wie nic o Tesseract.

- **`TesseractPageOcr`** — OCR pojedynczej strony:
  render strony przez `pypdfium2` (domyślnie 300 DPI) → obraz PIL →
  `pytesseract.image_to_string(image, lang=..., timeout=...)`.
  Metoda np. `ocr_page(pdf_path, page_index) -> str`. Ładowanie dokumentu
  PDFium raz na plik (nie raz na stronę) — patrz kompozyt.

- **`TextLayerWithOcrFallback`** (kompozyt implementujący `OcrEngine`):
  1. czyta warstwę tekstową wszystkich stron jak `PdfTextOcrEngine`,
  2. dla stron poniżej progu `min_text_chars` woła wstrzyknięty page-OCR,
     podmienia tekst strony wynikiem,
  3. zwraca listę tekstów (część z warstwy, część z OCR, część pusta).
  Page-OCR jest **wstrzykiwany** w konstruktorze → testy kompozytu bez
  realnego Tesseracta (fałszywy page-OCR).

Funkcja `alnum_count(text) -> int` (`sum(ch.isalnum() ...)`) w `ocr.py` —
jedno źródło liczenia znaków, importowane przez kompozyt (próg 25) i przez
pipeline (próg 0). Pipeline importuje z `ocr.py`; `ocr.py` nie importuje
pipeline — brak cyklu.

Wybór silnika w `api.py`: `settings.ocr_enabled` → kompozyt
(`TextLayerWithOcrFallback` z `TesseractPageOcr`), w przeciwnym razie obecny
`PdfTextOcrEngine`. Bez zmiany kształtu wywołania w handlerze.

## Sekcja 2: Konfiguracja (`config.py`, prefix `SPLITTER_`)

| Pole `SplitterSettings` | Env | Domyślnie | Znaczenie |
|---|---|---|---|
| `ocr_enabled` | `SPLITTER_OCR_ENABLED` | `True` | włącza fallback Tesseract |
| `ocr_min_text_chars` | `SPLITTER_OCR_MIN_TEXT_CHARS` | `25` | poniżej tylu znaków alfanumerycznych warstwy tekstowej strona idzie do OCR (tylko etap 1; bramka LLM ma osobny próg = 0) |
| `ocr_languages` | `SPLITTER_OCR_LANGUAGES` | `pol+eng` | języki przekazywane do Tesseracta (`-l`) |
| `ocr_dpi` | `SPLITTER_OCR_DPI` | `300` | rozdzielczość renderu strony do OCR |
| `ocr_timeout_seconds` | `SPLITTER_OCR_TIMEOUT_SECONDS` | `30` | limit czasu OCR jednej strony |

`extra="ignore"` już jest — brak ryzyka przy starych zmiennych.

## Sekcja 3: Bramka "pusta strona omija LLM" (`pipeline.py`)

Przed wywołaniem LLM dla strony niedopasowanej: jeśli
`alnum_count(text) == 0` (strona pusta również po OCR) → pomiń LLM.
Strona jest doklejana do bieżącego dokumentu z wymuszonym `requiresReview`
i powodem po polsku (styl ASCII jak istniejące powody):

> "strona N bez tekstu (rowniez po OCR) - dolaczona automatycznie"

Zachowanie brzegowe spójne z istniejącym `glued_unknown_page`: seria pustych
stron przed pierwszym rozpoznanym dokumentem tworzy "Nieznany typ dokumentu"
tak jak dziś (ta sama ścieżka doklejania, zmienia się tylko treść powodu).
Bramka nie potrzebuje konfiguracji — próg to stała 0 (brak znaków
alfanumerycznych).

## Sekcja 4: Obraz i zależności

- **Dockerfile**: dołożyć warstwę `apt-get`:
  `tesseract-ocr tesseract-ocr-pol` (pakiet `eng` wchodzi z bazowym
  `tesseract-ocr`). Sprzątanie `rm -rf /var/lib/apt/lists/*`. Wzrost obrazu
  rzędu ~30–50 MB.
- **pyproject.toml** — nowe zależności runtime:
  `pypdfium2`, `pytesseract`, `Pillow`.
  `pypdfium2` to wheel z wbudowanym PDFium — nie wymaga pakietów apt.
  `pytesseract` woła binarkę `tesseract` (stąd apt w obrazie).

## Sekcja 5: Obsługa błędów — OCR nigdy nie wywraca żądania

- **Brak binarki `tesseract`** (np. dev na Windows bez instalacji): przy
  próbie OCR łapiemy wyjątek, logujemy warning raz, strona traktowana jak
  pusta → ścieżka "doklej + review". Serwis działa jak dziś (sama warstwa
  tekstowa). (Ewentualnie wykrycie braku binarki na starcie i log ostrzeżenia.)
- **Błąd/timeout OCR jednej strony**: warning z numerem strony, ta strona
  traktowana jak pusta; pozostałe strony przetwarzane normalnie.
- **`ocr_enabled=False`**: zachowanie identyczne z obecnym
  (`PdfTextOcrEngine`), Tesseract nieużywany.

## Sekcja 6: Logowanie

Spójne z istniejącym logowaniem decyzji per strona:

- per strona uruchamiająca OCR: info np.
  "strona N: warstwa tekstowa poniżej progu, uruchamiam OCR",
- podsumowanie żądania: ile stron OCR-owanych, łączny czas OCR,
- ostrzeżenia jak w Sekcji 5.

## Sekcja 7: Testy

- **Jednostkowe kompozytu** (`TextLayerWithOcrFallback`) z fałszywym
  page-OCR — bez realnego Tesseracta:
  - strona z warstwą ≥ próg → OCR nie wołany, tekst z warstwy,
  - strona < próg → page-OCR wołany, tekst podmieniony,
  - page-OCR rzuca wyjątek → strona pusta (nie wywraca listy).
- **Testy pipeline**: strona pusta (po OCR) nie woła LLM, dostaje
  `requiresReview` z powodem; seria pustych na początku → "Nieznany typ".
- **Definicja pustości**: testy funkcji liczącej znaki alfanumeryczne
  (biały znak, interpunkcja, szczątkowa stopka skanera < próg).
- **Integracyjny z realnym Tesseractem**: `pytest.mark.skipif` gdy brak
  binarki — odpali się w kontenerze / u użytkownika po instalacji.
- **Ewaluacja LLM** (`scripts/llm_eval.py`) bez zmian — OCR jest przed nią
  w łańcuchu, nie dotyka jej wejścia.

## Poza zakresem (świadomie)

- **Wszywanie warstwy searchable w pliki wynikowe** — pliki wyjściowe to
  oryginały bez zmian. Przeszukiwalność w WEBCON użytkownik załatwia
  funkcjonalnością WEBCON / opcją "searchable PDF" na skanerach. Można dodać
  później jako osobny temat (OCRmyPDF + ghostscript).
- **Preprocessing obrazu** (deskew, binaryzacja) — dopiero jeśli jakość
  realnych skanów tego wymusi.

## Aktualizacja pamięci po wdrożeniu

- `open-topics-backlog`: punkt 1 (OCR) → zrobiony.
- `project-status`: nowy stan (zależności, zmienne env, bramka pustych stron).
