# Usuwanie pustych stron z paczki - Design

> **Zmiana zachowania (wlaczona domyslnie):** od tej wersji puste strony NIE sa
> juz doklejane do dokumentu z wymuszona weryfikacja, tylko usuwane z wynikow.
> Steruje tym `SPLITTER_DROP_EMPTY_PAGES` (domyslnie `true`). Instalacja po
> upgrade zaczyna wycinac puste strony bez ustawiania czegokolwiek; zeby
> zachowac stare zachowanie (doklejanie + flaga), ustaw `false`.

## Cel

Puste strony w paczce (typowo rewersy skanow dupleks, strony rozdzielajace,
artefakty skanu) maja przestac trafiac do wynikowych dokumentow i przestac
wymuszac weryfikacje. Dzis pusta strona jest doklejana do biezacego
rozpoznanego dokumentu z `requiresReview: true` (patrz
`2026-07-11-unknown-pages-design.md`, sekcja "Rewizja: doklejanie z flaga") -
zasmieca plik wynikowy i generuje falszywa weryfikacje. Celem jest ciche,
audytowalne usuniecie takich stron w ramach istniejacego `/api/split`, bez
osobnego kroku i bez nowej akcji WEBCON.

Oryginalny zalacznik-paczka w WEBCON pozostaje nietkniety - usuniecie dotyczy
wylacznie generowanych plikow wynikowych, wiec jest odwracalne (zrodlo zawsze
mozna podzielic ponownie).

## Kluczowa decyzja: usuwanie w `/api/split` (Opcja A)

Rozwazane warianty umiejscowienia:

1. **Wewnatrz `/api/split` (wybrany)** - pusta strona nie otwiera i nie
   przedluza segmentu, nie trafia do zadnego pliku wynikowego. Detekcja
   korzysta z tekstu juz wyliczonego przez OCR (`alnum_count`), wiec narzut
   jest zerowy; przy wlaczonym LLM dodatkowo znika koszt wywolan LLM na
   blankach z szumem OCR. Zero nowych endpointow i akcji.
2. Osobny krok `/api/pages/remove-empty` przed podzialem - odrzucony:
   detekcja blankow na skanie wymaga renderu/OCR, co przy naiwnej realizacji
   OCR-uje strony z trescia dwa razy (krok czyszczacy + split). Ma sens tylko
   z tania bramka pikselowa - poza zakresem tej iteracji.
3. Tylko wykrywanie + reczne usuwanie (istniejaca `RemovePagesAction`) -
   odrzucony jako rozwiazanie docelowe: nie znosi falszywej weryfikacji ani
   nie czysci wynikow automatycznie.

## Definicja pustej strony

Wylacznie prog tekstowy (bez bramki pikselowej w tej iteracji):

    page_is_empty = alnum_count(text) <= SPLITTER_EMPTY_PAGE_MAX_ALNUM

gdzie `text` to tekst strony PO OCR (`ocr.extract_page_texts`). To OSOBNY prog
niz `SPLITTER_OCR_MIN_TEXT_CHARS`:

- `SPLITTER_OCR_MIN_TEXT_CHARS` (25) - "ponizej tylu znakow SPROBUJ OCR"
  (dac stronie druga szanse);
- `SPLITTER_EMPTY_PAGE_MAX_ALNUM` - "na tylu znakach PO OCR uznaj za pusta".

Prog pustosci trzymamy maly. Wartosc wysoka = ryzyko utraty stron ze skapa,
ale realna trescia (pojedynczy akapit, pieczatka z podpisem, krotki
zalacznik) - to swiadome ryzyko utraty danych i dlatego domyslna wartosc to
`0` (usuwane tylko strony faktycznie bez tekstu; wartosc > 0 lapie dodatkowo
szum OCR na blankach).

Bramka pikselowa (render w niskim DPI + pomiar udzialu atramentu, ktora
skracalaby rowniez czas OCR na skanach dupleks) jest celowo POZA zakresem -
patrz sekcja "Poza zakresem".

## Reguly grupowania - zmiana wylacznie galezi pustych stron

Dzisiejsza petla po stronach (`pipeline.py`) pozostaje bez zmian z jednym
wyjatkiem. Gdy `SPLITTER_DROP_EMPTY_PAGES=true` i strona jest pusta wg progu:

