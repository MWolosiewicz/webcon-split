# Instrukcja aktualizacji kontenera testowego

Instrukcja odtworzenia kontenera `splitter-test` (port **8011**) na najnowszy kod
z gałęzi `branch/webcon-ocr-service`, bez scalania czegokolwiek do `main`
i bez dotykania kontenera na porcie 8010.

## Co trzeba wiedzieć na start

Na maszynie deweloperskiej działają **dwa różne** kontenery splittera:

| Kontener | Port | Obraz | Jak powstał |
|---|---|---|---|
| `webcon-pdf-splitter` | 8010 | `webcon-pdf-splitter:latest` | `docker compose` (plik `splitter/docker-compose.yml`) |
| `splitter-test` | 8011 | `webcon-pdf-splitter:test` | **ręcznie**: `docker build` + `docker run` |

To rozróżnienie jest istotne, bo **`docker compose up -d --build` nie zaktualizuje
kontenera testowego**. Compose nie wie o jego istnieniu (kontener nie ma etykiet
compose), więc ta komenda przebuduje kontener na 8010 — i to z gałęzi aktualnie
wybranej w głównym katalogu repozytorium, czyli zwykle z `main`. Efekt: niby coś
się przebudowało, a testowany kod się nie zmienił.

Druga rzecz: **kod jest wbudowany w obraz**, nie montowany z dysku. `Dockerfile`
robi `COPY src ./src` i `pip install .`, a kontener nie ma żadnych montowań.
Dlatego `docker restart` ani `docker start` nic nie dadzą — obraz trzeba
zbudować od nowa.

## Skąd budować

Gałąź `branch/webcon-ocr-service` jest wypożyczona do osobnego drzewa roboczego
(worktree). Buduj stamtąd — ten katalog ma i właściwy kod, i własny plik `.env`:

```
D:/!!Projects/Webcon_Split/.claude/worktrees/concurrent-document-processing-8913a9/splitter
```

Główny katalog repozytorium (`D:/!!Projects/Webcon_Split`) stoi na `main` i **nie
zawiera** zmian z gałęzi. Nie da się go po prostu przełączyć przez `git checkout`,
bo Git nie pozwala mieć tej samej gałęzi wypożyczonej w dwóch drzewach naraz.

## Komendy

Zachowanie obecnych liczników (opcjonalne — po przebudowie zerują się):

```bash
curl.exe -s http://localhost:8011/metrics > metryki-przed-przebudowa.json
```

Wejście do katalogu z kodem gałęzi:

```bash
cd 'D:/!!Projects/Webcon_Split/.claude/worktrees/concurrent-document-processing-8913a9/splitter'
```

Pobranie najnowszego stanu gałęzi (jeśli od ostatniego razu coś doszło):

```bash
git pull
```

Budowa obrazu testowego:

```bash
docker build -t webcon-pdf-splitter:test .
```

Usunięcie starego kontenera:

```bash
docker rm -f splitter-test
```

Uruchomienie nowego:

```bash
docker run -d --name splitter-test -p 8011:8000 --env-file .env --restart unless-stopped webcon-pdf-splitter:test
```

### Uwagi do składni (PowerShell)

- Ścieżkę podawaj w **apostrofach**. Nazwa katalogu zawiera `!!`, co
  w interaktywnym bashu uruchamia rozwijanie historii poleceń — nawet wewnątrz
  cudzysłowów. Apostrofy są bezpieczne w obu powłokach.
- Używaj **`curl.exe`**, nie `curl`. W PowerShellu `curl` to alias na
  `Invoke-WebRequest`, które nie zna przełącznika `-s`.

## Weryfikacja

```bash
curl.exe -s http://localhost:8011/metrics
```

Szukaj sekcji `queue` — istnieje **wyłącznie** w nowym kodzie:

```json
"queue": { "queued": 0, "running": 0, "done": 0, "failed": 0, "oldest_queued_seconds": 0.0 }
```

Jest → kontener chodzi na nowym kodzie. Nie ma → nadal na starym.

`GET /health` **nie nadaje się** do tej weryfikacji: odpowiada identycznie na
obu wersjach.

## Czego robić nie trzeba

- **Nie trzeba ruszać `.env`.** Nowa wersja nie wprowadza żadnego nowego
  ustawienia. Rozmiar porcji przy strumieniowym zapisie przyjmowanego pliku to
  stała w kodzie, nie parametr konfiguracji.
- **Nie trzeba wgrywać nowej paczki pluginu do Designer Studio.** Zmiany po
  stronie kontenera nie ruszają kontraktu API, więc nowy kontener działa ze starą
  paczką, a paczka `1.0.12.19` ze starym kontenerem. Kolejność wdrożenia jest
  dowolna. (Przy przejściu z wersji synchronicznej na kolejkę zadań było
  inaczej — tam paczka i kontener musiały iść razem.)
- **Nie trzeba zatrzymywać kontenera na 8010.** To osobny obraz i osobna nazwa;
  powyższe komendy go nie dotykają.

## Czego się spodziewać po przebudowie

**Liczniki `/metrics` startują od zera.** Są trzymane w pamięci procesu.

**Paczki w locie pójdą ścieżką odzyskiwania.** Kolejka zadań też żyje w pamięci,
więc po usunięciu kontenera wszystkie zadania znikają. Paczka, która ma w WEBCONie
zapisany `jobId`, przy najbliższym takcie akcji cyklicznej dostanie `404` →
licznik prób wzrośnie o 1 → podział zostanie zlecony od nowa. To zaprojektowana
reakcja, nie awaria: źródłem prawdy jest załącznik w WEBCONie, nie stan kontenera.
W polu statusu operator zobaczy „zadanie przepadło, ponowienie (1)".

Jeśli paczek w toku jest dużo, warto przebudowywać poza godzinami pracy — każda
z nich przejdzie OCR ponownie.

## Powrót na kontener produkcyjny

Kontener testowy zatrzymasz i usuniesz tak:

```bash
docker rm -f splitter-test
```

Kontener na 8010 działa niezależnie i nie wymaga wtedy żadnej akcji.
