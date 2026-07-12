# Ręczne akcje operatora: usuwanie stron, wycinanie do nowego formularza, sklejanie załączników

Data: 2026-07-12
Status: zatwierdzony projekt (do planu implementacji)

## Kontekst i problem

System automatycznie dzieli paczkę skanów na osobne dokumenty HR i oznacza
elementy wymagające weryfikacji. Gdy automat *sklei* dwa dokumenty w jeden
(np. do umowy o pracę doklejone zaświadczenie), operator dostaje sygnał
(zmieniony znacznik „do sprawdzenia"), ale **nie ma narzędzi, żeby ręcznie
rozdzielić plik**. Ta specyfikacja dodaje trzy ręczne akcje SDK dające
operatorowi kontrolę nad zawartością załączników PDF.

## Zakres

Trzy nowe akcje WEBCON (CustomAction) + trzy nowe endpointy w istniejącym
serwisie Python. Cała logika operacji na PDF trafia do serwisu (`pypdf`);
akcje C# pozostają cienkimi orkiestratorami — spójnie z obecną `SplitPdfAction`.

Poza zakresem: klasyfikacja wyciętych stron (świadomie pominięta — patrz niżej),
zmiana modelu wyboru dla sklejania, edycja zawartości stron.

## Decyzje projektowe (ustalone)

1. **Operacje na PDF w serwisie Python** (podejście A). Zero bibliotek PDF
   w pluginie; logika testowana istniejącym pytestem.
2. **Wybór źródła dla remove/extract — po kategorii załącznika.** Konfiguracja
   akcji wskazuje dozwolone kategorie załączników. Akcja wymaga **dokładnie
   jednego** PDF-a w tych kategoriach; przy 0 lub >1 → czytelny błąd.
3. **Los źródła — konfigurowalny per akcja.** Przełącznik „zachowaj oryginał /
   podmień w miejscu" (remove) oraz „usuń wycięte strony ze źródła" (extract).
4. **Wycięcie do nowego formularza tworzy element SUROWY** — bez klasyfikacji
   (bez OCR/LLM). Typ i weryfikację ustawia operator.
5. **Sklejanie — lista pozycji, wiersz = załącznik, kolejność wierszy =
   kolejność sklejania**, identyfikacja po ID załącznika. Wynik: nowy załącznik
   na bieżącym elemencie, źródła zostają.
6. **Wspólna baza konfiguracji połączenia** (URL/token/timeout) dla wszystkich
   czterech akcji, w tym migracja istniejącej `SplitPdfActionConfig`.

## Architektura

```
WEBCON (akcja C#)  --HTTP-->  serwis Python (FastAPI + pypdf)
  pobiera bajty załącznika       parsuje zakres, operuje na stronach
  operacje WEBCON na wyniku      zwraca PDF (base64) + metadane
```

### Serwis Python

**Format zakresu stron:** `parse_page_range(spec, page_count) -> list[int]`
- 1-based, inclusive, np. `"2-4,7,9-11"`.
- Waliduje: puste → błąd; wartość poza `[1, page_count]` → błąd; nieparsowalne →
  błąd. Zwraca listę indeksów w kolejności rosnącej (kolejność dokumentu),
  bez duplikatów.
- Jedno źródło prawdy; walidacja po stronie serwisu, żeby komunikaty błędów
  były spójne i przetestowane.

**Nowe funkcje w `pdf_io.py`:**
- `remove_pages(source_path, pages) -> Path` — zwraca PDF bez wskazanych stron,
  pozostałe w oryginalnej kolejności. Usunięcie wszystkich stron → błąd.
- `extract_pages(source_path, pages) -> Path` — PDF tylko ze wskazanymi stronami
  w kolejności dokumentu.
- `merge_pdfs(paths_in_order) -> Path` — skleja PDF-y w podanej kolejności.
  Pusta lista → błąd.

**Nowe endpointy** (auth Bearer jak `/api/split`):

| Endpoint | Wejście (multipart) | Wyjście |
|---|---|---|
| `POST /api/pages/remove`  | `file`, `pages` | PDF bez tych stron |
| `POST /api/pages/extract` | `file`, `pages` | PDF tylko z tymi stronami |
| `POST /api/merge`         | wiele `files` w kolejności | jeden sklejony PDF |

**Wspólny kontrakt odpowiedzi** (`PageOpResult`):
```json
{ "outputFileName": "...", "pageCount": 0, "fileContentBase64": "...", "warnings": [] }
```
Błędy walidacji (zły zakres, pusty wynik, PDF zaszyfrowany) → HTTP 400
z czytelnym komunikatem, który akcja pokazuje operatorowi.

### Akcje C#

Nazwy klas po angielsku, `DisplayName`/`Description` po polsku (jak obecnie).

**Wspólna baza konfiguracji** `SplitterConnectionConfig : PluginConfiguration`
z polami `SplitterBaseUrl`, `ApiToken`, `TimeoutSeconds`. Dziedziczą po niej
wszystkie cztery configi (w tym zmigrowana `SplitPdfActionConfig`).

**Wspólny helper wyboru źródła** — po `GetAttachmentsAsync` filtruje po
dozwolonych kategoriach + rozszerzeniu `pdf`; wymaga dokładnie jednego, inaczej
`InvalidOperationException` z jasnym komunikatem.

#### `RemovePagesAction` + `RemovePagesActionConfig`
- Config: baza + `AllowedCategories` (kategorie załączników), `PageRange`
  (tekst → zakres), `ReplaceInPlace` (bool).
- Flow: wybierz źródło wg kategorii → `GetContentAsync` → `/api/pages/remove` →
  jeśli `ReplaceInPlace`: nadpisz zawartość załącznika; inaczej dodaj nowy
  załącznik (z sufiksem w nazwie).

#### `ExtractPagesToNewFormAction` + config
- Config: baza + `AllowedCategories`, `PageRange`, `TargetWorkflowId`,
  `TargetDocTypeId`, `StartPathId`, `RemoveFromSource` (bool).
- Flow: wybierz źródło → `/api/pages/extract` → utwórz **surowy** element
  potomny w obiegu docelowym → wepnij wycięty PDF → wystartuj ścieżkę →
  jeśli `RemoveFromSource`: wykonaj remove na źródle i zapisz (nadpisz).

#### `MergeAttachmentsAction` + config
- Config: baza + `ItemListId`, `AttachmentIdColumnId`, `OutputFileName`.
- Flow: czytaj wiersze listy pozycji **w kolejności** → dla każdego wiersza
  pobierz ID załącznika → `GetContentAsync` → wyślij wszystkie do `/api/merge`
  w tej kolejności → dodaj sklejony PDF jako nowy załącznik do bieżącego
  elementu (źródła nietknięte).

**`SplitterClient`** dostaje `RemovePagesAsync`, `ExtractPagesAsync`,
`MergeAsync`; wspólna logika nagłówka auth i deserializacji wydzielona.

## Obsługa błędów

Wzorzec ze `SplitPdfAction`: `try/catch`, `args.HasErrors = true`,
`args.Message` = przyjazny operatorowi, `args.LogMessage` = wersja pluginu +
pełny szczegół. Komunikaty walidacyjne z serwisu (HTTP 400) trafiają do
`args.Message`, żeby operator wiedział, co poprawić (np. „zakres 5-8 poza
dokumentem, który ma 6 stron").

## Testy

**Python (pytest):**
- `parse_page_range`: poprawne zakresy, pojedyncza strona, poza zakresem, puste,
  białe znaki, duplikaty, odwrócony zakres.
- `remove_pages`: poprawna liczba stron, zachowana kolejność, usunięcie
  wszystkiego → błąd.
- `extract_pages`: kolejność dokumentu, pojedyncza strona, zły zakres.
- `merge_pdfs`: suma stron, kolejność, jeden plik, pusta lista → błąd.
- Endpointy: FastAPI `TestClient` z tokenem; wejście niepoprawne → 400;
  brak/zły token → 401.

**C#:** akcje cienkie, logika po stronie Pythona; weryfikacja przez build +
import paczki. Walidacja konfiguracji (parsowanie ID) pokryta jak obecnie.

## Do weryfikacji na etapie planu

- **Nadpisanie zawartości istniejącego załącznika** w SDK WEBCON: czy istnieje
  metoda aktualizacji zawartości, czy „podmiana w miejscu" = delete + add nowy.
- **Kategoria załącznika w SDK:** właściwość na `AttachmentData` / parametr
  w `GetAttachmentsParams` do filtrowania; jak konfigurować wybór kategorii
  (`ConfigEditable...`) — lista nazw/ID.
- **Odczyt listy pozycji** (row group) i kolumny z ID załącznika w kolejności
  wierszy przez SDK.
```