- strona NIE otwiera segmentu, NIE przedluza biezacego, NIE wymusza
  weryfikacji, NIE idzie do LLM;
- numer strony (numeracja oryginalnej paczki, 1-based) trafia na wewnetrzna
  liste `removed_pages`;
- `continue` - petla przechodzi do kolejnej strony, `current` zostaje otwarty
  bez zmian (pusta strona nie zamyka ani nie fragmentuje segmentu).

Gdy `SPLITTER_DROP_EMPTY_PAGES=false` - zachowanie identyczne jak dzis
(pusta strona doklejana do rozpoznanego dokumentu z `forced_review`,
badz wchodzi do serii nieznanej). Pelna wsteczna zgodnosc.

Rozdzial odpowiedzialnosci obu ustawien: `SPLITTER_EMPTY_PAGE_MAX_ALNUM`
definiuje POJECIE pustej strony globalnie (uzywane takze do pominiecia LLM
i do tekstu powodu weryfikacji), a `SPLITTER_DROP_EMPTY_PAGES` decyduje
wylacznie o AKCJI (usun vs doklej). Przy domyslnym progu `0` definicja jest
tozsama z dzisiejszym `== 0`, wiec `drop=false` daje 1:1 obecne zachowanie
niezaleznie od reszty konfiguracji.

Galaz stron NIEPUSTYCH, niedopasowanych zostaje bez zmian (dalej doklejanie
z `forced_review`). Zmieniamy wylacznie to, co dzieje sie z pusta strona.

Konsekwencje dla segmentow:

- pierwsza strona segmentu nigdy nie jest pusta (naglowek/tekst pierwszej
  strony ma `alnum > prog`), wiec segment ma zawsze >= 1 strone niepusta -
  NIE powstaja dokumenty 0-stronicowe;
- pusta strona ze SRODKA zakresu dokumentu (np. str. 6 w dokumencie 4-8)
  laduje na `removed_pages` i jest wycinana z pliku tego dokumentu;
- pusta strona MIEDZY dokumentami / na poczatku paczki (separator) jest
  "niczyja" - nie miesci sie w zadnym finalnym zakresie i tak nie zostalaby
  zapisana; raportujemy ja tylko na poziomie paczki.

## Wplyw na niezmiennik zakresow

Spec `2026-07-11-unknown-pages-design.md` deklaruje: "kazda strona paczki
nalezy do dokladnie jednego dokumentu - zakresy sa ciagle, bez dziur
i nakladek (suma zakresow = wszystkie strony)". Ta funkcja SWIADOMIE luzuje
ten niezmiennik:

- usuniete puste strony sa jedynymi dozwolonymi dziurami; nie naleza do
  zadnego pliku wynikowego;
- `SplitResult.pageCount` nadal rowna sie liczbie stron ORYGINALU
  (`len(page_texts)`) - opisuje wejscie, nie sume wynikow;
- `startPage`/`endPage` dokumentu nadal opisuja zakres w numeracji oryginalu;
  gdy w srodku zakresu byla pusta strona, plik wynikowy ma mniej stron niz
  `endPage - startPage + 1`. To jest wyjasniane w komentarzu dziecka
  (patrz "Raportowanie"), a nazwa pliku dalej niesie pelny zakres
  (`Typ_strony_004-008.pdf`) - swiadomy, drobny kompromis kosmetyczny.

## Raportowanie

Powierzchnie raportu (wszystkie wlaczone):

1. **Log zadania splittera** (zawsze): linia per usunieta strona, prefiks
   `[job=...]`, np. `Strona 6: pusta (0 znakow) - usunieta`.
2. **`SplitResult.warnings`** (poziom paczki): podsumowanie wszystkich
   usunietych stron, w tym separatorow, np.
   `Usunieto 2 puste strony: 6, 9 (z 20)`. Pole juz istnieje w kontrakcie
   i jest deserializowane po stronie C#.
3. **Log operacji WEBCON**: `SplitPdfAction` dopina `result.Warnings` do
   `args.LogMessage` (dzis je ignoruje) - operator widzi usuniete strony
   w logu operacji elementu-zrodla bez zagladania w docker logs.
