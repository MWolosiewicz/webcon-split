# Instrukcja uzupełniania słownika „Typ dokumentu"

Instrukcja dla osoby prowadzącej słownik typów dokumentów w WEBCON BPS.
Słownik steruje automatycznym podziałem zeskanowanych paczek PDF na osobne
dokumenty — każde pole ma bezpośredni wpływ na to, jak system rozpoznaje
i tnie dokumenty.

## Jak to działa (w skrócie)

1. Skaner tworzy jeden PDF z wieloma dokumentami (np. cała teczka HR).
2. System czyta tekst każdej strony i porównuje go z **wzorcami** ze słownika.
3. Strona, na której znaleziono **nagłówek wzorca**, zaczyna nowy dokument;
   kolejne strony są doklejane do bieżącego dokumentu.
4. Strony, których nie da się dopasować do żadnego wzorca, trafiają do
   „Nieznany typ dokumentu" albo do ręcznej weryfikacji.

**Ważne:** system nie zna żadnych typów „z góry". Wszystko, co rozpoznaje,
pochodzi z tego słownika. Pusty słownik = wszystko ląduje jako „Nieznany typ
dokumentu".

Zmiany w słowniku działają **od następnego uruchomienia podziału** — nie trzeba
niczego restartować ani nikogo prosić o wdrożenie.

## Polskie znaki i wielkość liter — przeczytaj przed wypełnianiem

System przed porównaniem **normalizuje tekst po obu stronach** (i tekst ze
strony PDF, i wpisy ze słownika): usuwa polskie znaki (`ą`→`a`, `ł`→`l`,
`ś`→`s` itd.), zamienia wszystko na wielkie litery i ściska wielokrotne
spacje. W praktyce:

- `Umowa o Pracę`, `UMOWA O PRACE` i `umowa o prace` to **dokładnie ten sam
  wzorzec** — dopasują się do siebie nawzajem;
- literówka w diakrytyku niczego nie psuje, ale literówka w literze już tak
  (`UMOWA O PRACY` ≠ `UMOWA O PRACE`);
- normalizacja łagodzi też błędy OCR na skanach — skaner, który odczyta
  `ą` jako `a`, nadal trafi we wzorzec.

Co z tego wynika — **reguły techniczne** (wpływają na działanie):

- **wielkość liter nie ma żadnego znaczenia** — w żadnym polu wzorca; możesz
  pisać dużymi, małymi lub mieszanie, dopasowanie wyjdzie identyczne;
- **polskie znaki nie mają znaczenia dla dopasowania** — `ę` i `e` to dla
  systemu ta sama litera;
- znaczenie ma **treść**: brakujące/nadmiarowe słowo albo literówka w literze
  (`UMOWA O PRACY` zamiast `UMOWA O PRACE`) psuje dopasowanie.

Osobna sprawa — **Nazwa typu**: to pole w ogóle nie służy do dopasowania,
jest etykietą, którą po podziale widzą ludzie. Wpisuj ją normalnie, z polskimi
znakami: `Umowa o pracę`, `Świadectwo pracy`.

Do tego jedna **konwencja porządkowa** (dobrowolna, bez wpływu na działanie):
we wpisach startowych nagłówki są zapisane wielkimi literami bez polskich
znaków (`UMOWA O PRACE`), a frazy małymi bez polskich znaków
(`rozwiazanie umowy`). Warto się jej trzymać tylko po
to, żeby słownik wyglądał jednolicie i łatwiej było porównywać wpisy między
sobą — ale wpis `Umowa o Pracę` zadziała dokładnie tak samo.

## Budowa słownika

