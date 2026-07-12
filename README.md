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
┌────────────────┐   akcja SDK    ┌──────────────────────┐
│  WEBCON BPS    │ ─────────────► │  PDF Splitter        │
│  2026.1        │  HTTP+token    │  (Python/FastAPI)    │
│                │  PDF + wzorce  │  Docker lub uvicorn  │
│  paczka skanu  │ ◄───────────── │  OCR + klasyfikacja  │
│  → dokumenty HR│  JSON + PDF-y  │  + podział PDF       │
└────────────────┘    (base64)    └──────────────────────┘
```

Trzy elementy:

- **Akcja `SplitPdfAction`** (plugin C#, BPS 2026 SDK, netstandard2.0) — pobiera
  PDF z paczki, czyta wzorce ze słownika przez źródło danych, woła splitter,
  tworzy elementy Dokument HR z wynikowymi plikami.
- **Serwis splittera** (Python/FastAPI) — jedyny komponent z logiką OCR i
  klasyfikacji; bezstanowe HTTP API.
- **Słownik typów** (proces słownikowy WEBCON) — nagłówek = typ, lista pozycji
  = wzorce; źródło danych mapuje go na pola żądania.

## Przepływ end-to-end

1. Na paczce skanu (jeden PDF jako załącznik) operator przechodzi ścieżką z akcją
   `SplitPdfAction`.
2. Akcja czyta aktywne wzorce ze słownika (źródło danych) i wysyła je razem z PDF
   w multipart `POST /api/split` (nagłówek `Authorization: Bearer` + `X-Webcon-Element-Id`).
3. Splitter dla **każdej strony** ustala tekst: warstwa tekstowa PDF, a gdy jej
   brak — OCR Tesseract (patrz [Zasady działania](#zasady-działania-splittera)).
4. Na tym tekście działa klasyfikacja: dopasowanie wzorców, wyznaczenie granic
   dokumentów, ewentualny fallback LLM dla stron niedopasowanych.
5. Splitter tnie oryginalny PDF na dokumenty i zwraca JSON: typ, zakres stron,
   pewność, powody weryfikacji, plik wynikowy (base64) i `jobId` (uuid korelacyjny).
6. Akcja tworzy element **Dokument HR** dla każdego wykrytego dokumentu (załącznik
   + komentarz + relacja do paczki); `requiresReview` i powody może zapisać w
   atrybutach elementu.

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
- **Omiń LLM (pusta strona)** — strona jest „pusta", gdy ma **zero** znaków
  alfanumerycznych, również po OCR (stała, nie env). Krótka, ale realna strona
  nie jest uznawana za pustą i idzie normalnie do LLM.

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

- **nagłówek** wzorca znaleziony w pierwszych ~1200 znakach → `+0.78 × waga`;
- każde trafienie **frazy** → `+min(0.18, liczba_trafień × 0.06)`;
- trafiona **fraza wykluczająca** → wzorzec całkowicie pomijany;
- pewność ograniczona do 0.99; **strona pierwsza dokumentu** przy pewności ≥ 0.70;
- gdy najlepszy wynik < 0.50 → „Nieznany typ dokumentu" (pewność 0.20).

Frazy trafione, ale bez nagłówka, tworzą „powinowactwo" typu (używane niżej).

### 3. Grupowanie stron

Dla kolejnych stron (każda należy do dokładnie jednego dokumentu):

1. **Nagłówek pasuje** (strona pierwsza) → nowy dokument.
2. **≥1 fraza typu bieżącego dokumentu** (powinowactwo) → kontynuacja bieżącego
   dokumentu (bez LLM).
3. **Strona pusta** (0 znaków, też po OCR) → **omija LLM**, doklejana do bieżącego
   dokumentu z wymuszonym `requiresReview` i powodem
   „strona N bez tekstu (rowniez po OCR) - dolaczona automatycznie".
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
(`forced_review`) **lub** pewność < `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE` (0.90).
`reviewReasons` (lista po polsku) zawiera m.in.: nierozpoznany typ, strona bez
tekstu, strona doklejona bez dopasowania (z pasującymi frazami innych typów i
propozycją LLM), odrzucony werdykt niespójny, pewność poniżej progu. `signals`
niosą ślad techniczny (`header_match:...`, `phrase_hits:N`, `glued_unknown_page:N`,
`llm:<kod>`). Status całości to `requires_review`, gdy choć jeden dokument wymaga
weryfikacji, inaczej `completed`.

### 6. Podział pliku

`split_pdf` kopiuje **oryginalne strony** źródłowego PDF do plików wynikowych
(bez ponownego kodowania, bez zmiany treści). Nazwa pliku:
`NNN_Typ_dokumentu_strony_SSS-EEE.pdf` (znaki `spacja / \ :` zamieniane na `_`).

## Konfiguracja serwisu

Wszystkie zmienne mają prefiks `SPLITTER_`. Ustawienia nieznane (np. po usunięciu
opcji) są ignorowane — nie wywracają startu. Szablon: [`splitter/.env.example`](splitter/.env.example).

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `SPLITTER_API_TOKEN` | (puste) | Wymusza `Authorization: Bearer <token>` na `/api/split`. Puste = brak autoryzacji |
| `SPLITTER_LOG_LEVEL` | `INFO` | Poziom logów w `docker logs`. Na INFO: decyzja klasyfikacji per strona + podsumowanie z powodami |
| `SPLITTER_WORK_DIR` | `/app/work` | Katalog plików tymczasowych (czyszczony po zadaniu) |
| `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE` | `0.90` | Poniżej → dokument dostaje `requiresReview` |
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

Plik `.env` jest czytany przy każdym żądaniu (zmiany bez restartu procesu; zmienna
środowiskowa procesu ma pierwszeństwo przed plikiem). **Zmiana `.env` w Dockerze:**
odtwórz kontener (`docker compose up -d`, w razie potrzeby `--force-recreate`) —
`docker compose restart` **nie** wczytuje `.env` na nowo. Zmiana `.env` nie wymaga
przebudowy obrazu (`--build`); rebuild jest potrzebny tylko przy zmianie kodu lub
Dockerfile.

## API splittera

| Endpoint | Opis |
|---|---|
| `GET /health` | Kontrola życia serwisu → `{"status":"ok"}` |
| `POST /api/split` | multipart: `file` (PDF) + `patterns` (JSON, opcjonalne) → `SplitResult` |

`/api/split` wymaga `Authorization: Bearer <SPLITTER_API_TOKEN>` (jeśli token
skonfigurowany) i przyjmuje nagłówek `X-Webcon-Element-Id` (trafia do logów —
korelacja z elementem paczki). Bez pola `patterns` serwis działa na pustej liście
wzorców (wszystko → „Nieznany typ dokumentu").

**Pole `patterns`** — lista obiektów: `documentType`, `header`, `phrases` (lista),
`excludedPhrases` (lista), `weight` (domyślnie 1.0).

**Odpowiedź `SplitResult`:** `sourceFileName`, `pageCount`, `status`
(`completed`/`requires_review`/`failed`), `warnings` (lista), `jobId` (uuid),
oraz `documents` — lista `DetectedDocument`:

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
| `signals` | ślad techniczny decyzji |
| `metadata` | zarezerwowane |

Błędy: `400` (PDF zaszyfrowany/uszkodzony, złe `patterns`, nie-PDF), `401` (zły token).

## Integracja z WEBCON

Środowisko docelowe: **WEBCON BPS 2026.1**. Akcja: `WebconPdfSplitterAction.SplitPdfAction`
(`CustomAction<SplitPdfActionConfig>`), zbudowana na `WEBCON.BPS.2026.SDK.Libraries`,
podpisana strong name. Wymaga licencji SDK.

### Rejestracja pluginu

1. `powershell -File webcon-action\package.ps1` → `webcon-action\Publish\WebconPdfSplitterAction-<wersja>.zip`
   (DLL pluginu + Newtonsoft.Json.dll + manifest; biblioteki SDK dostarcza host BPS).
   Skrypt sam podbija wersję; wersja jest też w logu operacji (`SplitPdfAction vX.Y.Z`).
2. Designer Studio → **Plugin packages** → **New package** → wskaż ZIP → **Verify plugins**.

### Konfiguracja akcji „SplitPdfAction"

| Pole | Wymagane | Opis / skąd wziąć |
|---|---|---|
| Splitter base URL | tak | Adres serwisu, np. `http://serwer:8010`. Osiągalny **z serwera WEBCON** (WorkflowService), nie z przeglądarki |
| Splitter API token | zalecane | Ta sama wartość co `SPLITTER_API_TOKEN` |
| Target workflow ID | tak | Obieg, w którym powstają elementy Dokument HR |
| Target document type ID | tak | Typ formularza elementów Dokument HR |
| Start path ID | tak | Ścieżka startowa obiegu Dokument HR |
| Patterns data source ID | tak | Źródło danych z aktywnymi wzorcami (kolumny niżej) |
| Timeout in seconds | nie (300) | Zwiększ dla dużych paczek z OCR |
| Requires review field ID | nie | Pole tak/nie na `requiresReview`; puste = pomijane |
| Review reasons field ID | nie | Pole tekstowe (wieloliniowe) na powody. Ustawione → powody tylko do pola; puste → do komentarza elementu (bez duplikacji) |

