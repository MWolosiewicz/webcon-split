# Logowanie wynikow OCR / warstwy tekstowej — projekt

Data: 2026-07-21
Status: zaakceptowany

## Problem

W docker logs splittera nie widac, jaki tekst zostal odczytany ze stron
(warstwa tekstowa lub OCR). Log OCR mowi tylko, ile stron uzupelniono,
a pipeline loguje decyzje klasyfikacji bez tekstu, ktory klasyfikator
faktycznie widzial. Gdy klasyfikacja sie myli (dokumenty nie sa
rozdzielane), nie da sie stwierdzic, czy winny jest OCR (zly odczyt),
czy slownik (zly naglowek/frazy).

Kontekst dopasowania: naglowek ze slownika szukany jest w pierwszych
1200 znakach tekstu strony PO normalizacji (ASCII, wielkie litery,
pojedyncze spacje); frazy szukane sa w calym znormalizowanym tekscie.

## Wymagania (ustalone z uzytkownikiem)

- Miejsce: wylacznie docker logs splittera (nie log akcji WEBCON).
- Zakres per strona: surowy tekst do 1200 znakow + znormalizowany tekst
  do 300 znakow.
- Dlugosci konfigurowalne w `.env`.
- Domyslnie wlaczone (poziom INFO), wylaczalne flaga.

## Rozwiazanie (podejscie A — blok diagnostyczny w api.py)

### 1. Konfiguracja (`config.py`, `.env.example`)

Nowe pola `SplitterSettings`:

| Zmienna | Domyslnie | Znaczenie |
|---|---|---|
| `SPLITTER_LOG_PAGE_TEXT` | `true` | wlacza logowanie tekstu stron |
| `SPLITTER_LOG_PAGE_TEXT_RAW_CHARS` | `1200` | limit surowego fragmentu |
| `SPLITTER_LOG_PAGE_TEXT_NORM_CHARS` | `300` | limit znormalizowanego fragmentu |

### 2. Normalizacja jako funkcja publiczna (`rules.py`)

`RuleBasedClassifier._normalize` wypromowana do modulowej funkcji
`normalize_text(value)`; klasyfikator z niej korzysta. Log pokazuje
tekst w identycznej postaci, w jakiej przeszukuje go klasyfikator.

### 3. Blok diagnostyczny (`api.py`)

Funkcja `_log_page_texts(page_texts, settings)` wywolywana w `_split`
po `ocr.extract_page_texts(...)`, przed klasyfikacja. Per strona jeden
wpis INFO:

```
Strona 2: 1543 znaki | surowy(1200): "Faktura VAT nr 12/2026 ..." | znorm(300): "FAKTURA VAT NR 12/2026 ..."
```

- lamania linii i wielokrotne spacje w surowym fragmencie zbite do
  pojedynczej spacji (jeden wpis = jedna linia logu),
- obciety tekst konczy sie `...`,
- pusta strona: `Strona 5: 0 znakow (pusta)`,
- gate: `settings.log_page_text`.

### 4. Zrodlo tekstu — domkniecie w `ocr.py`

`TextLayerWithOcrFallback` loguje dzis strony uzupelnione przez OCR
("OCR: uzupelniono...") oraz bledy OCR (warning). Dokladany brakujacy
przypadek: OCR uruchomil sie, ale nie poprawil strony (zwrocil nie
wiecej tresci niz warstwa) — wpis INFO `OCR nie poprawil stron: [...]`.
Z logu zawsze wynika, skad pochodzi tekst kazdej strony.

### 5. Testy

- unit `_log_page_texts` z `caplog`: obecnosc wpisow, limity dlugosci,
  pusta strona, wylaczenie flaga,
- domyslne wartosci nowych ustawien (rozszerzenie
  `test_config_logging.py`),
- wpis "OCR nie poprawil stron" w `test_ocr.py`.

## Poza zakresem

- Brak zmian w API `/api/split`, kontraktach i akcji WEBCON.
- Brak zmian w logice klasyfikacji i OCR (tylko logowanie).
- Log akcji WEBCON bez zmian.

## Odrzucone alternatywy

- **B: logowanie rozproszone po warstwach** (silniki OCR + pipeline) —
  duplikacja w dwoch klasach silnikow, wstrzykiwanie parametrow logow
  do konstruktorow, dluzsze wpisy klasyfikacji.
- **C: wzbogacony typ zwrotny `PageText(text, source)`** — najczystszy
  przeplyw danych, ale zmiana protokolu `OcrEngine` rozlewa sie na
  pipeline, api i testy; nadmiar wobec potrzeby diagnostycznej. Do
  rozwazenia, gdy zrodlo strony bedzie potrzebne w danych (petla
  uczenia z feedbacku), nie tylko w logu.