Jeden formularz słownika = **jeden typ dokumentu** (np. „Umowa o pracę").
Formularz ma pola nagłówkowe (opisują typ) oraz listę pozycji „Wzorce"
(każdy wiersz to jeden sposób rozpoznania tego typu — jeden typ może mieć
kilka wzorców).

## Pola nagłówka formularza

### Nazwa typu (tekst) — wymagane

Nazwa, pod którą dokument będzie widoczny po podziale — trafia do komentarza
elementu „Dokument HR" (np. `Type: Umowa o pracę; pages 1-3; ...`) oraz do
listy znanych typów podpowiadanych modelowi językowemu przy stronach
niepewnych.

Zasady:

- polskie znaki **są dozwolone** i wskazane — to nazwa „biznesowa",
  np. `Umowa o pracę`, `Świadectwo pracy`;
- nazwa musi być **unikalna i stała** — jeśli zmienisz nazwę istniejącego typu,
  nowe dokumenty dostaną nową etykietę, a stare zostaną ze starą;
- pisz pełną, jednoznaczną nazwę (nie skrót typu „UoP") — nazwa jest też
  podpowiedzią dla modelu językowego przy trudnych stronach.

### Aktywny (checkbox)

Odznaczenie wyłącza **cały typ razem ze wszystkimi jego wzorcami** — od
następnego podziału strony tego typu przestaną być rozpoznawane.

Używaj zamiast kasowania formularza: wpis zostaje w historii i można go
włączyć z powrotem jednym kliknięciem.

### Próg auto-akceptacji (liczba dziesiętna, domyślnie 0,90)

**Pole rezerwowe — obecnie nieużywane.** System stosuje dziś jeden globalny
próg dla wszystkich typów. Wpisuj `0,90` i nie zmieniaj — pole zacznie działać
w przyszłej wersji (będzie pozwalało zaostrzyć lub poluzować automatyczną
akceptację dla pojedynczego typu).

## Lista pozycji „Wzorce"

Jeden wiersz = jeden wzorzec rozpoznawania. Typ może mieć **kilka wzorców** —
dodawaj osobny wiersz dla każdego wariantu tytułu dokumentu, np. „Umowa
zlecenie" ma dwa wzorce: `UMOWA ZLECENIE` i `UMOWA ZLECENIA`.

### Nagłówek dokumentu (tekst) — najważniejsze pole

Tekst tytułu, jaki faktycznie występuje **na pierwszej stronie** dokumentu,
np. `UMOWA O PRACE`, `SWIADECTWO PRACY`. System szuka go w początkowej części
strony (mniej więcej pierwsze pół strony tekstu). Znaleziony nagłówek to
główny sygnał „tu zaczyna się nowy dokument".

Zasady:

- **wpisuj dokładnie tak, jak drukują to dokumenty** — całą frazę tytułu,
  nie pojedyncze słowo;
- wielkość liter i polskie znaki są obojętne dla dopasowania (patrz sekcja
  „Polskie znaki i wielkość liter"); we wpisach startowych przyjęto zapis
  wielkimi literami bez polskich znaków;
- **pusty nagłówek = wiersz jest ignorowany** — wzorzec bez nagłówka nigdy
  niczego nie rozpozna;
- nagłówek musi być **charakterystyczny** dla typu. Zbyt ogólny (np. samo
  `UMOWA`) złapie też inne typy umów — wtedy ratuj się frazami wykluczającymi
  albo niższą wagą.

### Frazy (tekst, rozdzielane średnikami)

Słowa i zwroty typowe dla treści dokumentu, szukane **na całej stronie**,
np. dla umowy o pracę: `pracodawca; pracownik; wynagrodzenie; wymiar czasu pracy`.

Frazy pełnią dwie role:

1. **Wzmacniają pewność** rozpoznania strony z nagłówkiem (każde trafienie
   dodaje trochę punktów — ale znacznie mniej niż nagłówek).
2. **Sklejają strony kontynuacji**: strona bez żadnego nagłówka, ale
   zawierająca frazę typu bieżącego dokumentu, jest automatycznie doklejana
   do tego dokumentu. To główny mechanizm trzymający wielostronicowe
   dokumenty w całości.

Zasady:

- rozdzielaj **średnikami** (`;`), nie przecinkami; spacje wokół średników
  nie przeszkadzają;
- wpisuj **3–5 fraz** charakterystycznych dla typu;
- lepsze są **zwroty dwu-trzywyrazowe** (`okres wypowiedzenia`,
  `badania profilaktyczne`) niż pojedyncze popularne słowa (`data`, `podpis`),
  które występują wszędzie;
- unikaj fraz wspólnych dla wielu typów — fraza, która pasuje „do wszystkiego",
  może dokleić stronę do niewłaściwego dokumentu;
- wielkość liter i polskie znaki są obojętne dla dopasowania (patrz sekcja
  „Polskie znaki i wielkość liter"); we wpisach startowych przyjęto zapis
  małymi literami bez polskich znaków, np. `rozwiazanie umowy`.

### Frazy wykluczające (tekst, średniki, może być puste)

Jeśli **którakolwiek** fraza wykluczająca występuje na stronie, ten wzorzec
jest dla tej strony **całkowicie pomijany** — nawet gdy nagłówek pasuje.

Typowe zastosowanie: rozdzielenie podobnych typów. Przykład ze wpisów
startowych — wzorzec „Umowa o pracę" ma wykluczenia
`aneks; wypowiedzenie; rozwiazanie umowy`, dzięki czemu aneks do umowy
(który cytuje tytuł „umowa o pracę") nie zostanie rozpoznany jako sama umowa,
tylko złapie go wzorzec aneksu.

Zasady:

- pole zwykle zostaje **puste** — dodawaj wykluczenia dopiero, gdy widzisz
  konkretne pomyłki między typami;
- wykluczenie działa zero-jedynkowo: jedno trafienie i wzorzec odpada —
  nie wpisuj słów, które mogą legalnie wystąpić w dokumencie tego typu.

### Waga (liczba dziesiętna, puste = 1,0)

Mnożnik siły nagłówka. Reguluje, jak bardzo system „ufa" temu wzorcowi:

- `1,2` — standard dla **pewnych, jednoznacznych** nagłówków (większość
  wpisów startowych);
- `1,0` — nagłówki poprawne, ale mniej charakterystyczne (np. `UMOWA ZLECENIA`
  jako wariant, `ZASWIADCZENIE LEKARSKIE`);
- poniżej `0,9` — praktycznie wyłącza samodzielne rozpoczynanie dokumentu:
  sam nagłówek przestaje wystarczać i wzorzec potrzebuje dodatkowo trafionych
  fraz, żeby strona została uznana za początek dokumentu. Używaj tylko
  świadomie, dla bardzo ogólnych nagłówków.

Wpisuj z **przecinkiem dziesiętnym** (`1,2`), zgodnie z formatem pola
liczbowego WEBCON. Puste pole oznacza `1,0`.

### Aktywny (checkbox)

Odznaczenie wyłącza **ten jeden wiersz wzorca**; pozostałe wzorce typu
działają dalej. Podobnie jak przy typie — wyłączaj zamiast kasować.

## Dobre praktyki przy dodawaniu nowego typu

1. Weź **2–3 prawdziwe dokumenty** danego typu i sprawdź, jak dokładnie brzmi
   tytuł na pierwszej stronie — to będzie Nagłówek dokumentu. Jeśli tytuł ma
   warianty (odmiana, inna redakcja), dodaj osobny wiersz wzorca na każdy
   wariant.
2. Z treści dokumentów wybierz 3–5 zwrotów, które występują w każdym
   egzemplarzu, a rzadko w innych typach — to Frazy.
3. Frazy wykluczające zostaw puste. Uzupełnij dopiero, gdy testy pokażą
   mylenie z innym typem.
4. Waga: zacznij od `1,2` dla jednoznacznego nagłówka, `1,0` dla wariantów.
5. Zaznacz Aktywny przy typie i przy każdym wzorcu, Próg zostaw `0,90`.
6. Przepuść testową paczkę zawierającą nowy typ i sprawdź wynik podziału.

## Najczęstsze problemy i co poprawić w słowniku

| Objaw | Prawdopodobna przyczyna | Poprawka w słowniku |
|---|---|---|
| Dokument wychodzi jako „Nieznany typ dokumentu" | Nagłówek w słowniku różni się od tego na wydruku (inna redakcja, literówka) albo typ/wzorzec nieaktywny | Porównaj Nagłówek dokumentu z pierwszą stroną prawdziwego dokumentu; sprawdź checkboxy Aktywny |
| Dwa typy się mylą (np. aneks rozpoznany jako umowa) | Nagłówek jednego typu zawiera się w treści drugiego | Dodaj Frazy wykluczające do „szerszego" wzorca |
| Wielostronicowy dokument pocięty na kilka części | Środkowa strona zawiera nagłówek innego typu (np. cytat tytułu) | Fraza wykluczająca na wzorcu, który błędnie „startuje" w środku |
| Strony kontynuacji trafiają do weryfikacji ręcznej | Strony nie zawierają żadnej frazy swojego typu | Dodaj do Fraz zwroty występujące na dalszych stronach (nie tylko na pierwszej) |
| Wszystko naraz przestało być rozpoznawane | Słownik pusty lub wszystko nieaktywne (w logu akcji: „patterns data source returned no rows") | Sprawdź checkboxy Aktywny na typach i wzorcach |

Problemy techniczne (komunikaty o brakujących kolumnach źródła danych,
„Invalid patterns payload") to sprawa administratora — dotyczą konfiguracji
źródła danych, nie treści słownika.

## Wpisy startowe (odniesienie)

Pełna tabela 10 typów HR i 15 wzorców startowych znajduje się w
[README.md](../README.md) w sekcji „Słownik typów i źródło danych" — przy
wątpliwościach „jak to powinno wyglądać" wzoruj się na tych wpisach.
