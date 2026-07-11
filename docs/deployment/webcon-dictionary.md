# Słownik typów dokumentów w WEBCON

Splitter czyta typy dokumentów i wzorce rozpoznawania bezpośrednio z bazy
treści WEBCON (tylko odczyt). Edycja odbywa się wyłącznie w WEBCON —
w procesie słownikowym opisanym niżej. Zmiany działają od następnego
wywołania `/api/split`, bez restartu serwisu.

## Proces słownikowy w Designer Studio

Utwórz proces słownikowy **"Typ dokumentu"** (jeden formularz = jeden typ):

Atrybuty nagłówka:

| Atrybut | Typ atrybutu | Uwagi |
|---|---|---|
| Nazwa typu | Wiersz tekstu | polskie znaki dozwolone — klasyfikator normalizuje do ASCII |
| Aktywny | Pole wyboru (checkbox) | odznaczony = cały typ wyłączony |
| Próg auto-akceptacji | Liczba zmiennoprzecinkowa | pole rezerwowe — obecnie splitter stosuje próg globalny |

Lista pozycji **"Wzorce"** (jeden wiersz = jeden wzorzec) — formularz powinien
mieć dokładnie jedną listę pozycji:

| Kolumna | Typ | Uwagi |
|---|---|---|
| Nagłówek dokumentu | Wiersz tekstu | np. `UMOWA O PRACE`; wiersz z pustym nagłówkiem jest pomijany |
| Frazy | Wiersz tekstu | rozdzielane średnikami, np. `pracodawca; pracownik` |
| Frazy wykluczające | Wiersz tekstu | rozdzielane średnikami, może być puste |
| Waga | Liczba zmiennoprzecinkowa | puste = 1,0 |
| Aktywny | Pole wyboru | odznaczony = wzorzec wyłączony |

## Odczyt ID i nazw kolumn

1. W Designer Studio włącz "Pokaż identyfikatory obiektów".
2. ID typu formularza słownika → właściwości typu formularza
   (`SPLITTER_WEBCON_DICT_FORM_TYPE_ID`).
3. Nazwę kolumny bazodanowej każdego atrybutu znajdziesz we właściwościach
   atrybutu (np. `WFD_AttText1` dla nagłówka, `DET_Att1` dla kolumn listy
   pozycji). Wpisz je do zmiennych `SPLITTER_WEBCON_DICT_COL_*`
   (tabela w `splitter-service.md`).

## Uprawnienia SQL

Konto splittera potrzebuje w bazie treści WEBCON wyłącznie:

```sql
GRANT SELECT ON dbo.WFElements TO splitter_svc;
GRANT SELECT ON dbo.WFElementDetails TO splitter_svc;
```

Splitter nigdy nie pisze do bazy treści. Tabele operacyjne
(`splitter_job`, `classification_feedback`) pozostają w bazie
`WebconPdfSplitter`.

## Dane startowe (typy HR i wzorce)

Wprowadź ręcznie w słowniku (jednorazowo, ok. 15 minut). Wszystkie typy:
Aktywny = tak, Próg = 0,90. Wszystkie wzorce: Aktywny = tak.

| Typ dokumentu | Nagłówek wzorca | Frazy | Frazy wykluczające | Waga |
|---|---|---|---|---|
| Umowa o pracę | UMOWA O PRACE | pracodawca; pracownik; wynagrodzenie; wymiar czasu pracy | aneks; wypowiedzenie; rozwiazanie umowy | 1,2 |
| Aneks do umowy o pracę | ANEKS DO UMOWY O PRACE | zmienia sie; pozostale warunki; porozumienie stron | | 1,2 |
| Aneks do umowy o pracę | ANEKS DO UMOWY | umowy o prace; zmienia sie | | 1,0 |
| Umowa zlecenie | UMOWA ZLECENIE | zleceniodawca; zleceniobiorca | | 1,2 |
| Umowa zlecenie | UMOWA ZLECENIA | zleceniodawca; zleceniobiorca | | 1,2 |
| Wypowiedzenie umowy o pracę | WYPOWIEDZENIE UMOWY O PRACE | okres wypowiedzenia; rozwiazanie umowy | | 1,2 |
| Wypowiedzenie umowy o pracę | ROZWIAZANIE UMOWY O PRACE | za wypowiedzeniem; bez wypowiedzenia; porozumienie stron | | 1,1 |
| Świadectwo pracy | SWIADECTWO PRACY | stosunek pracy; okres zatrudnienia; urlop wypoczynkowy | | 1,2 |
| Kwestionariusz osobowy | KWESTIONARIUSZ OSOBOWY | imie i nazwisko; data urodzenia; adres zamieszkania | | 1,2 |
| Orzeczenie lekarskie | ORZECZENIE LEKARSKIE | zdolny do pracy; badania profilaktyczne; medycyna pracy | | 1,2 |
| Orzeczenie lekarskie | ZASWIADCZENIE LEKARSKIE | zdolny do pracy; przeciwwskazania | | 1,0 |
| Zaświadczenie o ukończeniu szkolenia BHP | ZASWIADCZENIE O UKONCZENIU SZKOLENIA | bezpieczenstwa i higieny pracy; bhp; szkolenie okresowe | | 1,1 |
| Zaświadczenie o ukończeniu szkolenia BHP | KARTA SZKOLENIA WSTEPNEGO | instruktaz ogolny; instruktaz stanowiskowy; bhp | | 1,2 |
| Oświadczenie PIT-2 | PIT-2 | oswiadczenie; zaliczek na podatek; kwoty zmniejszajacej | | 1,2 |
| Zgoda na przetwarzanie danych osobowych | ZGODA NA PRZETWARZANIE DANYCH | danych osobowych; rodo; administratorem danych | | 1,2 |

Nagłówki i frazy wpisuj bez polskich znaków (jak w tabeli) — dopasowanie
i tak odbywa się po normalizacji do ASCII, ale ułatwia to diagnostykę.

## Rozwiązywanie problemów

- Błąd 500 przy `/api/split` z komunikatem o mapowaniu → sprawdź zmienne
  `SPLITTER_WEBCON_DICT_COL_*` (komunikat wskazuje brakującą/błędną zmienną);
  szczegóły w `splitter_job.technical_error`.
- Wszystko klasyfikowane jako "Nieznany typ dokumentu" → słownik pusty,
  wpisy nieaktywne albo złe `SPLITTER_WEBCON_DICT_FORM_TYPE_ID`.
- Ostrzeżenie o pustym nagłówku w logu → wiersz listy pozycji bez
  nagłówka dokumentu (jest pomijany).
