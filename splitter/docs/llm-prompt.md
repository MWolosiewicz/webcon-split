# Konfiguracja promptu LLM

Prompt, ktorym splitter odpytuje lokalny LLM o strony nierozpoznane przez
reguly, mozna podmienic bez przebudowy obrazu. Sluza do tego dwa szablony:
user prompt (tresc zadania) i system prompt (rola modelu).

## Zmienne srodowiskowe

| Zmienna | Opis |
|---|---|
| `SPLITTER_LLM_PROMPT_FILE` | Sciezka do pliku szablonu user promptu |
| `SPLITTER_LLM_SYSTEM_PROMPT_FILE` | Sciezka do pliku szablonu system promptu |

Obie sa opcjonalne i domyslnie puste — wtedy dziala prompt wbudowany w kod
(identyczny z plikami w `examples/prompts/`).

## Placeholdery

W szablonach uzywasz placeholderow w formacie `{nazwa}`:

| Placeholder | Za co odpowiada |
|---|---|
| `{znane_typy}` | Nazwy typow dokumentow ze slownika WEBCON (kolumna DocumentType zrodla danych, przysylane w polu `patterns` kazdego zadania `/api/split`), bez duplikatow, posortowane alfabetycznie, jako tablica JSON, np. `["Aneks do umowy", "Umowa o prace"]`. Tylko nazwy — bez fraz i wag. Punkt odniesienia dla `isKnownType` |
| `{typ_biezacego_dokumentu}` | Typ dokumentu, ktorego kontynuacja moglaby byc oceniana strona; `BRAK`, gdy nie ma poprzednika (poczatek paczki albo segment nieznany) |
| `{poprzednia_strona}` | Tekst poprzedniej strony (obciety do 2000 znakow) |
| `{aktualna_strona}` | Tekst ocenianej strony (obciety do 4000 znakow) |
| `{nastepna_strona}` | Tekst nastepnej strony (obciety do 2000 znakow) |
| `{format_json}` | Wymagany format odpowiedzi JSON — wstrzykiwany z kodu, zeby szablon nie mogl rozjechac sie z walidacja odpowiedzi |

Placeholdery dzialaja w obu szablonach (w system prompcie zwykle przydaje
sie najwyzej `{znane_typy}`).

Zasady:

- Literalny nawias klamrowy w szablonie zapisuj podwojnie: `{{` i `}}`.
- Nieznany placeholder (np. literowka `{aktualna_stron}`) nie wywraca
  zadania: serwis loguje WARNING i uzywa wbudowanego promptu.
- Brakujacy/nieczytelny plik: WARNING + wbudowany prompt.

## Hot-reload

Pliki sa czytane przy kazdym zadaniu. Edycja pliku na wolumenie dziala od
nastepnego splitu — bez restartu kontenera. Kazda zmiana tresci jest
logowana na poziomie INFO ("Prompt user z pliku '...' (N znakow)").

## Wdrozenie w Dockerze

1. Obok `docker-compose.yml` utworz katalog `prompts/`.
2. Skopiuj do niego pliki startowe:
   `cp examples/prompts/user-prompt.txt examples/prompts/system-prompt.txt prompts/`
3. W `.env` dopisz sciezki **z perspektywy kontenera** (nie hosta!):

   ```
   SPLITTER_LLM_PROMPT_FILE=/app/prompts/user-prompt.txt
   SPLITTER_LLM_SYSTEM_PROMPT_FILE=/app/prompts/system-prompt.txt
   ```

4. W `docker-compose.yml` odkomentuj sekcje `volumes` montujaca
   `./prompts:/app/prompts`.
5. Raz uruchom `docker compose up -d`. Od tego momentu edycja plikow
   w `prompts/` dziala bez restartu.

## Iteracja tresci promptu

Do porownywania wariantow promptu sluzy skrypt ewaluacyjny
`scripts/llm_eval.py` (syntetyczne przypadki, wymaga zywego endpointu LLM):

```bash
python scripts/llm_eval.py --endpoint http://192.168.1.147:1234/v1 --model qwen2.5-7b-instruct-1m
python scripts/llm_eval.py --prompt-file prompts/user-prompt.txt   # wariant z pliku
```
