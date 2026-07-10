# WEBCON PDF Splitter

System dzielenia zbiorczych skanów PDF (dokumenty HR) na osobne dokumenty
z automatycznym utworzeniem elementów w WEBCON BPS. Całość działa lokalnie —
żadne dane nie opuszczają infrastruktury firmy.

## Architektura

```
┌────────────────┐   akcja SDK    ┌──────────────────────┐    ODBC    ┌──────────────────┐
│  WEBCON BPS    │ ─────────────► │  PDF Splitter        │ ─────────► │  SQL Server      │
│  2026.1        │   HTTP+token   │  (Python/FastAPI)    │            │  WebconPdfSplitter│
│                │ ◄───────────── │  Docker lub uvicorn  │            │  (wzorce, joby,  │
│  paczka skanu  │  JSON + PDF-y  │  OCR + klasyfikacja  │            │   feedback)      │
│  → dokumenty HR│    (base64)    │  + podział PDF       │            └──────────────────┘
└────────────────┘                └──────────────────────┘
```

1. Akcja **SplitPdfAction** (plugin SDK) pobiera PDF z paczki skanu i wysyła do splittera.
2. Splitter czyta tekst stron, dopasowuje wzorce nagłówków z bazy, wyznacza granice
   dokumentów i tnie PDF.
3. Akcja tworzy element **Dokument HR** dla każdego wykrytego dokumentu (załącznik +
   komentarz z typem, stronami i pewnością), z relacją do paczki źródłowej.
4. Wyniki o niskiej pewności dostają `requiresReview = true`; korekty operatora
   trafiają przez `POST /api/feedback` do tabeli feedbacku (przyszłe uczenie wzorców).

## Struktura repozytorium

| Katalog | Zawartość |
|---|---|
| `splitter/` | Serwis Python/FastAPI + `Dockerfile`, `docker-compose.yml`, testy, skrypty |
| `splitter/src/webcon_pdf_splitter/db/` | `schema.sql` (DDL) i `seed.sql` (startowe typy i wzorce) |
| `webcon-action/` | Plugin C# (BPS 2026 SDK, netstandard2.0) + `package.ps1` budujący ZIP |
| `docs/deployment/` | Instrukcje wdrożenia: SQL Server, serwis, konfiguracja WEBCON |
| `docs/testing-guide.md` | Testowanie krok po kroku (poziomy 1–5) |
| `docs/superpowers/` | Specyfikacja projektowa i plan implementacji |

## Szybki start

### Serwis w Dockerze (zalecane)

```powershell
cd splitter
# utwórz .env (patrz docs/deployment/splitter-service.md), potem:
docker compose up -d --build
curl http://localhost:8000/health   # -> {"status":"ok"}
```

### Serwis bez Dockera

```powershell
cd splitter
pip install .[test]
python -m uvicorn webcon_pdf_splitter.api:app --host 127.0.0.1 --port 8000
```

### Baza danych

Na SQL Serverze obok baz WEBCON: `CREATE DATABASE WebconPdfSplitter;`,
potem `schema.sql` i `seed.sql` — szczegóły w
[docs/deployment/sql-server.md](docs/deployment/sql-server.md).

### Plugin WEBCON

```powershell
powershell -File webcon-action\package.ps1
# wynik: webcon-action\Publish\WebconPdfSplitterAction.zip
```

ZIP rejestruje się w Designer Studio (Plugin packages → New package → Verify plugins).
Opis pól konfiguracji akcji:
[docs/deployment/webcon-configuration.md](docs/deployment/webcon-configuration.md).

## API splittera

| Endpoint | Opis |
|---|---|
| `GET /health` | Kontrola życia serwisu |
| `POST /api/split` | multipart PDF → JSON z dokumentami (typ, strony, pewność, plik base64, `jobId`) |
| `POST /api/feedback` | Korekta operatora → `classification_feedback` |

Oba endpointy POST wymagają nagłówka `Authorization: Bearer <SPLITTER_API_TOKEN>`,
jeśli token jest skonfigurowany. Dodatkowo `/api/split` przyjmuje nagłówek
`X-Webcon-Element-Id` do korelacji zadania z elementem paczki.

## Testy

```powershell
cd splitter
python -m pytest tests/ -v     # hermetyczne, bez bazy i sieci
```

Pełny przewodnik testów (z testową paczką PDF): [docs/testing-guide.md](docs/testing-guide.md).

## Status projektu / ograniczenia MVP

- OCR: czytana jest warstwa tekstowa PDF (`PdfTextOcrEngine`); skany bitmapowe
  wymagają podłączenia Tesseracta za interfejsem `OcrEngine` (zaplanowane).
- LLM: interfejs `LlmClassifier` gotowy, domyślnie wyłączony (`SPLITTER_LLM_ENABLED=false`).
- Tryb pracy: synchroniczny; kontrakt odpowiedzi przygotowany pod przejście na asynchroniczny.
- Feedback operatora jest zapisywany, ale automatyczna aktualizacja wzorców
  na jego podstawie nie jest jeszcze zaimplementowana.
