# WEBCON PDF Splitter - Design

## Cel

Rozwiazanie ma obslugiwac paczki skanow HR, w ktorych jeden zbiorczy plik PDF zawiera kilka roznych dokumentow. System ma lokalnie przeanalizowac PDF, wykryc granice dokumentow, podzielic plik na osobne PDF-y i utworzyc dla nich osobne elementy w WEBCON BPS.

Priorytety:

- dane HR nie opuszczaja infrastruktury firmy;
- WEBCON pozostaje glownym systemem procesu, uprawnien, historii i repozytorium dokumentow;
- OCR, analiza dokumentow i ewentualny lokalny LLM sa wydzielone do lokalnego serwisu;
- system startuje z baza znanych typow dokumentow, ale moze uczyc sie nowych wzorcow po korektach operatora;
- decyzje o niskiej pewnosci trafiaja do weryfikacji czlowieka.

## Zakres

W zakresie:

- niestandardowa akcja WEBCON uruchamiana na elemencie "Paczka skanu";
- lokalny serwis PDF Splitter;
- lokalny OCR;
- klasyfikacja stron jako poczatek dokumentu / kontynuacja dokumentu;
- podzial PDF na osobne pliki;
- utworzenie osobnych elementow WEBCON dla dokumentow wynikowych;
- zapis metadanych rozpoznania, pewnosci, logu i relacji do paczki zrodlowej;
- mechanizm korekty i uczenia wzorcow po akceptacji operatora.

Poza zakresem pierwszej wersji:

- pelna ekstrakcja wszystkich danych kadrowych z dokumentow;
- automatyczne podpisywanie lub archiwizacja kwalifikowana;
- trenowanie wlasnego modelu OCR od zera;
- integracje chmurowe lub wysylanie skanow poza infrastrukture firmy.

## Rekomendowana architektura

System sklada sie z trzech warstw:

1. WEBCON BPS
   - przechowuje element paczki skanu;
   - przechowuje oryginalny zbiorczy PDF;
   - uruchamia akcje "Podziel PDF";
   - tworzy elementy dokumentow wynikowych;
   - obsluguje weryfikacje operatora, statusy, uprawnienia i raportowanie.

2. WEBCON Custom Action
   - cienka warstwa integracyjna;
   - pobiera wskazany zalacznik PDF z elementu;
   - przekazuje go do lokalnego serwisu PDF Splitter;
   - odbiera wynik analizy;
   - tworzy elementy potomne i dodaje do nich wynikowe PDF-y;
   - zapisuje status i log przetwarzania na elemencie paczki.

3. Lokalny serwis PDF Splitter
   - dziala jako wewnetrzne HTTP API lub proces wywolywany przez akcje;
   - wykonuje OCR, klasyfikacje i fizyczny podzial PDF;
   - korzysta z dedykowanej bazy rozwiazania na SQL Serverze;
   - moze korzystac z lokalnego LLM jako modulu pomocniczego;
   - nie komunikuje sie z uslugami zewnetrznymi.

## Model procesu w WEBCON

### Element "Paczka skanu"

Element reprezentuje jeden zbiorczy skan. Zawiera:

- oryginalny PDF;
- status przetwarzania;
- liczbe stron;
- liczbe wykrytych dokumentow;
- wynik ostatniej analizy;
- informacje o bledach;
- liste powiazanych elementow dokumentow wynikowych.

Proponowane statusy:

- `Nowa paczka`;
- `W trakcie analizy`;
- `Podzielona automatycznie`;
- `Wymaga weryfikacji`;
- `Zakonczona`;
- `Blad przetwarzania`.

### Element "Dokument HR"

Kazdy wykryty dokument jest osobnym elementem WEBCON. Zawiera:

- pojedynczy PDF jako zalacznik;
- typ dokumentu;
- zakres stron w oryginalnym PDF;
- poziom pewnosci rozpoznania;
- identyfikator paczki zrodlowej;
- status weryfikacji;
- opcjonalne metadane wykryte z OCR, np. imie i nazwisko, numer pracownika, data dokumentu.

Proponowane statusy:

- `Rozpoznany automatycznie`;
- `Do weryfikacji`;
- `Zweryfikowany`;
- `Odrzucony / scalony z innym`;
- `Przekazany do procesu docelowego`.

