# Obsluga nierozpoznanych stron i fallback LLM - Design

> **REWIZJA 2026-07-11 (po wdrozeniu):** produkcyjnie potwierdzono, ze strony
> kontynuacji czesto nie zawieraja zadnej frazy swojego typu (frazy opisuja
> pierwsze strony), a frazy roznych typow nakladaja sie w naturalnym jezyku
> umow - deterministyczne powinowactwo fraz nie wystarcza jako jedyny sygnal.
> Zmiana zachowania (sekcja "Rewizja: doklejanie z flaga" na koncu): gdy LLM
> jest wylaczony/niepewny, strona bez powinowactwa NIE otwiera serii nieznanej,
> jesli istnieje otwarty dokument rozpoznany - jest do niego doklejana,
> a dokument dostaje wymuszone `requiresReview: true`. Serie nieznane wystepuja
> odtad wylacznie przed pierwszym rozpoznanym dokumentem. LLM pozostaje
> wlasciwym mechanizmem rozdzielania obcych wtracen.

## Cel

Nierozpoznane strony i zakresy stron maja byc poprawnie obslugiwane w kazdym
miejscu paczki (poczatek, srodek, koniec): trafiac do wynikow jako osobne
dokumenty "Nieznany typ dokumentu" wymagajace weryfikacji, zamiast ginac
z wynikow (poczatek paczki) albo doklejac sie po cichu do poprzedniego
dokumentu (srodek i koniec). Dodatkowo lokalny LLM - przewidziany w pierwotnym
projekcie, ale dotad niewpiety - ma pomagac klasyfikowac strony, ktorych
reguly nie rozpoznaly.

Problemy dzisiejszego pipeline'u:

- strony przed pierwsza wykryta "pierwsza strona" nie naleza do zadnego
  dokumentu wynikowego (gina z wynikow podzialu);
- nieznane strony w srodku/na koncu sa doklejane do poprzedniego dokumentu;
  jesli mial pewnosc >= progu, element przechodzi jako auto-zaakceptowany
  z zawyzonym zakresem stron i bez flagi weryfikacji;
- flaga `SPLITTER_LLM_ENABLED` jest ignorowana - `api.py` wpina na sztywno
  `DisabledLlmClassifier`, a pipeline przekazuje LLM-owi pusta liste znanych
  typow.

## Kluczowa decyzja: powinowactwo fraz

Druga i kolejne strony wielostronicowego dokumentu nie zawieraja naglowka
wzorca - dla klasyfikatora wygladaja jak strony obcego dokumentu. Sygnalem
roznicujacym jest obecnosc fraz wzorca: strony kontynuacji zwykle zawieraja
frazy swojego typu, strony obcego pisma - nie.

Rozwazane warianty:

1. **Powinowactwo fraz (wybrany)** - strona bez naglowka, ale z >=1 fraza
   wzorcow typu biezacego dokumentu = kontynuacja; strona bez zadnego
   dopasowania otwiera serie nieznana. Wielostronicowe dokumenty zostaja
   scale, obce wtracenia sa wydzielane; przypadki graniczne trafiaja do
   weryfikacji zamiast zginac po cichu.
2. Zachowawczo (doklejanie + flaga review) - odrzucony: obce wtracenia nadal
   laduja w cudzym pliku PDF.
3. Kazda seria nieznanych = osobny dokument - odrzucony: posiekalby
   wielostronicowe dokumenty na strony.

## Reguly grupowania

Sekwencyjny przebieg po stronach:

- strona z klasyfikacja "pierwsza strona" (regulowa lub z LLM) otwiera nowy
  dokument rozpoznanego typu;
- strona niebedaca pierwsza strona:
  - jesli istnieje otwarty dokument rozpoznany i strona ma powinowactwo do
    jego typu (>=1 fraza ktoregokolwiek wzorca tego typu, frazy wykluczajace
    honorowane) -> kontynuacja tego dokumentu;
  - w przeciwnym razie -> nalezy do serii "Nieznany typ dokumentu"; seria
    trwa az do nastepnej pierwszej strony (strona "wracajaca" frazami do
    poprzedniego typu NIE skleja go z powrotem - zakresy musza byc ciagle,
    a taki przypadek i tak idzie do weryfikacji);
