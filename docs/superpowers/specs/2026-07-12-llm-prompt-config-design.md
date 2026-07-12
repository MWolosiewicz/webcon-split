# Konfigurowalny prompt LLM + poprawa klasyfikacji — projekt

Data: 2026-07-12
Status: zaakceptowany przez użytkownika (brainstorming 2026-07-12)
Zakres: punkty 2 i 3 backlogu (poprawa promptu LLM, wyniesienie promptu do
konfiguracji) + dokumentacja placeholderów + skrypt ewaluacyjny.

## Cel

1. Prompt LLM (system + user) konfigurowalny plikami na wolumenie Dockera,
   z wbudowanym fallbackiem w kodzie — iteracja treści promptu bez
   przebudowy obrazu.
2. Lepsza klasyfikacja stron: model dostaje typ bieżącego dokumentu,
   werdykty wewnętrznie sprzeczne są odrzucane (degradowane do podpowiedzi
   dla operatora), a treść promptu adresuje znane patologie małych modeli.
3. Mierzalna weryfikacja: syntetyczny zestaw ewaluacyjny uruchamiany na
   LM Studio użytkownika, porównanie przed/po zmianie promptu.

## Zasada nadrzędna (feedback użytkownika 2026-07-12)

Żaden mechanizm podziału nie może opierać się na jednym paradygmacie
wyglądu nagłówka (np. "tytuł wielkimi literami"). Testy prowadzone są na
dokumentach syntetycznych; na realnych dokumentach tytuły mogą mieć różną
formę (pełna nazwa, kod/symbol formularza, nagłówek firmowy). Wskazówki
w prompcie muszą być wieloparadygmatowe i neutralne; strażnik spójności
nie dokłada żadnych heurystyk wyglądu strony — sprawdza wyłącznie logiczną
spójność odpowiedzi modelu.

## Sekcja 1: Mechanizm szablonów promptu

### Konfiguracja

Dwie nowe zmienne w `SplitterSettings` (`splitter/src/webcon_pdf_splitter/config.py`):

- `SPLITTER_LLM_PROMPT_FILE` — ścieżka do szablonu user promptu,
- `SPLITTER_LLM_SYSTEM_PROMPT_FILE` — ścieżka do szablonu system promptu.

Obie domyślnie puste = wbudowany prompt (finalna wersja z sekcji 3,
zapisana w kodzie jako fallback).

### Ładowanie (hot-reload)

- Plik czytany przy **każdym żądaniu** — edycja na wolumenie działa od
  następnego splitu, bez restartu kontenera.
- Przy starcie serwisu i przy każdej zmianie zawartości: log INFO
  ("prompt z pliku X, N znaków").
- Plik brakujący/nieczytelny mimo ustawionej zmiennej: WARNING + fallback
  na wbudowany prompt (split nie może się wywrócić przez literówkę
  w ścieżce).

### Placeholdery

Format `{nazwa}` (Python `str.format`). Nieznany placeholder w szablonie
(np. literówka `{aktualna_stron}`) = WARNING + fallback na wbudowany
prompt — literówka nie może wysadzić żądania.

| Placeholder | Zawartość |
|---|---|
| `{znane_typy}` | nazwy typów dokumentów ze słownika WEBCON (kolumna DocumentType źródła danych, przysyłane w polu `patterns` każdego żądania), deduplikowane i posortowane alfabetycznie, renderowane jako tablica JSON (cudzysłowy) |
| `{typ_biezacego_dokumentu}` | typ dokumentu, którego kontynuacją mogłaby być strona; `BRAK` gdy nie ma poprzednika (początek paczki / segment nieznany) |
| `{poprzednia_strona}` | tekst poprzedniej strony (obcięty do 2000 znaków) |
| `{aktualna_strona}` | tekst klasyfikowanej strony (obcięty do 4000 znaków) |
| `{nastepna_strona}` | tekst następnej strony (obcięty do 2000 znaków) |
| `{format_json}` | wymagany format odpowiedzi JSON — wstrzykiwany z kodu, żeby szablon nie mógł rozjechać się z walidacją Pydantic |

Placeholdery działają też w system prompcie.

`{znane_typy}` zawiera **tylko nazwy typów** — bez nagłówków, fraz, wag
i excludedPhrases. Frazy służą regułom; LLM ocenia stronę semantycznie.
Lista jest dynamiczna per żądanie i jest punktem odniesienia dla
`isKnownType` (identyczna pisownia).

### Dokumentacja i wdrożenie w Dockerze