## Przeplyw przetwarzania

1. Uzytkownik dodaje zbiorczy PDF do elementu "Paczka skanu".
2. WEBCON uruchamia akcje "Podziel PDF" recznie lub automatycznie na sciezce.
3. Akcja ustawia status paczki na `W trakcie analizy`.
4. Akcja przekazuje PDF do lokalnego serwisu PDF Splitter.
5. Splitter renderuje strony i wykonuje OCR.
6. Splitter analizuje kazda strone:
   - czy strona wyglada jak poczatek dokumentu;
   - jaki to typ dokumentu;
   - z jaka pewnoscia podjeto decyzje;
   - czy potrzebna jest weryfikacja.
7. Splitter wyznacza grupy stron i tworzy osobne PDF-y.
8. Splitter zwraca do akcji wynik analizy oraz pliki wynikowe.
9. Akcja tworzy osobne elementy "Dokument HR" i dodaje do nich PDF-y.
10. Akcja zapisuje relacje dokumentow do paczki zrodlowej.
11. Jesli wszystkie decyzje maja wysoka pewnosc, paczka przechodzi do `Podzielona automatycznie`.
12. Jesli przynajmniej jedna decyzja ma niska pewnosc, paczka lub dokument trafia do `Wymaga weryfikacji`.
13. Operator poprawia typ, granice stron lub laczenie dokumentow.
14. Zatwierdzone korekty aktualizuja lokalna baze wzorcow.

## Strategia rozpoznawania dokumentow

System powinien korzystac z podejscia hybrydowego:

1. Reguly deterministyczne
   - rozpoznanie znanych naglowkow;
   - slowniki nazw dokumentow;
   - normalizacja bledow OCR;
   - dopasowanie tekstu z pierwszej czesci strony;
   - wykrywanie pustych stron lub stron separatorow, jesli wystepuja.

2. Klasyfikator semantyczny
   - porownanie tekstu strony z baza znanych typow dokumentow;
   - podobienstwo naglowkow i fragmentow formularzy;
   - ocena, czy strona jest pierwsza strona dokumentu czy kontynuacja.

3. Lokalny LLM jako fallback
   - uzywany tylko przy niepewnych przypadkach;
   - otrzymuje tekst OCR strony, ewentualnie tekst poprzedniej i nastepnej strony;
   - odpowiada strukturalnie, bez swobodnego generowania nazw plikow lub decyzji bez confidence;
   - nie podejmuje ostatecznych decyzji przy niskiej pewnosci, tylko kieruje do weryfikacji.

Pierwsza wersja nie musi uzywac lokalnego LLM dla kazdej strony. Efektywniejsze jest uzycie go tylko tam, gdzie reguly i klasyfikator nie sa wystarczajaco pewne.

## Lokalny LLM

Lokalny LLM powinien byc traktowany jako modul decyzyjny drugiego poziomu, a nie jako podstawowy mechanizm podzialu PDF. Podstawowa decyzja powinna wynikac z OCR, regul, dopasowania naglowkow i bazy wzorcow. LLM dostaje tylko przypadki niepewne, dzieki czemu system jest tanszy obliczeniowo, szybszy i bardziej przewidywalny.

Rekomendowany sposob integracji:

- splitter komunikuje sie z lokalnym endpointem LLM przez interfejs zgodny z OpenAI Chat Completions albo prosty adapter dla Ollama/vLLM;
- LLM nie dostaje pliku PDF ani obrazow w MVP, tylko tekst OCR z aktualnej strony oraz ograniczony kontekst: poprzednia strona, nastepna strona, lista znanych typow dokumentow;
- prompt wymusza odpowiedz w scislym JSON;
- odpowiedz LLM jest walidowana schematem przed uzyciem;
- decyzja LLM nigdy nie nadpisuje reguly wysokiej pewnosci;
- decyzja LLM o niskiej pewnosci ustawia `requiresReview = true`.

Przykladowy kontrakt odpowiedzi LLM:

