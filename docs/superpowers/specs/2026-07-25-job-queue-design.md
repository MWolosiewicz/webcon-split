# Kolejka zadan OCR i klasyfikacji - Design

> **Zmiana lamiaca zgodnosc.** `POST /api/split` przestaje zwracac wynik.
> Stan sprzed zmiany zachowany pod tagiem **`v1.0.12-sync`** (commit `5efe237`,
> paczki pluginu `2026r1-1.0.12.7` / `2025r2-1.0.12.8`) - odtwarzalny przez
> `git checkout v1.0.12-sync`. Kontener i paczka pluginu wdrazaja sie razem.

## Cel

Umozliwic dodanie kilku paczek dokumentow naraz bez bledow po stronie WEBCON
i bez rywalizacji o zasoby splittera. Paczki maja byc przetwarzane **po kolei**,
a zadna akcja WEBCON nie moze **czekac** na zakonczenie OCR.

## Problem: co dzieje sie dzis

`/api/split` jest zadeklarowany jako `async def` (`api.py:240`), ale cala ciezka
praca - `ocr.read_pages` (`api.py:322`), render, Tesseract, `split_pdf`, base64 -
jest synchroniczna i wykonuje sie **bezposrednio na petli zdarzen**. Uvicorn
startuje bez `--workers` (`Dockerfile:24`), wiec to jeden proces z jedna petla.

Skutek: pierwsza paczka zamraza caly serwis. Kolejne zadania nie sa nawet
odczytywane, `/health` tez nie odpowiada. Z tego wynikaja cztery awarie:

1. **Timeout klienta -> element w bledzie.** `HttpClient.Timeout`
   (`SplitPdfAction.cs:41`, domyslnie 300 s wg README) odlicza od chwili
   wyslania, nie od chwili rozpoczecia pracy. Przy ~90 s na paczke czwarta
   z kolei przekracza limit. Kazdy wyjatek trafia w `catch`, ktory ustawia
   `args.HasErrors = true` (`SplitPdfAction.cs:110`).
2. **Praca bez odbiorcy.** Timeout po stronie klienta nie przerywa serwera -
   kontener dalej mieli porzucona paczke i blokuje kolejne.
3. **`unhealthy`.** Healthcheck (`docker-compose.yml:19`) stoi na tej samej
   zablokowanej petli.
4. **Obciazenie WEBCON.** Akcja siedzi na przejsciu sciezka, wiec przez caly
   czas OCR trzyma watek serwisu i otwarta transakcje - blokady wychodza poza
   nasz obieg.

## Rozwazane warianty

| Wariant | Opis | Werdykt |
|---|---|---|
| **A** | Kolejka po stronie WEBCON: krok-muteks o pojemnosci 1, akcja cykliczna nalewajaca | Odrzucony |
| **B** | Kolejka w splitterze: `202` + `jobId` + odpytywanie | **Wybrany** |
| **C** | Semafor + `429` + ponawianie z WEBCON | Odrzucony |

**C odrzucony**, bo nie rozwiazuje problemu zrodlowego: pierwsza paczka dalej
wisi na przejsciu sciezka z otwarta transakcja. Chroni przed kumulacja
obciazenia, nie przed dlugim trzymaniem transakcji. Dodatkowo semafor
z odbijaniem nie daje FIFO - element moze byc odbijany w kolko.

**A odrzucony** z dwoch powodow. Po pierwsze, akcja cykliczna nadal **czeka** na
OCR, wiec okupuje watek puli serwisu WEBCON i transakcje na czas przetwarzania -
przy duzej paczce liczony w minutach. Po drugie, cala maszyneria wariantu A
(krok kolejkowy, bramka, akcja nalewajaca, dozorca przeciw zakleszczeniu)
istnieje wylacznie po to, by wymusic "po jednym naraz". Gdy robi to splitter,
**B okazuje sie prostszy od A**: jeden krok zamiast dwoch, jedna akcja cykliczna
zamiast dwoch, zero liczenia elementow w krokach, zero wyscigow TOCTOU.

Widocznosc kolejki, ktora A dawal przez kroki obiegu, B odzyskuje przez pole
`position` w odpowiedzi statusu - z dokladnoscia do miejsca w kolejce.

## Architektura splittera: trzy warstwy

Dzis warstwa HTTP i logika sa zrosniete: `_split()` (`api.py:285`) przyjmuje
`UploadFile`, robi `await file.read()` i od razu mieli. Rozdzielamy to:

