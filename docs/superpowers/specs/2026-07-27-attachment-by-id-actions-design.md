# Zrodlo wskazywane po ID zalacznika, porzadki w akcjach recznych - Design

## Cel

Akcje reczne operatora (`RemovePagesAction`, `ExtractPagesToNewFormAction`)
wybieraja dzis zrodlowy PDF posrednio: po kategorii (grupie plikow) zalacznika,
z twardym wymogiem, ze w dozwolonych kategoriach jest **dokladnie jeden** PDF.
Na formularzu z paczka skanu i dokumentem wynikowym w tej samej kategorii akcja
jest wiec bezuzyteczna, a operator nie ma jak wskazac, o ktory plik mu chodzi.

Ta zmiana zastepuje wybor po kategorii jawnym wskazaniem **ID zalacznika**
(typowo z reguly biznesowej), doklada w akcji wycinajacej kategorie docelowa dla
nowo tworzonego zalacznika i przy okazji porzadkuje zestaw akcji: zmiana nazwy
`ExtractPagesToNewFormAction` na `ExtractPagesAction` oraz usuniecie
`MergeAttachmentsAction`.

Po zmianie plugin wystawia **cztery** akcje: `SubmitSplitJobAction`,
`CollectSplitJobAction`, `RemovePagesAction`, `ExtractPagesAction`.

## Decyzja 1: zrodlo wskazywane WYLACZNIE przez ID, bez auto-wyboru

Pole "Dozwolone kategorie zalacznikow" znika z obu akcji. W jego miejsce wchodzi
pole tekstowe **"ID zalacznika zrodlowego"**, wymagane, z ewaluacja tagow
(`TagEvaluationMode = EvaluationMode.Default`) - dzieki temu wartosc moze pochodzic
z reguly biznesowej, stalej albo pola formularza.

Rozwazany byl wariant posredni: puste ID oznacza "wez jedyny PDF na formularzu",
a wskazanie jest potrzebne dopiero przy wielu plikach. Zostal odrzucony swiadomie -
dwie sciezki wyboru zrodla to dwa zestawy komunikatow bledu i dwa zachowania do
wyjasnienia operatorowi, a regula biznesowa zwracajaca ID zalacznika i tak musi
powstac dla przypadku z wieloma plikami. Jedna sciezka jest prostsza w budowie
i jednoznaczna w dzialaniu.

Konsekwencja: akcja bez wypelnionego ID **nie ma trybu domyslnego** i konczy sie
bledem konfiguracji. To jest zamierzone.

## Decyzja 2: walidacja wskazanego zalacznika

Wspolny helper (`AttachmentSourceHelper`, przepisany z wyszukiwania po kategoriach
na pobranie po ID) wykonuje kolejno:

1. `ConfigHelper.ParsePositiveInt(rawId, "ID zalacznika zrodlowego")` - pusta
   wartosc, tekst albo liczba <= 0 daja komunikat o blednej konfiguracji.
2. `DocumentAttachmentsManager.GetAttachmentAsync(new GetAttachmentParams { AttachmentId = id, SkipPermissionsCheck = false })`.
   Wariant z `GetAttachmentParams` zamiast pozycyjnego `GetAttachmentAsync(id, bool)`
   - zgodnie z zasada jawnych przypisan przy API SDK.
   `SkipPermissionsCheck = false`, bo obie akcje wykonuje klikajacy uzytkownik
   i to jego uprawnienia maja decydowac (tak samo, jak przy tworzeniu elementu
   w akcji wycinajacej).
3. Brak zalacznika -> blad z podanym ID.
4. **`DocumentID` rozne od `args.Context.CurrentDocument.ID` -> blad.** To nie jest
   ostroznosc na wyrost: regula biznesowa zwraca sama liczbe, a `GetAttachmentAsync`
   siega do calej bazy. Bez tej kontroli bledna regula w trybie "podmien zawartosc
   w miejscu" nadpisalaby zalacznik CUDZEGO elementu - po cichu i nieodwracalnie.
5. Rozszerzenie inne niz `pdf` (porownanie bez wzgledu na wielkosc liter, po
   obcieciu wiodacej kropki) -> blad z nazwa pliku, bo splitter przyjmuje wylacznie PDF.

Wszystkie bledy leca jako `InvalidOperationException` i sa lapane przez istniejacy
`try/catch` akcji: `args.HasErrors = true`, krotki `args.Message` dla operatora,
pelny wyjatek z wersja pluginu w `args.LogMessage`.

## Decyzja 3: kategoria docelowa w akcji wycinajacej

