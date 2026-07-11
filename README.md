# WEBCON PDF Splitter

System dzielenia zbiorczych skanów PDF (dokumenty HR) na osobne dokumenty
z automatycznym utworzeniem elementów w WEBCON BPS. Całość działa lokalnie —
żadne dane nie opuszczają infrastruktury firmy.

## Architektura

```
┌────────────────┐   akcja SDK    ┌──────────────────────┐
│  WEBCON BPS    │ ─────────────► │  PDF Splitter        │
│  2026.1        │  HTTP+token    │  (Python/FastAPI)    │
│                │  PDF + wzorce  │  Docker lub uvicorn  │
│  paczka skanu  │ ◄───────────── │  OCR + klasyfikacja  │
│  → dokumenty HR│  JSON + PDF-y  │  + podział PDF       │
└────────────────┘    (base64)    └──────────────────────┘
```

1. Akcja **SplitPdfAction** (plugin SDK) pobiera PDF z paczki skanu i wysyła do
   splittera razem z wzorcami rozpoznawania ze słownika WEBCON (źródło danych).
2. Splitter czyta tekst stron, dopasowuje wzorce nagłówków, wyznacza granice
   dokumentów i tnie PDF.
3. Akcja tworzy element **Dokument HR** dla każdego wykrytego dokumentu (załącznik +
   komentarz z typem, stronami i pewnością), z relacją do paczki źródłowej.
4. Wyniki o niskiej pewności dostają `requiresReview = true` wraz z listą powodów
   (`reviewReasons`); akcja może je zapisać w atrybutach elementu Dokument HR.

## Struktura repozytorium

| Katalog | Zawartość |
|---|---|
| `splitter/` | Serwis Python/FastAPI + `Dockerfile`, `docker-compose.yml`, testy, skrypty |
| `webcon-action/` | Plugin C# (BPS 2026 SDK, netstandard2.0) + `package.ps1` budujący ZIP |
| `docs/deployment/` | Instrukcje wdrożenia: serwis, konfiguracja WEBCON, słownik wzorców |
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

### Plugin WEBCON

```powershell
powershell -File webcon-action\package.ps1
# wynik: webcon-action\Publish\WebconPdfSplitterAction-<wersja>.zip
```

ZIP rejestruje się w Designer Studio (Plugin packages → New package → Verify plugins).
Opis pól konfiguracji akcji:
[docs/deployment/webcon-configuration.md](docs/deployment/webcon-configuration.md).

## API splittera

| Endpoint | Opis |
|---|---|
| `GET /health` | Kontrola życia serwisu |
| `POST /api/split` | multipart PDF + wzorce → JSON z dokumentami (typ, strony, pewność, powody weryfikacji, plik base64, `jobId`) |

`/api/split` wymaga nagłówka `Authorization: Bearer <SPLITTER_API_TOKEN>`,
jeśli token jest skonfigurowany. Dodatkowo przyjmuje nagłówek
`X-Webcon-Element-Id`, który trafia do logów serwisu (korelacja z elementem paczki).

## Testy

```powershell
cd splitter
python -m pytest tests/ -v     # hermetyczne, bez sieci
```

Pełny przewodnik testów (z testową paczką PDF): [docs/testing-guide.md](docs/testing-guide.md).

## Status projektu / ograniczenia MVP

- OCR: czytana jest warstwa tekstowa PDF (`PdfTextOcrEngine`); skany bitmapowe
  wymagają podłączenia Tesseracta za interfejsem `OcrEngine` (zaplanowane).
- LLM: interfejs `LlmClassifier` gotowy, domyślnie wyłączony (`SPLITTER_LLM_ENABLED=false`).
- Tryb pracy: synchroniczny; kontrakt odpowiedzi przygotowany pod przejście na asynchroniczny.
- Pętla uczenia z korekt operatora (feedback) jest zaplanowana, ale nie
  zaimplementowana — serwis działa bezstanowo, bez własnej bazy danych.