**1. Warstwa HTTP** - wylacznie przyjmowanie i odczyt stanu. Zapisuje plik na
dysk, wklada zadanie do kolejki, oddaje `jobId`. Handlery koncza sie
w milisekundach (poza samym transferem pliku).

**2. Kolejka i worker** - `queue.Queue` oraz watek-demon konsumujacy ja po
jednym zadaniu. Liczba workerow z konfiguracji, **domyslnie 1** - to jest
gwarancja "po kolei". Podniesienie do 2 nie wymaga zmian w kodzie ani
w konfiguracji WEBCON.

**3. Rdzen przetwarzania** - czysta funkcja synchroniczna
`process(pdf_path, patterns, filename) -> SplitResult`, wyjeta z `_split()`.
Bez `async`, bez `UploadFile`, bez `HTTPException`.

Przy tym podziale blokowanie petli zdarzen znika **z definicji**, a nie przez
latke: ciezka praca nigdy nie dotyka watku, na ktorym stoi uvicorn.

**Plik zrodlowy trzymamy na dysku, nie w RAM.** Zadanie czekajace w kolejce ma
swoj PDF w `SPLITTER_WORK_DIR` (katalog istnieje i jest zamontowany -
`Dockerfile:18-21`), usuwany po zakonczeniu przetwarzania. Inaczej kilkanascie
zakolejkowanych paczek trzymaloby setki megabajtow w pamieci. Przy starcie
kontener zamiata pozostalosci po poprzednim wcieleniu.

**Logowanie i metryki dzialaja bez zmian.** `_JOB_ID` (`api.py:55`) i kolektor
metryk (`metrics.py:30`) opieraja sie na `ContextVar`, ktory ma osobny kontekst
per watek - ustawienie go w workerze dziala poprawnie. `MetricsRegistry` ma juz
`threading.Lock` (`metrics.py:59`). Kontekst `job_log_context` i
`request_collector` przenosza sie z handlera do workera; prefiks `[job=...]`
zyskuje na wartosci, bo `jobId` jest teraz kluczem kolejki widocznym takze
w polu na formularzu WEBCON.

## Kontrakt API

| Endpoint | Zwraca | Po co |
|---|---|---|
| `POST /api/split` | `202 {jobId, position}` | Przyjecie paczki do kolejki |
| `GET /api/jobs/{jobId}` | status bez base64 | Lekkie odpytywanie |
| `GET /api/jobs/{jobId}/result` | pelny `SplitResult` | Pobranie wyniku, raz |
| `DELETE /api/jobs/{jobId}` | `204` | Zwolnienie wyniku po odebraniu |

Rozdzielenie statusu od wyniku jest istotne: gdyby odpytywanie zwracalo komplet,
akcja cykliczna co minute przeciagalaby przez siec megabajty base64 dla zadania,
ktore jeszcze sie nie skonczylo.

Odpowiedz statusu:

```json
{
  "jobId": "...",
  "status": "queued | running | done | failed",
  "position": 3,
  "runningSeconds": 0,
  "pageCount": 0,
  "documentCount": 0,
  "documentsRequiringReview": 0,
  "warnings": [],
  "error": null
}
```

`documentsRequiringReview` jest w statusie swiadomie: operator patrzacy na
formularz chce wiedziec nie tyle "ile dokumentow", co **"ile wymaga
weryfikacji"**. Splitter i tak juz to liczy na potrzeby metryk (`api.py:265`),
wiec pole statusu na paczce moze pokazac "8 dokumentow, 2 do weryfikacji" bez
sciagania ani jednego bajta base64.

`GET /api/jobs/{jobId}/result` zwraca **niezmieniony** `SplitResult`
(`contracts.py:37`) - dokladnie to, co dzis przychodzi w odpowiedzi na
`POST /api/split`. Zmienia sie moment dostarczenia, nie zawartosc.

### Deduplikacja po elemencie WEBCON

Dodatek juz dzis wysyla naglowek `X-Webcon-Element-Id` (`api.py:244`) - dotad
uzywany tylko w logu. Teraz: jesli dla danego elementu istnieje **aktywne**
zadanie (`queued` lub `running`), `POST` zwraca istniejacy `jobId` zamiast
tworzyc drugie.

Zamyka to scenariusz, w ktorym zlecenie doszlo, ale odpowiedz zginela po drodze,
WEBCON ponowil - i paczka podzielilaby sie dwukrotnie.

