# Wykrywanie pustych stron po obrazie - Design

> **Zastepuje `2026-07-24-empty-pages-removal-design.md`** (podejscie czysto
> tekstowe). Powod: incydent produkcyjny 2026-07-24 z utrata stron - patrz
> "Post-mortem". Tamten spec zostaje w repo jako zapis tego, co bylo probowane
> i dlaczego nie dziala; NIE nalezy go implementowac ponownie.

## Post-mortem: dlaczego zmieniamy podejscie

Pierwsza wersja uznawala strone za pusta na podstawie **liczby znakow po OCR**
(`alnum_count(text) <= prog`). Na produkcyjnej paczce skanow (job
`01129b03-...`, 17 stron) Tesseract przekroczyl limit 30 s na 11 stronach.
Kazda taka strona wracala z tekstem `""` = 0 znakow = "pusta" -> usunieta.
Z paczki zostaly 3 strony.

Blad w zalozeniu: **brak odczytanego tekstu != pusta strona**. Skany dowodow
osobistych, dowodow rejestracyjnych i podobnych dokumentow (drobny druk na
wzorze giloszowym, hologramy, zdjecie, krzywo ulozony kartonik) sa dla
Tesseracta bardzo trudne - potrafi zwrocic pustke albo smieci, mimo ze strona
jest pelna tresci. W warstwie tekstowej "biala kartka rozdzielajaca" i "dowod
osobisty, ktorego OCR nie ruszyl" sa **nieodroznialne** - obie maja 0 znakow.

Drugi blad: brak ogranicznika skali. Usuniecie 14 z 17 stron nie wzbudzilo
zadnego alarmu, choc taki wynik zawsze oznacza awarie, a nie paczke pelna
separatorow.

Trzeci blad: brak stanu posredniego. Przelacznik `true/false` nie pozwalal
zobaczyc, co funkcja ZROBI, zanim zacznie to robic naprawde.

## Cel

Usuwac z wynikow **wylacznie strony faktycznie puste** - typowo biale kartki
rozdzielajace skany - i **nigdy** stron, ktorych OCR nie potrafil odczytac.
Decyzja ma opierac sie na tym, czy na stronie **jest atrament**, a nie na tym,
czy udalo sie z niej cokolwiek przeczytac.

Dodatkowo: dac operatorowi tryb obserwacyjny, w ktorym widzi decyzje funkcji
bez ponoszenia ich skutkow, oraz bezpiecznik odcinajacy masowe usuniecia.

## Kluczowa decyzja: bramka atramentowa (pokrycie pikseli)

Strona jest **wizualnie pusta**, gdy udzial ciemnych pikseli na renderze
w niskiej rozdzielczosci jest ponizej progu.

- **biala kartka rozdzielajaca** -> pokrycie ~0% -> pusta;
- **skan dowodu osobistego / rejestracyjnego** -> sam kartonik to ~7%
  powierzchni A4, plus zdjecie i ramki -> pokrycie grubo powyzej progu ->
  **ma tresc**, choćby OCR zwrocil zero znakow.

Detale decydujace o dzialaniu na realnych skanach:

- **odciety margines** (`SPLITTER_BLANK_MARGIN_RATIO`, domyslnie 4% z kazdej
  strony) - skan "pustej" kartki ma czarne krawedzie z szyby skanera, dziurki
  po dziurkaczu i czarne trojkaty w rogach przy przekrzywieniu;
- **prog ciemnosci** piksela = 200/255 (stala modulu `DARK_THRESHOLD`, nie env)
  - papier bywa szary/kremowy, wiec "nie-biel" to za malo;
- **prog pokrycia** (`SPLITTER_BLANK_MAX_INK_RATIO`, domyslnie 0.002 = 0,2%)
  - dopuszcza kurz, szum JPEG i pojedyncze artefakty skanu.

Rzad wielkosci dla kalibracji: A4 przy 60 DPI to ~348 tys. pikseli, po odcieciu
marginesu ~295 tys.; prog 0,2% to ~590 ciemnych pikseli. Pojedyncza linia
drobnego tekstu daje ~0,3%, podpis lub pieczatka ~0,5-1%, kartonik dowodu
kilka procent - wszystkie **powyzej** progu, czyli zachowane.

**Warunek usuniecia jest koniunkcja**: strona jest usuwana tylko gdy
**obraz mowi "pusto" I tekst jest pusty**
(`alnum_count(text) <= SPLITTER_EMPTY_PAGE_MAX_ALNUM`). Jesli OCR cokolwiek
odczytal - strona zostaje, bez dyskusji.

