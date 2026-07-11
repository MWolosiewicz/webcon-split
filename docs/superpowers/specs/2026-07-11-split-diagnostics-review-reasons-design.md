# Diagnostyka dzielenia + powody weryfikacji na podobiegach

Data: 2026-07-11
Status: zatwierdzony

## Problem

1. Logi aplikacji splittera w Dockerze zawierają za mało informacji o przebiegu
   dzielenia dokumentów. Przyczyna techniczna: uvicorn nie konfiguruje root
   loggera Pythona, więc istniejące wywołania `logger.info(...)` w ogóle nie
   trafiają do `docker logs`. Dodatkowo pipeline klasyfikacji nie loguje
   decyzji per strona ani podsumowania wyniku.
2. Gdy wykryty dokument ma `requiresReview=true`, nigdzie nie jest zapisany
   powód — ani w logach, ani w odpowiedzi API, ani na podobiegu utworzonym
   w WEBCON. Operator nie wie, dlaczego dokument wymaga weryfikacji, i nie da
   się po tym raportować.

## Cel

- Pełna ścieżka decyzyjna dzielenia widoczna w `docker logs` na poziomie INFO.
- Powody weryfikacji dostępne w odpowiedzi API (`reviewReasons`) oraz
  zapisywane w atrybutach (polach formularza) podobiegów tworzonych przez
  akcję WEBCON, aby dało się je raportować i używać w regułach formularza.

## Zakres — splitter (serwis Python)

### 1. Konfiguracja logowania (bugfix)

- Nowe ustawienie `log_level: str = "INFO"` w `SplitterSettings`
  (env: `SPLITTER_LOG_LEVEL`).
- Przy starcie aplikacji w `api.py` wywołanie `logging.basicConfig(...)`
  z tym poziomem i formatem zawierającym timestamp, poziom i nazwę loggera.
  Konfiguracja nie może nadpisywać loggerów uvicorna (basicConfig konfiguruje
  tylko root — to wystarcza).

### 2. Pole `reviewReasons` w kontrakcie

- `DetectedDocument.reviewReasons: list[str]` (domyślnie pusta lista).
- Czytelne polskie komunikaty bez diakrytyków (spójnie z `warnings`):
  - niska pewność: `"pewnosc 0.55 ponizej progu auto-akceptacji 0.90"`
  - doklejona strona: `"strona 4 doklejona bez dopasowania do wzorca"`
    (jedna pozycja na każdą doklejoną stronę)
  - nieznany segment: `"nierozpoznany typ dokumentu (zadna regula nie pasowala)"`
- Lista pusta wtedy i tylko wtedy, gdy `requiresReview=false`.

### 3. Logi decyzji per strona (INFO)

Jedna linia na stronę w `ClassificationPipeline.split_pages`, opisująca którą
ścieżką strona została zaklasyfikowana:

- `Strona 3: pierwsza strona 'Umowa o prace' (regula, confidence 0.85, sygnaly: header_match:...)`
- `Strona 4: kontynuacja 'Umowa o prace' (dopasowanie fraz)`
- `Strona 5: LLM -> pierwsza strona 'Aneks' (confidence 0.80, reasonCodes: ...)` /
  `LLM -> kontynuacja 'Umowa o prace' (...)`
- `Strona 6: brak dopasowania -> doklejona do 'Umowa o prace', wymuszona weryfikacja`
- `Strona 7: brak dopasowania -> kontynuacja nieznanego segmentu` /
  `-> nowy nieznany segment`

### 4. Log podsumowania (INFO)

Po klasyfikacji:

- jedna linia na dokument:
  `Dokument 1: 'Umowa o prace', strony 1-3, confidence 0.85, weryfikacja: TAK (powody: ...)` /
  `weryfikacja: NIE`
- linia końcowa:
  `Podzial 'plik.pdf' zakonczony: N stron, M dokumentow, status=requires_review`

## Zakres — plugin WEBCON (akcja Split PDF)

### 5. Kontrakt C#

- `DetectedDocument.ReviewReasons: List<string>` w `SplitterContracts.cs`
  (deserializacja z JSON; brak pola w odpowiedzi = pusta lista, żeby stary
  serwis nie wywracał nowego pluginu).

### 6. Konfiguracja akcji — dwa nowe opcjonalne pola

W `SplitPdfActionConfig` (atrybut `ConfigEditableFormFieldID`, opcjonalne):

- `RequiresReviewFieldId` — „Pole: wymaga weryfikacji (tak/nie)"
- `ReviewReasonsFieldId` — „Pole: powody weryfikacji (tekst)"

Wartość pusta/0 = akcja pomija zapis danego pola (pełna kompatybilność
wsteczna z istniejącymi konfiguracjami).

### 7. Zapis do atrybutów podobiegu

Po `GetNewDocumentAsync`, przed `StartNewWorkFlowAsync`:

- pole „wymaga weryfikacji" — wartość logiczna `RequiresReview`,
- pole „powody weryfikacji" — `ReviewReasons` połączone znakami nowej linii
  (pusty tekst, gdy lista pusta).

### 8. Rozszerzony komentarz

Do istniejącego komentarza (`FormatDetectionComment`) dochodzą powody
weryfikacji, gdy `RequiresReview=true` — pełen kontekst pozostaje widoczny
w historii elementu niezależnie od konfiguracji pól.

### 9. Wersja

Podbicie wersji pluginu 1.0.5 → 1.0.6 (`version.txt`).

## Poza zakresem

- Strukturalne kody powodów (machine-readable) — YAGNI, nic ich dziś nie
  konsumuje programowo; czytelne stringi wystarczają.
- Zmiany w obiegu WEBCON (utworzenie pól formularza po stronie WEBCON to
  konfiguracja wdrożeniowa, nie kod).
- Logowanie treści stron (dane osobowe HR — do logów trafiają tylko decyzje,
  typy, confidence i sygnały, nigdy tekst strony).

## Testy

- pytest (pipeline): `reviewReasons` dla trzech przypadków — niska pewność,
  doklejona strona, nieznany segment; pusta lista przy auto-akceptacji.
- pytest (`caplog`): logi per strona i podsumowanie obecne na poziomie INFO.
- pytest (kontrakt/API): serializacja `reviewReasons` w odpowiedzi.
- plugin: `dotnet build` + wygenerowanie pakietu (`package.ps1`); weryfikacja
  ręczna na środowisku WEBCON (brak testów jednostkowych w projekcie pluginu).