### Ograniczenie kolejki

`SPLITTER_MAX_QUEUE_SIZE` (domyslnie 50). Przepelnienie -> `503` z naglowkiem
`Retry-After`. Bez tego zalew paczek zapchalby dysk.

## Przeplyw danych

```
WEBCON                          SPLITTER
  |
  |- POST /api/split ------------>  zapis PDF do work_dir
  |                                 utworzenie zadania
  |  <-------- 202 {jobId, pos:3} - wstawienie do kolejki
  |                                        |
  |- zapis jobId + daty w polach           |  worker bierze
  |- przejscie -> "Przetwarzanie"          |  zadania po jednym
  |                                        v
  |                                 OCR -> klasyfikacja -> podzial
  |                                 wynik w RAM, PDF z dysku skasowany
  |
  |- GET /api/jobs/{id} ---------->
  |  <---- {status:"queued",pos:2} -   (akcja cykliczna, co minute)
  |- zapis pozycji w polu statusu
  |
  |- GET /api/jobs/{id} ---------->
  |  <-------- {status:"done", ...} -
  |
  |- GET /api/jobs/{id}/result --->
  |  <---- pelny SplitResult -------
  |- utworzenie dokumentow potomnych
  |- DELETE /api/jobs/{id} ------->  zwolnienie pamieci
  |- przejscie -> "Podzielona"
```

Kolejnosc nie jest przypadkowa: `DELETE` idzie **po** utworzeniu dokumentow
potomnych. Gdyby WEBCON przewrocil sie miedzy pobraniem wyniku a zapisem dzieci,
zadanie wciaz istnieje i kolejny takt sprobuje ponownie.

## Strona WEBCON

**Kroki:** `Rejestracja -> Przetwarzanie -> Podzielona`, plus `Blad` jako
odnoga z "Przetwarzania".

Brak osobnego kroku kolejkowego i kroku-muteksu. Kolejka zyje w splitterze;
"Przetwarzanie" znaczy "zlecone, czekamy" niezaleznie od tego, czy zadanie stoi
trzecie w kolejce, czy wlasnie jest mielone.

**Pola na paczce:**

| Pole | Typ | Rola |
|---|---|---|
| `jobId` | tekst | Klucz zadania; korelacja z logiem kontenera |
| `Data zlecenia` | data i czas | Podstawa dla akcji na timeout |
| `Status przetwarzania` | tekst | Dla operatora: "3. w kolejce" / "8 dok., 2 do weryfikacji" / tresc bledu |
| `Liczba prob` | liczba | Zabezpieczenie przed petla ponowien |
| `Ostatni utworzony dokument` | liczba | Wznawianie odbioru po awarii (patrz nizej) |

**Dwie akcje w dodatku:**

`SubmitSplitJobAction` - na przejsciu z "Rejestracji". Robi to, co dzis poczatek
`SplitPdfAction`: wczytuje wzorce ze zrodla danych (`SplitPdfAction.cs:159`),
pobiera zalacznik PDF (`SplitPdfAction.cs:116`), wysyla. Zamiast czekac na wynik
zapisuje `jobId` i date zlecenia. Trwa tyle, co transfer pliku.

**Zlecenie jest najlepszym staraniem, nie warunkiem przejscia.** Element
przechodzi do "Przetwarzania" **zawsze** - takze gdy zlecenie sie nie udalo
(`503` z pelnej kolejki, zerwana siec, niedostepny kontener). Akcja zapisuje
wtedy powod w polu statusu i **nie** ustawia `HasErrors`: uzytkownik klikajacy
sciezke nie moze dostac bledu dlatego, ze kolejka jest chwilowo pelna.

`CollectSplitJobAction` - akcja cykliczna na kroku "Przetwarzanie". Zaczyna od
sprawdzenia, czy element ma `jobId`:

- **brak `jobId`** -> zleca (ta sama logika co akcja zlecajaca), konczy;
- `queued` / `running` -> aktualizuje pole statusu, konczy;
- `done` -> pobiera wynik, tworzy dokumenty potomne (kod przeniesiony
  z `SplitPdfAction.cs:54-96`), kasuje zadanie, przechodzi na "Podzielona";
- `failed` -> zwieksza `Liczba prob`; powyzej limitu "Blad", inaczej czysci
  `jobId` i pozwala zlecic ponownie;
