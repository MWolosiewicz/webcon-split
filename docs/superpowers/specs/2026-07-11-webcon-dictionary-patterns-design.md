# Slowniki typow dokumentow w WEBCON - Design

> **ZASTAPIONY** przez `2026-07-11-patterns-in-request-design.md` - wzorce
> przekazuje plugin SDK w zadaniu `/api/split`; splitter nie czyta bazy
> tresci WEBCON.

## Cel

Przeniesc zarzadzanie slownikami splittera (typy dokumentow i wzorce rozpoznawania)
z recznych operacji SQL na bazie `WebconPdfSplitter` do natywnego procesu
slownikowego WEBCON BPS. Uzytkownik biznesowy edytuje typy i wzorce na
formularzu WEBCON (z uprawnieniami i historia zmian), a splitter czyta te dane
bezposrednio z bazy tresci WEBCON.

Priorytety:

- jedna kopia danych slownikowych - zrodlem prawdy jest proces slownikowy WEBCON;
- zero synchronizacji i zero dryfu danych;
- brak zaleznosci splittera od portalu WEBCON (odczyt przez SQL, nie REST/OAuth);
- kod klasyfikacji bez zmian - nowa implementacja istniejacego protokolu
  `PatternRepository`;
- tryb standalone (dotychczasowe tabele wlasne) zostaje jako fallback.

## Zakres

W zakresie:

- proces slownikowy "Typ dokumentu" w WEBCON (naglowek + lista pozycji wzorcow);
- nowa implementacja `WebconDictionaryPatternRepository` w splitterze;
- konfigurowalne mapowanie kolumn bazy tresci WEBCON w ustawieniach splittera;
- rozszerzenie fabryki `build_pattern_repository` o wybor trybu;
- dokument wdrozeniowy z danymi startowymi (10 typow HR, 15 wzorcow) do
  recznego wprowadzenia w slowniku;
- testy jednostkowe mapowania i wyboru repozytorium.

Poza zakresem:

- zmiany w tabelach operacyjnych `splitter_job` i `classification_feedback`
  (zostaja w bazie `WebconPdfSplitter`, endpoint `/api/feedback` bez zmian);
- automatyczna aktualizacja wzorcow na podstawie feedbacku (osobna iteracja);
- zapis czegokolwiek do bazy tresci WEBCON (zabronione - wylacznie odczyt);
- endpointy administracyjne CRUD na splitterze (niepotrzebne w tym wariancie);
- kierowanie roznych typow dokumentow do roznych obiegow
  (`target_workflow` / `target_attachment_category` pozostaja nieuzywane);
- prog auto-akceptacji per typ dokumentu - pole jest na formularzu slownika
  (zadatek na przyszlosc, jak dzis nieuzywana kolumna `auto_accept_threshold`),
  ale pipeline nadal stosuje wylacznie prog globalny
  `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE`.

## Rozwazane warianty

1. **Push: WEBCON edytuje przez API splittera, replika w bazie splittera** -
   odrzucony: dwie kopie danych, ryzyko dryfu, dodatkowe endpointy i akcje.
2. **Pull przez REST API BPS** - odrzucony: zaleznosc od dostepnosci portalu,
   konfiguracja OAuth per srodowisko, przerobka warstwy odczytu.
3. **Pull przez SQL z bazy tresci WEBCON (wybrany)** - splitter i tak dziala
   na tej samej infrastrukturze SQL Server; odczyt `WFElements` przez SQL to
   udokumentowana praktyka w ekosystemie WEBCON; jedna kopia danych; profil
   dostepnosci bez zmian.

## Proces slownikowy "Typ dokumentu"

Jeden formularz slownika = jeden typ dokumentu.

Naglowek:

- Nazwa typu (tekst) - polskie znaki dozwolone, klasyfikator normalizuje
  tekst do ASCII przed dopasowaniem;
- Aktywny (checkbox) - wylacza caly typ wraz ze wszystkimi wzorcami;
- Prog auto-akceptacji (liczba dziesietna, domyslnie 0,90).

Lista pozycji "Wzorce" (jeden wiersz = jeden wzorzec):

- Naglowek dokumentu (tekst), np. `UMOWA O PRACE`;
- Frazy (tekst, rozdzielane srednikami), np. `pracodawca; pracownik; wynagrodzenie`;
- Frazy wykluczajace (tekst, sredniki, moze byc puste);
- Waga (liczba dziesietna, domyslnie 1,0);
- Aktywny (checkbox) - wylacza pojedynczy wzorzec.

## Konfiguracja splittera

Nowe ustawienia w `SplitterSettings` (prefiks `SPLITTER_`):