**Kazda niepewnosc = strona zostaje.** Blad renderu, brak `pypdfium2`, wyjatek
w detektorze -> strona traktowana jako "ma tresc" (nie pusta). Detektor nigdy
nie wywraca zadania - analogicznie do zasady przyjetej dla OCR.

Zadnych nowych zaleznosci: `pypdfium2` i Pillow sa juz uzywane w `ocr.py`.

## Umiejscowienie: przed OCR

Detekcja biegnie **przed** Tesseractem, na stronach ubogich w tekst warstwy
(tych samych, ktore dzis kwalifikuja sie do OCR). Strona wykryta jako wizualnie
pusta **pomija OCR calkowicie**.

Konsekwencje:

- **poprawnosc**: strona nieodczytana przez OCR ma atrament -> nigdy nie
  zostanie uznana za pusta;
- **wydajnosc**: kazda biala kartka to oszczednosc pelnego cyklu OCR (w logu
  incydentu strony timeoutowaly po 30 s kazda). Render 60 DPI + zliczenie
  histogramu to ulamek sekundy;
- zysk wydajnosciowy dziala **rowniez w trybie `keep`** - blanki nie ida do
  Tesseracta niezaleznie od tego, czy cokolwiek usuwamy.

## Tryby pracy (zastepuja przelacznik on/off)

`SPLITTER_EMPTY_PAGE_MODE`:

| Wartosc | Zachowanie |
|---|---|
| **`keep`** (domyslna) | Nic nie jest usuwane. Puste strony doklejane do dokumentu z `requiresReview` - **dokladnie zachowanie sprzed zmiany z 2026-07-24**. Detekcja i tak biegnie: loguje pokrycie i pozwala pominac OCR. |
| **`report`** | Wykrywa i **raportuje** (log + `warnings`), co BY usunelo. Nie usuwa nic. Tryb obserwacyjny do kalibracji progu na realnych paczkach. |
| **`remove`** | Usuwa strony potwierdzone jako puste (obraz I tekst), z bezpiecznikiem ponizej. |

Nieznana wartosc -> **`keep`** + `logger.warning`. Swiadome odstepstwo od
fail-fast: dla parametru bezpieczenstwa lepszy jest bezpieczny stan niz
zatrzymany serwis (por. incydent z `SPLITTER_DROP_EMPTY_PAGES=falsw`, ktory
wywrocil kontener w petli restartow).

`SPLITTER_DROP_EMPTY_PAGES` **znika**. Pozostawiony w `.env` nie wywroci
serwisu (`extra="ignore"` w `SplitterSettings`), ale przestaje cokolwiek
znaczyc - migracja opisana w README.

## Bezpiecznik: limit udzialu usunietych stron

`SPLITTER_EMPTY_PAGE_MAX_SHARE` (domyslnie `0.5`): jesli w trybie `remove`
odsetek stron uznanych za puste przekracza prog, **nie usuwamy nic** -
zamiast tego wpis w `warnings` i normalne (dzisiejsze) traktowanie tych stron.

Uzasadnienie: 14 pustych stron z 17 nie znaczy "duzo separatorow", tylko
"cos sie zepsulo" (padl OCR, padl render, zly prog). Bezpiecznik **zastepuje**
dotychczasowe zabezpieczenie "cala paczka pusta" - to jego szczegolny przypadek
(100% > 50%).

Dwie niezalezne warstwy ochrony: incydent z 2026-07-24 zostalby zatrzymany
**i** przez bramke atramentowa (dowod ma atrament), **i** przez bezpiecznik
(82% > 50%).

## Przeplyw sterowania

1. `PdfTextOcrEngine` czyta warstwe tekstowa (bez zmian).
2. Kandydaci = strony z `alnum_count < SPLITTER_OCR_MIN_TEXT_CHARS`.
3. `BlankPageDetector` renderuje kandydatow w `SPLITTER_BLANK_DETECT_DPI`
   i liczy pokrycie atramentem -> zbior stron wizualnie pustych.
4. OCR (Tesseract) biegnie po kandydatach **pomniejszonych o strony puste**.
5. Pipeline dostaje teksty **oraz** zbior stron wizualnie pustych.
6. Pipeline wyznacza zbior `removable` = wizualnie puste AND tekstowo puste;
   stosuje tryb i bezpiecznik; dopiero potem rusza petla segmentacji.
7. `split_pdf` pomija strony z `removedPages` (mechanizm juz istnieje).

Wyznaczenie `removable` **przed** petla segmentacji (a nie w jej trakcie) jest
swiadome: bezpiecznik musi znac pelna liste, zanim cokolwiek zostanie pominiete,
inaczej trzeba by "cofac" juz podjete decyzje.

