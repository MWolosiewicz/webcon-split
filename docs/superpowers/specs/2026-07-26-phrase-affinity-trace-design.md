# Slad przy doklejaniu strony po powinowactwie fraz - Design

## Cel

Doklejenie strony do biezacego dokumentu na podstawie trafionej frazy jest dzis
**jedyna sciezka w calym pipelinie, ktora nie zostawia po sobie zadnego sladu**.
Ta zmiana doklada zapis - i tylko zapis.

Stan obecny (`classification/pipeline.py`, galaz "kontynuacja po frazach"):

```python
if current is not None and current.known and current.document_type in page.phrase_affinities:
    current.end_page = page_number
    logger.info("Strona %s: kontynuacja '%s' (dopasowanie fraz)", page_number, current.document_type)
    continue
```

Strona zostaje wchlonieta przez biezacy dokument bez wywolania LLM, bez
`requiresReview`, bez wpisu w `signals`, bez wpisu w `warnings` i bez podania
w logu, ktora fraza o tym zdecydowala. Wszystkie pozostale sciezki cos zapisuja:
`header_match:<naglowek>`, `phrase_hits:<n>`, `llm:<kod>`, `glued_unknown_page:N`,
`unknown_run`, `no_pattern_match`.

Skutek praktyczny (wykryty 2026-07-11 na realnej paczce): strona INNEGO dokumentu
nieznanego typu - np. zaswiadczenie o zatrudnieniu przy slowniku bez tego typu -
zawierajaca generyczna fraze biezacego typu ("pracownik", "wynagrodzenie") jest
uznawana za zwykla kontynuacje. Operator nie ma jak tego zobaczyc inaczej niz
czytajac PDF.

## Niezmiennik nadrzedny: zero zmian w decyzjach

Segmentacja, `requiresReview`, `confidence`, `removedPages` i `warnings` musza
pozostac **identyczne** dla kazdego wejscia. To jest kryterium akceptacji, nie
deklaracja intencji: istniejace testy segmentacji przechodza **bez modyfikacji**,
a nowy test pilnuje, ze dokument zlozony z samych kontynuacji po frazach nadal
ma `requiresReview == False`.

Powod rozdzielenia: pytanie "kiedy powinowactwo fraz jest za slabe, zeby uzasadnic
doklejenie" jest realnym problemem projektowym, ktory wymaga danych z produkcji.
Tych danych dzis nie ma, bo nikt ich nie zbiera. Ten spec dostarcza dane; decyzja
o zmianie progu to osobny temat, ktory bedzie mial na czym sie oprzec.

## Decyzja 1: slad niesie strone I fraze

Sam numer strony ("strona 7 zostala doklejona") mowi, ze cos sie stalo, ale nie
daje operatorowi nic do zrobienia. Dopiero fraza wskazuje **pozycje slownika do
poprawienia**: skoro doklejenie spowodowalo slowo "wynagrodzenie", to ta fraza
jest za generyczna dla swojego typu i nalezy ja usunac, uszczegolowic albo
zrownowazyc przez `excludedPhrases`.

Fraza jest zapisywana w **oryginalnym brzmieniu ze slownika**, nie znormalizowana.
Operator ma rozpoznac to, co sam wpisal (`wynagrodzenie`, nie `WYNAGRODZENIE`).
Ma to dodatkowe znaczenie przy zalecanej praktyce wpisywania rdzeni: gdy
w slowniku siedzi `ZASWIADCZ`, operator musi zobaczyc dokladnie `ZASWIADCZ`,
zeby trafic do wlasciwego wiersza.

## Decyzja 2: grupowanie po frazie, nie po stronie

Format wpisu w `signals`:

```
phrase_continuation:wynagrodzenie(7,8,11)
```

Jeden wpis na fraze, lista stron w nawiasie. Alternatywa (jeden wpis na strone,
spojna z istniejacym `glued_unknown_page:N`) zostala odrzucona: w 30-stronicowej
umowie prawie kazda strona jest kontynuacja po frazach, wiec komentarz dziecka
stalby sie sciana tekstu i utopil pozostale sygnaly.

Przy grupowaniu liczba wpisow jest ograniczona **liczba fraz danego typu
w slowniku** (typowo 3-8), a nie liczba stron - dokument dowolnej dlugosci daje
staly, maly zestaw wpisow. Grupowanie idzie po jednostce, ktora operator realnie
poprawia (fraza), a nie po jednostce, ktorej nie da sie poprawic (strona).

