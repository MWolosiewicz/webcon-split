# Splitter Service

Serwis działa jako wewnętrzne HTTP API. Zalecane uruchomienie: Docker.

## Zmienne środowiskowe

| Zmienna | Wymagana | Opis |
|---|---|---|
| `SPLITTER_DATABASE_CONNECTION_STRING` | tak (produkcyjnie) | ODBC do bazy `WebconPdfSplitter`; bez niej serwis działa na pustej liście wzorców (wszystko → "Nieznany typ dokumentu") |
| `SPLITTER_API_TOKEN` | zalecane | Wymusza `Authorization: Bearer <token>` na `/api/split` i `/api/feedback` |
| `SPLITTER_WORK_DIR` | nie | Katalog roboczy plików tymczasowych (w kontenerze: `/app/work`) |
| `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE` | nie (0.90) | Próg automatycznej akceptacji |
| `SPLITTER_MIN_REVIEW_CONFIDENCE` | nie (0.70) | Próg kierowania do weryfikacji |
| `SPLITTER_LLM_ENABLED` | nie (false) | Włącza fallback LLM (wymaga endpointu) |
| `SPLITTER_LLM_ENDPOINT`, `SPLITTER_LLM_MODEL` | nie | Lokalny endpoint zgodny z OpenAI Chat Completions (Ollama/vLLM) |

Przykładowy connection string (logowanie SQL):

```
Driver={ODBC Driver 18 for SQL Server};Server=SERWER_SQL;Database=WebconPdfSplitter;Uid=splitter_svc;Pwd=***;TrustServerCertificate=yes
```

## Uruchomienie w Dockerze (zalecane)

W katalogu `splitter/` utwórz plik `.env` ze zmiennymi jak wyżej
(jedna linia = jedna zmienna, bez cudzysłowów), następnie:

```powershell
cd splitter
docker compose up -d --build
curl http://localhost:8000/health    # -> {"status":"ok"}
```

- Obraz bazuje na `python:3.12-slim` i zawiera sterownik
  **ODBC Driver 18 for SQL Server** (ten sam identyfikator drivera co na
  Windows — connection string nie wymaga zmian).
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
