# Przewodnik testowania krok po kroku

## Poziom 1: Testy jednostkowe (bez bazy, bez WEBCON)

```powershell
cd splitter
python -m pytest tests/ -v
```

Oczekiwane: 15 testów przechodzi.

## Poziom 2: Serwis lokalnie, bez bazy

Wygeneruj testowa paczke (5 stron: umowa 2 str., aneks 1 str., swiadectwo 2 str.):

```powershell
cd splitter
pip install fpdf2
python scripts/make_test_bundle.py test_bundle.pdf
```

Uruchom serwis:

```powershell
python -m uvicorn webcon_pdf_splitter.api:app --host 127.0.0.1 --port 8000
```

W drugim oknie wyslij paczke:

```powershell
curl.exe -s http://127.0.0.1:8000/health
curl.exe -s -X POST http://127.0.0.1:8000/api/split -F "file=@test_bundle.pdf"
```

Oczekiwane bez bazy: wszystkie strony jako jeden dokument
`Nieznany typ dokumentu` z `requiresReview: true` — to poprawne,
bo lista wzorcow jest pusta.

## Poziom 3: Serwis z baza wzorcow (SQL Server)

Na serwerze SQL (SSMS lub sqlcmd):

```sql
CREATE DATABASE WebconPdfSplitter;
```

Nastepnie na bazie `WebconPdfSplitter` wykonaj kolejno:

1. `splitter/src/webcon_pdf_splitter/db/schema.sql`
2. `splitter/src/webcon_pdf_splitter/db/seed.sql`

Sprawdz: `SELECT name FROM dbo.document_type;` — 10 typow.

Uruchom serwis ze wskazaniem bazy:

```powershell
$env:SPLITTER_DATABASE_CONNECTION_STRING = "Driver={ODBC Driver 18 for SQL Server};Server=TWOJ_SERWER;Database=WebconPdfSplitter;Trusted_Connection=yes;TrustServerCertificate=yes"
python -m uvicorn webcon_pdf_splitter.api:app --host 127.0.0.1 --port 8000
```

Wyslij ponownie `test_bundle.pdf`. Oczekiwane: 3 dokumenty —
`Umowa o prace` (strony 1-2), `Aneks do umowy o prace` (strona 3),
`Swiadectwo pracy` (strony 4-5), kazdy z `confidence: 0.99`,
`requiresReview: false` i wypelnionym `fileContentBase64`.

## Poziom 4: Token API

```powershell
$env:SPLITTER_API_TOKEN = "sekret123"
# restart uvicorn
curl.exe -s -o NUL -w "%{http_code}" -X POST http://127.0.0.1:8000/api/split -F "file=@test_bundle.pdf"
# oczekiwane: 401
curl.exe -s -X POST http://127.0.0.1:8000/api/split -H "Authorization: Bearer sekret123" -F "file=@test_bundle.pdf"
# oczekiwane: 200 i wynik jak wyzej
```

## Poziom 5: Plugin WEBCON (srodowisko testowe BPS 2026.1)

1. `dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release`
2. Podpisz DLL kluczem SNK i spakuj z manifestem przez WEBCON BPS SDK Tools.
3. Zarejestruj pakiet w Designer Studio (Konfiguracja systemu -> Pluginy SDK).
4. Utworz procesy wg `docs/deployment/webcon-configuration.md`
   (Paczka skanu + Dokument HR) i zanotuj ID workflow, typu dokumentu
   i sciezki startowej dokumentu HR.
5. Dodaj akcje SDK na sciezce paczki skanu i uzupelnij konfiguracje:
   URL splittera, token, ID-ki z punktu 4.
6. Zaloz element paczki, dodaj `test_bundle.pdf` jako zalacznik,
   przejdz sciezka z akcja.

Oczekiwane: 3 nowe elementy Dokument HR, kazdy z jednym PDF-em
i komentarzem `Type: ...; pages X-Y; confidence ...`; elementy sa
podpiete do paczki przez `ParentDocumentID`.

Scenariusze negatywne warte sprawdzenia:

- paczka bez zalacznika PDF -> akcja zglasza blad biznesowy;
- dwa PDF-y na paczce -> blad o niejednoznacznym pliku zrodlowym;
- PDF zabezpieczony haslem -> HTTP 400 `PDF is encrypted`, akcja zglasza blad;
- zly token w konfiguracji akcji -> blad (splitter zwraca 401).