| Zmienna | Opis |
|---|---|
| `WEBCON_DB_CONNECTION_STRING` | ODBC do bazy tresci WEBCON; konto z uprawnieniem wylacznie do odczytu |
| `WEBCON_DICT_FORM_TYPE_ID` | ID typu formularza slownika (`WFD_DTYPEID`) |
| `WEBCON_DICT_COL_TYPE_NAME` | kolumna naglowka z nazwa typu, np. `WFD_AttText1` |
| `WEBCON_DICT_COL_TYPE_ACTIVE` | kolumna naglowka z flaga aktywnosci typu, np. `WFD_AttBool1` |
| `WEBCON_DICT_COL_PATTERN_HEADER` | kolumna listy pozycji z naglowkiem wzorca, np. `DET_AttText1` |
| `WEBCON_DICT_COL_PATTERN_PHRASES` | kolumna listy pozycji z frazami, np. `DET_AttText2` |
| `WEBCON_DICT_COL_PATTERN_EXCLUDED` | kolumna listy pozycji z frazami wykluczajacymi, np. `DET_AttText3` |
| `WEBCON_DICT_COL_PATTERN_WEIGHT` | kolumna listy pozycji z waga, np. `DET_AttDecimal1` |
| `WEBCON_DICT_COL_PATTERN_ACTIVE` | kolumna listy pozycji z flaga aktywnosci wzorca, np. `DET_AttBool1` |

Nazwy kolumn odczytuje sie z Designer Studio (wlasciwosci atrybutu), dlatego
sa konfiguracja per srodowisko, nie kodem. Tryb WEBCON jest wlaczony, gdy
ustawione sa `WEBCON_DB_CONNECTION_STRING` i `WEBCON_DICT_FORM_TYPE_ID`;
wszystkie mapowania kolumn sa wtedy wymagane (walidacja przy starcie odczytu,
czytelny blad przy braku).

## Kod: warstwa odczytu

Nowa klasa `WebconDictionaryPatternRepository` w
`splitter/src/webcon_pdf_splitter/db/repository.py` implementujaca istniejacy
protokol `PatternRepository`:

- jedno zapytanie JOIN `WFElements` (naglowki) x `WFElementDetails`
  (wiersze wzorcow) po `WFD_ID`;
- filtry: element nalezy do skonfigurowanego typu formularza, element nie jest
  usuniety, typ aktywny AND wzorzec aktywny (ta sama logika co dzis w JOIN
  `document_type` x `document_pattern`);
- frazy i frazy wykluczajace dzielone po `;`, kazda fraza trimowana,
  puste pomijane;
- brak wartosci wagi -> 1,0;
- zwraca liste `DocumentPattern` - klasyfikator i pipeline bez zmian.

Fabryka `build_pattern_repository` wybiera implementacje:

1. mapowanie WEBCON skonfigurowane -> `WebconDictionaryPatternRepository`;
2. inaczej `database_connection_string` ustawione -> `SqlServerPatternRepository`
   (tryb standalone, tabele wlasne);
3. inaczej -> `InMemoryPatternRepository` (pusta lista).

Wzorce sa czytane przy kazdym zadaniu `/api/split` (jak dotychczas), wiec
zmiany w slowniku dzialaja od nastepnego wywolania bez restartu serwisu.

## Migracja i dane startowe

Zawartosci `seed.sql` nie da sie wgrac skryptem do bazy tresci WEBCON
(pisanie do niej jest zabronione). Powstaje dokument wdrozeniowy
(`docs/deployment/webcon-dictionary.md`) zawierajacy:

- instrukcje utworzenia procesu slownikowego i atrybutow w Designer Studio;
- instrukcje odczytania ID typu formularza i nazw kolumn bazodanowych;
- tabele 10 typow HR i 15 wzorcow (przeniesiona z `seed.sql`) do recznego
  wprowadzenia w slowniku (jednorazowo ok. 15 minut);
- wymagane uprawnienia SQL: konto splittera dostaje `SELECT` na
  `WFElements` i `WFElementDetails` w bazie tresci (lub dedykowany widok).

`seed.sql` oraz tabele `document_type` / `document_pattern` zostaja bez zmian
dla trybu standalone.

## Obsluga bledow

- Blad polaczenia lub zle mapowanie kolumn (nieistniejaca kolumna, brak
  uprawnien) -> wyjatek z czytelnym komunikatem wskazujacym zmienna
  konfiguracyjna; `/api/split` konczy sie statusem 500, a komunikat trafia do
  `splitter_job.technical_error` (obciete do 2000 znakow, jak dzis);
- pusta lista wzorcow (slownik bez wpisow lub wszystko nieaktywne) ->
  zachowanie jak dzis: wszystkie strony klasyfikowane jako
  "Nieznany typ dokumentu", bez bledu;
- wiersz wzorca z pustym naglowkiem -> pomijany (nie da sie go dopasowac),
  logowany jako ostrzezenie.

## Testy

- jednostkowe: parsowanie fraz po srednikach (trim, puste elementy,
  brak srednikow, pole puste), mapowanie krotek SQL na `DocumentPattern`
  (na wstrzyknietych danych, bez polaczenia SQL);
- jednostkowe: wybor implementacji w `build_pattern_repository` dla trzech
  kombinacji konfiguracji;
- jednostkowe: walidacja niekompletnego mapowania kolumn (czytelny blad);
- istniejace testy pipeline'u i klasyfikatora bez zmian - protokol
  `PatternRepository` sie nie zmienia.
