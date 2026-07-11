# Wzorce w zadaniu: plugin SDK czyta slownik i wysyla wzorce do splittera - Design

Zastepuje spec `2026-07-11-webcon-dictionary-patterns-design.md` (odczyt slownika
przez SQL po stronie splittera). Tamten wariant zostal wdrozony, a nastepnie
uznany za gorszy: mapowanie kolumn w `.env` splittera jest kruche miedzy
srodowiskami, a splitter nie powinien zagladac do bazy tresci WEBCON.

## Cel

Plugin SDK (akcja `SplitPdfAction`) odczytuje wzorce rozpoznawania ze slownika
WEBCON poprzez zrodlo danych zdefiniowane w Designer Studio i wysyla je razem
z plikiem PDF w `POST /api/split`. Splitter uzywa wzorcow z zadania i traci
wszelki dostep do bazy tresci WEBCON.

Priorytety:

- splitter bez dostepu do bazy tresci WEBCON (znika konto SQL read-only,
  GRANT SELECT i 9 zmiennych `SPLITTER_WEBCON_*`);
- mapowanie atrybutow slownika zyje w Designer Studio (zrodlo danych),
  migruje z eksportem procesu miedzy srodowiskami;
- konfiguracja akcji rozszerza sie o jedno pole (ID zrodla danych);
- kontrakt `/api/split` rozszerzony wstecznie zgodnie (pole opcjonalne);
- zasada "WEBCON wola splitter, splitter nie wola WEBCON-a" przywrocona.

## Zakres

W zakresie:

- plugin: nowe pole konfiguracyjne, odczyt zrodla danych przez SDK,
  budowa JSON wzorcow, dolaczenie pola `patterns` do multipart;
- splitter: opcjonalne pole formularza `patterns` w `/api/split`,
  parsowanie i walidacja, uzycie `InMemoryPatternRepository` per zadanie;
- splitter: usuniecie trybu SQL-slownika (`WebconDictionaryPatternRepository`,
  `split_phrases`, 9 ustawien `webcon_*`, powiazane testy);
- dokumentacja: zrodlo danych z szablonem SQL zamiast mapowania kolumn;
- testy splittera dla nowego pola; weryfikacja pluginu przez `dotnet build`.

Poza zakresem:

- tryb standalone splittera (tabele `document_type`/`document_pattern`,
  `seed.sql`, `SqlServerPatternRepository`) - zostaje bez zmian jako fallback,
  gdy zadanie nie zawiera wzorcow;
- tabele operacyjne `splitter_job`/`classification_feedback` i `/api/feedback` -
  bez zmian;
- automatyczna aktualizacja wzorcow z feedbacku - osobna iteracja;
- prog auto-akceptacji per typ - nadal wylacznie prog globalny.

## Rozwazane warianty

1. **Zrodlo danych WEBCON (wybrany)** - konfiguracja akcji trzyma jedno ID;
   zapytanie i mapowanie utrzymywane w Designer Studio; plugin zna tylko
   kontrakt nazw kolumn.
2. **SQL w pluginie + mapowanie w konfiguracji akcji** - odrzucony: wiele pol
   konfiguracyjnych, sztywne zapytanie w kodzie pluginu.
3. **ID atrybutow + automatyczne rozwiazywanie kolumn** - odrzucony: zalezy
   od wewnetrznych struktur konfiguracji BPS, najbardziej zlozony kod.

## Kontrakt `/api/split`

Nowe opcjonalne pole formularza multipart `patterns` - JSON, tablica obiektow:

```json
[
  {
    "documentType": "Umowa o prace",
    "header": "UMOWA O PRACE",
    "phrases": ["pracodawca", "pracownik"],
    "excludedPhrases": ["aneks"],
    "weight": 1.2
  }
]
```

Zasady:

- frazy jako tablice stringow (rozbicie po srednikach wykonuje plugin;
  konwencja srednikow nie wycieka do API);
- plugin wysyla wylacznie aktywne wzorce - pole `active` nie wystepuje;
- `weight` opcjonalne, domyslnie 1.0; `excludedPhrases` opcjonalne, domyslnie
  pusta lista;
- pole obecne -> splitter buduje `InMemoryPatternRepository` z przeslanych
  wzorcow dla tego zadania; pole nieobecne -> dotychczasowa fabryka
  (wlasny SQL -> in-memory);
- bledny JSON lub niezgodnosc ze schematem -> HTTP 400 z opisem bledu
  (job konczy sie statusem `failed`, komunikat w `technical_error`).

## Zrodlo danych w Designer Studio

Administrator definiuje zrodlo danych (zapytanie SQL po procesie slownikowym)
zwracajace kolumny o umownych nazwach:

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `DocumentType` | tekst | nazwa typu dokumentu |
| `Header` | tekst | naglowek wzorca |
| `Phrases` | tekst | frazy rozdzielane srednikami |
| `ExcludedPhrases` | tekst | frazy wykluczajace rozdzielane srednikami |
| `Weight` | liczba | waga wzorca (puste = 1.0) |

Zrodlo zwraca wylacznie aktywne wpisy (filtr aktywnosci typu i wzorca jest
czescia zapytania). Szablon zapytania (JOIN `WFElements` x `WFElementDetails`
z filtrami `WFD_IsDeleted = 0` i flagami aktywnosci) trafia do
`docs/deployment/webcon-dictionary.md` jako przyklad do wklejenia i
dostosowania nazw kolumn.