- kazda seria nieznana staje sie osobnym dokumentem: typ
  "Nieznany typ dokumentu", pewnosc 0.20, `requiresReview: true`,
  sygnal `unknown_run`;
- kazda strona paczki nalezy do dokladnie jednego dokumentu - zakresy sa
  ciagle, bez dziur i nakladek (suma zakresow = wszystkie strony);
- cala paczka nierozpoznana -> jeden dokument "Nieznany typ dokumentu"
  (wynika z regul naturalnie; specjalny przypadek `forced_first_page` znika);
- dokumenty rozpoznane zachowuja sie jak dotychczas (auto-akceptacja wg
  pewnosci pierwszej strony);
- do `SplitResult.warnings` trafia wpis per seria nieznana, np.
  "Strony 3-4: nierozpoznany dokument".

## Fallback LLM

Polityka wywolan (wybrana sposrod: kazda strona ponizej progu auto-akceptacji
vs tylko strony bez dopasowania): **LLM jest wolany wylacznie dla stron,
ktore reguly i powinowactwo zostawily jako nieznane**. Wielostronicowy
dokument z frazami na kolejnych stronach nie generuje zadnych wywolan LLM.

- `api.py` wybiera klasyfikator wg konfiguracji: `llm_enabled=True` oraz
  niepuste `llm_endpoint` i `llm_model` -> `OpenAiCompatibleLlmClassifier`;
  inaczej `DisabledLlmClassifier`. Bez LLM cala reszta projektu dziala
  (strony nieznane ida do serii nieznanych).
- Nowe ustawienie `llm_timeout_seconds` (`SPLITTER_LLM_TIMEOUT_SECONDS`,
  domyslnie 30) przekazywane do konstruktora `OpenAiCompatibleLlmClassifier`
  (parametr `timeout_seconds` juz istnieje).
- Pipeline przekazuje LLM-owi rzeczywista liste znanych typow (unikalne
  `document_type` z aktywnych wzorcow).
- Werdykt LLM dla strony nieznanej:
  - `isFirstPage=true` i pewnosc >= `min_review_confidence` -> strona
    otwiera dokument typu `documentType` z pewnoscia LLM (o `requiresReview`
    decyduje prog auto-akceptacji, jak dla regul);
  - `isFirstPage=false` i `documentType` zgodny z typem otwartego dokumentu
    rozpoznanego i pewnosc >= `min_review_confidence` -> kontynuacja tego
    dokumentu; dotyczy wylacznie sytuacji, gdy dokument rozpoznany jest
    segmentem bezposrednio poprzedzajacym strone (jesli otwarta jest juz
    seria nieznana, strona zostaje w serii - zakresy musza byc ciagle);
  - brak odpowiedzi, blad, timeout lub pewnosc ponizej
    `min_review_confidence` -> strona zostaje w serii nieznanej;
- blad/timeout LLM nie przerywa zadania - jest logowany (logging), strona
  traktowana jak bez LLM;