- Nowy manual `splitter/docs/llm-prompt.md`: opis obu zmiennych, tabela
  placeholderów z opisami, wbudowany prompt jako przykład startowy, uwagi
  (hot-reload, fallback, obcinanie tekstów) oraz rozdział "Wdrożenie
  w Dockerze" krok po kroku:
  1. utwórz katalog `prompts/` obok `docker-compose.yml`,
  2. wrzuć `user-prompt.txt` / `system-prompt.txt` (można zacząć od kopii
     z `examples/prompts/`),
  3. w `.env` ustaw `SPLITTER_LLM_PROMPT_FILE=/app/prompts/user-prompt.txt`
     — ścieżka **z perspektywy kontenera**, nie hosta (wyraźnie zaznaczone),
  4. odkomentuj wolumen i raz odpal `docker compose up -d`; od tego
     momentu edycja plików działa bez restartu.
- `splitter/docker-compose.yml`: zakomentowana, gotowa do odkomentowania
  sekcja `volumes: - ./prompts:/app/prompts` z komentarzem odsyłającym
  do manuala.
- Przykładowe pliki: `splitter/examples/prompts/user-prompt.txt`
  i `system-prompt.txt` (zawartość = wbudowany prompt).
- Aktualizacja `docs/deployment/splitter-service.md` o wzmiankę i link.

## Sekcja 2: Pipeline — typ bieżącego dokumentu i strażnik spójności

### Typ bieżącego dokumentu

`LlmClassifier.classify_uncertain_page` dostaje nowy parametr
`current_document_type: str` (pusty string, gdy brak poprzednika).
Pipeline (`pipeline.py`, gałąź LLM) przekazuje `current.document_type`,
gdy `current is not None and current.known`. Prompt mówi modelowi wprost,
czego strona miałaby być kontynuacją.

### Strażnik spójności

Czysta funkcja w `llm.py`, wywoływana po sparsowaniu odpowiedzi.
Degraduje do "podpowiedzi dla operatora" (jak dzisiejsze werdykty
częściowe) werdykty wewnętrznie sprzeczne:

1. `isFirstPage=false` + `documentType` inny niż typ bieżącego dokumentu
   — kontynuacja czegoś innego niż bieżący dokument nie ma sensu.
2. `isFirstPage=false` + brak bieżącego dokumentu (pusty
   `current_document_type`) — nie ma czego kontynuować.
3. `isKnownType=true` + `documentType` spoza listy znanych typów —
   halucynacja znanego typu.

Zdegradowany werdykt nie decyduje o podziale, ale `documentType`,
`isFirstPage` i `suggestedNewPatterns` trafiają do `reviewReasons`
i logów z dopiskiem, że werdykt odrzucono jako niespójny (z konkretnym
powodem). Strażnik nie zawiera żadnych heurystyk wyglądu strony.

## Sekcja 3: Treść nowego promptu (wersja startowa)

Wbudowany fallback w kodzie i zawartość plików w `examples/prompts/`.
Konwencja bez polskich znaków diakrytycznych (jak dotychczas). Wersja
startowa — ostateczny kształt po ewaluacji z sekcji 4.

System prompt:

```
Jestes klasyfikatorem stron w paczkach zeskanowanych dokumentow HR.
Oceniasz jedna strone na raz. Odpowiadasz wylacznie jednym poprawnym
obiektem JSON, bez markdown i bez zadnego tekstu poza JSON.
```

User prompt (szkielet):

```
ZADANIE: Ustal, czy AKTUALNA_STRONA to pierwsza strona NOWEGO dokumentu,
czy KONTYNUACJA biezacego dokumentu typu "{typ_biezacego_dokumentu}".

WSKAZOWKI:
- Nowy dokument zwykle zaczyna sie od wyraznego tytulu lub naglowka.
  Tytul moze miec rozna forme: pelna nazwa dokumentu, kod lub symbol
  formularza, naglowek firmowy. NIE zakladaj, ze tytul musi byc
  wielkimi literami.
- Nowy dokument czesto dotyczy innej sprawy, innej osoby lub innej daty
  niz poprzednia strona.
- Kontynuacja zwykle: zaczyna sie w polowie zdania, listy lub tabeli;
  kontynuuje watek z POPRZEDNIA_STRONA; zawiera numeracje stron (np. 2/3).
- Sam fakt, ze strona zawiera slowa typowe dla dokumentow HR
  (np. "pracownik", "wynagrodzenie"), NIE oznacza kontynuacji.

ZASADY ODPOWIEDZI:
- Jesli isFirstPage=false, documentType MUSI byc rowny
  "{typ_biezacego_dokumentu}".
- isKnownType=true tylko wtedy, gdy documentType jest DOKLADNIE jedna
  z pozycji ZNANE_TYPY (uzyj identycznej pisowni).
- documentType nigdy nie moze byc null ani pusty. Jesli nie rozpoznajesz
  typu, opisz go wlasnymi slowami, ustaw isKnownType=false i obniz
  confidence.
- confidence to ulamek od 0.0 do 1.0, nie procent.

FORMAT ODPOWIEDZI: {format_json}

ZNANE_TYPY={znane_typy}
TYP_BIEZACEGO_DOKUMENTU={typ_biezacego_dokumentu}
POPRZEDNIA_STRONA={poprzednia_strona}
AKTUALNA_STRONA={aktualna_strona}
NASTEPNA_STRONA={nastepna_strona}
```