4. **Komentarz dokumentu-dziecka** (per-dokument): puste strony ze SRODKA
   zakresu danego dokumentu trafiaja do `DetectedDocument.removedPages`;
   `SplitPdfAction` dopisuje je do komentarza TEGO dziecka, np.
   `usunieto puste strony: 6`. Reviewer od razu rozumie, czemu plik ma mniej
   stron niz sugeruje zakres w nazwie. Separatory miedzy dokumentami tu NIE
   trafiaja (sa niczyje - zostaja na poziomie paczki, pkt 2-3).

Usuniecie NIE ustawia `requiresReview` - caly sens funkcji to zniesienie
falszywej weryfikacji na blankach. Raport jest informacyjny, nieblokujacy.

## Konfiguracja

Nowe pola w `SplitterSettings` (`config.py`, wzorzec `SPLITTER_*`):

| Zmienna | Typ | Domyslnie | Znaczenie |
|---|---|---|---|
| `SPLITTER_DROP_EMPTY_PAGES` | bool | `true` | Usuwanie pustych stron zamiast doklejania z weryfikacja |
| `SPLITTER_EMPTY_PAGE_MAX_ALNUM` | int | `0` | Do ilu znakow alnum po OCR strona jest uznawana za pusta |

Oba progi wstrzykiwane do `ClassificationPipeline` przez konstruktor - tak
samo, jak juz sa wstrzykiwane `min_auto_accept_confidence` /
`min_review_confidence` (`pipeline.py`). Zero nowej mechaniki konfiguracji.

## Zakres zmian w kodzie

- `splitter/src/webcon_pdf_splitter/config.py`: pola `drop_empty_pages: bool
  = True` i `empty_page_max_alnum: int = 0`.
- `splitter/src/webcon_pdf_splitter/contracts.py`: `DetectedDocument` dostaje
  `removedPages: list[int] = Field(default_factory=list)` (puste strony ze
  srodka zakresu tego dokumentu, numeracja oryginalu).
- `splitter/src/webcon_pdf_splitter/classification/pipeline.py`:
  - konstruktor przyjmuje `drop_empty_pages` i `empty_page_max_alnum`;
  - `page_is_empty = alnum_count(text) <= self._empty_page_max_alnum`
    (zamiast `== 0`);
  - nowa galaz: `page_is_empty and drop_empty_pages` -> dopisz numer do
    `removed_pages`, zaloguj, `continue`;
  - przy `drop_empty_pages=false` zachowanie bez zmian;
  - przy budowie `DetectedDocument`: `removedPages = [p for p in removed_pages
    if seg.start_page <= p <= seg.end_page]`;
  - wpis podsumowujacy do `warnings` z pelna lista `removed_pages`.
- `splitter/src/webcon_pdf_splitter/pdf_io.py`: `split_pdf` pomija strony
  z `document.removedPages` przy zapisie kazdego dokumentu (skip po
  1-based numerze); zachowanie bez usuniec identyczne jak dzis.
- `splitter/src/webcon_pdf_splitter/api.py`: `_split` przekazuje
  `drop_empty_pages` i `empty_page_max_alnum` z ustawien do pipeline'u
  (`split_pdf` czyta `removedPages` z kazdego dokumentu - nie trzeba przekazywac
  osobnej listy).
- `webcon-action/SplitterContracts.cs`: `DetectedDocument` dostaje
  `public List<int> RemovedPages { get; set; } = new();` (Newtonsoft dopasuje
  camelCase `removedPages` case-insensitive, jak reszte pol).
- `webcon-action/SplitPdfAction.cs`:
  - `FormatDetectionComment`: gdy `detected.RemovedPages.Count > 0` -> dopisek
    `; usunieto puste strony: <lista>`;
  - `args.LogMessage`: dopina `result.Warnings` (poziom paczki).
- `README.md`: wiersze `SPLITTER_DROP_EMPTY_PAGES` i
  `SPLITTER_EMPTY_PAGE_MAX_ALNUM` w tabeli zmiennych; aktualizacja opisu
  obslugi pustych stron (dzis: doklejanie + review; nowe domyslne: usuwanie);
  wyrazna nota o zmianie zachowania po upgrade.

### Zgodnosc z dwiema liniami SDK WEBCON (2025 R2 / 2026 R1)