- `404` -> zwieksza `Liczba prob`, czysci `jobId`; nastepny takt potraktuje
  element jak "brak `jobId`".

Dzieki temu `503`, blad sieci, `404` i wygasly wynik maja **jedna wspolna
sciezke** ("brak waznego zadania -> zlec ponownie") zamiast czterech osobnych
obslug. Logika zlecania zyje w jednym miejscu i jest wywolywana z obu akcji.

### Licznik prob broni przed zatruta paczka, nie przed zajetoscia

Rozroznienie krytyczne dla zachowania w szczycie:

| Sytuacja | `Liczba prob` | Uzasadnienie |
|---|---|---|
| `503` - kolejka pelna | **nie rosnie** | Poprawna praca pod obciazeniem, nie awaria |
| Brak polaczenia z kontenerem | **nie rosnie** | Restart lub okno serwisowe mija samo |
| `404` - zadanie przepadlo | rosnie | Powtarzalna utrata wskazuje na problem |
| `failed` - zadanie zakonczone bledem | rosnie | Cos w tej paczce powoduje porazke |

Gdyby `503` zwiekszal licznik, element odpytywany co minute wypalilby limit
w kilka minut i trafil do "Bledu" **mimo poprawnie dzialajacego systemu** -
dokladnie w szczycie, przed ktorym ta kolejka ma chronic. Zajetosc i awaria to
dwie rozne rzeczy i wymagaja roznych reakcji.

Nieograniczone ponawianie przy `503` nie jest luka: elementem, ktory utknal
z powodu trwalej niedostepnosci uslugi, zajmuje sie **akcja na timeout** w kroku
"Przetwarzanie" (N minut od `Data zlecenia` -> "Blad"). To wlasciwe narzedzie,
bo mierzy realny czas oczekiwania, a nie liczbe prob.

## Tryby awarii

**Restart kontenera.** Kolejka i wyniki zyja w RAM, wiec przepadaja; pliki
zrodlowe w `work_dir` zamiatane przy starcie. WEBCON odpytuje i dostaje `404`.
Akcja odbierajaca czysci `jobId` i zleca ponownie. Dziala, bo **zrodlem prawdy
jest zalacznik w WEBCONie** - splitter niczego nie musi pamietac trwale. To
swiadoma rezygnacja z trwalego magazynu stanu: koszt to powtorzenie pracy nad
paczkami, ktore byly w locie, zysk to brak bazy do utrzymania i brak ryzyka
rozjazdu miedzy nia a WEBCONem.

Zabezpieczenie przed petla: pole `Liczba prob`. Po trzeciej probie element idzie
na "Blad" zamiast krazyc bez konca.

**Worker nie moze umrzec - punkt krytyczny.** Wyjatek przy przetwarzaniu jednej
paczki nie moze zabic watku, bo wtedy kolejka staje na zawsze i **nic tego nie
zglosi**. Petla workera jest opakowana tak, ze zadanie konczy sie statusem
`failed` z trescia bledu, a worker bierze nastepne. Ma to dedykowany test.

**Zaklinowane zadanie.** Tesseract ma timeout na strone (`config.py:53`), wiec
gorna granica to okolo liczba stron x timeout - ale render moze zawiesic sie
poza tym budzetem. Watku w Pythonie nie da sie czysto zabic, wiec splitter
tylko **raportuje** `runningSeconds`, a bezpiecznikiem jest akcja na timeout
w kroku "Przetwarzanie": po N minutach od `Data zlecenia` element idzie na
"Blad".

**Pad WEBCON w polowie odbioru.** `DELETE` nie doszedl, zadanie wciaz jest
`done`, kolejny takt sprobuje ponownie - ale jesli pierwsza proba zdazyla
utworzyc czesc dokumentow, powtorzenie zrobi duplikaty. Rozwiazanie: pole
`Ostatni utworzony dokument`; petla przetwarza tylko pozycje o `documentIndex`
wiekszym od zapisanej wartosci i aktualizuje ja po kazdym utworzonym dziecku.