`ExtractPagesAction` dostaje pole **"ID kategorii dla nowego zalacznika"** - tekst
wymagany, z ewaluacja tagow. Podaje sie ID grupy plikow z typu formularza
DOCELOWEGO (nie biezacego).

ID, a nie nazwa: `AttachmentData.SetFileGroupAsync` przyjmuje wlasnie ID (string),
wiec sciezka po ID nie wymaga tlumaczenia nazw ani listowania grup docelowego typu
formularza. Nazwa dodatkowo psulaby konfiguracje po zmianie etykiety kategorii
w Designer Studio.

Realizacja: `newDocument.Attachments.AddNewAsync(nazwa, bajty)` zwraca
`AttachmentData`, wiec na zwroconym obiekcie wolamy `SetFileGroupAsync(idKategorii)`
- ten sam wzorzec, ktorego `RemovePagesAction` uzywa dzis dla biezacego elementu.

**Ryzyko do zweryfikowania empirycznie:** nie jest pewne, czy SDK pozwala ustawic
grupe plikow na dokumencie przed `StartNewWorkFlowAsync` (element nie istnieje
jeszcze w bazie). Wariant zapasowy, jesli SDK odrzuci: ustawic grupe PO starcie -
wczytac zalacznik utworzonego elementu (`started.CreatedDocumentID`) przez
`DocumentAttachmentsManager` i zapisac przez `UpdateAttachmentAsync`. Wybor
rozstrzyga test na dev, nie dokumentacja.

## Decyzja 4: RemovePagesAction bez pola kategorii

W trybie "nowy zalacznik" `RemovePagesAction` zostaje przy dzisiejszym zachowaniu:
nowy plik dziedziczy kategorie zalacznika zrodlowego (`SetFileGroupAsync(source.FileGroup.ID)`).
Wynik zostaje na tym samym elemencie obok zrodla, wiec dziedziczenie jest sensownym
domyslnym zachowaniem, a kazde dodatkowe pole to kolejna rzecz do wypelnienia przy
wdrozeniu. Symetria z akcja wycinajaca nie jest tu wartoscia sama w sobie - tam
kategoria jest potrzebna, bo zalacznik trafia do INNEGO typu formularza, gdzie
grupy zrodla moga w ogole nie istniec.

## Decyzja 5: zmiana nazwy na ExtractPagesAction

`ExtractPagesToNewFormAction` -> `ExtractPagesAction`, wraz z klasa konfiguracji
(`ExtractPagesToNewFormActionConfig` -> `ExtractPagesActionConfig`) i nazwami plikow.
Pliki przenosimy przez `git mv`, zeby historia zostala przy tresci.

W manifescie `WebconPdfSplitterAction.json` zmieniamy `name`, `class` i opis,
**zachowujac GUID `d707e16e-80df-4395-8f68-76000f90d838`**. Zalozenie: BPS wiaze
wpiete instancje akcji po GUID, wiec akcja pojawi sie pod nowa nazwa bez
odpinania od przyciskow i sciezek. Gdyby na dev okazalo sie, ze wiazanie idzie
po nazwie klasy, skutek jest taki sam jak przy nowym GUID - instancje trzeba
wpiac ponownie.

Do poprawienia takze prefiks w `args.LogMessage` (zawiera nazwe klasy) i sekcja
"Reczne akcje operatora" w README.

## Decyzja 6: usuniecie MergeAttachmentsAction

Usuwamy `MergeAttachmentsAction`, `MergeAttachmentsActionConfig` (razem z klasami
`MergeItemListConfig` i `MergeItemListColumns`) oraz wpis w manifescie
(GUID `b9bfe1d9-07ca-4cd7-bc6f-002f75ed3a9e`). Wraz z akcja wypada osierocony kod
klienta: `SplitterClient.MergeAsync` i kontrakt `MergeInput` - po usunieciu akcji
nie maja zadnego wywolania.

**Strona serwisu zostaje nietknieta:** endpoint `/api/merge`, funkcja
`pdf_io.merge_pdfs` i ich testy nie sa ruszane. Zakres zmiany to akcja WEBCON;
endpoint jest niezalezna, przetestowana powierzchnia HTTP, a jego usuniecie to
osobna decyzja.

Wdrozeniowo: obieg, w ktorym akcja sklejajaca jest wpieta, po wgraniu paczki
zglosi brakujacy plugin. Akcje trzeba wypiac w Designer Studio przed aktualizacja
albo bezposrednio po niej.

## Konfiguracja akcji po zmianie

`RemovePagesActionConfig` (dziedziczy `SplitterConnectionConfig`: adres serwisu,
token, limit czasu):