Determinizm wymagany przez testy: frazy w kolejnosci pierwszego wystapienia
(slowniki w Pythonie zachowuja kolejnosc wstawiania), numery stron rosnaco.

Format `nazwa:wartosc` trzyma sie konwencji istniejacych sygnalow. Wartosc jest
czytana przez czlowieka, nie parsowana - fraza zawierajaca dwukropek lub nawias
nie psuje niczego poza czytelnoscia.

## Decyzja 3: `phrase_affinities` jako slownik

`PageClassification.phrase_affinities` zmienia typ z `set[str]` na
`dict[str, list[str]]` - typ dokumentu na liste fraz, ktore trafily.

Kluczowa obserwacja: **oba miejsca uzycia dzialaja na slowniku bez zmiany kodu.**
`current.document_type in page.phrase_affinities` to sprawdzenie klucza,
a `sorted(page.phrase_affinities)` sortuje klucze. Zmiana jest wiec ograniczona
do miejsca powstania danych i do konsumenta nowej informacji.

Odrzucone alternatywy:

- **osobne pole `matched_phrases` obok `phrase_affinities`** - zero zepsutych
  testow, ale dwa pola niosace te sama informacje, ktore musza pozostac zgodne;
  klasyczne miejsce na przyszly rozjazd;
- **dataklasa `PhraseAffinity(document_type, phrases)` i lista takich** -
  najbardziej opisowe, ale wymaga przepisania obu miejsc uzycia i psuje te same
  testy, tylko drozej.

Dwa szczegoly do utrzymania w `RuleBasedClassifier.classify_page`:

- gdy kilka wierszy slownika dzieli ten sam `DocumentType`, frazy **sumuja sie**,
  nie nadpisuja;
- wykluczenie (`excluded_hit`) nadal ucina wzorzec **przed** dopisaniem
  czegokolwiek do powinowactw - ta kolejnosc juz jest w kodzie i zostaje.

## Gdzie slad NIE trafia

- **`reviewReasons`** - te znacza "sprawdz to", a my swiadomie nie podnosimy
  `requiresReview`; wpis bylby zreszta niewidoczny, bo powody wypelniamy
  wylacznie dla dokumentow z `requiresReview == True`.
- **`warnings`** - dzis oznaczaja anomalie (nierozpoznany dokument, strona
  doklejona BEZ dopasowania, usuniete strony). Doklejenie po frazach to normalna
  praca pipeline'u; wpis tutaj odpalilby sie przy prawie kazdym wielostronicowym
  dokumencie i utopil prawdziwe ostrzezenia.
- **`removedPages`, `confidence`, segmentacja** - patrz niezmiennik nadrzedny.

## Raportowanie

- **`DetectedDocument.signals`**: wpisy `phrase_continuation:<fraza>(<strony>)`.
  `signals` jest **juz** w kontrakcie jako `list[str]` i **juz** trafia do
  komentarza dziecka przez `FormatDetectionComment` w `CollectSplitJobAction`
  (sekcja `sygnaly: ...`). Zero zmian w kontrakcie i w C#.
- **Log techniczny**: linia mowiaca dzis "kontynuacja '%s' (dopasowanie fraz)"
  dostaje liste fraz. To miejsce, w ktore zajrzy administrator strojacy slownik -
  z prefiksem `[job=...]` do korelacji przy rownoczesnych zadaniach.

## Zakres zmian w kodzie

- **`splitter/src/webcon_pdf_splitter/classification/rules.py`**:
  - `PageClassification.phrase_affinities: dict[str, list[str]]` (bylo `set[str]`);
    `field(default_factory=dict)`;
  - `classify_page` zbiera dopasowane frazy zamiast tylko je liczyc
    (`phrase_hits` staje sie `len(matched)`), dopisuje je do powinowactw pod
    kluczem typu dokumentu, sumujac przy powtorzonym typie.
- **`splitter/src/webcon_pdf_splitter/classification/pipeline.py`**:
  - `_Segment` dostaje `phrase_continuations: dict[str, list[int]]`
    (`field(default_factory=dict)`);
  - galaz kontynuacji po frazach dopisuje numer strony pod kazda fraza biezacego
    typu, ktora trafila, i wzbogaca linie logu;
  - budowa `DetectedDocument` formatuje `phrase_continuations` do wpisow
    `signals` (po istniejacych sygnalach segmentu).