## Raportowanie

- **Log per oceniana strona** (poziom INFO, prefiks `[job=...]`):
  - `Strona 6: pokrycie atramentem 0.03% -> wizualnie pusta`
  - `Strona 2: pokrycie atramentem 7.20% -> ma tresc (mimo braku tekstu)`

  Druga linia jest kluczowa diagnostycznie: pokazuje dokladnie te przypadki,
  w ktorych bramka uratowala strone przed skasowaniem.
- **`warnings`** (poziom paczki):
  - `remove`: `Usunieto 2 puste strony: 6, 9 (z 20)`
  - `report`: `Tryb report: 2 strony wygladaja na puste (nie usunieto): 6, 9 (z 20)`
  - bezpiecznik: `Bezpiecznik: 14 z 17 stron (82%) uznano za puste - nie usunieto nic, sprawdz OCR/render`
- **`DetectedDocument.removedPages`** i komentarz dziecka w `SplitPdfAction` -
  bez zmian (mechanizm z poprzedniej iteracji). W trybie `report` pozostaja
  puste - `removedPages` znaczy "faktycznie usuniete", nie "kandydaci".

## Konfiguracja

| Zmienna | Domyslnie | Znaczenie |
|---|---|---|
| `SPLITTER_EMPTY_PAGE_MODE` | `keep` | `keep` / `report` / `remove` |
| `SPLITTER_EMPTY_PAGE_MAX_ALNUM` | `0` | Do ilu znakow alfanum. strona jest "tekstowo pusta" (bez zmian) |
| `SPLITTER_EMPTY_PAGE_MAX_SHARE` | `0.5` | Bezpiecznik: powyzej tego udzialu pustych stron nie usuwaj nic |
| `SPLITTER_BLANK_DETECT_DPI` | `60` | Rozdzielczosc renderu do pomiaru pokrycia |
| `SPLITTER_BLANK_MAX_INK_RATIO` | `0.002` | Udzial ciemnych pikseli, ponizej ktorego strona jest wizualnie pusta |
| `SPLITTER_BLANK_MARGIN_RATIO` | `0.04` | Odcinany margines (krawedzie skanera, dziurki, przekrzywienie) |

**Parametry liczbowe zostaja fail-fast** (decyzja swiadoma): nieparsowalna
wartosc zatrzymuje start serwisu, jak kazde inne pole pydantic. Ryzykiem jest
tu polski odruch zapisu `0,002` zamiast `0.002` - adresowane **dokumentacja**:
`.env.example` musi zawierac wyrazna adnotacje "separator dziesietny to KROPKA,
nie przecinek" przy tych zmiennych. Wyjatkiem pozostaje
`SPLITTER_EMPTY_PAGE_MODE` (wartosc tekstowa): nieznana wartosc -> `keep`
+ ostrzezenie, bo bezpieczny stan jest tam wazniejszy niz sygnal o literowce.

## Zakres zmian w kodzie

- **`splitter/src/webcon_pdf_splitter/blank_pages.py`** (nowy modul):
  - `ink_ratio(image, margin_ratio, dark_threshold=DARK_THRESHOLD) -> float`
    - konwersja na skale szarosci, odciecie marginesu, `histogram()`,
      suma binow ciemnych / liczba pikseli (bez numpy);
  - `BlankPageDetector(dpi, max_ink_ratio, margin_ratio)` z metoda
    `detect_blank_pages(pdf_path, page_indices) -> set[int]` - render przez
    `pypdfium2` (sekwencyjnie; PDFium nie jest thread-safe), per strona lapie
    wyjatki i traktuje strone jako "ma tresc".
- **`ocr.py`**:
  - `PageRead` (dataclass: `text: str`, `blank: bool = False`);
  - protokol `OcrEngine` dostaje `read_pages(pdf_path) -> list[PageRead]`;
    `extract_page_texts` zostaje jako cienka nakladka
    (`[p.text for p in self.read_pages(path)]`), zeby istniejace testy
    i `PdfTextOcrEngine` dzialaly bez zmian;
  - `TextLayerWithOcrFallback` przyjmuje opcjonalny `blank_detector`;
    w `read_pages` wyznacza kandydatow, odpytuje detektor, OCR-uje wylacznie
    kandydatow niebedacych blankami, zwraca `PageRead` z `blank=True` dla
    wykrytych pustych.
