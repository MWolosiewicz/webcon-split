# Splitter Service

Serwis działa jako wewnętrzne HTTP API w kontenerze Docker.

Topologia docelowa: kontener na **dedykowanym serwerze** (nie na serwerze
WEBCON). Serwer WEBCON komunikuje się ze splitterem po HTTP z tokenem.
Serwis jest bezstanowy — nie potrzebuje bazy danych.

## Zmienne środowiskowe

| Zmienna | Wymagana | Opis |
|---|---|---|
| `SPLITTER_API_TOKEN` | zalecane | Wymusza `Authorization: Bearer <token>` na `/api/split` |
| `SPLITTER_WORK_DIR` | nie | Katalog roboczy plików tymczasowych (w kontenerze: `/app/work`) |
| `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE` | nie (0.90) | Próg automatycznej akceptacji |
| `SPLITTER_MIN_REVIEW_CONFIDENCE` | nie (0.70) | Próg kierowania do weryfikacji |
| `SPLITTER_LLM_ENABLED` | nie (false) | Włącza fallback LLM dla stron nierozpoznanych (wymaga endpointu i modelu) |
| `SPLITTER_LLM_TIMEOUT_SECONDS` | nie (30) | Limit czasu pojedynczego wywołania LLM |
| `SPLITTER_LLM_ENDPOINT`, `SPLITTER_LLM_MODEL` | nie | Lokalny endpoint zgodny z OpenAI Chat Completions (Ollama/vLLM) |
| `SPLITTER_LLM_PROMPT_FILE` | nie | Plik szablonu user promptu LLM (wolumen); pusty = prompt wbudowany. Patrz `splitter/docs/llm-prompt.md` |
| `SPLITTER_LLM_SYSTEM_PROMPT_FILE` | nie | Plik szablonu system promptu LLM (wolumen); pusty = prompt wbudowany |
| `SPLITTER_LOG_LEVEL` | nie (INFO) | Poziom logów aplikacji widocznych w `docker logs` (`DEBUG`/`INFO`/`WARNING`/`ERROR`); na INFO serwis loguje decyzję klasyfikacji dla każdej strony i podsumowanie podziału z powodami weryfikacji |

Wzorce rozpoznawania przychodzą w żądaniu z akcji WEBCON (pole `patterns`);
patrz `docs/deployment/webcon-dictionary.md`. Gdy żądanie nie zawiera wzorców,
serwis działa na pustej liście (wszystko → "Nieznany typ dokumentu").

## Wdrożenie docelowe: dedykowany serwer z Dockerem

1. Zainstaluj Docker Engine (Linux) lub Docker Desktop (Windows Server).
2. Skopiuj na serwer katalog `splitter/` (albo sklonuj repozytorium).
3. W `splitter/` utwórz plik `.env` ze zmiennymi jak wyżej
   (jedna linia = jedna zmienna, bez cudzysłowów).
4. Uruchom i sprawdź:

```bash
cd splitter
docker compose up -d --build
curl http://localhost:8010/health    # -> {"status":"ok"}
```

5. Otwórz na serwerze port 8010 dla ruchu z serwera WEBCON
   (mapowanie portu zmienisz w `docker-compose.yml`).
6. W konfiguracji akcji SDK ustaw `http://<adres-serwera>:8010`
   i ten sam token co `SPLITTER_API_TOKEN`.

- Obraz bazuje na `python:3.12-slim`.
- Kontener działa jako użytkownik nieuprzywilejowany, katalog roboczy
  `/app/work`, healthcheck co 30 s, `restart: unless-stopped`.
- Plik `.env` nie jest kopiowany do obrazu (`.dockerignore`) — compose
  wstrzykuje go w czasie startu.
- Aktualizacja: `docker compose up -d --build` (przebudowa + podmiana).
- Logi: `docker logs webcon-pdf-splitter`.

## Uruchomienie bez Dockera

```powershell
cd splitter
pip install .
python -m uvicorn webcon_pdf_splitter.api:app --host 127.0.0.1 --port 8000
```

Konfiguracja przez zmienne środowiskowe lub plik `splitter/.env`
(czytany przy każdym żądaniu — zmiany nie wymagają restartu; zmienna
procesu ma pierwszeństwo przed plikiem).

## Produkcja — zalecenia

- HTTPS lub wydzielona/zaufana sieć między serwerem WEBCON a splitterem;
- token API zawsze ustawiony;
- limity rozmiaru PDF egzekwowane na reverse proxy (np. `client_max_body_size`);
- logi nie zawierają treści dokumentów HR — tylko metadane i statusy;
- retencja plików tymczasowych: katalog roboczy jest czyszczony po każdym
  zadaniu (`TemporaryDirectory`).

## Lokalny LLM (opcjonalny)

Fallback LLM pomaga klasyfikować wyłącznie strony, których nie rozpoznały
reguły i powinowactwo fraz — wielostronicowe dokumenty ze znanymi frazami
nie generują żadnych wywołań. Bez LLM strona nierozpoznana jest doklejana
do bieżącego dokumentu, który dostaje wtedy wymuszoną flagę weryfikacji
(nigdy nie przejdzie auto-akceptacji); osobnym dokumentem "Nieznany typ
dokumentu" stają się tylko strony sprzed pierwszego rozpoznanego dokumentu.
Dopiero LLM potrafi rozdzielić obce wtrącenie w środku paczki na osobny
dokument — bez niego rozdziela je operator przy weryfikacji.

Wymagany jest lokalny serwer zgodny z OpenAI Chat Completions — splitter go
nie uruchamia. Przykład (Ollama jako kontener na tym samym hoście):

```bash
docker run -d --name ollama -p 11434:11434 ollama/ollama
docker exec ollama ollama pull llama3.1:8b
```

Konfiguracja w `.env` splittera:

```
SPLITTER_LLM_ENABLED=true
SPLITTER_LLM_ENDPOINT=http://host.docker.internal:11434/v1
SPLITTER_LLM_MODEL=llama3.1:8b
SPLITTER_LLM_TIMEOUT_SECONDS=60
```

Dane stron nie opuszczają infrastruktury — żądania idą tylko do wskazanego
lokalnego endpointu. Błąd lub timeout LLM nie przerywa podziału: strona
pozostaje "Nieznany typ dokumentu".

Treść promptu (system + user) można podmienić plikami na wolumenie bez
przebudowy obrazu — instrukcja krok po kroku i lista placeholderów:
`splitter/docs/llm-prompt.md`.