Kluczowe różnice względem obecnego promptu:

1. Typ bieżącego dokumentu podany wprost (współgra ze strażnikiem —
   prompt wymaga tego, co strażnik egzekwuje).
2. Wskazówki wieloparadygmatowe, jawny zakaz założenia
   "wielkie litery = tytuł".
3. Generyczne frazy HR nie dowodzą kontynuacji (klasa błędu
   "wniosek o okulary uznany za kontynuację świadectwa").
4. Jawne reguły przeciw znanym patologiom: null documentType (bielik),
   confidence w procentach, wymyślanie znanych typów.
5. Bez few-shot — qwen2.5-7b odpowiada ~13 s; przykłady dołożymy jako
   iterację (edycja pliku), jeśli ewaluacja pokaże, że wskazówki nie
   wystarczą.

## Sekcja 4: Skrypt ewaluacyjny

- `splitter/scripts/llm_eval.py` + przypadki `splitter/scripts/eval_cases/*.json`.
- Narzędzie deweloperskie uruchamiane ręcznie, **poza pytest** (wymaga
  żywego LM Studio, nie może blokować CI).

Format przypadku (jeden plik JSON na przypadek):

```json
{
  "id": "wniosek-po-swiadectwie",
  "opis": "Nowy wniosek z generycznymi frazami HR po swiadectwie pracy",
  "znane_typy": ["Swiadectwo pracy", "Umowa o prace"],
  "typ_biezacego_dokumentu": "Swiadectwo pracy",
  "poprzednia_strona": "...",
  "aktualna_strona": "...",
  "nastepna_strona": "...",
  "oczekiwane": { "isFirstPage": true, "isKnownType": false }
}
```

Zestaw startowy ~10–12 przypadków, różnorodność stylów:

- tytuł wielkimi literami / tytuł normalną pisownią / kod formularza
  w nagłówku (np. "KW-3/2026") / nagłówek firmowy,
- kontynuacje: środek zdania, ciąg tabeli, numeracja "2/3", kontynuacja
  bez żadnej frazy typu,
- pułapki: nowy dokument nieznanego typu z generycznymi frazami HR,
  strona z małą ilością tekstu, początek paczki (pusty typ bieżącego
  dokumentu).

Runner:

- woła `OpenAiCompatibleLlmClassifier` + strażnik spójności (ten sam kod
  co produkcja — mierzymy zachowanie pipeline'u, nie surowego modelu),
- CLI: `--endpoint` (domyślnie `http://192.168.1.147:1234/v1`), `--model`
  (domyślnie qwen2.5-7b), `--prompt-file` / `--system-prompt-file`
  (porównywanie wariantów szablonów), `--cases` (filtr po id),
  `--out wyniki.json`,
- wynik: tabela per przypadek (oczekiwane vs otrzymane, PASS/FAIL, czas
  odpowiedzi, powód odrzucenia przez strażnika) + podsumowanie (X/Y,
  średni czas).

Przebieg pracy po implementacji: baseline na obecnym prompcie → nowy
prompt → porównanie → decyzja o dalszych iteracjach (np. few-shot).

## Testy jednostkowe (pytest, bez LLM)

- ładowanie szablonów z plików + hot-reload,
- fallback przy brakującym/nieczytelnym pliku i nieznanym placeholderze,
- trzy reguły strażnika spójności (degradacja + treść powodu),
- przekazywanie `current_document_type` z pipeline'u,
- rendering `{znane_typy}` jako tablicy JSON i `BRAK` dla pustego typu.

## Poza zakresem

- OCR dla skanów (punkt 1 backlogu),
- pętla uczenia z feedbacku (punkt 4),
- progi/obiegi per typ (punkt 5),
- zmiany w gałęzi powinowactwa fraz (punkt 6) — tylko treść promptu
  adresuje generyczne frazy; sam mechanizm gałęzi bez zmian.