```json
{
  "isFirstPage": true,
  "documentType": "Aneks do umowy",
  "isKnownType": true,
  "confidence": 0.82,
  "reasonCodes": [
    "title_indicates_document_type",
    "contains_employee_contract_reference"
  ],
  "suggestedNewPatterns": [
    "ANEKS DO UMOWY O PRACE"
  ]
}
```

LLM powinien byc wolany tylko, gdy zachodzi co najmniej jeden warunek:

- klasyfikator regulowy ma confidence ponizej progu automatycznej akceptacji;
- strona wyglada jak poczatek dokumentu, ale typ nie jest znany;
- dwie sasiednie strony wygladaja jak mozliwe poczatki dokumentow;
- OCR znalazl naglowek, ktory nie pasuje do zadnego aktywnego wzorca;
- operator oznaczyl podobny przypadek jako problematyczny w historii feedbacku.

Domyslnie MVP moze miec LLM wylaczony flaga konfiguracyjna `LLM_ENABLED=false`. Kod powinien jednak miec interfejs `LlmClassifier`, zeby wlaczenie lokalnego modelu nie wymagalo przebudowy pipeline'u.

## Baza rozwiazania

Baza rozwiazania powinna dzialac na SQL Serverze, najlepiej na tym samym serwerze infrastrukturalnym, na ktorym dzialaja bazy WEBCON. Zalecane jest utworzenie oddzielnej bazy, np. `WebconPdfSplitter`, zamiast dopisywania tabel technicznych bezposrednio do baz systemowych WEBCON.

Ta baza przechowuje typy dokumentow, wzorce rozpoznawania, feedback operatorow, konfiguracje progow pewnosci i logi techniczne splittera. WEBCON pozostaje systemem procesu i dokumentow, a dedykowana baza jest magazynem wiedzy oraz audytu dla komponentu rozpoznawania.

Minimalny model:

- `document_type`
  - identyfikator;
  - nazwa typu;
  - aktywny / nieaktywny;
  - prog pewnosci automatycznej akceptacji;
  - domyslny workflow docelowy w WEBCON;
  - domyslna kategoria zalacznika.

- `document_pattern`
  - typ dokumentu;
  - przykladowy naglowek;
  - frazy charakterystyczne;
  - frazy wykluczajace;
  - waga wzorca;
  - data ostatniej aktualizacji;
  - zrodlo: konfiguracja startowa albo korekta operatora.

- `classification_feedback`
  - identyfikator paczki;
  - numer strony;
  - decyzja systemu;
  - decyzja operatora;
  - data korekty;
  - operator;
  - czy korekta zostala uzyta do aktualizacji wzorca.

- `splitter_job`
  - identyfikator zadania;
  - identyfikator elementu paczki w WEBCON;
  - nazwa pliku zrodlowego;
  - status;
  - data rozpoczecia;
  - data zakonczenia;
  - liczba stron;
  - liczba wykrytych dokumentow;
  - komunikat bledu technicznego.

## Format odpowiedzi splittera

Akcja WEBCON powinna dostac wynik w formacie strukturalnym. Przykladowy kontrakt:

```json
{
  "sourceFileName": "scan_2026_000123.pdf",
  "pageCount": 28,
  "status": "requires_review",
  "documents": [
    {
      "documentIndex": 1,
      "documentType": "Umowa o prace",
      "confidence": 0.94,
      "requiresReview": false,
      "startPage": 1,
      "endPage": 7,
      "outputFileName": "001_Umowa_o_prace.pdf",
      "signals": [
        "header_match:UMOWA O PRACE",
        "first_page_score:0.96"
      ],
      "metadata": {
        "employeeName": "Jan Kowalski",
        "documentDate": "2026-06-30"
      }
    },
    {
      "documentIndex": 2,
      "documentType": "Nieznany typ dokumentu",
      "confidence": 0.61,
      "requiresReview": true,
      "startPage": 8,
      "endPage": 11,
      "outputFileName": "002_Do_weryfikacji.pdf",
      "signals": [
        "possible_new_header",
        "low_type_confidence"
      ],
      "metadata": {}
    }
  ],
  "warnings": []
}
```

Pliki wynikowe moga byc zwracane jako:

- archiwum ZIP zawierajace PDF-y i `result.json`;
- odpowiedz multipart;
- zapis do bezpiecznego katalogu roboczego plus zwrocenie identyfikatora zadania.

