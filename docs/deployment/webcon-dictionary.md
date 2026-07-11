# Słownik typów dokumentów w WEBCON

Wzorce rozpoznawania są utrzymywane w procesie słownikowym WEBCON.
Akcja SDK odczytuje je poprzez źródło danych (Designer Studio) i wysyła
razem z PDF-em w każdym wywołaniu `/api/split` — splitter nie ma żadnego
dostępu do bazy treści WEBCON. Zmiany w słowniku działają od następnego
wywołania akcji, bez restartów.

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

## Źródło danych wzorców

W Designer Studio utwórz źródło danych (zapytanie SQL do bazy treści),
które zwraca **wyłącznie aktywne** wzorce w kolumnach o dokładnie tych
nazwach:

| Kolumna | Znaczenie |
|---|---|
| `DocumentType` | nazwa typu dokumentu |
| `Header` | nagłówek wzorca (wiersz z pustym nagłówkiem jest pomijany) |
| `Phrases` | frazy rozdzielane średnikami |
| `ExcludedPhrases` | frazy wykluczające rozdzielane średnikami |
| `Weight` | waga wzorca (puste = 1,0) |

Szablon zapytania — dostosuj ID typu formularza i nazwy kolumn atrybutów
(znajdziesz je we właściwościach atrybutów w Designer Studio):

```sql
SELECT
    el.WFD_AttText1  AS DocumentType,
    det.DET_Att1     AS Header,
    det.DET_Att2     AS Phrases,
    det.DET_Att3     AS ExcludedPhrases,
    det.DET_Value1   AS Weight
FROM dbo.WFElements el
JOIN dbo.WFElementDetails det ON det.DET_WFDID = el.WFD_ID
WHERE el.WFD_DTYPEID = 123          -- ID typu formularza slownika
  AND el.WFD_IsDeleted = 0
  AND el.WFD_AttBool1 = 1           -- typ aktywny
  AND det.DET_Bool1 = 1             -- wzorzec aktywny
```

ID tego źródła danych wpisz w konfiguracji akcji SplitPdfAction
(pole "Patterns data source ID").

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

- Błąd akcji o brakujących kolumnach → nazwy kolumn w zapytaniu źródła
  muszą brzmieć dokładnie: DocumentType, Header, Phrases, ExcludedPhrases,
  Weight (aliasy `AS`).
- Ostrzeżenie "patterns data source returned no rows" w logu akcji →
  słownik pusty albo wszystkie wpisy nieaktywne; wszystko będzie
  klasyfikowane jako "Nieznany typ dokumentu".
- HTTP 400 od splittera z opisem "Invalid patterns payload" → źródło
  zwraca wartości w złych typach (np. tekst w kolumnie Weight);
  szczegóły w `splitter_job.technical_error`.