- sygnaly stron klasyfikowanych przez LLM: `llm:<reasonCode>` (jak w
  istniejacym kodzie pipeline'u).

## Zakres zmian w kodzie

- `splitter/src/webcon_pdf_splitter/classification/rules.py`:
  `PageClassification` dostaje pole `phrase_affinities: set[str]` (typy
  z >=1 trafiona fraza, liczone w istniejacej petli po wzorcach; wzorzec
  z trafiona fraza wykluczajaca nie liczy sie do powinowactwa).
- `splitter/src/webcon_pdf_splitter/classification/pipeline.py`: nowa logika
  grupowania (sekwencyjna, wg regul wyzej) zamiast pary "first_pages +
  doklejanie"; wywolania LLM tylko dla stron nieznanych; przekazywanie listy
  znanych typow; warnings per seria nieznana.
- `splitter/src/webcon_pdf_splitter/api.py`: wybor klasyfikatora LLM wg
  ustawien (`llm_enabled`, `llm_endpoint`, `llm_model`,
  `llm_timeout_seconds`).
- `splitter/src/webcon_pdf_splitter/config.py`: nowe pole
  `llm_timeout_seconds: int = 30`.
- `docs/deployment/splitter-service.md`: wiersz `SPLITTER_LLM_TIMEOUT_SECONDS`
  w tabeli zmiennych oraz krotka sekcja o wymaganym lokalnym serwerze LLM
  (Ollama/vLLM jako osobny kontener/proces; przyklad endpointu).
- Kontrakty, plugin SDK, baza danych - bez zmian. Elementy "Nieznany typ
  dokumentu" przychodza do WEBCON-a istniejaca sciezka z komentarzem
  `requires review: true`.

## Poza zakresem

- zmiany w pluginie SDK i kontraktach API;
- uczenie wzorcow z feedbacku;
- konfigurowalny prog powinowactwa (na start: >=1 fraza);
- scalanie rozdzielonych fragmentow tego samego dokumentu (zakresy ciagle).

## Testy

Pipeline (jednostkowe, na tekstach stron, LLM jako stub):

- obce wtracenie w srodku -> 3 dokumenty z poprawnymi zakresami
  (rozpoznany / nieznany / rozpoznany);
- nieznane strony na poczatku -> osobny dokument nieznany + kolejne
  dokumenty bez przesuniecia zakresow;
- nieznany ogon na koncu -> osobny dokument nieznany;
- cala paczka nierozpoznana -> jeden dokument nieznany, status
  `requires_review`;
- wielostronicowy dokument z frazami na kolejnych stronach -> jeden dokument
  (kontynuacje nie sa wydzielane), zero wywolan LLM (licznik stuba);
- strona z frazami obcego typu (bez naglowka) -> seria nieznana;
- w kazdym tescie grupowania: suma zakresow pokrywa wszystkie strony,
  bez dziur i nakladek;
- LLM-stub klasyfikuje nieznana strone jako pierwsza strone znanego typu ->
  osobny rozpoznany dokument;
- LLM-stub wskazuje kontynuacje biezacego typu -> doklejenie do dokumentu;
- LLM-stub rzuca wyjatek -> zachowanie identyczne jak bez LLM;
- LLM-stub zwraca pewnosc ponizej `min_review_confidence` -> strona zostaje
  nieznana;
- api: fabryka klasyfikatora LLM wg ustawien (enabled+endpoint+model ->
  OpenAiCompatible; inaczej Disabled);
- istniejace testy API przechodza bez zmian; test grupowania
  `test_pipeline_groups_pages_between_detected_first_pages` jest
  zaktualizowany do nowego kontraktu (wzorce dostaja frazy, strony
  kontynuacji je zawieraja) - jego dotychczasowa postac (kontynuacja bez
  zadnej frazy) opisuje wlasnie zachowanie, ktore celowo zmieniamy.

## Rewizja: doklejanie z flaga (2026-07-11)

Drabinka decyzyjna dla strony niebedacej pierwsza strona:

1. powinowactwo do typu otwartego dokumentu rozpoznanego -> kontynuacja
   (bez zmian);
2. LLM (gdy wlaczony) -> werdykt jak w sekcji "Fallback LLM" (bez zmian);
3. **nowosc:** brak powinowactwa i brak pewnego werdyktu LLM:
   - jesli otwarty segment to dokument rozpoznany -> strona jest doklejana
     do niego, segment dostaje wymuszone `requiresReview: true` (niezaleznie
     od pewnosci pierwszej strony), sygnal `glued_unknown_page:<nr>` oraz
     wpis w warnings: "Strona <nr>: brak dopasowania - doklejona do
     dokumentu '<typ>', wymagana weryfikacja";
   - jesli nie ma otwartego dokumentu rozpoznanego (poczatek paczki albo
     trwajaca seria nieznana) -> seria "Nieznany typ dokumentu" jak dotad.

Konsekwencje:

- serie nieznane wystepuja wylacznie na poczatku paczki (przed pierwszym
  rozpoznanym dokumentem) oraz gdy cala paczka jest nierozpoznana;
- bez LLM obce wtracenie w srodku/na koncu laduje w pliku poprzedniego
  dokumentu, ale dokument nigdy nie przejdzie auto-akceptacji - operator
  rozdziela recznie przy weryfikacji;
- z wlaczonym LLM obce wtracenia sa rozdzielane werdyktem modelu
  (isFirstPage=true), a kontynuacje bez fraz potwierdzane
  (isFirstPage=false + zgodny typ);
- testy grupowania "wtracenie w srodku" i "nieznany ogon" zmieniaja
  oczekiwania na doklejanie z flaga; separacja wtracen jest testowana
  ze stubem LLM.