| Pole | Typ | Wymagane | Uwagi |
| --- | --- | --- | --- |
| ID zalacznika zrodlowego | tekst + tagi | tak | zastepuje "Dozwolone kategorie zalacznikow" |
| Zakres stron do usuniecia | tekst + tagi | tak | bez zmian |
| Podmien zawartosc w miejscu | bool | - | bez zmian |

`ExtractPagesActionConfig`:

| Pole | Typ | Wymagane | Uwagi |
| --- | --- | --- | --- |
| ID zalacznika zrodlowego | tekst + tagi | tak | zastepuje "Dozwolone kategorie zalacznikow" |
| Zakres stron do wyciecia | tekst + tagi | tak | bez zmian |
| ID obiegu docelowego | tekst + tagi | tak | bez zmian |
| ID typu formularza docelowego | tekst + tagi | tak | bez zmian |
| ID sciezki startowej | tekst + tagi | tak | bez zmian |
| ID kategorii dla nowego zalacznika | tekst + tagi | tak | nowe |
| Usun wyciete strony ze zrodla | bool | - | bez zmian |

## Ustalenia o SDK (zweryfikowane refleksja, WEBCON.BPS.2026.SDK.Libraries 26.1.6.209)

- `AttachmentData`: `int ID`, **`int? DocumentID`**, `string FileName`,
  `string FileExtension`, `AttachmentsGroup FileGroup`,
  `Task<AttachmentsGroup> SetFileGroupAsync(string fileGroup)`,
  `Task<byte[]> GetContentAsync()`, `void SetContent(byte[])`.
- `AttachmentsGroup`: **`string ID`**, `string DisplayName`, `bool IsCustomGroup`.
- `DocumentAttachmentsManager`: `GetAttachmentAsync(GetAttachmentParams)` obok
  wariantu pozycyjnego; `GetAttachmentParams { int AttachmentId, bool SkipPermissionsCheck, bool IncludeDeleted }`.
- `AttachmentsCollection.AddNewAsync(string name, byte[] content)` zwraca
  **`Task<AttachmentData>`** - stad mozliwosc ustawienia grupy na nowym elemencie.

## Wplyw na istniejace wdrozenia (zmiana lamiaca)

Usuniecie `AllowedCategories` i dodanie wymaganych pol oznacza, ze **kazda juz
skonfigurowana instancja obu akcji przestanie dzialac po wgraniu paczki**, dopoki
operator nie uzupelni ID zalacznika (a w akcji wycinajacej takze ID kategorii
docelowej). Awaria jest glosna i opisowa - akcja konczy sie bledem z nazwa
brakujacego pola, nie cichym pominieciem.

Kolejnosc przy wdrozeniu:
1. Wypiac `MergeAttachmentsAction` z obiegow.
2. Wgrac paczke.
3. Uzupelnic nowe pola w kazdej instancji `RemovePagesAction` i `ExtractPagesAction`
   (regula biznesowa zwracajaca ID zalacznika musi istniec wczesniej).

## Paczki

Bez zmian w skrypcie: `powershell -File webcon-action\package.ps1` domyslnie
(`-Sdk both`) buduje obie linie z JEDNEGO podbicia wersji i wypuszcza do
`webcon-action\Publish`:

- `WebconPdfSplitterAction-2025r2-<wersja>.zip` (SDK 25.2.1.359)
- `WebconPdfSplitterAction-2026r1-<wersja>.zip` (SDK 26.1.6.209)

## Testy i weryfikacja

W repo nie ma projektu testowego dla C# (znany punkt backlogu), wiec weryfikacja
to `dotnet build` dla obu linii SDK plus scenariusze reczne na dev:

- poprawne ID PDF-a z biezacego elementu - obie akcje koncza sie sukcesem,
- ID zalacznika z INNEGO elementu - blad, zrodlo nietkniete,
- ID zalacznika nie-PDF - blad z nazwa pliku,
- ID nieistniejace oraz pole puste - bledy konfiguracji,
- `ExtractPagesAction`: nowy zalacznik lezy we wskazanej kategorii elementu
  docelowego (to samo sprawdzenie rozstrzyga ryzyko z Decyzji 3),
- `RemovePagesAction` w trybie nowego zalacznika: wynik dziedziczy kategorie zrodla.

Strona Pythona nie jest ruszana, wiec jej testy musza przechodzic bez zmian.

## Poza zakresem

- Usuwanie `/api/merge` i `merge_pdfs` z serwisu.
- Pole kategorii docelowej w `RemovePagesAction`.
- Auto-wybor zalacznika, gdy na formularzu jest tylko jeden PDF.
- Projekt testowy dla logiki C#.
