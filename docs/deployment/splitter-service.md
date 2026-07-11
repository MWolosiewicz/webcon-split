# Splitter Service

Serwis działa jako wewnętrzne HTTP API w kontenerze Docker.

Topologia docelowa: kontener na **dedykowanym serwerze** (nie na serwerze
WEBCON). Serwer WEBCON komunikuje się ze splitterem po HTTP z tokenem;
splitter łączy się bezpośrednio z SQL Serverem.

## Zmienne środowiskowe

| Zmienna | Wymagana | Opis |
|---|---|---|
| `SPLITTER_DATABASE_CONNECTION_STRING` | tak (produkcyjnie) | ODBC do bazy `WebconPdfSplitter`; bez niej serwis działa na pustej liście wzorców (wszystko → "Nieznany typ dokumentu") |
| `SPLITTER_WEBCON_DB_CONNECTION_STRING` | dla trybu słownika WEBCON | ODBC do bazy treści WEBCON (konto tylko-odczyt); razem z ID typu formularza włącza odczyt wzorców ze słownika WEBCON zamiast tabel własnych |
| `SPLITTER_WEBCON_DICT_FORM_TYPE_ID` | dla trybu słownika WEBCON | ID typu formularza procesu słownikowego (`WFD_DTYPEID`) |
| `SPLITTER_WEBCON_DICT_COL_TYPE_NAME` | dla trybu słownika WEBCON | kolumna nagłówka z nazwą typu, np. `WFD_AttText1` |
| `SPLITTER_WEBCON_DICT_COL_TYPE_ACTIVE` | dla trybu słownika WEBCON | kolumna nagłówka z flagą aktywności typu, np. `WFD_AttBool1` |
| `SPLITTER_WEBCON_DICT_COL_PATTERN_HEADER` | dla trybu słownika WEBCON | kolumna listy pozycji z nagłówkiem wzorca, np. `DET_Att1` |
| `SPLITTER_WEBCON_DICT_COL_PATTERN_PHRASES` | dla trybu słownika WEBCON | kolumna listy pozycji z frazami (średniki), np. `DET_Att2` |
| `SPLITTER_WEBCON_DICT_COL_PATTERN_EXCLUDED` | dla trybu słownika WEBCON | kolumna listy pozycji z frazami wykluczającymi, np. `DET_Att3` |
| `SPLITTER_WEBCON_DICT_COL_PATTERN_WEIGHT` | dla trybu słownika WEBCON | kolumna listy pozycji z wagą, np. `DET_Value1` |
| `SPLITTER_WEBCON_DICT_COL_PATTERN_ACTIVE` | dla trybu słownika WEBCON | kolumna listy pozycji z flagą aktywności wzorca, np. `DET_Bool1` |
| `SPLITTER_API_TOKEN` | zalecane | Wymusza `Authorization: Bearer <token>` na `/api/split` i `/api/feedback` |
| `SPLITTER_WORK_DIR` | nie | Katalog roboczy plików tymczasowych (w kontenerze: `/app/work`) |
| `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE` | nie (0.90) | Próg automatycznej akceptacji |
| `SPLITTER_MIN_REVIEW_CONFIDENCE` | nie (0.70) | Próg kierowania do weryfikacji |
| `SPLITTER_LLM_ENABLED` | nie (false) | Włącza fallback LLM (wymaga endpointu) |
| `SPLITTER_LLM_ENDPOINT`, `SPLITTER_LLM_MODEL` | nie | Lokalny endpoint zgodny z OpenAI Chat Completions (Ollama/vLLM) |

Konfiguracja słownika WEBCON: patrz `docs/deployment/webcon-dictionary.md`.
Tryb słownika WEBCON ma pierwszeństwo przed `SPLITTER_DATABASE_CONNECTION_STRING`
przy odczycie wzorców; tabele własne pozostają używane dla jobów i feedbacku.

Przykładowy connection string (logowanie SQL):

```
Driver={ODBC Driver 18 for SQL Server};Server=SERWER_SQL;Database=WebconPdfSplitter;Uid=splitter_svc;Pwd=***;TrustServerCertificate=yes
```

## Wdrożenie docelowe: dedykowany serwer z Dockerem

1. Zainstaluj Docker Engine (Linux) lub Docker Desktop (Windows Server).
2. Skopiuj na serwer katalog `splitter/` (albo sklonuj repozytorium).
3. W `splitter/` utwórz plik `.env` ze zmiennymi jak wyżej
   (jedna linia = jedna zmienna, bez cudzysłowów) — connection string
   wskazuje bezpośrednio serwer SQL.
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

- Obraz bazuje na `python:3.12-slim` i zawiera sterownik
  **ODBC Driver 18 for SQL Server** (ten sam identyfikator drivera co na
  Windows — connection string nie wymaga zmian).
- Kontener działa jako użytkownik nieuprzywilejowany, katalog roboczy
  `/app/work`, healthcheck co 30 s, `restart: unless-stopped`.
- Plik `.env` nie jest kopiowany do obrazu (`.dockerignore`) — compose
  wstrzykuje go w czasie startu.
- Aktualizacja: `docker compose up -d --build` (przebudowa + podmiana).
- Logi: `docker logs webcon-pdf-splitter`.

### Topologia deweloperska: Docker na hoście, WEBCON/SQL na VM Hyper-V

Docker Desktop (WSL2) często nie ma trasy do podsieci Hyper-V Default Switch,
więc kontener nie połączy się z SQL Serverem na VM bezpośrednio. Kontener widzi
za to hosta (`host.docker.internal`), a host widzi VM — rozwiązaniem jest
lekki forwarder TCP na hoście:

```powershell
# okno 1 (zostaw uruchomione):
cd splitter
python scripts/sql_proxy.py          # nasłuch 14330 -> 172.19.180.146:1433

# okno 2:
docker compose up -d                 # kontener czyta .env.docker
```

Wariant deweloperski włącza się przez `docker-compose.override.yml`
(compose czyta go automatycznie; plik poza gitem), który podmienia
`env_file` na `.env.docker` — kopię `.env` z adresem serwera SQL
`host.docker.internal,14330`.

Ta topologia jest tylko deweloperska — na docelowym dedykowanym serwerze
kontener łączy się z SQL bezpośrednio (sekcja wyżej), bez proxy i bez
plików override. Uwaga: podsieć Default Switch zmienia się po restarcie
hosta — po reboocie sprawdź adresy (`Get-NetIPAddress`).

## Uruchomienie bez Dockera

```powershell
cd splitter
pip install .
python -m uvicorn webcon_pdf_splitter.api:app --host 127.0.0.1 --port 8000
```

Wymagany zainstalowany "ODBC Driver 18 for SQL Server" (msodbcsql.msi).
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
