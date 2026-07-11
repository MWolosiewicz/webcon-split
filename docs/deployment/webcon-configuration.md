# WEBCON Configuration

Środowisko docelowe: WEBCON BPS 2026.1.

## Plugin SDK

Akcja jest zbudowana na `WEBCON.BPS.2026.SDK.Libraries` (26.1.6.209),
target .NET Standard 2.0, zestaw podpisany strong name
(`PublicKeyToken=f058138f2a0511b3`). Punkt wejścia:
`WebconPdfSplitterAction.SplitPdfAction : CustomAction<SplitPdfActionConfig>`.

### Budowanie i rejestracja paczki

1. `powershell -File webcon-action\package.ps1` — wynik:
   `webcon-action\Publish\WebconPdfSplitterAction.zip`
   (DLL pluginu + Newtonsoft.Json.dll + manifest; bibliotek WEBCON SDK
   celowo brak — dostarcza je host BPS).
2. Designer Studio → **Plugin packages** → **New package** → wskaż ZIP.
3. Kliknij **Verify plugins** — po pozytywnej weryfikacji akcja jest dostępna.
4. Wymagana licencja SDK.

## Konfiguracja akcji "SplitPdfAction"

Każde pole ma opis widoczny w Designer Studio; poniżej pełna ściąga.

| Pole | Wymagane | Opis | Skąd wziąć wartość |
|---|---|---|---|
| Splitter base URL | tak | Adres serwisu splittera, np. `http://serwer:8000` | Adres hosta/kontenera ze splitterem. Musi być osiągalny **z serwera WEBCON** (WorkflowService), nie z przeglądarki użytkownika |
| Splitter API token | zalecane | Wysyłany jako `Authorization: Bearer ...` | Ta sama wartość co `SPLITTER_API_TOKEN` w konfiguracji serwisu |
| Target workflow ID | tak | Obieg, w którym powstają elementy Dokument HR | Designer Studio → obieg docelowy → właściwości → ID (włącz "Pokaż identyfikatory obiektów", jeśli niewidoczne) |
| Target document type ID | tak | Typ formularza elementów Dokument HR | Designer Studio → typ formularza → właściwości → ID |
| Start path ID | tak | Ścieżka startowa obiegu Dokument HR (przejście z kroku startowego) | Designer Studio → krok startowy obiegu docelowego → ścieżka → właściwości → ID |
| Patterns data source ID | tak | Źródło danych zwracające aktywne wzorce (kolumny: DocumentType, Header, Phrases, ExcludedPhrases, Weight) | Designer Studio → Źródła danych → właściwości → ID; szablon zapytania w `docs/deployment/webcon-dictionary.md` |
| Timeout in seconds | nie (300) | Maksymalny czas oczekiwania na splitter | Zwiększ dla dużych paczek z OCR |
| Requires review field ID | nie | Pole tak/nie w obiegu Dokument HR, w które akcja zapisuje `requiresReview` splittera | Designer Studio → atrybuty obiegu docelowego → właściwości pola → ID; puste = pomijane |
| Review reasons field ID | nie | Pole tekstowe (wieloliniowe) w obiegu Dokument HR na powody weryfikacji (jeden na linię) | Designer Studio → atrybuty obiegu docelowego → właściwości pola → ID; puste = pomijane |

## Procesy

### Proces "Paczka skanu"

Atrybuty minimalne:

- oryginalny PDF jako załącznik (dokładnie jeden — więcej niż jeden PDF
  powoduje błąd akcji o niejednoznacznym pliku źródłowym);
- status przetwarzania (`Nowa paczka`, `W trakcie analizy`,
  `Podzielona automatycznie`, `Wymaga weryfikacji`, `Zakończona`, `Błąd przetwarzania`);
- liczba stron, liczba wykrytych dokumentów;
- odniesienie do logu technicznego (akcja loguje `jobId` splittera —
  koreluje z tabelą `dbo.splitter_job` w bazie `WebconPdfSplitter`).

Akcję "SplitPdfAction" podpinamy na ścieżce przejścia (np. "Podziel PDF")
na kroku, w którym paczka ma komplet załączników.

### Proces "Dokument HR"

Elementy tworzone przez akcję dostają:

- jeden wynikowy PDF jako załącznik;
- komentarz `Type: <typ>; pages <od>-<do>; confidence <0.00-1.00>; requires review: <true/false>`;
- relację do paczki źródłowej (`ParentDocumentID`).

Atrybuty warto odwzorować z komentarza w polach formularza (typ dokumentu,
zakres stron, pewność, status weryfikacji) — w kolejnej iteracji akcja może
wypełniać pola bezpośrednio po podaniu ich ID.

## Obsługa błędów

Akcja rozróżnia i raportuje (użytkownik widzi komunikat biznesowy,
administrator pełny stack w logu):

- brak załącznika PDF na paczce;
- więcej niż jeden PDF (niejednoznaczny plik źródłowy);
- PDF zaszyfrowany/uszkodzony (HTTP 400 od splittera);
- zły token (HTTP 401);
- niedostępność serwisu / timeout.

Oryginalny PDF nigdy nie jest modyfikowany ani usuwany.

## Feedback operatora

Pętla uczenia z korekt operatora jest zaplanowana, ale nie zaimplementowana.
Splitter nie ma endpointu feedbacku ani bazy danych — gdy pętla powstanie,
korekty będą zbierane po stronie WEBCON (np. w słowniku wzorców).