Najbardziej odporne operacyjnie jest podejscie asynchroniczne: akcja tworzy zadanie, splitter przetwarza je lokalnie, a WEBCON pobiera wynik po zakonczeniu albo cyklicznie sprawdza status.

## Tryb synchroniczny i asynchroniczny

### Tryb synchroniczny

Akcja czeka na wynik splittera w jednym wywolaniu.

Zalety:

- prostsza pierwsza wersja;
- mniej elementow infrastruktury;
- latwiejsze debugowanie.

Wady:

- ryzyko timeoutow;
- slabsze dla duzych PDF-ow;
- trudniejsza obsluga kolejek i retry.

### Tryb asynchroniczny

Akcja rejestruje zadanie, a osobna akcja lub mechanizm cykliczny odbiera wynik.

Zalety:

- lepsze dla produkcji;
- odporne na dluzsze OCR;
- mozna kolejkowac zadania;
- mozna latwiej wznawiac po bledach.

Wady:

- wieksza zlozonosc wdrozenia;
- potrzeba modelu statusow zadania.

Rekomendacja: pierwsze MVP moze byc synchroniczne, ale projekt interfejsu powinien od razu przewidywac przejscie na tryb asynchroniczny.

## Progi pewnosci

Proponowane progi startowe:

- `>= 0.90`: automatyczne utworzenie dokumentu bez wymogu weryfikacji;
- `0.70 - 0.89`: utworzenie dokumentu, ale oznaczenie jako `Do weryfikacji`;
- `< 0.70`: paczka trafia do weryfikacji granic przed finalnym utworzeniem dokumentow docelowych.

Progi powinny byc konfigurowalne globalnie i per typ dokumentu.

## Obsluga bledow

Akcja WEBCON powinna rozrozniac co najmniej:

- brak zalacznika PDF;
- wiecej niz jeden PDF bez wskazania pliku zrodlowego;
- PDF zabezpieczony haslem;
- PDF uszkodzony;
- blad renderowania strony;
- blad OCR;
- blad klasyfikacji;
- blad podzialu PDF;
- blad tworzenia elementu WEBCON;
- blad dodawania zalacznika wynikowego.

W przypadku bledu:

- oryginalny PDF zostaje nienaruszony;
- paczka dostaje status `Blad przetwarzania`;
- log techniczny jest zapisywany na elemencie lub w tabeli technicznej;
- uzytkownik widzi komunikat biznesowy bez szczegolow infrastrukturalnych;
- administrator ma dostep do pelnego logu korelacyjnego.

## Nazewnictwo plikow

Nazwy wynikowych PDF-ow powinny byc deterministyczne i bezpieczne dla systemu plikow:

`{kolejnosc}_{typ_dokumentu}_{zakres_stron}.pdf`

Przyklad:

- `001_Umowa_o_prace_strony_001-007.pdf`
- `002_Aneks_strony_008-010.pdf`
- `003_Do_weryfikacji_strony_011-014.pdf`

Jesli z OCR uda sie pewnie wykryc pracownika lub date dokumentu, te dane moga trafic do metadanych WEBCON, ale nie powinny byc wymagane do nazwy pliku w pierwszej wersji.

## Bezpieczenstwo

Wymagania:

- brak wysylania PDF-ow do zewnetrznych uslug;
- lokalny OCR i lokalny LLM;
- katalog roboczy splittera czyszczony po zakonczeniu zadania;
- kontrola rozmiaru i liczby stron PDF;
- logi nie powinny zawierac pelnej tresci dokumentow HR;
- komunikacja WEBCON - splitter po HTTPS albo przez lokalny bezpieczny kanal;
- uwierzytelnienie akcji do splittera tokenem technicznym lub certyfikatem;
- osobna konfiguracja retencji plikow tymczasowych.

## Testowanie

Minimalny zestaw testow:

- PDF z jednym dokumentem;
- PDF z kilkoma znanymi typami dokumentow;
- PDF z nowym typem dokumentu;
- PDF z nieczytelnym skanem;
- PDF z pusta strona;
- PDF z blednie obrocona strona;
- PDF z dokumentem wielostronicowym bez naglowka na kolejnych stronach;
- PDF zabezpieczony haslem;
- PDF uszkodzony;
- przypadek, w ktorym operator poprawia granice dokumentu.