Plugin buduje sie z jednego `WebconPdfSplitterAction.csproj` (netstandard2.0);
linie SDK przelacza wlasciwosc MSBuild `BpsSdk` (`package.ps1 -Sdk 2025|2026`),
ktora wybiera `WEBCON.BPS.2025.SDK.Libraries` (25.2.x = R2) albo
`WEBCON.BPS.2026.SDK.Libraries` (26.1.x = R1). Zmiany C# tej funkcji dotykaja
wylacznie:

- `SplitterContracts.cs` -> nowe pole DTO `RemovedPages` (Newtonsoft, bez API
  SDK);
- `SplitPdfAction.cs` -> `args.LogMessage` (string) oraz
  `newDocument.Comment.AddCommentAsync(...)` - stabilne API obecne w obu
  liniach.

Zadnego kodu wersjonowanego (`#if`) nie trzeba - obie zmiany sa neutralne
wzgledem linii SDK. Weryfikacja przy wydaniu: `package.ps1 -Sdk 2025` ORAZ
`package.ps1 -Sdk 2026` buduja sie bez bledow i daja dwa ZIP-y (po jednym na
linie; `version.txt` podbija sie per uruchomienie). Pakiety SDK wymagaja
licencji, wiec kompilacja/pakowanie C# odbywa sie w srodowisku z dostepem do
tych pakietow (po stronie operatora); zmiany projektuje sie tak, by nie
wprowadzac nowej powierzchni API SDK i uniknac rozjazdu miedzy liniami.

## Poza zakresem

- **Bramka pikselowa** (render w niskim DPI + pomiar atramentu, pomijanie
  Tesseractu na wizualnie pustych stronach) - to jedyna dzwignia realnie
  skracajaca CZAS OCR na skanach dupleks; osobna iteracja, wlasne progi env
  (`SPLITTER_BLANK_INK_RATIO`, `SPLITTER_BLANK_DETECT_DPI`).
- Osobny endpoint / akcja WEBCON do czyszczenia paczki przed podzialem.
- Konfigurowalne progi per typ dokumentu / per obieg.
- Zmiana nazewnictwa plikow wynikowych, by odzwierciedlala faktyczna liczbe
  stron po usunieciach.

## Testy

Pipeline (jednostkowe, na tekstach stron, LLM jako stub):

- pusta strona w SRODKU rozpoznanego dokumentu (prog domyslny 0) -> usunieta,
  segment bez `forced_review`, `removedPages` zawiera jej numer, zakres
  `start-end` obejmuje ja, ale plik jej nie ma;
- pusta strona MIEDZY dokumentami (separator) -> usunieta, nie tworzy serii
  nieznanej, nie trafia do `removedPages` zadnego dziecka, jest w `warnings`;
- pusta strona na POCZATKU paczki -> usunieta, kolejne dokumenty bez
  przesuniecia numeracji zrodlowej;
- `SPLITTER_DROP_EMPTY_PAGES=false` -> stare zachowanie (doklejanie
  z `forced_review`, powod weryfikacji o stronie bez tekstu);
- `SPLITTER_EMPTY_PAGE_MAX_ALNUM=3` -> strona z 1-3 znakami szumu OCR uznana
  za pusta i usunieta;
- strona ze skapa, ale realna trescia powyzej progu -> NIE usunieta;
- pusta strona nie generuje wywolania LLM (licznik stuba = 0 na tej stronie);
- `warnings` zawiera podsumowanie z pelna lista usunietych stron;
- suma: zakresy pokrywaja wszystkie strony ORYGINALU z wyjatkiem tych na
  liscie usunietych (jedyne dozwolone dziury).

pdf_io (`test_pdf_io.py`):

- `split_pdf` z `document.removedPages` pomija te strony; liczba stron pliku
  = szerokosc zakresu minus usuniete; brak plikow 0-stronicowych;
- `split_pdf` bez usuniec (`removedPages=[]`) dziala identycznie jak dzis.

api (`test_api_split.py`):

- odpowiedz zawiera `warnings` z podsumowaniem usuniec; `pageCount` = liczba
  stron oryginalu (nie po usunieciu);
- `DetectedDocument.removedPages` w odpowiedzi dla dokumentu z pusta strona
  w srodku.

Kontrakty / regresja:

- istniejace testy przechodza bez zmian przy `drop_empty_pages=false`;
  testy zalozone na dzisiejszym doklejaniu pustych stron (jesli sa)
  aktualizowane do nowego domyslnego zachowania z jawna adnotacja, ze to
  celowa zmiana.