- **`splitter/tests/test_rule_classifier.py`**: trzy asercje porownujace
  `phrase_affinities` ze zbiorem przechodza na slownik.
- **C# (`webcon-action/`)**: bez zmian. Nowa paczka pluginu **nie jest potrzebna**.
- **README**: jedno zdanie w sekcji klasyfikacji o nowym sygnale.

## Wdrozenie

Zmiana wylacznie w splitterze, bez dotkniecia kontraktu HTTP. Wchodzi w przebudowe
kontenera, ktora i tak czeka (kontener produkcyjny 8010 stoi na `main`, czyli
przed kolejka zadan). Paczka pluginu bez zmian.

## Poza zakresem

- **Zmiana progu doklejania po frazach** (np. wymaganie 2 trafien zamiast 1,
  wagi fraz, odrzucanie fraz generycznych). To jest cel, dla ktorego zbieramy
  dane - decyzja dopiero po zobaczeniu sladu na realnych paczkach.
- **Odpornosc fraz na odmiane** (lematyzacja, fuzzy, sklejanie przeniesien
  z myslnikiem). Osobny temat z wlasnym specem. Uzasadnienie rozdzielenia: chybiona
  fraza daje falszywy NEGATYW, ktory system juz sygnalizuje glosno (strona spada
  do LLM, a przy braku werdyktu laduje jako `_UnmatchedPage` z wymuszonym
  `requiresReview` i sygnalem `glued_unknown_page`). Ten spec adresuje falszywy
  POZYTYW - fraze, ktora trafila, choc nie powinna. Luki sa rozlaczne.
- **Notatka o rdzeniach fraz w `docs/instrukcja-slownika-typow-dokumentow.md`**
  (dopasowanie jest podciagiem bez granic slow, wiec `ZASWIADCZ` trafia
  w `zaswiadcza`, `zaswiadczyla` i `zaswiadczenie`). Warta zrobienia, ale to
  dokumentacja dla uzytkownikow biznesowych, nie ta zmiana.
- **Agregacja sladu miedzy paczkami** (statystyka "fraza X skleila 40 stron
  w tym miesiacu"). Splitter jest bezstanowy; takie zliczanie nalezy do petli
  uczenia po stronie WEBCON.

## Testy

`rules.py`:

- strona z jedna trafiona fraza -> `phrase_affinities == {"Umowa o prace": ["wynagrodzenie"]}`;
- strona z dwiema trafionymi frazami tego samego typu -> obie na liscie,
  w kolejnosci ze slownika;
- dwa wiersze slownika o tym samym `DocumentType` -> frazy **zsumowane** pod
  jednym kluczem, nie nadpisane;
- wzorzec odciety przez `excludedPhrases` -> nie wnosi do powinowactw nic,
  nawet gdy jego frazy trafily;
- brak trafien -> `phrase_affinities == {}`;
- `phrase_hits` nadal steruje punktacja tak samo jak przed zmiana (regresja
  punktacji: naglowek + 2 frazy przy wadze 1.0 = 1.0).

`pipeline.py`:

- strona doklejona po frazie -> dokument ma sygnal
  `phrase_continuation:wynagrodzenie(2)`;
- trzy strony doklejone ta sama fraza -> **jeden** wpis z lista stron
  `(2,3,4)`, nie trzy wpisy;
- dwie rozne frazy -> dwa wpisy, kolejnosc pierwszego wystapienia;
- **dokument zlozony z samych kontynuacji po frazach ma `requiresReview == False`**
  (straznik niezmiennika nadrzednego);
- strona doklejona po frazie nie wola LLM (regresja
  `test_llm_not_called_for_affine_continuation_pages`);
- dokument bez zadnej kontynuacji po frazach nie ma zadnego wpisu
  `phrase_continuation` (brak pustych/smieciowych sygnalow);
- podzial (`startPage`/`endPage`/`documentType` wszystkich dokumentow) jest
  identyczny jak przed zmiana dla paczki z mieszanymi sciezkami: naglowek,
  kontynuacja po frazach, strona niedopasowana.