Kryteria akceptacji MVP:

- system dzieli paczke na osobne PDF-y zgodnie z naglowkami pierwszych stron;
- tworzy osobne elementy WEBCON dla kazdego dokumentu;
- zachowuje relacje z paczka zrodlowa;
- dokumenty o niskiej pewnosci trafiaja do weryfikacji;
- korekty operatora sa zapisywane jako feedback;
- oryginalny PDF nigdy nie jest usuwany ani nadpisywany.

## Decyzje projektowe

1. WEBCON tworzy osobne elementy dla dokumentow wynikowych.
   - Uzasadnienie: najlepsze wykorzystanie workflow, uprawnien, historii, raportowania i wyszukiwania.

2. OCR i LLM nie sa wykonywane bezposrednio w akcji WEBCON.
   - Uzasadnienie: mniejsze ryzyko timeoutow, prostsze utrzymanie zaleznosci i lepsza skalowalnosc.

3. Lokalny LLM jest opcjonalnym fallbackiem, nie jedynym mechanizmem decyzyjnym.
   - Uzasadnienie: lepsza przewidywalnosc, nizszy koszt obliczeniowy i latwiejsze wyjasnianie decyzji.

4. System przy niskiej pewnosci wymaga weryfikacji operatora.
   - Uzasadnienie: dokumenty HR sa danymi wrazliwymi, a bledny podzial moze miec skutki procesowe.

5. Baza rozwiazania dziala na SQL Serverze i jest rozszerzana po zatwierdzonych korektach.
   - Uzasadnienie: system moze startowac szybko, ale poprawia sie wraz z realnymi przypadkami.

## Domyslne wybory dla MVP

Na potrzeby pierwszego planu implementacji przyjmujemy nastepujace wybory:

- akcja WEBCON: C# Custom Action zgodna z wersja SDK uzywana w srodowisku klienta;
- tworzenie elementow wynikowych: preferowane przez mechanizmy WEBCON dostepne w SDK; REST API jest wariantem zapasowym, jesli dana instalacja ma wygodniejszy lub bezpieczniejszy model uprawnien dla operacji na elementach i zalacznikach;
- lokalny splitter: Python + FastAPI jako wewnetrzne HTTP API;
- baza rozwiazania: dedykowana baza SQL Server, np. `WebconPdfSplitter`, na tym samym serwerze SQL, na ktorym dzialaja bazy WEBCON;
- OCR: Tesseract jako wariant startowy, z interfejsem pozwalajacym podmienic silnik na ABBYY lokalnie lub PaddleOCR;
- tryb pracy: synchroniczny dla MVP przy malych paczkach, ale z kontraktem odpowiedzi przygotowanym pod tryb asynchroniczny;
- ekran korekty: natywny formularz WEBCON z tabela wykrytych dokumentow i polami: typ, strona poczatkowa, strona koncowa, status weryfikacji, uwagi;
- lokalny LLM: wylaczony domyslnie w MVP, gotowy jako modul fallback po zebraniu probek i ustaleniu lokalnego endpointu.

Przed kodowaniem trzeba potwierdzic tylko parametry srodowiskowe: wersje WEBCON BPS, sposob autoryzacji akcji do splittera, limity wielkosci PDF oraz docelowy katalog lub wolumen na pliki tymczasowe.

## Rekomendacja MVP

MVP powinno obejmowac:

- akcje WEBCON "Podziel PDF";
- lokalny splitter jako HTTP API;
- OCR lokalny;
- reguly i semantyczne dopasowanie naglowkow;
- fizyczny podzial PDF;
- tworzenie elementow dokumentow wynikowych w WEBCON;
- status `Do weryfikacji` dla niepewnych dokumentow;
- zapis feedbacku operatora.

Nie nalezy zaczynac od pelnego automatycznego uczenia ani od ciezkiego LLM dla kazdej strony. Najpierw trzeba zbudowac stabilny pipeline, logowanie, podzial i petle korekty. Lokalny LLM mozna wlaczyc jako modul fallback po zebraniu pierwszych przykladow.
