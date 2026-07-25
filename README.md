# WEBCON PDF Splitter

System dzielenia zbiorczych skanów PDF (dokumenty HR) na osobne dokumenty
z automatycznym utworzeniem elementów w WEBCON BPS. Całość działa lokalnie —
żadne dane nie opuszczają infrastruktury firmy.

Ten plik jest **jedynym zbiorczym opisem rozwiązania**: założenia, architektura,
zasady działania, konfiguracja, API, integracja z WEBCON, wdrożenie i testy.
Szczegółowe zapisy projektowe (historia decyzji) leżą w `docs/superpowers/` —
to migawki z poszczególnych dni, nie bieżąca dokumentacja.

## Spis treści

1. [Założenia i cele](#założenia-i-cele)
2. [Architektura](#architektura)
3. [Przepływ end-to-end](#przepływ-end-to-end)
4. [Zasady działania splittera](#zasady-działania-splittera)
5. [Konfiguracja serwisu](#konfiguracja-serwisu)
6. [API splittera](#api-splittera)
7. [Integracja z WEBCON](#integracja-z-webcon)
8. [Wdrożenie](#wdrożenie)
9. [Testy](#testy)
10. [Struktura repozytorium](#struktura-repozytorium)
11. [Status i ograniczenia](#status-i-ograniczenia)

---

## Założenia i cele

- **Prywatność przede wszystkim** — przetwarzanie w całości lokalne. Splitter,
  opcjonalny LLM i OCR działają w infrastrukturze firmy; treść dokumentów HR
  nie trafia do żadnej usługi zewnętrznej.
- **Bezstanowość** — splitter nie ma własnej bazy danych. Każde żądanie jest
  samowystarczalne (PDF + wzorce w jednym wywołaniu); katalog roboczy jest
  czyszczony po zadaniu. Stan (słownik typów, korekty) żyje po stronie WEBCON.
- **Słownik po stronie WEBCON** — typy dokumentów i wzorce rozpoznawania są
  utrzymywane w procesie słownikowym WEBCON i wysyłane w żądaniu. Splitter nie
  zna z góry żadnych typów; bez wzorców wszystko jest „Nieznany typ dokumentu".
- **Człowiek w pętli** — dokumenty o niskiej pewności lub wątpliwym podziale
  dostają `requiresReview` z listą powodów po polsku; decyduje operator na
  podobiegu. System nie „udaje", że jest pewny.
- **Brak sztywnego paradygmatu nagłówka** — mechanizm podziału nie zakłada, że
  tytuł jest np. wielkimi literami. Nagłówek to konfigurowalny wzorzec ze
  słownika; dopasowanie idzie po tekście znormalizowanym do ASCII, więc znosi
  różnice diakrytyków i wielkości liter.
- **Odporność** — OCR ani LLM nigdy nie wywracają żądania: przy braku binarki,
  timeoucie czy błędzie strona jest traktowana zachowawczo (pusta / doklejona
  do weryfikacji), a podział leci dalej.

## Architektura

```
┌────────────────┐  POST /api/split   ┌──────────────────────┐
│  WEBCON BPS    │ ─────────────────► │  PDF Splitter        │
│  2026.1        │  ◄── 202 {jobId} ─ │  (Python/FastAPI)    │
│                │                    │  Docker lub uvicorn  │
│  paczka skanu  │  GET /api/jobs/…   │                      │
│  → dokumenty HR│ ─────────────────► │  kolejka FIFO        │
│                │  ◄── status/wynik─ │  → OCR+klasyfikacja  │
└────────────────┘    (base64)        └──────────────────────┘
```

Serwis ma **wewnętrzną kolejkę zadań**: zlecenie wraca natychmiast (`202` +
`jobId`), a paczki przetwarza kolejno wątek roboczy (domyślnie jeden —
gwarancja „po kolei" przy kilku paczkach naraz). Żadna akcja WEBCON nie czeka
na OCR — dzięki temu długie paczki nie powodują timeoutów HTTP ani nie trzymają
transakcji WEBCON przez czas przetwarzania.

Trzy elementy:

- **Akcje `SubmitSplitJobAction` + `CollectSplitJobAction`** (plugin C#, BPS 2026
  SDK, netstandard2.0) — pierwsza zleca podział (wysyła PDF + wzorce ze słownika,
  zapisuje `jobId`), druga (cykliczna) odpytuje o status i po zakończeniu tworzy
  elementy Dokument HR z wynikowymi plikami.
- **Serwis splittera** (Python/FastAPI) — jedyny komponent z logiką OCR i
  klasyfikacji; kolejka i wyniki żyją w pamięci procesu (bez bazy), pliki
  oczekujących zadań w `SPLITTER_WORK_DIR`.
- **Słownik typów** (proces słownikowy WEBCON) — nagłówek = typ, lista pozycji
  = wzorce; źródło danych mapuje go na pola żądania.

## Przepływ end-to-end

1. Na paczce skanu (jeden PDF jako załącznik) operator przechodzi ścieżką z akcją
   `SubmitSplitJobAction` — paczka trafia do kroku „Przetwarzanie".
2. Akcja czyta aktywne wzorce ze słownika (źródło danych) i wysyła je razem z PDF
   w multipart `POST /api/split` (nagłówek `Authorization: Bearer` +
   `X-Webcon-Element-Id`); odpowiedź `202` z `jobId` zapisuje w polu paczki.
   Akcja trwa tyle, co transfer pliku — nie czeka na OCR.
3. Splitter wkłada zadanie do kolejki; wątek roboczy dla **każdej strony** ustala
   tekst: warstwa tekstowa PDF, a gdy jej brak — OCR Tesseract (patrz
   [Zasady działania](#zasady-działania-splittera)).
4. Na tym tekście działa klasyfikacja: dopasowanie wzorców, wyznaczenie granic
   dokumentów, ewentualny fallback LLM dla stron niedopasowanych.
5. Akcja cykliczna `CollectSplitJobAction` odpytuje `GET /api/jobs/{jobId}`
   (lekki status: pozycja w kolejce, liczba dokumentów, ile do weryfikacji) i po
   `done` pobiera pełny wynik z `GET /api/jobs/{jobId}/result`: typ, zakres
   stron, pewność, powody weryfikacji, plik wynikowy (base64).
6. Akcja tworzy element **Dokument HR** dla każdego wykrytego dokumentu (załącznik
   + komentarz + relacja do paczki), kasuje zadanie (`DELETE /api/jobs/{jobId}`)
   i przechodzi paczką na krok końcowy; `requiresReview` i powody może zapisać
   w atrybutach elementu.

## Zasady działania splittera

Dwa etapy dla każdej strony: **(1) zdobycie tekstu**, potem **(2) klasyfikacja**.
Klasyfikacja jest jedna i ta sama niezależnie od tego, czy tekst pochodzi z
warstwy tekstowej, czy z OCR.

### 1. Zdobycie tekstu (OCR)

Za protokołem `OcrEngine` stoi kompozyt `TextLayerWithOcrFallback`:

- czyta osadzoną warstwę tekstową (born-digital PDF) jak `PdfTextOcrEngine`;
- stronę, której warstwa ma **mniej niż `SPLITTER_OCR_MIN_TEXT_CHARS`** (domyślnie
  25) znaków alfanumerycznych, renderuje przez `pypdfium2` (domyślnie 300 DPI) i
  puszcza przez Tesseract (`pytesseract`, języki `SPLITTER_OCR_LANGUAGES`, domyślnie
  `pol+eng`);
- **nadpisuje warstwę tekstową tylko wtedy, gdy OCR dostarczył więcej znaków** —
  inaczej krótki, ale realny tekst (albo pusty wynik przy braku binarki tesseract)
  skasowałby oryginał. To reguła „OCR nie niszczy danych".

**Dwa różne progi (celowo):**

- **Uruchom OCR** — `SPLITTER_OCR_MIN_TEXT_CHARS` (25, konfigurowalny). Wysoki,
  aby strona z samą stopką skanera trafiła do OCR.
- **Omiń LLM (strona tekstowo pusta)** — strona ma **≤
  `SPLITTER_EMPTY_PAGE_MAX_ALNUM`** znaków alfanumerycznych, również po OCR
  (domyślnie 0). Nie ma czego posłać do modelu, więc LLM jest pomijany.
  Krótka, ale realna strona nie jest uznawana za pustą i idzie normalnie do LLM.

Sam brak tekstu **nie oznacza pustej strony** — o tym decyduje osobno ocena
obrazu (`SPLITTER_BLANK_MAX_INK_RATIO`), patrz „Grupowanie stron", punkt 3.

OCR nigdy nie wywraca żądania: brak binarki / timeout (`SPLITTER_OCR_TIMEOUT_SECONDS`,
30 s) / błąd renderu → strona traktowana jak pusta, pozostałe strony przetwarzane
normalnie. Gdy `SPLITTER_OCR_ENABLED=false`, działa sama warstwa tekstowa.

Pliki wynikowe to **oryginalne strony** — OCR służy tylko klasyfikacji, nie wszywa
warstwy tekstowej w wynik (przeszukiwalność skanów załatwia się po stronie WEBCON
lub opcją „searchable PDF" na skanerach).

### 2. Klasyfikacja regułowa (słownik)

`RuleBasedClassifier` dla każdej strony liczy najlepsze dopasowanie wzorca na
tekście **znormalizowanym do ASCII** (fold `ł`→`l`, usunięcie diakrytyków, wielkie
litery, kompresja spacji) — po obu stronach porównania, więc znosi różnice zapisu:

- **nagłówek** wzorca znaleziony w pierwszych ~1200 znakach → `+0.80 × waga`;
- trafione **frazy** → `+0.10 × liczba_trafień × waga`;
- trafiona **fraza wykluczająca** → wzorzec całkowicie pomijany;
- pewność ograniczona do 1.00; **strona pierwsza dokumentu** przy pewności ≥ 0.70;
- gdy najlepszy wynik < 0.50 → „Nieznany typ dokumentu" (pewność 0.20).

Przy samym dopasowaniu **nagłówka** cyfry mylone przez OCR są dodatkowo
sprowadzane do liter (`0→O`, `1→I`, `5→S`), więc nagłówek zniekształcony przez
skan (np. `5WIADECTWO`) nadal zostaje rozpoznany — strona zaczyna nowy dokument,
zamiast trafić po cichu jako doklejka do poprzedniego. Frazy i właściwy tekst
strony pozostają bez zmian.

Efekt progów przy domyślnej wadze 1,0: sam trafiony nagłówek daje równo 0.80
i przechodzi próg auto-akceptacji (0.80); nagłówek + 2 trafione frazy dają
pełne 1.00.

Frazy trafione, ale bez nagłówka, tworzą „powinowactwo" typu (używane niżej).

### 3. Grupowanie stron

Dla kolejnych stron (każda należy do dokładnie jednego dokumentu):

1. **Nagłówek pasuje** (strona pierwsza) → nowy dokument.
2. **≥1 fraza typu bieżącego dokumentu** (powinowactwo) → kontynuacja bieżącego
   dokumentu (bez LLM).
3. **Strona pusta** → o pustce decyduje **obraz**, nie tekst. Strona jest
   usuwana wyłącznie gdy jednocześnie (a) render wykazał pokrycie atramentem
   poniżej `SPLITTER_BLANK_MAX_INK_RATIO` i (b) ma ≤ `SPLITTER_EMPTY_PAGE_MAX_ALNUM`
   znaków. Sam brak tekstu **nie wystarczy** — skan dowodu osobistego czy
   rejestracyjnego bywa dla OCR nieczytelny, a strona jest pełna treści.
   Zachowanie zależy od `SPLITTER_EMPTY_PAGE_MODE`: `keep` (domyślnie) dokleja
   z `requiresReview`, `report` tylko raportuje, `remove` usuwa. Bezpiecznik
   `SPLITTER_EMPTY_PAGE_MAX_SHARE` blokuje masowe usunięcia (np. przy awarii
   OCR), a cała paczka nigdy nie zostaje usunięta. Strony wizualnie puste
   **omijają OCR i LLM** — to również oszczędność czasu.
4. **W innym wypadku (ma tekst, brak dopasowania)** → fallback LLM (jeśli włączony).
5. **Fallback bez werdyktu / LLM wyłączony** → strona doklejana do bieżącego
   dokumentu z wymuszonym `requiresReview` i sygnałem `glued_unknown_page:N`.
   Serie stron sprzed pierwszego rozpoznanego dokumentu tworzą osobny segment
   „Nieznany typ dokumentu".

Powód rewizji doklejania: strony kontynuacji realnych dokumentów często nie mają
żadnej frazy typu, a frazy różnych typów się nakładają — samo powinowactwo fraz
siekałoby dokumenty, dlatego niepewne strony idą do weryfikacji, a nie na siłę do
podziału.

### 4. Fallback LLM (opcjonalny, domyślnie wyłączony)

Wołany **tylko** dla stron niedopasowanych i niepustych (`OpenAiCompatibleLlmClassifier`,
lokalny endpoint zgodny z OpenAI Chat Completions). Cechy:

- **retry bez `response_format`** przy HTTP 400 (LM Studio przyjmuje tylko
  `json_schema`/`text`); tolerancyjne parsowanie JSON (płoty markdown); normalizacja
  pewności podanej w procentach;
- **werdykt bez typu** (`documentType=""`) nigdy nie decyduje o podziale — jawna
  bramka w pipeline, nawet przy wysokiej pewności; `isFirstPage` i sugerowane frazy
  trafiają tylko do powodów/logów;
- **strażnik spójności** (`find_inconsistencies`) — czysto logiczne reguły, zero
  heurystyk wyglądu strony: (a) kontynuacja z typem innym niż bieżący, (b)
  kontynuacja bez bieżącego dokumentu, (c) `isKnownType=true` dla typu spoza
  słownika. Werdykt niespójny jest odrzucany jako decyzja, ale jego treść idzie do
  `reviewReasons` jako podpowiedź;
- werdykt „prawdziwej pierwszej strony" jest akceptowany dopiero od
  `SPLITTER_MIN_REVIEW_CONFIDENCE` (0.70).

Bez LLM obce wtrącenie w środku paczki nie zostanie rozdzielone automatycznie —
robi to operator przy weryfikacji. LLM proponuje też nowe typy i frazy
(`suggestedNewPatterns`) — dziś tylko jako podpowiedź, nikt ich nie agreguje
(patrz [Status i ograniczenia](#status-i-ograniczenia)).

### 5. Weryfikacja i powody

Dokument dostaje `requiresReview = true`, gdy jest doklejona strona
(`forced_review`) **lub** pewność < `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE` (0.80).
`reviewReasons` (lista po polsku) zawiera m.in.: nierozpoznany typ, strona bez
tekstu, strona doklejona bez dopasowania (z pasującymi frazami innych typów i
propozycją LLM), odrzucony werdykt niespójny, pewność poniżej progu. `signals`
niosą ślad techniczny (`header_match:...`, `phrase_hits:N`, `glued_unknown_page:N`,
`llm:<kod>`). Status całości to `requires_review`, gdy choć jeden dokument wymaga
weryfikacji, inaczej `completed`.

### 6. Podział pliku

`split_pdf` kopiuje **oryginalne strony** źródłowego PDF do plików wynikowych
(bez ponownego kodowania, bez zmiany treści). Nazwa pliku:
`Typ_dokumentu_strony_SSS-EEE.pdf` (znaki `spacja / \ :` zamieniane na `_`).

## Konfiguracja serwisu

Wszystkie zmienne mają prefiks `SPLITTER_`. Ustawienia nieznane (np. po usunięciu
opcji) są ignorowane — nie wywracają startu. Szablon: [`splitter/.env.example`](splitter/.env.example).

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `SPLITTER_API_TOKEN` | (puste) | Wymusza `Authorization: Bearer <token>` na `/api/split`. Puste = brak autoryzacji |
| `SPLITTER_LOG_LEVEL` | `INFO` | Poziom logów w `docker logs`. Na INFO: tekst odczytany z każdej strony (patrz niżej), decyzja klasyfikacji per strona + podsumowanie z powodami |
| `SPLITTER_LOG_PAGE_TEXT` | `true` | Loguje per strona tekst odczytany z warstwy/OCR: fragment surowy + fragment znormalizowany (ASCII, wielkie litery) — dokładnie w postaci, w jakiej klasyfikator szuka nagłówków i fraz. Diagnostyka „czemu słownik nie zadziałał" |
| `SPLITTER_LOG_PAGE_TEXT_RAW_CHARS` | `1200` | Limit znaków surowego fragmentu w logu |
| `SPLITTER_LOG_PAGE_TEXT_NORM_CHARS` | `300` | Limit znaków znormalizowanego fragmentu w logu |
| `SPLITTER_WORK_DIR` | `/app/work` | Katalog roboczy serwisu: pliki oczekujących zadań (kasowane po przetworzeniu — także gdy zadanie skończy się błędem) oraz katalogi tymczasowe na pliki wynikowe, sprzątane po odczytaniu do base64. **Wyłącznie serwisu** — przy starcie kontenera zamiatany w całości (pozostałości po poprzednim wcieleniu) |
| `SPLITTER_WORKER_COUNT` | `1` | Ile paczek przetwarzanych jednocześnie. `1` = gwarancja „po kolei" |
| `SPLITTER_MAX_QUEUE_SIZE` | `50` | Ile zadań może **czekać** w kolejce; powyżej → `503` + `Retry-After`. Limit chroni dysk (każde zadanie trzyma swój PDF w `SPLITTER_WORK_DIR`); głębsza kolejka nie przyspiesza przetwarzania |
| `SPLITTER_JOB_RESULT_TTL_SECONDS` | `3600` | Jak długo gotowy wynik czeka na odbiór. Musi być znacznie dłuższy niż interwał odpytywania (przy takcie minutowym daje 60 szans) |
| `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE` | `0.80` | Poniżej → dokument dostaje `requiresReview` (0.80 = sam dobry nagłówek z wagą 1,0 przechodzi) |
| `SPLITTER_MIN_REVIEW_CONFIDENCE` | `0.70` | Minimalna pewność, przy której werdykt LLM jest brany pod uwagę |
| `SPLITTER_LLM_ENABLED` | `false` | Włącza fallback LLM (wymaga endpointu i modelu) |
| `SPLITTER_LLM_ENDPOINT` | (puste) | Endpoint zgodny z OpenAI, np. `http://host:1234/v1` |
| `SPLITTER_LLM_MODEL` | (puste) | Nazwa modelu |
| `SPLITTER_LLM_TIMEOUT_SECONDS` | `30` | Limit czasu wywołania LLM |
| `SPLITTER_LLM_PROMPT_FILE` | (puste) | Plik szablonu user promptu (wolumen); puste = wbudowany. Patrz [`splitter/docs/llm-prompt.md`](splitter/docs/llm-prompt.md) |
| `SPLITTER_LLM_SYSTEM_PROMPT_FILE` | (puste) | Plik szablonu system promptu (wolumen); puste = wbudowany |
| `SPLITTER_OCR_ENABLED` | `true` | Fallback Tesseract dla skanów bez warstwy tekstowej |
| `SPLITTER_OCR_MIN_TEXT_CHARS` | `25` | Poniżej tylu znaków alfanum. warstwy tekstowej → strona idzie do OCR |
| `SPLITTER_OCR_LANGUAGES` | `pol+eng` | Języki Tesseracta (muszą być w obrazie) |
| `SPLITTER_OCR_DPI` | `300` | Rozdzielczość renderu strony do OCR |
| `SPLITTER_OCR_TIMEOUT_SECONDS` | `30` | Limit czasu OCR jednej strony |
| `SPLITTER_OCR_WORKERS` | `2` | Liczba równoległych wątków OCR (procesów Tesseracta); render stron pozostaje sekwencyjny. Więcej = szybsze duże paczki kosztem CPU/RAM |
| `SPLITTER_EMPTY_PAGE_MODE` | `keep` | `keep` = nic nie usuwa (puste strony doklejane z `requiresReview`); `report` = wykrywa i raportuje, nie usuwa; `remove` = usuwa potwierdzone puste. Nieznana wartość → `keep` + ostrzeżenie |
| `SPLITTER_EMPTY_PAGE_MAX_ALNUM` | `0` | Do ilu znaków alfanum. strona jest „tekstowo pusta". Warunek usunięcia to **koniunkcja** z oceną obrazu |
| `SPLITTER_EMPTY_PAGE_MAX_SHARE` | `0.5` | Bezpiecznik: powyżej tego udziału „pustych" stron nie usuwaj nic. Całej paczki nie usuwa nigdy |
| `SPLITTER_BLANK_DETECT_DPI` | `60` | Rozdzielczość renderu do pomiaru pokrycia atramentem |
| `SPLITTER_BLANK_MAX_INK_RATIO` | `0.002` | Udział ciemnych pikseli, poniżej którego strona jest wizualnie pusta (0,2%) |
| `SPLITTER_BLANK_MARGIN_RATIO` | `0.04` | Odcinany margines (krawędzie skanera, dziurki, przekrzywienie) |

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

**Strojenie równoległości OCR (`OMP_THREAD_LIMIT`)** — `SPLITTER_OCR_WORKERS` to
liczba równoległych **procesów** Tesseracta (po jednym na stronę z bieżącej
partii). Haczyk: pojedynczy proces Tesseracta zbudowany z OpenMP (jak w obrazie
Debiana) domyślnie tworzy zespół wątków wielkości **liczby rdzeni** — więc przy
`workers > 1` sumaryczna liczba wątków wynosi `workers × rdzenie` i przekracza
liczbę rdzeni. Ta **nadsubskrypcja** wydłuża czas pojedynczej strony i wywołuje
timeouty (`SPLITTER_OCR_TIMEOUT_SECONDS`) tam, gdzie sekwencyjnie ich nie było.
Lekarstwo: ograniczyć wątki **na proces** zmienną OpenMP `OMP_THREAD_LIMIT`.

`OMP_THREAD_LIMIT` **nie jest** zmienną `SPLITTER_*` — to surowa zmienna
środowiskowa OpenMP (pydantic ją ignoruje, a błędna wartość nie wywróci
serwisu). Ustawia się ją w tym samym pliku `.env` obok compose (Docker
wstrzykuje cały `.env` do kontenera przez `env_file`), a proces `tesseract`
dziedziczy ją przy starcie. Zasada: **`OMP_THREAD_LIMIT` = liczba rdzeni na
jeden proces**, a `SPLITTER_OCR_WORKERS × OMP_THREAD_LIMIT ≈ liczba rdzeni
(vCPU)`.

Przykłady na maszynie 4-rdzeniowej:

| `.env` | Efekt |
|---|---|
| `SPLITTER_OCR_WORKERS=4` + `OMP_THREAD_LIMIT=1` | 4 strony naraz, każda 1 rdzeń — **maks. przepustowość** |
| `SPLITTER_OCR_WORKERS=2` + `OMP_THREAD_LIMIT=2` | 2 strony naraz, każda 2 rdzenie — **zbalansowane** (mniej timeoutów na ciężkich stronach) |
| `SPLITTER_OCR_WORKERS=1` (bez `OMP_THREAD_LIMIT`) | 1 strona na wszystkich rdzeniach — najniższa przepustowość, ale najkrótszy czas pojedynczej strony |

Do przerobienia całej paczki więcej **procesów** zwykle bije więcej **wątków na
proces** — Tesseract słabo skaluje się wątkowo w obrębie jednej strony (~1,5× z
4 wątków, nie 4×). Domyślne `workers=2` **bez** `OMP_THREAD_LIMIT` na maszynie z
małą liczbą rdzeni łatwo prowadzi do nadsubskrypcji — ustaw `OMP_THREAD_LIMIT`
świadomie. Uwaga: `OMP_THREAD_LIMIT=2` znaczy „2 rdzenie **na proces**", a nie
„2 rdzenie łącznie"; żeby każdy z 2 procesów dostał 4 rdzenie, potrzeba
`OMP_THREAD_LIMIT=4` (i co najmniej 8 vCPU).

**Diagnostyka klasyfikacji w logach** — przy `SPLITTER_LOG_PAGE_TEXT=true` każde
żądanie `/api/split` loguje po ekstrakcji tekstu wpis per strona, np.:

```
Strona 2: 830 znakow alnum | surowy(1200): "Faktura VAT nr 12/2026 ..." | znorm(300): "FAKTURA VAT NR 12/2026 ..."
Strona 5: 0 znakow (pusta)
```

Każda linia logu żądania `/api/split` ma prefiks `[job=<jobId>]` — przy
równoczesnych żądaniach logi różnych paczek da się rozdzielić i skorelować
z `jobId` zapisanym w logu operacji akcji WEBCON.

Po każdym podziale log dostaje linię podsumowania, np. `Metryki zadania: 12
stron (OCR: 5), wywolania LLM: 2, dokumenty: 4 (weryfikacja: 1), czas 8.3 s`,
a te same wielkości skumulowane od startu procesu zwraca `GET /metrics` —
`review_rate` (odsetek dokumentów do weryfikacji) to główny wskaźnik, czy
zmiany słownika i progów faktycznie poprawiają automatykę.

Fragment `znorm` porównuje się 1:1 z nagłówkami i frazami ze słownika (nagłówek
musi wystąpić w pierwszych ~1200 znormalizowanych znakach). Dodatkowo OCR loguje
`OCR: uzupelniono tekst N stron (strony: [...])` oraz `OCR nie poprawil stron [...]
- zachowano tekst warstwy` — z logu zawsze wynika, skąd pochodzi tekst strony.
Uwaga: przy włączonym logowaniu fragmenty treści dokumentów trafiają do logów
kontenera — patrz [Zalecenia produkcyjne](#zalecenia-produkcyjne).

Plik `.env` jest czytany przy każdym żądaniu (zmiany bez restartu procesu; zmienna
środowiskowa procesu ma pierwszeństwo przed plikiem). **Zmiana `.env` w Dockerze:**
odtwórz kontener (`docker compose up -d`, w razie potrzeby `--force-recreate`) —
`docker compose restart` **nie** wczytuje `.env` na nowo. Zmiana `.env` nie wymaga
przebudowy obrazu (`--build`); rebuild jest potrzebny tylko przy zmianie kodu lub
Dockerfile.

## API splittera

| Endpoint | Opis |
|---|---|
| `GET /health` | Kontrola życia serwisu → `{"status":"ok"}`. Odpowiada także w trakcie przetwarzania paczki |
| `GET /metrics` | Liczniki skumulowane od startu procesu (JSON, w pamięci): żądania, strony (w tym uzupełnione OCR), wywołania LLM, dokumenty, odsetek weryfikacji (`review_rate`), łączny czas przetwarzania. Token jak `/api/split` |
| `POST /api/split` | multipart: `file` (PDF) + `patterns` (JSON, opcjonalne) → **`202`** `{jobId, position}` — zlecenie trafia do kolejki |
| `GET /api/jobs/{jobId}` | Lekki status zadania (bez base64) — do odpytywania co takt akcji cyklicznej |
| `GET /api/jobs/{jobId}/result` | Pełny `SplitResult` z plikami (base64) — po `status=done` |
| `DELETE /api/jobs/{jobId}` | Kasuje zadanie i zwalnia pamięć — wołane po zapisaniu dokumentów w WEBCON |
| `POST /api/pages/remove` | multipart: `file` (PDF) + `pages` (zakres) → `PageOpResult` bez tych stron (synchronicznie) |
| `POST /api/pages/extract` | multipart: `file` (PDF) + `pages` (zakres) → `PageOpResult` tylko z tymi stronami (synchronicznie) |
| `POST /api/merge` | multipart: wiele `files` (PDF) w kolejności + `output_file_name` → `PageOpResult` (sklejony, synchronicznie) |

`/api/split` wymaga `Authorization: Bearer <SPLITTER_API_TOKEN>` (jeśli token
skonfigurowany) i przyjmuje nagłówek `X-Webcon-Element-Id` — służy do
**deduplikacji**: jeśli element ma już aktywne zadanie (`queued`/`running`),
powtórne zlecenie zwraca istniejący `jobId` zamiast tworzyć drugie (ochrona
przed podwójnym podziałem po zgubionej odpowiedzi). Bez pola `patterns` serwis
działa na pustej liście wzorców (wszystko → „Nieznany typ dokumentu").

**Pole `patterns`** — lista obiektów: `documentType`, `header`, `phrases` (lista),
`excludedPhrases` (lista), `weight` (domyślnie 1.0).

**Status zadania (`GET /api/jobs/{jobId}`):** `jobId`, `status`
(`queued` → `running` → `done` | `failed`), `position` (miejsce w kolejce, od 1;
0 = już zdjęte), `runningSeconds`, `pageCount`, `documentCount`,
`documentsRequiringReview`, `warnings`, `error`. Celowo **bez base64** —
odpytywanie co minutę nie może przeciągać całej paczki przez sieć.

**Wynik (`GET /api/jobs/{jobId}/result`) — `SplitResult`:** `sourceFileName`,
`pageCount`, `status` (`completed`/`requires_review`/`failed`), `warnings`
(lista), `jobId` (uuid), oraz `documents` — lista `DetectedDocument`:

| Pole | Znaczenie |
|---|---|
| `documentIndex` | numer kolejny (od 1) |
| `documentType` | rozpoznany typ lub „Nieznany typ dokumentu" |
| `confidence` | pewność 0.00–1.00 |
| `requiresReview` | czy wymaga weryfikacji operatora |
| `reviewReasons` | lista powodów po polsku (gdy `requiresReview`) |
| `startPage` / `endPage` | zakres stron w oryginale |
| `outputFileName` | nazwa pliku wynikowego |
| `fileContentBase64` | zawartość wynikowego PDF (base64) |
| `signals` | ślad techniczny decyzji klasyfikacji (`header_match:…`, `phrase_hits:…`, `llm:…`) — akcja dopisuje go do komentarza dokumentu |

Kody: `202` (przyjęte do kolejki), `400` (złe `patterns`, nie-PDF w nazwie —
błędy konfiguracji wracają synchronicznie), `401` (zły token), `404` (nieznane
zadanie — także po restarcie kontenera i po TTL; WEBCON zleca wtedy ponownie),
`409` (wynik jeszcze niegotowy), `503` + `Retry-After` (kolejka pełna — ponowić
później, to nie błąd). PDF zaszyfrowany/uszkodzony **nie** daje `400` — zadanie
kończy się `status=failed` z treścią w polu `error`.

**Trwałość:** kolejka i wyniki żyją w pamięci procesu, pliki oczekujących zadań
w `SPLITTER_WORK_DIR`. Po restarcie kontenera zadania przepadają (a `work_dir`
jest zamiatany przy starcie) — to świadome: źródłem prawdy jest załącznik
w WEBCONie, akcja odbierająca dostaje `404` i zleca ponownie.

### Ręczne operacje na PDF (dla akcji operatora)

Endpointy `/api/pages/remove`, `/api/pages/extract`, `/api/merge` obsługują ręczną
korektę załączników przez operatora. Nie używają OCR/LLM/wzorców — to czyste operacje
na stronach. Uwierzytelnianie i nagłówek `X-Webcon-Element-Id` jak w `/api/split`.

- **`pages`** — zakres stron **1-based, inclusive**, np. `2-4,7`. Zły zakres / pusty
  wynik (usunięcie wszystkich stron) → `400` z komunikatem w `detail`.
- **`/api/merge`** — pola `files` powtórzone w kolejności sklejania; `output_file_name`
  opcjonalne (domyślnie `merged.pdf`).

**Odpowiedź `PageOpResult`:** `{ outputFileName, pageCount, fileContentBase64, warnings }`.

## Integracja z WEBCON

Środowisko docelowe: **WEBCON BPS 2026.1** (domyślnie) lub **BPS 2025 R2**
(`package.ps1 -Sdk 2025`). Akcje podziału: `SubmitSplitJobAction` (zlecenie)
i `CollectSplitJobAction` (odbiór, cykliczna), zbudowane na
`WEBCON.BPS.<linia>.SDK.Libraries`, podpisane strong name. Wymagają licencji SDK.

### Rejestracja pluginu

1. `powershell -File webcon-action\package.ps1 [-Sdk 2025|2026]` →
   `webcon-action\Publish\WebconPdfSplitterAction-<linia BPS>-<wersja>.zip`,
   np. `WebconPdfSplitterAction-2025r2-1.0.12.1.zip`
   (DLL pluginu + Newtonsoft.Json.dll + manifest; biblioteki SDK dostarcza host BPS).
   Skrypt sam podbija 4-częściową wersję (= wersja assembly); wersja jest też
   w logu operacji (`SubmitSplitJobAction vX.Y.Z.W`).
2. Designer Studio → **Plugin packages** → **New package** → wskaż ZIP → **Verify plugins**.

### Obieg paczki: kroki i pola

Kolejka żyje w splitterze, więc obieg paczki jest prosty — bez kroku-muteksu
i liczenia elementów w krokach:

```
Rejestracja → Przetwarzanie → Podzielona
                   │
                   └─(limit prób / timeout dozorcy)→ Błąd
```

- **Rejestracja → Przetwarzanie**: na przejściu `SubmitSplitJobAction`. Element
  przechodzi **zawsze** — nieudane zlecenie (kolejka pełna, serwis niedostępny)
  nie jest błędem elementu; akcja odbierająca ponowi je przy kolejnym takcie.
- **Przetwarzanie**: akcja cykliczna `CollectSplitJobAction` (zalecany interwał
  ~1 min) + **akcja na timeout** (dozorca: po N minutach od daty zlecenia →
  ścieżka na Błąd; N ≈ 3× spodziewany czas największej paczki).
- **Podzielona / Błąd**: kroki końcowe (Błąd z opisem w polu statusu).

Pola na formularzu paczki (ID podaje się w konfiguracji obu akcji):

| Pole | Typ | Rola |
|---|---|---|
| Job ID | tekst | Klucz zadania; korelacja z logiem kontenera (`[job=…]`) |
| Data zlecenia | data i czas | Podstawa dla akcji na timeout (dozorcy) |
| Status przetwarzania | tekst | Dla operatora: „3. w kolejce" / „8 dok., 2 do weryfikacji" / treść błędu |
| Liczba prób | liczba | Ochrona przed pętlą ponowień (rośnie tylko przy `404`/`failed`, **nie** przy zajętości) |
| Ostatni utworzony dokument | liczba | Wznawianie odbioru po awarii bez duplikatów (`documentIndex`) |
| **Wynik przetwarzania** | tekst | `GOTOWE` / `BLAD` / puste — **wyzwalacz przejścia ścieżką po stronie WEBCON** |

### Dlaczego przejście wykonuje WEBCON, a nie akcja

Akcja SDK **nie może przenieść własnego elementu**. `DocumentsManager.MoveDocumentToNextStepAsync`
służy do przesuwania *innych* elementów; wywołana na elemencie, w którego kontekście
działa, kończy się wyjątkiem:

```
SDKOperationException: Workflow instance is being saved.
  at ElementFormEnsurer.EnsureRequestsSafety()
```

WEBCON trzyma element otwarty do zapisu przez cały czas wykonania akcji, a
`RunCustomActionParams.TransitionInfo` jest tylko do odczytu — w SDK nie ma
żadnej właściwości pozwalającej wskazać ścieżkę dla bieżącego elementu.

Dlatego `CollectSplitJobAction` **kończy pracę zapisem pola „Wynik przetwarzania"**
(`GOTOWE` albo `BLAD`), a samo przejście konfigurujesz w Designer Studio jako
przejście warunkowe na tym polu. Akcja zlecająca czyści to pole przy każdym
wejściu w obieg, więc paczka puszczona ponownie po błędzie nie zostanie
natychmiast wypchnięta ze starą wartością.

### Konfiguracja akcji „SubmitSplitJobAction" (przejście z Rejestracji)

| Pole | Wymagane | Opis / skąd wziąć |
|---|---|---|
| Splitter base URL | tak | Adres serwisu, np. `http://serwer:8010`. Osiągalny **z serwera WEBCON** (WorkflowService), nie z przeglądarki |
| Splitter API token | zalecane | Ta sama wartość co `SPLITTER_API_TOKEN` |
| Timeout in seconds | nie (300) | Limit HTTP — po zmianie na kolejkę wystarcza na sam transfer pliku |
| Patterns data source ID | tak | Źródło danych z aktywnymi wzorcami (kolumny niżej) |
| Job ID field ID | tak | Pole tekstowe na `jobId` |
| Submitted at field ID | tak | Pole daty i czasu z momentem zlecenia |
| Outcome field ID | tak | Pole tekstowe na `GOTOWE`/`BLAD` — wyzwalacz przejścia |
| Status field ID | nie | Pole tekstowe na status dla operatora |
| Attempts field ID | nie | Pole liczbowe z liczbą nieudanych prób |
| Last created document index field ID | nie | Pole liczbowe do wznawiania odbioru |

### Konfiguracja akcji „CollectSplitJobAction" (cykliczna na Przetwarzaniu)

Wszystkie pola powyżej (wspólna konfiguracja połączenia i pól paczki), plus:

| Pole | Wymagane | Opis |
|---|---|---|
| Target workflow ID | tak | Obieg, w którym powstają elementy Dokument HR |
| Target document type ID | tak | Typ formularza elementów Dokument HR |
| Start path ID | tak | Ścieżka startowa obiegu Dokument HR |
| Requires review field ID | nie | Pole tak/nie na `requiresReview`; puste = pomijane |
| Review reasons field ID | nie | Pole tekstowe (wieloliniowe) na powody. Ustawione → powody tylko do pola; puste → do komentarza elementu |
| Parent element ID field ID | nie | Pole na ID elementu nadrzędnego; relacja systemowa rodzic–dziecko jest ustawiana zawsze |
| Max attempts | nie (3) | Po ilu **nieudanych** próbach (`404`/`failed`) element dostaje `BLAD`. Zajętość (`503`) i brak połączenia się nie liczą |
| Pomijaj sprawdzanie uprawnień | nie (włączone) | Konieczne dla akcji cyklicznej — patrz niżej |

### Kontekst wykonania: konto serwisowe, nie operator

Akcja na przejściu ścieżką dziedziczy kontekst klikającego użytkownika. Akcja
**cykliczna** działa jako konto serwisowe WEBCON, które zwykle nie ma
przypisanej spółki ani prawa startowania elementów. Bez uwzględnienia tego
tworzenie dokumentów potomnych kończy się:

```
SDKSecurityException: Nieprawidłowy identyfikator spółki lub użytkownik
nie ma uprawnień do startowania elementów workflow z wybranej spółki.
```

`CollectSplitJobAction` rozwiązuje to dwojako: **dziedziczy `CompanyID` po
paczce** (dokument potomny należy do tej samej spółki co jego źródło) i
przekazuje `SkipPermissionsCheck` do `GetNewDocumentAsync` oraz
`StartNewWorkFlowAsync`. Przełącznik jest domyślnie włączony — wyłącz go tylko
wtedy, gdy konto serwisowe ma nadane realne uprawnienia w docelowej spółce.

Logika taktu `CollectSplitJobAction`: brak `jobId` → zleca (wspólna ścieżka dla
`503`, błędu sieci, `404` i wygasłego wyniku); `queued`/`running` → aktualizuje
pole statusu; `done` → pobiera wynik, tworzy dokumenty potomne (wznawiając od
`documentIndex` > „Ostatni utworzony dokument"), kasuje zadanie i zapisuje
`GOTOWE`; `failed`/`404` → licznik prób, powyżej limitu zapisuje `BLAD`.
Przejście ścieżką wykonuje WEBCON na podstawie pola wyniku — patrz wyżej.

ID obiektów: Designer Studio → właściwości obiektu → ID (włącz „Pokaż identyfikatory
obiektów", jeśli niewidoczne).

### Ręczne akcje operatora

Gdy automat sklei dwa dokumenty w jeden (element oznaczony „do sprawdzenia"),
operator koryguje wynik trzema akcjami — zwykle podpiętymi pod przyciski w kroku
weryfikacji:

- **RemovePagesAction** — usuwa zakres stron (np. `2-4,7`) z jedynego PDF-a
  w dozwolonych kategoriach załącznika. Przełącznik „Podmień zawartość w miejscu"
  (nadpisz oryginał) lub dodanie nowego załącznika (oryginał zostaje).
- **ExtractPagesToNewFormAction** — wycina strony do nowego, surowego elementu
  (bez klasyfikacji — typ i weryfikację ustawia operator) w obiegu docelowym;
  przełącznik „Usuń wycięte strony ze źródła" (przenoszenie vs kopiowanie).
- **MergeAttachmentsAction** — skleja załączniki wskazane w liście pozycji
  (wiersz = załącznik po ID z kolumny picker, kolejność wierszy = kolejność
  sklejania) w jeden PDF dodawany do bieżącego elementu; źródła zostają.

Wszystkie trzy dzielą konfigurację połączenia (URL/token/timeout) z akcjami podziału.
Kategorie załączników podaje się nazwami lub ID grup, rozdzielone średnikami;
akcje remove/extract wymagają **dokładnie jednego** PDF-a w tych kategoriach
(0 lub >1 → czytelny błąd). Komunikaty walidacyjne serwisu (np. „Strona 8 poza
dokumentem (1-6)") trafiają do komunikatu błędu akcji.

### Słownik typów i źródło danych

Wzorce żyją w procesie słownikowym WEBCON (nagłówek = typ, lista pozycji = wzorce)
i są wysyłane w każdym żądaniu — splitter nie ma dostępu do bazy WEBCON. Zmiany
działają od następnego wywołania, bez restartów.

Proces słownikowy „Typ dokumentu" — atrybuty nagłówka: **Nazwa typu** (tekst,
polskie znaki dozwolone), **Aktywny** (checkbox), **Próg auto-akceptacji** (liczba,
pole rezerwowe — dziś splitter stosuje próg globalny). Lista pozycji „Wzorce":
**Nagłówek dokumentu** (pusty = pomijany), **Frazy** (średniki), **Frazy wykluczające**
(średniki), **Waga** (puste = 1,0), **Aktywny**.

Źródło danych musi zwracać **wyłącznie aktywne** wzorce w kolumnach o dokładnych
nazwach `DocumentType`, `Header`, `Phrases`, `ExcludedPhrases`, `Weight`:

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

Nagłówki i frazy najlepiej wpisywać bez polskich znaków (dopasowanie i tak
normalizuje do ASCII — ułatwia diagnostykę). Przykład wzorców do testów generuje
`scripts/make_test_documents.py`.

**Dane startowe** (wprowadź ręcznie, ~15 min; wszystkie typy i wzorce: Aktywny = tak,
Próg = 0,90):

| Typ dokumentu | Nagłówek wzorca | Frazy | Frazy wykluczające | Waga |
|---|---|---|---|---|
| Umowa o pracę | UMOWA O PRACE | pracodawca; pracownik; wynagrodzenie; wymiar czasu pracy | aneks; wypowiedzenie; rozwiazanie umowy | 1,2 |
| Aneks do umowy o pracę | ANEKS DO UMOWY O PRACE | zmienia sie; pozostale warunki; porozumienie stron | | 1,2 |
| Aneks do umowy o pracę | ANEKS DO UMOWY | umowy o prace; zmienia sie | | 1,0 |
| Umowa zlecenie | UMOWA ZLECENIE | zleceniodawca; zleceniobiorca | | 1,2 |
| Umowa zlecenie | UMOWA ZLECENIA | zleceniodawca; zleceniobiorca | | 1,2 |
| Wypowiedzenie umowy o pracę | WYPOWIEDZENIE UMOWY O PRACE | okres wypowiedzenia; rozwiazanie umowy | | 1,2 |
| Wypowiedzenie umowy o pracę | ROZWIAZANIE UMOWY O PRACE | za wypowiedzeniem; bez wypowiedzenia; porozumienie stron | | 1,1 |
| Świadectwo pracy | SWIADECTWO PRACY | stosunek pracy; okres zatrudnienia; urlop wypoczynkowy | | 1,2 |
| Kwestionariusz osobowy | KWESTIONARIUSZ OSOBOWY | imie i nazwisko; data urodzenia; adres zamieszkania | | 1,2 |
| Orzeczenie lekarskie | ORZECZENIE LEKARSKIE | zdolny do pracy; badania profilaktyczne; medycyna pracy | | 1,2 |
| Orzeczenie lekarskie | ZASWIADCZENIE LEKARSKIE | zdolny do pracy; przeciwwskazania | | 1,0 |
| Zaświadczenie o ukończeniu szkolenia BHP | ZASWIADCZENIE O UKONCZENIU SZKOLENIA | bezpieczenstwa i higieny pracy; bhp; szkolenie okresowe | | 1,1 |
| Zaświadczenie o ukończeniu szkolenia BHP | KARTA SZKOLENIA WSTEPNEGO | instruktaz ogolny; instruktaz stanowiskowy; bhp | | 1,2 |
| Oświadczenie PIT-2 | PIT-2 | oswiadczenie; zaliczek na podatek; kwoty zmniejszajacej | | 1,2 |
| Zgoda na przetwarzanie danych osobowych | ZGODA NA PRZETWARZANIE DANYCH | danych osobowych; rodo; administratorem danych | | 1,2 |

Diagnostyka słownika: błąd o brakujących kolumnach → aliasy w zapytaniu muszą
brzmieć dokładnie `DocumentType/Header/Phrases/ExcludedPhrases/Weight`;
„patterns data source returned no rows" w logu akcji → słownik pusty lub wszystko
nieaktywne (wszystko → „Nieznany typ dokumentu"); HTTP 400 „Invalid patterns payload"
→ złe typy wartości (np. tekst w kolumnie Weight).

### Procesy i elementy

- **Paczka skanu** — dokładnie jeden PDF jako załącznik (więcej niż jeden = błąd
  o niejednoznacznym pliku), pola kolejki (Job ID, data zlecenia, status, liczba
  prób, ostatni utworzony dokument — patrz
  [Obieg paczki](#obieg-paczki-kroki-i-pola)). `SubmitSplitJobAction` podpina
  się na ścieżce przejścia na kroku z kompletem załączników.
- **Dokument HR** — element na każdy wykryty dokument: jeden PDF, komentarz
  `Type: <typ>; pages <od>-<do>; confidence <0.00-1.00>; requires review: <t/f>`
  (+ `sygnaly: …` — ślad decyzji klasyfikacji, np. `header_match:UMOWA O PRACE`),
  relacja do paczki (`ParentDocumentID`), opcjonalnie `requiresReview` i powody
  w polach formularza.

Akcje rozróżniają i raportują błędy (użytkownik: komunikat biznesowy;
administrator: stack w logu): brak PDF, więcej niż jeden PDF, złe wzorce (400),
zły token (401). **Zajętość serwisu (503) i brak połączenia nie są błędami
elementu** — element czeka w Przetwarzaniu, a zlecenie ponawia się przy kolejnym
takcie. PDF zaszyfrowany/uszkodzony kończy zadanie statusem `failed` (treść
w polu statusu paczki). Oryginalny PDF nigdy nie jest modyfikowany ani usuwany.
`jobId` trafia do pola paczki i do logu operacji obu akcji.

## Wdrożenie

Topologia docelowa: kontener na **dedykowanym serwerze** (nie na serwerze WEBCON);
serwer WEBCON łączy się po HTTP z tokenem. Serwis bez bazy — kolejka i wyniki
w pamięci procesu, pliki oczekujących zadań w `SPLITTER_WORK_DIR`.

### Migracja z wersji synchronicznej (≤ v1.0.12-sync)

Wersje do taga **`v1.0.12-sync`** (paczki `2026r1-1.0.12.7` / `2025r2-1.0.12.8`)
zwracały wynik wprost z `POST /api/split`, a akcja `SplitPdfAction` czekała na
niego synchronicznie. To **zmiana łamiąca zgodność** — stary plugin nie działa
z nowym kontenerem i odwrotnie:

1. Wdróż nowy kontener i nową paczkę pluginu **razem** (okno serwisowe).
2. Załóż kroki `Przetwarzanie`/`Błąd` i pola paczki
   (patrz [Obieg paczki](#obieg-paczki-kroki-i-pola)).
3. Przepnij akcje: `SubmitSplitJobAction` na przejście z Rejestracji,
   `CollectSplitJobAction` jako cykliczna na Przetwarzaniu, akcja na timeout
   jako dozorca.
4. Elementy będące w locie w chwili wdrożenia przepchnij ręcznie — paczka
   czekająca na odpowiedź starego API nie ma ścieżki migracji.

Powrót: `git checkout v1.0.12-sync` + przebudowa kontenera i paczki pluginu.

### Docker (zalecane)

```bash
cd splitter
cp .env.example .env      # uzupełnij token, ewentualnie LLM/OCR
docker compose up -d --build
curl http://localhost:8010/health   # -> {"status":"ok"}
```

- Obraz `python:3.12-slim` + `tesseract-ocr` i `tesseract-ocr-pol` (OCR polskich
  skanów), użytkownik nieuprzywilejowany, healthcheck co 30 s, `restart: unless-stopped`.
- Compose mapuje **port hosta 8010 → 8000 w kontenerze** (8000 bywa zajęte przez
  inny kontener); zmienisz w `docker-compose.yml`.
- `.env` nie jest kopiowany do obrazu — compose wstrzykuje go przy starcie.
- Aktualizacja kodu/obrazu: `docker compose up -d --build`. Logi:
  `docker logs webcon-pdf-splitter`.

### Aktualizacja wdrożenia (nowa wersja z repozytorium)

Na serwerze, na którym działa kontener:

```bash
cd <katalog-repo>          # klon https://github.com/MWolosiewicz/webcon-split
git pull                   # pobierz aktualny main
cd splitter
docker compose up -d --build   # przebuduj obraz i odtwórz kontener
curl http://localhost:8010/health              # -> {"status":"ok"}
docker logs --tail 20 webcon-pdf-splitter      # sanity check logów
```

- `docker compose up -d --build` robi całość: buduje obraz z nowego kodu i
  podmienia kontener tylko wtedy, gdy coś się zmieniło. Lokalny `.env` zostaje —
  nie jest częścią repo ani obrazu.
- Sama zmiana `.env` (bez zmiany kodu) nie wymaga budowania: wystarczy
  `docker compose up -d` (w razie potrzeby `--force-recreate`); `docker compose
  restart` **nie** wczytuje `.env` na nowo.
- Zmiany wyłącznie w `splitter/` nie dotykają paczki WEBCON — importu pluginu
  nie trzeba ponawiać. Nową paczkę importuje się tylko po zmianach w
  `webcon-action/` (patrz [Rejestracja pluginu](#rejestracja-pluginu)).

### Wdrożenie gałęzi testowej (bez scalania do `main`)

Gdy chcesz sprawdzić wersję na serwerze **przed** scaleniem do `main` (np. gałąź
`branch/...` wypchniętą na GitHub), przełącz repozytorium serwera na tę gałąź
i przebuduj obraz. Zwykłe `git pull` ciągnie gałąź aktualnie wybraną na serwerze
(u nas zwykle `main`), dlatego gałąź trzeba najpierw jawnie wskazać przez
`git checkout`.

Na serwerze, na którym działa kontener:

```bash
cd <katalog-repo>
git fetch origin
git checkout <nazwa-galezi>        # np. branch/splitter-document-classify-v2
git pull                           # dociagnij najnowszy stan tej galezi
cd splitter
docker compose up -d --build       # przebuduj obraz i odtworz kontener
curl http://localhost:8010/health              # -> {"status":"ok"}
docker logs --tail 20 webcon-pdf-splitter      # sanity check logow
```

Powrót do `main` (po testach albo po scaleniu gałęzi):

```bash
cd <katalog-repo>
git checkout main
git pull                           # aktualny main (z ewentualnie scalona zmiana)
cd splitter
docker compose up -d --build
curl http://localhost:8010/health
```

- Gałąź musi być wcześniej wypchnięta na GitHub (`git push`), inaczej
  `git checkout` nie znajdzie jej na serwerze.
- Serwer zostaje na wybranej gałęzi, dopóki go nie przełączysz z powrotem —
  kolejne `git pull` ciągną **tę** gałąź, nie `main`. Po scaleniu zmiany wróć
  serwer na `main`, żeby nie utknął na gałęzi roboczej.
- `.env` zostaje nietknięty — nie jest w repo, `git checkout` go nie rusza.
- Jak przy zwykłej aktualizacji: obraz budowany jest lokalnie z kodu, a zmiany
  wyłącznie w `splitter/` nie wymagają ponownego importu pluginu WEBCON.

### Bez Dockera

```powershell
cd splitter
pip install .
python -m uvicorn webcon_pdf_splitter.api:app --host 127.0.0.1 --port 8000
```

OCR wymaga wtedy binarki `tesseract` (z modelem `pol`) zainstalowanej w systemie;
bez niej OCR degraduje się (strony skanów traktowane jak puste), serwis działa dalej.

### Lokalny LLM (opcjonalny)

Wymagany lokalny serwer zgodny z OpenAI Chat Completions (Ollama/vLLM/LM Studio) —
splitter go nie uruchamia. Przykład (Ollama):

```bash
docker run -d --name ollama -p 11434:11434 ollama/ollama
docker exec ollama ollama pull llama3.1:8b
```

```
SPLITTER_LLM_ENABLED=true
SPLITTER_LLM_ENDPOINT=http://host.docker.internal:11434/v1
SPLITTER_LLM_MODEL=llama3.1:8b
SPLITTER_LLM_TIMEOUT_SECONDS=60
```

Dane stron idą tylko do wskazanego lokalnego endpointu. Błąd/timeout LLM nie
przerywa podziału. Treść promptu (system + user) podmienia się plikami na wolumenie
bez przebudowy obrazu — [`splitter/docs/llm-prompt.md`](splitter/docs/llm-prompt.md).

### Zalecenia produkcyjne

- HTTPS lub wydzielona/zaufana sieć między WEBCON a splitterem; token API zawsze ustawiony.
- Limit rozmiaru PDF na reverse proxy (`client_max_body_size`).
- Przy domyślnym `SPLITTER_LOG_PAGE_TEXT=true` logi zawierają **fragmenty treści
  dokumentów** (diagnostyka klasyfikacji) — traktuj `docker logs` jak dane wrażliwe
  (dostęp, retencja/rotacja) albo ustaw `SPLITTER_LOG_PAGE_TEXT=false`, by logować
  wyłącznie metadane i statusy.

## Testy

```powershell
cd splitter
python -m pytest tests/ -v     # hermetyczne, bez sieci
```

Testy z prawdziwym Tesseractem są oznaczone `skipif` (pomijane, gdy brak binarki,
np. dev Windows) — wykonują się w kontenerze:

```bash
cd splitter && docker compose build
docker run --rm -v "$PWD":/mnt/proj -e PYTHONPATH=/mnt/proj/src \
  webcon-pdf-splitter:latest bash -c "pip install -q pytest httpx && cd /mnt/proj && python -m pytest -q"
```

**Testowe PDF-y:**

- `scripts/make_scanned_bundle.py` — „skan" **bez warstwy tekstowej** (strony jako
  obrazy) do testu OCR; flagi `--z-nieznanym`, `--z-pusta`, `--z-separatorami`,
  `--z-dowodem`, `--dpi N`. Wymaga Pillow.

  Do weryfikacji wykrywania pustych stron:

  ```bash
  python scripts/make_scanned_bundle.py --z-separatorami --z-dowodem
  ```

  Daje paczkę z białymi kartkami między dokumentami (z artefaktami realnego
  skanu: czarna krawędź szyby, dziurki, kurz) oraz ze **skanem dowodu
  osobistego** — dużo atramentu, zero czytelnego tekstu. Pierwsze mają zniknąć,
  drugi **musi przetrwać**. Pomiary sprawdzisz w logu:
  `docker compose logs | Select-String "pokrycie atramentem"`.
- `scripts/make_test_documents.py` / `make_test_bundle.py` — paczki born-digital
  (z warstwą tekstową) i `wzorce_testowe.json` do pola `patterns`. Wymaga fpdf2.

Ręczny test na uruchomionym serwisie:

```powershell
curl.exe -s -X POST http://localhost:8010/api/split `
  -F "file=@test-data/skan_dokumenty_hr.pdf" `
  -F "patterns=<test-data/wzorce_testowe.json"
```

Bez wzorców: wszystko jako jeden „Nieznany typ dokumentu" z `requiresReview: true`
(poprawne — pusta lista wzorców). Z wzorcami: dokumenty rozdzielone wg nagłówków.

**Ewaluacja LLM:** `scripts/llm_eval.py` + przypadki w `scripts/eval_cases/`
uruchamia się ręcznie przeciw lokalnemu modelowi (poza pytest) do strojenia promptu.

## Struktura repozytorium

| Katalog | Zawartość |
|---|---|
| `splitter/` | Serwis Python/FastAPI + `Dockerfile`, `docker-compose.yml`, `.env.example`, testy, skrypty |
| `splitter/src/webcon_pdf_splitter/` | Kod serwisu (moduły opisane niżej) |
| `splitter/docs/llm-prompt.md` | Manual placeholderów promptu LLM |
| `webcon-action/` | Plugin C# (BPS 2026/2025 SDK, przełącznik `-Sdk`) + `package.ps1` budujący ZIP |
| `docs/superpowers/` | Historia projektowa: specyfikacje i plany (migawki dzienne, nie bieżąca dokumentacja) |

### Moduły serwisu (`splitter/src/webcon_pdf_splitter/`)

| Plik | Odpowiedzialność |
|---|---|
| `api.py` | Warstwa HTTP (FastAPI): zlecanie `/api/split` (202), status/wynik/kasowanie `/api/jobs/*`, `/health`, `/metrics`, `/api/pages/*`, `/api/merge`; lifespan (start/stop workerów, zamiatanie `work_dir`), autoryzacja Bearer, wczesna walidacja `patterns`, dekodowanie nazw plików RFC 2047 z klienta .NET, `run_job` (wykonanie zadania z kontekstem logu i metryk), konfiguracja logowania |
| `jobs.py` | Kolejka zadań: `Job`, `JobStore` (FIFO z limitem, deduplikacja po `element_id`, TTL wyników, `position`), `JobWorker` (wątek-demon; wyjątek zadania → `failed`, wątek żyje dalej) |
| `processing.py` | Rdzeń przetwarzania `process()` (PDF na dysku → `SplitResult`) — synchroniczny, wolny od FastAPI; budowa silnika OCR/LLM/detektora z ustawień, parsowanie `patterns` |
| `config.py` | `SplitterSettings` — wszystkie zmienne `SPLITTER_*` (pydantic-settings, czyta `.env`, nieznane wpisy ignoruje) |
| `metrics.py` | Metryki: kolektor per zadanie (contextvar; OCR/LLM raportują przez `add_*`, poza zadaniem no-op) + rejestr skumulowany od startu procesu dla `GET /metrics` |
| `contracts.py` | Modele Pydantic API: `PatternPayload` (wejście), `DetectedDocument`, `SplitResult`, `SubmitJobResponse`, `JobStatusResponse`, `PageOpResult` (wyjście) |
| `patterns.py` | `DocumentPattern` (typ, nagłówek, frazy, frazy wykluczające, waga, aktywność) + `InMemoryPatternRepository` zwracające tylko aktywne wzorce |
| `ocr.py` | Zdobycie tekstu stron: `PdfTextOcrEngine` (warstwa tekstowa), `TesseractPageOcr` (render pypdfium2 + pytesseract), kompozyt `TextLayerWithOcrFallback` (progi, „OCR nie niszczy danych", degradacja bez wywracania żądania), wspólny licznik `alnum_count` |
| `pdf_io.py` | Czyste operacje na PDF (bez klasyfikacji): `split_pdf` (cięcie wg wykrytych dokumentów, oryginalne strony), `remove_pages` / `extract_pages` / `merge_pdfs` dla akcji ręcznych, `parse_page_range` (zakresy `2-4,7`), `validate_pdf` |
| `classification/rules.py` | `RuleBasedClassifier` — punktacja wzorców (nagłówek/frazy/wykluczenia) na tekście znormalizowanym do ASCII; wyznacza pierwszą stronę i powinowactwo fraz |
| `classification/pipeline.py` | `ClassificationPipeline` — serce podziału: grupowanie stron w segmenty (reguła → powinowactwo → LLM → doklejenie / segment nieznany), bramka pustych stron, progi pewności, budowa `reviewReasons`, `warnings`, nazw plików i całego `SplitResult` |
| `classification/llm.py` | Fallback LLM: `OpenAiCompatibleLlmClassifier` (retry bez `response_format`, tolerancyjne parsowanie JSON, normalizacja pewności w procentach), strażnik spójności `find_inconsistencies`, model `LlmClassification`, `DisabledLlmClassifier` (LLM wyłączony) |
| `classification/prompts.py` | `PromptProvider` — wbudowane szablony system/user promptu, ładowanie nadpisań z plików (`SPLITTER_LLM_PROMPT_FILE` / `..._SYSTEM_PROMPT_FILE`), `build_context` wypełniający placeholdery |

### Testy (`splitter/tests/`)

| Plik | Zakres |
|---|---|
| `conftest.py` | Fixture izolujące ustawienia (env, `work_dir` → tmp) między testami + wspólny helper `split_and_wait` (zlecenie → odpytanie → odbiór wyniku) |
| `test_api.py` | Endpoint `/health` |
| `test_api_split.py` | `/api/split` end-to-end (przez kolejkę): token (brak/zły/dobry), pliki wynikowe w base64 |
| `test_api_jobs.py` | Endpointy zadań: 202+jobId, status bez base64, wynik, delete, 404/409/503+Retry-After, deduplikacja po elemencie, `failed` dla uszkodzonego PDF, `/health` w trakcie mielenia paczki, zamiatanie `work_dir` |
| `test_job_store.py` | `JobStore`: FIFO, `position`, limit kolejki, deduplikacja aktywnych zadań, TTL wyników, delete |
| `test_job_worker.py` | `JobWorker`: przejścia statusów, wyjątek zadania nie zabija wątku, sprzątanie pliku (także przy błędzie i przy nieusuwalnym pliku), stop |
| `test_processing.py` | Rdzeń `process()` bez warstwy HTTP: podział, wzorce z JSON, brak pola `metadata` |
| `test_api_pages.py` | `/api/pages/remove` / `extract` / `merge`: poprawne operacje, złe zakresy, nie-PDF, token, nazwy plików RFC 2047 z .NET |
| `test_split_patterns.py` | Pole `patterns` żądania: mapowanie na `DocumentPattern`, wartości domyślne, odrzucanie złego JSON/schematu, podział bez wzorców (wszystko „Nieznany typ dokumentu") |
| `test_config_logging.py` | Domyślne ustawienia (log level, OCR, logowanie tekstu stron), czytanie env, `configure_logging`, wybór silnika OCR wg `SPLITTER_OCR_ENABLED` |
| `test_page_text_logging.py` | Diagnostyczny log tekstu stron: fragment surowy + znormalizowany, limity długości, strona pusta, wyłączenie flagą |
| `test_contracts.py` | Serializacja modeli odpowiedzi |
| `test_metrics.py` | Rejestr metryk (`review_rate`), kolektor per żądanie, zliczanie stron OCR i wywołań LLM, endpoint `/metrics` (wartości po podziale, token) |
| `test_job_logging.py` | Prefiks `[job=<jobId>]` w logach przetwarzania (kontekst przenosi się do wątku roboczego) |
| `test_normalization.py` | Normalizacja ASCII (diakrytyki, `ł`→`l`, wielkość liter, kompresja spacji) po obu stronach porównania |
| `test_rule_classifier.py` | Punktacja reguł: nagłówek, frazy, frazy wykluczające, progi pierwszej strony i braku dopasowania |
| `test_repository_mapping.py` | Filtrowanie aktywnych wzorców w repozytorium |
| `test_pipeline.py` | Grupowanie stron: segmenty, kontynuacja po powinowactwie, doklejanie z `forced_review`, segmenty nieznane, bramka pustych stron, werdykty LLM w pipeline, `reviewReasons`/`warnings`/logi |
| `test_ocr.py` | Kompozyt OCR: próg uruchomienia, reguła „OCR nie niszczy danych", degradacja przy braku binarki; testy z realnym Tesseractem oznaczone `skipif` |
| `test_pdf_io.py` | `parse_page_range` (błędne zakresy, odwrócone, poza dokumentem), remove/extract/merge, cięcie `split_pdf` |
| `test_llm_classifier.py` | Klient LLM: wyciąganie JSON z płotów markdown, retry po HTTP 400, normalizacja procentów, werdykt bez typu, strażnik spójności |
| `test_llm_wiring.py` | `build_llm_classifier`: wybór `Disabled`/`OpenAiCompatible` wg ustawień (flaga, endpoint, model) |
| `test_prompts.py` | `PromptProvider`: szablony wbudowane vs z plików, placeholdery, `format_json` wstrzykiwany z kodu |

### Skrypty (`splitter/scripts/`)

| Plik | Rola |
|---|---|
| `make_test_documents.py` | Zestaw paczek born-digital pokrywających scenariusze pipeline'u (czysty podział, wtrącenie, obcy początek/ogon, paczka nieznana) + `wzorce_testowe.json` |
| `make_test_bundle.py` | Pojedyncza paczka testowa z kilkoma dokumentami HR (`--z-nieznanym`) |
| `make_scanned_bundle.py` | „Skan" bez warstwy tekstowej (strony jako obrazy, Pillow) do weryfikacji fallbacku OCR i wykrywania pustych stron (`--z-nieznanym`, `--z-pusta`, `--z-separatorami`, `--z-dowodem`, `--dpi`) |
| `llm_eval.py` | Ewaluacja promptu LLM na przypadkach z `scripts/eval_cases/` przeciw żywemu endpointowi (poza pytest); do strojenia promptu |

## Status i ograniczenia

**Działa i wdrożone:** OCR skanów (Tesseract), klasyfikacja regułowa ze słownika,
fallback LLM ze strażnikiem spójności, konfigurowalny prompt, bramka pustych stron,
diagnostyka `reviewReasons`, kolejka zadań (202 + `jobId` + odpytywanie — kilka
paczek naraz bez timeoutów). Serwis bez bazy danych; kolejka w pamięci procesu.

**Zaplanowane (backlog):**

- **Pętla uczenia z feedbacku** — LLM proponuje nowe typy/frazy w `reviewReasons`,
  ale nikt ich nie agreguje. Docelowo korekty operatora zbierane po stronie WEBCON
  (splitter zostaje bezstanowy).
- **Pola per typ** — próg auto-akceptacji per typ (jest na formularzu słownika,
  pipeline używa globalnego 0.90) i kierowanie typów do różnych obiegów (plugin ma
  jeden Target workflow).
- **Ciche doklejanie po powinowactwie fraz** — strona obcego dokumentu z generycznymi
  frazami bieżącego typu bywa uznana za kontynuację bez śladu; obejście: kompletny
  słownik + niegeneryczne frazy + frazy wykluczające.

**Świadomie poza zakresem:** wszywanie warstwy tekstowej (searchable) w pliki
wynikowe — przeszukiwalność skanów robi się po stronie WEBCON lub na skanerach.