- **`config.py`**: `empty_page_mode: str = "keep"`, `empty_page_max_share:
  float = 0.5`, `blank_detect_dpi: int = 60`, `blank_max_ink_ratio: float =
  0.002`, `blank_margin_ratio: float = 0.04`; usuniete `drop_empty_pages`.
- **`api.py`**: budowa `BlankPageDetector` i wstrzykniecie do silnika OCR;
  `_split` uzywa `read_pages`, przekazuje teksty i zbior stron pustych do
  pipeline'u; przekazanie trybu, progow i bezpiecznika z ustawien.
- **`classification/pipeline.py`**:
  - konstruktor: `empty_page_mode`, `empty_page_max_alnum`,
    `empty_page_max_share` (zamiast `drop_empty_pages`);
  - `split_pages(..., blank_pages: set[int] | None = None)`;
  - wyznaczenie `removable` przed petla + bezpiecznik + tryby;
  - petla pomija strony z `removable`; `removedPages` per dokument i wpisy
    do `warnings` jak wyzej.
- **`README.md`** i **`splitter/.env.example`**: nowe zmienne, opis trzech
  trybow, sciezka kalibracji (`report` -> odczyt pokrycia z logu -> `remove`),
  nota migracyjna o `SPLITTER_DROP_EMPTY_PAGES`.
- **C# (`webcon-action/`)**: bez zmian. `removedPages` juz jest w kontrakcie
  i w komentarzu dziecka; nowa paczka pluginu **nie jest potrzebna**.

## Poza zakresem

- Zmiana silnika OCR / strojenie Tesseracta (timeouty, `OMP_THREAD_LIMIT`,
  DPI) - osobny temat operacyjny, udokumentowany w README.
- Deskewing, usuwanie szumu, wykrywanie separatorow po kodzie kreskowym.
- Wykrywanie stron "prawie pustych" (sama stopka skanera) - swiadomie
  zachowywane.
- Automatyczna kalibracja progu na podstawie historii paczek.

## Testy

`blank_pages.py` (jednostkowe, na obrazach PIL - bez PDF, szybkie i dokladne):

- calkowicie biala plansza -> `ink_ratio` == 0.0;
- plansza z czarnym prostokatem 7% powierzchni (model kartonika dowodu) ->
  ratio > progu -> NIE pusta;
- plansza biala z czarna ramka przy krawedzi (krawedz skanera) -> po odcieciu
  marginesu ratio == 0 -> pusta;
- plansza z pojedynczymi ciemnymi pikselami (kurz) ponizej progu -> pusta;
- szare tlo (papier kremowy, wartosc > progu ciemnosci) -> pusta.

`BlankPageDetector` (integracyjne, PDF budowany Pillow -> `save(..., "PDF")`):

- PDF z jedna strona biala i jedna z czarnym prostokatem -> `detect_blank_pages`
  zwraca tylko indeks bialej;
- `page_indices` puste -> brak renderu, pusty wynik;
- render rzucajacy wyjatek (stub) -> strona NIE trafia do zbioru pustych.

`ocr.py`:

- `TextLayerWithOcrFallback` z detektorem-stubem: strona wykryta jako blank
  **nie trafia** do `ocr_pages` (licznik stuba) i wraca z `blank=True`;
- strona kandydujaca niebedaca blankiem nadal idzie do OCR (bez regresji);
- `extract_page_texts` zwraca to samo co przed zmiana (nakladka na `read_pages`).

`pipeline.py`:

- `mode=remove`: strona wizualnie pusta I tekstowo pusta -> usunieta,
  `removedPages` na dokumencie, wpis w `warnings`;
- **strona tekstowo pusta, ale NIE wizualnie pusta (dowod osobisty) ->
  NIE usunieta**, doklejona z `requiresReview` (regresja incydentu);
- `mode=report`: te same strony wykryte, ale `removedPages` puste, dokumenty
  jak w `keep`, wpis "Tryb report: ...";
- `mode=keep`: zachowanie sprzed zmiany (doklejanie + review);
- bezpiecznik: 3 z 4 stron puste przy `max_share=0.5` -> nic nie usuniete,
  wpis "Bezpiecznik: ...", dokumenty jak w `keep`;
- nieznana wartosc trybu -> zachowanie `keep` + ostrzezenie;
- separator miedzy dokumentami vs pusta w srodku dokumentu - atrybucja
  `removedPages` jak w poprzedniej iteracji.

`api.py`:

- odpowiedz zawiera `warnings` z podsumowaniem trybu;
- `pageCount` = liczba stron oryginalu (nie po usunieciu);
- domyslna konfiguracja (`keep`) nie usuwa niczego - test regresji incydentu
  na poziomie API.