ID obiektów: Designer Studio → właściwości obiektu → ID (włącz „Pokaż identyfikatory
obiektów", jeśli niewidoczne).

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
  o niejednoznacznym pliku), status przetwarzania, liczba stron/dokumentów. Akcję
  podpina się na ścieżce przejścia na kroku z kompletem załączników.
- **Dokument HR** — element na każdy wykryty dokument: jeden PDF, komentarz
  `Type: <typ>; pages <od>-<do>; confidence <0.00-1.00>; requires review: <t/f>`,
  relacja do paczki (`ParentDocumentID`), opcjonalnie `requiresReview` i powody
  w polach formularza.

Akcja rozróżnia i raportuje błędy (użytkownik: komunikat biznesowy; administrator:
stack w logu): brak PDF, więcej niż jeden PDF, PDF zaszyfrowany/uszkodzony (400),
zły token (401), niedostępność/timeout. Oryginalny PDF nigdy nie jest modyfikowany
ani usuwany. `jobId` z odpowiedzi (uuid korelacyjny) trafia do logu operacji akcji.

## Wdrożenie

Topologia docelowa: kontener na **dedykowanym serwerze** (nie na serwerze WEBCON);
serwer WEBCON łączy się po HTTP z tokenem. Serwis bezstanowy, bez bazy.

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
- Logi nie zawierają treści dokumentów — tylko metadane i statusy.

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
  obrazy) do testu OCR; flagi `--z-nieznanym`, `--z-pusta`, `--dpi N`. Wymaga Pillow.
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
| `splitter/src/webcon_pdf_splitter/` | `api.py`, `ocr.py`, `config.py`, `contracts.py`, `patterns.py`, `pdf_io.py`, `classification/` (rules, llm, pipeline, prompts) |
| `splitter/docs/llm-prompt.md` | Manual placeholderów promptu LLM |
| `webcon-action/` | Plugin C# (BPS 2026 SDK) + `package.ps1` budujący ZIP |
| `docs/superpowers/` | Historia projektowa: specyfikacje i plany (migawki dzienne, nie bieżąca dokumentacja) |

## Status i ograniczenia

**Działa i wdrożone:** OCR skanów (Tesseract), klasyfikacja regułowa ze słownika,
fallback LLM ze strażnikiem spójności, konfigurowalny prompt, bramka pustych stron,
diagnostyka `reviewReasons`. Serwis bezstanowy, bez bazy danych.

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