## Zmiany w pluginie (`webcon-action/`)

- `SplitPdfActionConfig`: nowe wymagane pole "Patterns data source ID"
  (ID zrodla danych; edytor dedykowany dla zrodel danych, jesli SDK 26.1.6.209
  go udostepnia, w przeciwnym razie pole tekstowe walidowane jak pozostale ID).
- `SplitPdfAction.RunAsync`: przed wywolaniem klienta wykonuje zrodlo danych
  przez SDK (`DataSourcesHelper` z `WebCon.WorkFlow.SDK.Tools.Data`; dokladna
  sygnatura do weryfikacji na pakiecie SDK podczas implementacji):
  - brak ktorejkolwiek wymaganej kolumny -> blad akcji z lista oczekiwanych
    kolumn;
  - wiersz z pustym `Header` -> pomijany;
  - puste `Weight` -> 1.0;
  - `Phrases`/`ExcludedPhrases` rozbijane po `;`, kazda fraza trimowana,
    puste pomijane;
  - blad wykonania zrodla -> `args.HasErrors = true` (zaden cichy fallback);
  - 0 wierszy -> akcja kontynuuje z pusta lista i dopisuje ostrzezenie do
    `args.LogMessage`.
- `SplitterContracts`: nowa klasa `PatternPayload` (DocumentType, Header,
  Phrases, ExcludedPhrases, Weight) serializowana Newtonsoft.Json
  z nazwami camelCase.
- `SplitterClient.SplitAsync`: nowy parametr `IReadOnlyList<PatternPayload>?
  patterns`; gdy niepusty, dolacza `StringContent` z JSON jako pole `patterns`.
- `version.txt` podbite; paczka przebudowana `package.ps1` i wymagajaca
  ponownej rejestracji w Designer Studio.

## Zmiany w splitterze (`splitter/`)

- `contracts.py`: model `PatternPayload` (pydantic, pola `documentType`,
  `header`, `phrases`, `excludedPhrases` domyslnie `[]`, `weight` domyslnie
  `1.0`).
- `api.py`: `patterns: str | None = Form(default=None)` w `/api/split`;
  gdy obecne - `json.loads` + walidacja lista `PatternPayload`
  (blad -> HTTP 400), konwersja na `DocumentPattern(active=True)`
  i `InMemoryPatternRepository`; gdy nieobecne - `build_pattern_repository`.
- `config.py`: usuniete pola `webcon_db_connection_string`,
  `webcon_dict_form_type_id` i 7 pol `webcon_dict_col_*`.
- `repository.py`: usuniete `WebconDictionaryPatternRepository`,
  `split_phrases`, `logger`, `_SQL_IDENTIFIER`; fabryka wraca do postaci:
  wlasny SQL -> in-memory.
- testy: usuniete `tests/test_webcon_dictionary.py` i webconowe testy fabryki;
  nowe testy API dla pola `patterns`.

## Obsluga bledow

- Plugin: blad zrodla danych lub brak kolumn -> uzytkownik widzi komunikat
  biznesowy, administrator pelny stack w logu (istniejacy wzorzec obslugi
  bledow akcji).
- Splitter: bledne `patterns` -> 400, job `failed` z opisem w
  `technical_error`; brak pola -> zachowanie identyczne jak przed zmiana.
- Pusta lista wzorcow (payload `[]` lub zrodlo bez wierszy) -> wszystkie
  strony "Nieznany typ dokumentu" (bez bledu) - jak dotychczas przy pustej
  liscie.

## Testy

- splitter (pytest, `TestClient`):
  - `/api/split` z poprawnym `patterns` -> klasyfikacja uzywa przeslanych
    wzorcow (strona z naglowkiem pasujacym do wzorca dostaje jego typ);
  - `patterns` z blednym JSON -> 400;
  - `patterns` ze zlym schematem (np. brak `header`) -> 400;
  - brak `patterns` -> fallback do fabryki (istniejace zachowanie);
  - domyslne `weight`/`excludedPhrases` w payloadzie;
- fabryka: istniejace testy SQL/in-memory pozostaja, webconowe usuniete;
- plugin: `dotnet build` bez bledow + reczna sciezka weryfikacji opisana
  w dokumentacji wdrozeniowej.

## Dokumentacja

- `docs/deployment/webcon-dictionary.md`: sekcje "Odczyt ID i nazw kolumn"
  i "Uprawnienia SQL" zastapione sekcja o zrodle danych (kontrakt kolumn,
  szablon SQL); proces slownikowy i dane startowe bez zmian.
- `docs/deployment/splitter-service.md`: usuniete wiersze `SPLITTER_WEBCON_*`
  i akapit o trybie slownika.
- `docs/deployment/webcon-configuration.md`: nowe pole konfiguracji akcji
  (ID zrodla danych) w tabeli konfiguracyjnej.
- `docs/deployment/sql-server.md`: sekcja "Tryb slownika WEBCON" zastapiona
  nota, ze wzorce przychodza z pluginu, a tabele wzorcow sa uzywane tylko
  standalone.