Istnieje prostsza alternatywa - liczyc na to, ze WEBCON opakuje cala akcje jedna
transakcja, wiec pad wycofa wszystko. Odrzucona, bo zalezy od semantyki
transakcji akcji cyklicznej, ktorej **nie zweryfikowano** (patrz "Do
zweryfikowania"). Wznawianie po `documentIndex` jest poprawne niezaleznie od
tego, jak ta semantyka wyglada.

**Kolejka pelna.** `503` + `Retry-After`. Element mimo to przechodzi do
"Przetwarzania" bez `jobId`, z powodem w polu statusu; kolejny takt akcji
odbierajacej zleca ponownie (wspolna sciezka "brak waznego zadania"). Klikajacy
sciezke uzytkownik nie widzi bledu - widzi element w kroku "Przetwarzanie"
z opisem "kolejka pelna, ponowienie". **`Liczba prob` nie rosnie** - patrz
"Licznik prob broni przed zatruta paczka".

Glebokosc kolejki to nie sufit na liczbe dodanych paczek, tylko na liczbe
**oczekujacych**; zadanie zdjete przez workera zwalnia miejsce. Nadmiarowe
paczki czekaja dluzej, ale zadna nie jest odrzucana trwale.

**Zgubiona odpowiedz na zlecenie.** Zamknieta deduplikacja po
`X-Webcon-Element-Id` (wyzej).

**Wygasniecie wyniku (TTL).** TTL musi byc znacznie dluzszy niz interwal
odpytywania - domyslnie 3600 s przy takcie minutowym daje 60 szans. Wygasniecie
zachowuje sie jak `404`: ponowne zlecenie, praca powtorzona, wynik poprawny.

## Zmiany w kontrakcie danych

**`signals` trafiaja do komentarza dziecka.** Dzis sa wypelniane realna
diagnostyka - `header_match:<naglowek>` (`rules.py:77`), `phrase_hits:<liczba>`
(`rules.py:80`), `no_pattern_match` (`rules.py:99`), `llm:<kod>`
(`pipeline.py:155`), `glued_unknown_page:<strona>` (`pipeline.py:189`),
`unknown_run` (`pipeline.py:208`) - czyli odpowiedz na pytanie "dlaczego ten
dokument dostal taki typ i taka pewnosc". Sa deserializowane w C#
(`SplitterContracts.cs:26`) i **po cichu wyrzucane**: w calym `webcon-action/`
nie ma ani jednego odwolania do `.Signals`.

Dopisujemy je do komentarza tworzonego przez `FormatDetectionComment`. Kosztuje
kilka linijek, a daje osobie weryfikujacej odpowiedz wprost na formularzu,
zamiast szukania w `docker logs`. Strojenie slownika wzorcow to temat, wokol
ktorego kreci sie wiekszosc README - trzymanie tej informacji poza zasiegiem
operatora jest marnotrawstwem.

**`metadata` znika z kontraktu.** `pipeline.py:244` wpisuje tam na sztywno `{}`
i nikt tego nie nadpisuje - pusty slownik w kazdym dokumencie kazdej odpowiedzi.
Skoro i tak lamiemy zgodnosc, to wlasciwy moment na usuniecie z obu stron
(`contracts.py:34`, `SplitterContracts.cs:28`). Wroci, gdy bedzie potrzebny.

## Konfiguracja

| Zmienna | Domyslnie | Znaczenie |
|---|---|---|
| `SPLITTER_WORKER_COUNT` | `1` | Ile paczek naraz. Jedynka = gwarancja "po kolei" |
| `SPLITTER_MAX_QUEUE_SIZE` | `50` | Ile zadan moze **czekac**; powyzej - `503` z `Retry-After` |
| `SPLITTER_JOB_RESULT_TTL_SECONDS` | `3600` | Ile wynik czeka na odbior |

**Dobor glebokosci kolejki** wynika z miejsca na dysku, nie z przepustowosci:
kazde oczekujace zadanie trzyma swoj PDF w `SPLITTER_WORK_DIR`, wiec
`max_queue_size x sredni rozmiar paczki` musi miescic sie w wolnym miejscu
z zapasem. Domyslne 50 zaklada paczki rzedu 20 MB (okolo 1 GB) - **wartosc do
zweryfikowania realnymi rozmiarami po wdrozeniu**. Zwiekszenie glebokosci nie
podnosi przepustowosci: przy jednym workerze i ~2 min na paczke pelna
piecdziesieciolementowa kolejka oznacza okolo 100 minut oczekiwania dla
ostatniej. Glebsza kolejka daje dluzszy ogon, nie szybsze przetwarzanie.

**TTL wyniku** musi z duzym zapasem przekraczac interwal odpytywania - 3600 s
przy takcie minutowym daje 60 szans na odbior.

Istniejace zmienne bez zmian. Po stronie dodatku dochodzi maksymalna liczba prob
(domyslnie 3); interwal odpytywania to harmonogram akcji cyklicznej w WEBCON,
nie parametr kodu.

## Zakres zmian w kodzie

- **`splitter/src/webcon_pdf_splitter/jobs.py`** (nowy modul):
  - `Job` (dataclass: `job_id`, `element_id`, `status`, `created_at`,
    `started_at`, `finished_at`, `result`, `error`, `source_path`);
  - `JobQueue` - kolejka FIFO z limitem rozmiaru, rejestr zadan pod `job_id`,
    indeks aktywnych zadan po `element_id` (deduplikacja), wygasanie wynikow po
    TTL, `position(job_id)`;
  - `JobWorker` - watek-demon; petla odporna na wyjatki zadania.
- **`splitter/src/webcon_pdf_splitter/processing.py`** (nowy modul): `process()`
  - rdzen wyjety z `_split()` (`api.py:285`), synchroniczny, bez zaleznosci od
  FastAPI. Budowa pipeline'u, silnika OCR i detektora blankow przenosi sie tu
  z `api.py:187-223`.
- **`api.py`**: handlery skracaja sie do przyjmowania i odczytu stanu; nowe
  endpointy zadan; start/stop workerow w cyklu zycia aplikacji; zamiatanie
  `work_dir` przy starcie; `job_log_context` i `request_collector` przenosza sie
  do workera.
- **`config.py`**: `worker_count`, `max_queue_size`, `job_result_ttl_seconds`.
- **`contracts.py`**: nowe modele odpowiedzi zadan; usuniete pole `metadata`.
- **C# (`webcon-action/`)**: `SubmitSplitJobAction` + `CollectSplitJobAction`
  (nowe pliki wraz z konfiguracjami); `SplitterClient` dostaje `SubmitAsync`,
  `GetJobStatusAsync`, `GetJobResultAsync`, `DeleteJobAsync`;
  `SplitterContracts.cs` - modele statusu, usuniete `Metadata`;
  `FormatDetectionComment` uzupelniony o `Signals`. **`SplitPdfAction`,
  `SplitPdfActionConfig` usuniete.** Akcje `Merge`, `RemovePages`,
  `ExtractPages` **bez zmian** - korzystaja z endpointow, ktorych nie ruszamy.
- **`README.md`** i **`splitter/.env.example`**: nowe zmienne, opis kolejki,
  konfiguracja krokow i pol w WEBCON, nota migracyjna.

## Migracja

1. Wdrozyc nowy kontener i nowa paczke pluginu **razem** - stara akcja przestaje
   dzialac z nowym API i odwrotnie.
2. Zalozyc kroki `Przetwarzanie` i `Blad` oraz piec pol na paczce.
3. Przepiac akcje: `SubmitSplitJobAction` na przejscie z "Rejestracji",
   `CollectSplitJobAction` jako cykliczna na "Przetwarzaniu", akcja na timeout
   na "Przetwarzaniu".
4. Elementy w locie w chwili wdrozenia trzeba przepchnac recznie - nie ma
   sciezki migracji dla paczki, ktora czeka na odpowiedz starego API.

Powrot: `git checkout v1.0.12-sync`, przebudowa kontenera i paczki.

## Poza zakresem

- **Trwaly magazyn zadan** (baza, Redis). Swiadomie: zrodlem prawdy jest
  zalacznik w WEBCONie, a ponowne zlecenie po `404` jest tansze niz utrzymanie
  drugiego magazynu stanu.
- **Kooperacyjne przerywanie zadania po deadline** - dzis granica jest timeout
  Tesseracta na strone plus akcja na timeout w WEBCON.
- **Porcjowanie tworzenia dokumentow potomnych.** Paczka dzielona na 40
  dokumentow to 40 elementow z zalacznikami w jednej akcji - realna praca
  w WEBCONie, niezalezna od architektury kolejki. Adresowac dopiero po
  zobaczeniu realnych rozmiarow paczek; pole `Ostatni utworzony dokument` juz
  teraz daje punkt zaczepienia.
- **Priorytety w kolejce** - FIFO wystarcza.
- **Skalowanie na wiele kontenerow** - wymagaloby wspolnej kolejki, czyli
  odwrocenia decyzji o braku trwalego magazynu.

## Testy

`jobs.py` (jednostkowe, bez HTTP):

- kolejnosc FIFO: trzy zadania wychodza w kolejnosci wejscia;
- `position` maleje w miare opustoszania kolejki;
- limit rozmiaru: zadanie ponad `max_queue_size` odrzucone sygnalem dla `503`;
- deduplikacja: drugi `POST` z tym samym `element_id` przy aktywnym zadaniu
  zwraca ten sam `job_id`, nie tworzy drugiego;
- deduplikacja **nie** dziala na zadania zakonczone - nowa paczka dla tego
  samego elementu tworzy nowe zadanie;
- wynik wygasa po TTL i zachowuje sie jak nieznane zadanie;
- `delete` zwalnia wynik i usuwa plik zrodlowy.

`JobWorker`:

- przejscia statusu `queued` -> `running` -> `done`;
- zadanie rzucajace wyjatek konczy sie `failed` z trescia bledu, **a worker
  bierze nastepne zadanie** (test krytyczny - bez tego kolejka staje po cichu);
- plik zrodlowy usuwany po zakonczeniu, takze przy `failed`.

`api.py` (endpointy zadan):

- `POST /api/split` zwraca `202` z `jobId` i `position`;
- `GET /api/jobs/{id}` **nie zawiera** base64 (regresja na przypadkowe
  dolaczenie wyniku do statusu);
- `GET /api/jobs/{id}/result` zwraca pelny `SplitResult` zgodny z dzisiejszym
  kontraktem;
- `DELETE` zwraca `204`, po nim status to `404`;
- nieznany `jobId` -> `404` na wszystkich trzech endpointach;
- **`/health` odpowiada, gdy worker mieli paczke** - regresja na blokowanie
  petli zdarzen. Ten test nie przechodzi na dzisiejszym kodzie.

Zamiatanie `work_dir`: plik-sierota z poprzedniego wcielenia znika przy starcie.

Istniejacy `test_api_split.py` przechodzi na nowy kontrakt. Testy rdzenia -
`test_pipeline.py`, `test_ocr.py`, `test_blank_pages.py`, `test_rule_classifier.py`,
`test_split_patterns.py` - **zostaja nietkniete**. To sprawdzian podzialu warstw:
jesli ktorys z nich trzeba by ruszyc, znaczy ze przeciekla odpowiedzialnosc.

## Do zweryfikowania przed wdrozeniem

Trzy zalozenia o WEBCON, ktorych nie potwierdzono w dokumentacji:

1. **Semantyka transakcji akcji cyklicznej** - czy tworzenie wielu dokumentow
   potomnych jest jedna transakcja. Projekt jest poprawny w obie strony dzieki
   wznawianiu po `documentIndex`, ale odpowiedz wplywa na to, czy pole
   `Ostatni utworzony dokument` jest konieczne, czy tylko zapasowe.
2. **Zachowanie przy wielu wezlach serwisu** - czy dwa wezly moga podjac ten sam
   element w tym samym takcie. Deduplikacja po `element_id` chroni przed
   podwojnym **zleceniem**.

   **Korekta po przegladzie galezi:** wczesniejsze zdanie tego specu mowilo, ze
   przy odbiorze zabezpiecza wznawianie po `documentIndex`. **To nieprawda.**
   `lastCreated` jest czytany raz, na poczatku taktu; dwa wezly wykonujace akcje
   cykliczna rownoczesnie oba odczytaja te sama wartosc i oba utworza komplet
   dokumentow potomnych - beda duplikaty. Znacznik chroni ponowienia
   **sekwencyjne** (pad w polowie petli), nie **rownoczesne** wykonania.

   Dopoki nie potwierdzimy, ze WEBCON serializuje akcje cykliczne per element,
   to jest realne ryzyko przy farmie serwisow. Wyjscie, gdyby sie nie
   potwierdzilo: zaczynac takt od "zajecia" elementu (zapis znacznika przed
   pobraniem wyniku), co daje blokade na poziomie elementu.
3. **Limit czasu wykonania akcji** - istotny dla akcji zlecajacej, ktora
   przesyla duzy plik. Jesli limit okaze sie niski, transfer duzych paczek
   moze wymagac osobnego podejscia.

Zadne z tych zalozen nie zagraza poprawnosci projektu - wplywaja na strojenie,
nie na architekture. Wszystkie sa konsekwencja tego, ze **gwarancje trzymamy po
stronie splittera**, nie po stronie WEBCON.
