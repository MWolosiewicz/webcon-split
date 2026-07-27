# Zrodlo po ID zalacznika i porzadki w akcjach recznych - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Akcje `RemovePagesAction` i `ExtractPagesAction` wybieraja zrodlowy PDF po ID zalacznika zamiast po kategorii, akcja wycinajaca zapisuje wynik we wskazanej kategorii elementu docelowego, a plugin przestaje wystawiac akcje sklejajaca.

**Architecture:** Wspolny helper `AttachmentSourceHelper` przestaje przeszukiwac zalaczniki po kategoriach i pobiera jeden wskazany po ID, walidujac przynaleznosc do biezacego elementu i rozszerzenie. Obie akcje dostaja wymagane pole tekstowe z ewaluacja tagow (wartosc typowo z reguly biznesowej), akcja wycinajaca dodatkowo pole ID kategorii docelowej ustawianej przez `SetFileGroupAsync` na zalaczniku zwroconym przez `AddNewAsync`. Zmiany sa czysto po stronie pluginu C# - serwis Pythona nie jest ruszany.

**Tech Stack:** C# / .NET Standard 2.0, WEBCON BPS SDK (linie 2025 R2 i 2026 R1), Newtonsoft.Json, PowerShell do pakowania.

**Spec:** `docs/superpowers/specs/2026-07-27-attachment-by-id-actions-design.md`

## Global Constraints

- Kod, komentarze i komunikaty w plikach `.cs`: polski **bez znakow diakrytycznych** (ASCII) - taka jest konwencja calego katalogu `webcon-action`. README pisany jest po polsku **z** diakrytykami.
- Docelowy framework `netstandard2.0`, `Nullable` wlaczone - nie zmieniac `WebconPdfSplitterAction.csproj`.
- Przy API SDK uzywac **jawnych przypisan wlasciwosci** zamiast argumentow pozycyjnych (w repo jest juz udokumentowana pulapka z `GetNewDocumentParams`).
- Zadnych zmian w `splitter/` - endpoint `/api/merge` i `pdf_io.merge_pdfs` zostaja nietkniete.
- Nie podbijac recznie `webcon-action/version.txt` - robi to `package.ps1`.
- W repo **nie ma projektu testowego dla C#**. Bramka kazdego zadania to zielony `dotnet build`; weryfikacja zachowania jest reczna na dev (Zadanie 5).
- Komenda budowania (z katalogu glownego worktree):
  ```bash
  dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release -p:BpsSdk=2026
  ```
  Oczekiwane: `Build succeeded`, kod wyjscia 0.

---

### Zadanie 1: Usuniecie akcji sklejajacej

**Files:**
- Delete: `webcon-action/MergeAttachmentsAction.cs`
- Delete: `webcon-action/MergeAttachmentsActionConfig.cs`
- Modify: `webcon-action/SplitterClient.cs:170-181` (metoda `MergeAsync`)
- Modify: `webcon-action/SplitterContracts.cs:75-79` (klasa `MergeInput`)
- Modify: `webcon-action/WebconPdfSplitterAction.json:35-42` (wpis akcji)
- Modify: `README.md:437`, `README.md:589-607` (opis akcji recznych)

**Interfaces:**
- Consumes: nic (pierwsze zadanie).
- Produces: manifest z czterema wpisami akcji; `SplitterClient` bez `MergeAsync`; `SplitterContracts` bez `MergeInput`.

- [ ] **Step 1: Usun pliki akcji sklejajacej**

```bash
git rm webcon-action/MergeAttachmentsAction.cs webcon-action/MergeAttachmentsActionConfig.cs
```

- [ ] **Step 2: Usun metode `MergeAsync` z klienta**

W `webcon-action/SplitterClient.cs` usun caly blok (wraz z pusta linia po nim):

```csharp
    public async Task<PageOpResult> MergeAsync(
        IReadOnlyList<MergeInput> files, int? webconElementId = null)
    {
        using var content = new MultipartFormDataContent();
        foreach (var file in files)
        {
            var part = new ByteArrayContent(file.Content);
            part.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
            content.Add(part, "files", file.FileName);
        }
        return await PostAsync<PageOpResult>("/api/merge", content, webconElementId);
    }
```

`using System.Collections.Generic;` na gorze pliku **zostaje** - uzywa go jeszcze `SubmitAsync` (`IReadOnlyList<PatternPayload>`).

- [ ] **Step 3: Usun kontrakt `MergeInput`**

W `webcon-action/SplitterContracts.cs` usun z konca pliku:

```csharp
public sealed class MergeInput
{
    public string FileName { get; set; } = "";
    public byte[] Content { get; set; } = System.Array.Empty<byte>();
}
```

- [ ] **Step 4: Usun wpis z manifestu**

W `webcon-action/WebconPdfSplitterAction.json` zamien:

```json
      "class": "WebconPdfSplitterAction.ExtractPagesToNewFormAction",
      "type": "CustomAction"
    },
    {
      "guid": "b9bfe1d9-07ca-4cd7-bc6f-002f75ed3a9e",
      "name": "MergeAttachmentsAction",
      "description": "Skleja wybrane zalaczniki PDF w jeden wg kolejnosci wierszy listy pozycji i dodaje wynik do biezacego elementu.",
      "assembly": "WebconPdfSplitterAction",
      "class": "WebconPdfSplitterAction.MergeAttachmentsAction",
      "type": "CustomAction"
    }
  ],
```

na:

```json
      "class": "WebconPdfSplitterAction.ExtractPagesToNewFormAction",
      "type": "CustomAction"
    }
  ],
```

(Nazwa klasy akcji wycinajacej zmieni sie w Zadaniu 2 - tutaj zostaje bez zmian.)

- [ ] **Step 5: Zaktualizuj README**

W `README.md` zamien punkt listy:

```markdown
- **MergeAttachmentsAction** — skleja załączniki wskazane w liście pozycji
  (wiersz = załącznik po ID z kolumny picker, kolejność wierszy = kolejność
  sklejania) w jeden PDF dodawany do bieżącego elementu; źródła zostają.
```

na (usuniecie punktu) - oraz w zdaniu wprowadzajacym zamien:

```markdown
operator koryguje wynik trzema akcjami — zwykle podpiętymi pod przyciski w kroku
```

na:

```markdown
operator koryguje wynik dwiema akcjami — zwykle podpiętymi pod przyciski w kroku
```

oraz zamien:

```markdown
Wszystkie trzy dzielą konfigurację połączenia (URL/token/timeout) z akcjami podziału.
```

na:

```markdown
Obie dzielą konfigurację połączenia (URL/token/timeout) z akcjami podziału.
```

W sekcji o endpointach serwisu (`README.md:437`) zamien:

```markdown
- **`/api/merge`** — pola `files` powtórzone w kolejności sklejania; `output_file_name`
  opcjonalne (domyślnie `merged.pdf`).
```

na:

```markdown
- **`/api/merge`** — pola `files` powtórzone w kolejności sklejania; `output_file_name`
  opcjonalne (domyślnie `merged.pdf`). Endpoint zostaje dostępny w serwisie, ale
  **nie ma już po stronie pluginu akcji, która go woła** (akcja sklejająca została
  usunięta) — jest do użytku z zewnątrz, np. w testach i integracjach.
```

- [ ] **Step 6: Zbuduj**

```bash
dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release -p:BpsSdk=2026
```

Oczekiwane: `Build succeeded`, kod 0. Blad `CS0246` o `MergeInput` oznacza, ze zostalo jakies odwolanie - znajdz je przez `git grep -n "MergeInput\|MergeAsync\|MergeAttachments" -- webcon-action` (`git grep` pomija `bin/` i `obj/`, ktore zwykly `grep -r` by przeszukal).

- [ ] **Step 7: Commit**

```bash
git add -A webcon-action README.md
git commit -m "refactor(webcon): usun akcje MergeAttachmentsAction"
```

---

### Zadanie 2: Zmiana nazwy na ExtractPagesAction

**Files:**
- Rename: `webcon-action/ExtractPagesToNewFormAction.cs` -> `webcon-action/ExtractPagesAction.cs`
- Rename: `webcon-action/ExtractPagesToNewFormActionConfig.cs` -> `webcon-action/ExtractPagesActionConfig.cs`
- Modify: `webcon-action/WebconPdfSplitterAction.json` (wpis `d707e16e-80df-4395-8f68-76000f90d838`)
- Modify: `README.md` (punkt listy akcji recznych)

**Interfaces:**
- Consumes: manifest po Zadaniu 1 (cztery wpisy).
- Produces: klasy `ExtractPagesAction` i `ExtractPagesActionConfig` - pod tymi nazwami odwoluja sie do nich Zadania 3 i 4.

- [ ] **Step 1: Przenies pliki zachowujac historie**

```bash
git mv webcon-action/ExtractPagesToNewFormAction.cs webcon-action/ExtractPagesAction.cs
git mv webcon-action/ExtractPagesToNewFormActionConfig.cs webcon-action/ExtractPagesActionConfig.cs
```

- [ ] **Step 2: Zmien nazwe klasy konfiguracji**

W `webcon-action/ExtractPagesActionConfig.cs` zamien:

```csharp
public class ExtractPagesToNewFormActionConfig : SplitterConnectionConfig
```

na:

```csharp
public class ExtractPagesActionConfig : SplitterConnectionConfig
```

- [ ] **Step 3: Zmien nazwe klasy akcji i prefiksy logu**

W `webcon-action/ExtractPagesAction.cs` zamien:

```csharp
public class ExtractPagesToNewFormAction : CustomAction<ExtractPagesToNewFormActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        var pluginVersion = typeof(ExtractPagesToNewFormAction).Assembly.GetName().Version?.ToString() ?? "?";
```

na:

```csharp
public class ExtractPagesAction : CustomAction<ExtractPagesActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        var pluginVersion = typeof(ExtractPagesAction).Assembly.GetName().Version?.ToString() ?? "?";
```

oraz oba wystapienia nazwy w komunikatach logu:

```csharp
                $"ExtractPagesToNewFormAction v{pluginVersion}. Zrodlo '{source.FileName}' (ID {source.ID}); " +
```

na:

```csharp
                $"ExtractPagesAction v{pluginVersion}. Zrodlo '{source.FileName}' (ID {source.ID}); " +
```

i w bloku `catch`:

```csharp
            args.LogMessage = $"ExtractPagesToNewFormAction v{pluginVersion}. {ex}";
```

na:

```csharp
            args.LogMessage = $"ExtractPagesAction v{pluginVersion}. {ex}";
```

- [ ] **Step 4: Zaktualizuj manifest (GUID BEZ ZMIAN)**

W `webcon-action/WebconPdfSplitterAction.json` zamien:

```json
      "guid": "d707e16e-80df-4395-8f68-76000f90d838",
      "name": "ExtractPagesToNewFormAction",
      "description": "Wycina wskazane strony z zalacznika PDF i tworzy nowy (surowy) element weryfikacyjny; opcjonalnie usuwa strony ze zrodla.",
      "assembly": "WebconPdfSplitterAction",
      "class": "WebconPdfSplitterAction.ExtractPagesToNewFormAction",
```

na:

```json
      "guid": "d707e16e-80df-4395-8f68-76000f90d838",
      "name": "ExtractPagesAction",
      "description": "Wycina wskazane strony ze wskazanego zalacznika PDF i tworzy nowy (surowy) element weryfikacyjny; opcjonalnie usuwa strony ze zrodla.",
      "assembly": "WebconPdfSplitterAction",
      "class": "WebconPdfSplitterAction.ExtractPagesAction",
```

GUID zostaje ten sam celowo - to on wiaze juz wpiete instancje akcji.

- [ ] **Step 5: Zaktualizuj README**

W `README.md` zamien:

```markdown
- **ExtractPagesToNewFormAction** — wycina strony do nowego, surowego elementu
```

na:

```markdown
- **ExtractPagesAction** — wycina strony do nowego, surowego elementu
```

- [ ] **Step 6: Sprawdz, czy stara nazwa nigdzie nie zostala**

```bash
git grep -n "ExtractPagesToNewForm" -- webcon-action README.md
```

Oczekiwane: brak wynikow (kod wyjscia 1). Trafienia w `docs/` sa poprawne - to zapis historyczny, nie ruszaj ich.

- [ ] **Step 7: Zbuduj**

```bash
dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release -p:BpsSdk=2026
```

Oczekiwane: `Build succeeded`, kod 0.

- [ ] **Step 8: Commit**

```bash
git add -A webcon-action README.md
git commit -m "refactor(webcon): zmien nazwe na ExtractPagesAction"
```

---

### Zadanie 3: Wybor zrodla po ID zalacznika

**Files:**
- Modify: `webcon-action/AttachmentSourceHelper.cs` (przepisanie calego pliku)
- Modify: `webcon-action/RemovePagesActionConfig.cs:8-15` (pole `AllowedCategories`)
- Modify: `webcon-action/RemovePagesAction.cs:18-19` (wywolanie helpera)
- Modify: `webcon-action/ExtractPagesActionConfig.cs:8-15` (pole `AllowedCategories`)
- Modify: `webcon-action/ExtractPagesAction.cs:26-27` (wywolanie helpera)
- Modify: `README.md:593-607` (opis akcji recznych)

**Interfaces:**
- Consumes: `ConfigHelper.ParsePositiveInt(string configuredValue, string fieldName) -> int` (istnieje); klasy `ExtractPagesAction` / `ExtractPagesActionConfig` z Zadania 2.
- Produces: `AttachmentSourceHelper.GetPdfByIdAsync(RunCustomActionParams args, string rawAttachmentId) -> Task<AttachmentData>`; wlasciwosci konfiguracji `RemovePagesActionConfig.SourceAttachmentId` i `ExtractPagesActionConfig.SourceAttachmentId` (obie `string`).

- [ ] **Step 1: Przepisz helper na pobranie po ID**

Zastap **cala** zawartosc `webcon-action/AttachmentSourceHelper.cs`:

```csharp
using System;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

internal static class AttachmentSourceHelper
{
    /// <summary>
    /// Zwraca zalacznik PDF wskazany po ID - typowo z reguly biznesowej
    /// wystawionej na pole konfiguracji akcji.
    ///
    /// Kontrola przynaleznosci do biezacego elementu nie jest tu ostroznoscia
    /// na wyrost: regula zwraca sama liczbe, a GetAttachmentAsync siega do
    /// calej bazy. Bez niej bledne ID w trybie "podmien zawartosc w miejscu"
    /// nadpisaloby zalacznik CUDZEGO elementu - po cichu i nieodwracalnie.
    /// </summary>
    public static async Task<AttachmentData> GetPdfByIdAsync(
        RunCustomActionParams args, string rawAttachmentId)
    {
        var attachmentId = ConfigHelper.ParsePositiveInt(
            rawAttachmentId, "ID zalacznika zrodlowego");

        var manager = new DocumentAttachmentsManager(args.Context);
        // jawne przypisania zamiast pozycyjnego GetAttachmentAsync(id, bool);
        // SkipPermissionsCheck = false, bo akcje reczne wykonuje klikajacy
        // uzytkownik i to jego uprawnienia maja decydowac
        var attachment = await manager.GetAttachmentAsync(new GetAttachmentParams
        {
            AttachmentId = attachmentId,
            SkipPermissionsCheck = false,
        });

        if (attachment == null)
            throw new InvalidOperationException(
                $"Nie znaleziono zalacznika o ID {attachmentId} " +
                "(nie istnieje albo uzytkownik nie ma do niego uprawnien).");

        var currentDocumentId = args.Context.CurrentDocument.ID;
        if (attachment.DocumentID != currentDocumentId)
            throw new InvalidOperationException(
                $"Zalacznik ID {attachmentId} nalezy do elementu " +
                $"{attachment.DocumentID?.ToString() ?? "nieznanego"}, a nie do biezacego " +
                $"({currentDocumentId}). Sprawdz regule wskazujaca ID zalacznika.");

        var extension = attachment.FileExtension?.TrimStart('.') ?? "";
        if (!string.Equals(extension, "pdf", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException(
                $"Zalacznik '{attachment.FileName}' (ID {attachmentId}) nie jest plikiem PDF.");

        return attachment;
    }
}
```

- [ ] **Step 2: Zamien pole konfiguracji w akcji usuwajacej**

W `webcon-action/RemovePagesActionConfig.cs` zamien:

```csharp
    [ConfigEditableText(
        DisplayName = "Dozwolone kategorie zalacznikow",
        Description = "Nazwy lub ID kategorii (grup) zalacznikow, na ktorych akcja moze dzialac. " +
                      "Kilka rozdziel srednikiem. Akcja wymaga dokladnie jednego PDF w tych kategoriach.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 10)]
    public string AllowedCategories { get; set; } = "";
```

na:

```csharp
    [ConfigEditableText(
        DisplayName = "ID zalacznika zrodlowego",
        Description = "ID zalacznika PDF biezacego elementu, na ktorym akcja ma dzialac. " +
                      "Zwykle regula biznesowa albo pole formularza zwracajace ID zalacznika.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 10)]
    public string SourceAttachmentId { get; set; } = "";
```

- [ ] **Step 3: Przepnij akcje usuwajaca na nowy helper**

W `webcon-action/RemovePagesAction.cs` zamien:

```csharp
            var source = await AttachmentSourceHelper.GetSinglePdfInCategoriesAsync(
                args, Configuration.AllowedCategories);
```

na:

```csharp
            var source = await AttachmentSourceHelper.GetPdfByIdAsync(
                args, Configuration.SourceAttachmentId);
```

- [ ] **Step 4: Zamien pole konfiguracji w akcji wycinajacej**

W `webcon-action/ExtractPagesActionConfig.cs` zamien:

```csharp
    [ConfigEditableText(
        DisplayName = "Dozwolone kategorie zalacznikow",
        Description = "Nazwy lub ID kategorii (grup) zalacznikow zrodlowych. Kilka rozdziel srednikiem. " +
                      "Akcja wymaga dokladnie jednego PDF w tych kategoriach.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 10)]
    public string AllowedCategories { get; set; } = "";
```

na:

```csharp
    [ConfigEditableText(
        DisplayName = "ID zalacznika zrodlowego",
        Description = "ID zalacznika PDF biezacego elementu, z ktorego wycinamy strony. " +
                      "Zwykle regula biznesowa albo pole formularza zwracajace ID zalacznika.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 10)]
    public string SourceAttachmentId { get; set; } = "";
```

- [ ] **Step 5: Przepnij akcje wycinajaca na nowy helper**

W `webcon-action/ExtractPagesAction.cs` zamien:

```csharp
            var source = await AttachmentSourceHelper.GetSinglePdfInCategoriesAsync(
                args, Configuration.AllowedCategories);
```

na:

```csharp
            var source = await AttachmentSourceHelper.GetPdfByIdAsync(
                args, Configuration.SourceAttachmentId);
```

- [ ] **Step 6: Zaktualizuj README**

W `README.md` zamien punkt akcji usuwajacej:

```markdown
- **RemovePagesAction** — usuwa zakres stron (np. `2-4,7`) z jedynego PDF-a
  w dozwolonych kategoriach załącznika. Przełącznik „Podmień zawartość w miejscu"
  (nadpisz oryginał) lub dodanie nowego załącznika (oryginał zostaje).
```

na:

```markdown
- **RemovePagesAction** — usuwa zakres stron (np. `2-4,7`) ze wskazanego PDF-a.
  Przełącznik „Podmień zawartość w miejscu" (nadpisz oryginał) lub dodanie nowego
  załącznika (oryginał zostaje, wynik dziedziczy kategorię źródła).
```

oraz akapit o kategoriach:

```markdown
Obie dzielą konfigurację połączenia (URL/token/timeout) z akcjami podziału.
Kategorie załączników podaje się nazwami lub ID grup, rozdzielone średnikami;
akcje remove/extract wymagają **dokładnie jednego** PDF-a w tych kategoriach
(0 lub >1 → czytelny błąd). Komunikaty walidacyjne serwisu (np. „Strona 8 poza
dokumentem (1-6)") trafiają do komunikatu błędu akcji.
```

na:

```markdown
Obie dzielą konfigurację połączenia (URL/token/timeout) z akcjami podziału.
Źródłowy PDF wskazuje się **ID załącznika** — pole przyjmuje tag/regułę biznesową,
więc na formularzu z wieloma plikami to reguła decyduje, który jest dzielony.
Akcja odrzuca ID spoza bieżącego elementu i ID pliku, który nie jest PDF-em.
Komunikaty walidacyjne serwisu (np. „Strona 8 poza dokumentem (1-6)") trafiają
do komunikatu błędu akcji.
```

- [ ] **Step 7: Sprawdz, czy stara sciezka nigdzie nie zostala**

```bash
git grep -n "AllowedCategories\|GetSinglePdfInCategories" -- webcon-action
```

Oczekiwane: brak wynikow (kod wyjscia 1).

- [ ] **Step 8: Zbuduj**

```bash
dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release -p:BpsSdk=2026
```

Oczekiwane: `Build succeeded`, kod 0. Jesli kompilator zglosi `CS0117` na `GetAttachmentParams`, sprawdz nazwy wlasciwosci refleksja:

```powershell
$dll = "$env:USERPROFILE\.nuget\packages\webcon.bps.2026.sdk.libraries\26.1.6.209\lib\netstandard2.0\WebCon.WorkFlow.SDK.dll"
[System.Reflection.Assembly]::LoadFrom($dll).GetType('WebCon.WorkFlow.SDK.Documents.Model.Attachments.GetAttachmentParams').GetProperties().Name
```

Oczekiwane wlasciwosci: `AttachmentId`, `SkipPermissionsCheck`, `IncludeDeleted`.

- [ ] **Step 9: Commit**

```bash
git add -A webcon-action README.md
git commit -m "feat(webcon): wskazuj zrodlowy PDF po ID zalacznika"
```

---

### Zadanie 4: Kategoria docelowa nowego zalacznika

**Files:**
- Modify: `webcon-action/ExtractPagesActionConfig.cs` (nowe pole + `Order` przelacznika)
- Modify: `webcon-action/ExtractPagesAction.cs` (walidacja przed utworzeniem elementu, `SetFileGroupAsync`, log)
- Modify: `README.md` (punkt akcji wycinajacej)

**Interfaces:**
- Consumes: `ExtractPagesActionConfig.SourceAttachmentId` z Zadania 3.
- Produces: `ExtractPagesActionConfig.TargetAttachmentCategoryId` (`string`).

- [ ] **Step 1: Dodaj pole kategorii docelowej**

W `webcon-action/ExtractPagesActionConfig.cs` zamien blok przelacznika:

```csharp
    [ConfigEditableBool(
        DisplayName = "Usun wyciete strony ze zrodla",
        Description = "Wlaczone: po wycieciu usuwa te strony z zalacznika zrodlowego (przenoszenie). " +
                      "Wylaczone: zrodlo zostaje nietkniete (kopiowanie).",
        Order = 15)]
    public bool RemoveFromSource { get; set; }
```

na:

```csharp
    [ConfigEditableText(
        DisplayName = "ID kategorii dla nowego zalacznika",
        Description = "ID grupy plikow (kategorii zalacznikow) w typie formularza DOCELOWYM, " +
                      "do ktorej trafi wyciety PDF. Liczba lub tag/stala.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 15)]
    public string TargetAttachmentCategoryId { get; set; } = "";

    [ConfigEditableBool(
        DisplayName = "Usun wyciete strony ze zrodla",
        Description = "Wlaczone: po wycieciu usuwa te strony z zalacznika zrodlowego (przenoszenie). " +
                      "Wylaczone: zrodlo zostaje nietkniete (kopiowanie).",
        Order = 16)]
    public bool RemoveFromSource { get; set; }
```

- [ ] **Step 2: Zwaliduj kategorie PRZED utworzeniem elementu**

W `webcon-action/ExtractPagesAction.cs` zamien blok walidacji na poczatku `RunAsync`:

```csharp
            var startPathId = ConfigHelper.ParsePositiveInt(
                Configuration.StartPathId, "ID sciezki startowej");
```

na:

```csharp
            var startPathId = ConfigHelper.ParsePositiveInt(
                Configuration.StartPathId, "ID sciezki startowej");
            // walidacja PRZED utworzeniem elementu - pusta kategoria wykryta
            // dopiero po StartNewWorkFlowAsync zostawilaby w obiegu wystartowany
            // element potomny, ktorego nikt nie zamowil
            var targetCategoryId = Configuration.TargetAttachmentCategoryId?.Trim() ?? "";
            if (targetCategoryId.Length == 0)
                throw new InvalidOperationException(
                    "Pole konfiguracji 'ID kategorii dla nowego zalacznika' jest puste.");
```

- [ ] **Step 3: Ustaw kategorie na nowym zalaczniku**

W tym samym pliku zamien:

```csharp
            await newDocument.Attachments.AddNewAsync(
                extractResult.OutputFileName,
                Convert.FromBase64String(extractResult.FileContentBase64));
```

na:

```csharp
            // AddNewAsync zwraca AttachmentData, wiec grupe plikow ustawiamy na
            // zwroconym obiekcie - tak samo, jak RemovePagesAction robi to dla
            // zalacznika biezacego elementu
            var newAttachment = await newDocument.Attachments.AddNewAsync(
                extractResult.OutputFileName,
                Convert.FromBase64String(extractResult.FileContentBase64));
            await newAttachment.SetFileGroupAsync(targetCategoryId);
```

- [ ] **Step 4: Dopisz kategorie do logu operacji**

W tym samym pliku zamien:

```csharp
                $"utworzono element {started.CreatedDocumentID}; " +
```

na:

```csharp
                $"utworzono element {started.CreatedDocumentID}, kategoria zalacznika '{targetCategoryId}'; " +
```

- [ ] **Step 5: Zaktualizuj README**

W `README.md` zamien:

```markdown
- **ExtractPagesAction** — wycina strony do nowego, surowego elementu
  (bez klasyfikacji — typ i weryfikację ustawia operator) w obiegu docelowym;
  przełącznik „Usuń wycięte strony ze źródła" (przenoszenie vs kopiowanie).
```

na:

```markdown
- **ExtractPagesAction** — wycina strony do nowego, surowego elementu
  (bez klasyfikacji — typ i weryfikację ustawia operator) w obiegu docelowym.
  Wycięty PDF powstaje **wyłącznie** na nowym elemencie, we wskazanej kategorii
  załączników typu docelowego; na formularzu źródłowym nie pojawia się nowy plik.
  Przełącznik „Usuń wycięte strony ze źródła" decyduje tylko o losie stron w źródle
  (przenoszenie vs kopiowanie) — usunięcie nadpisuje istniejący załącznik, więc jego
  ID się nie zmienia.
```

- [ ] **Step 6: Zbuduj**

```bash
dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release -p:BpsSdk=2026
```

Oczekiwane: `Build succeeded`, kod 0.

- [ ] **Step 7: Commit**

```bash
git add -A webcon-action README.md
git commit -m "feat(webcon): kategoria docelowa zalacznika w ExtractPagesAction"
```

---

### Zadanie 5: Paczki dla obu linii BPS i weryfikacja na dev

**Files:**
- Modify: `webcon-action/version.txt` (podbija skrypt - nie edytuj recznie)
- Create: `webcon-action/Publish/WebconPdfSplitterAction-2025r2-<wersja>.zip`
- Create: `webcon-action/Publish/WebconPdfSplitterAction-2026r1-<wersja>.zip`

**Interfaces:**
- Consumes: kod po Zadaniach 1-4.
- Produces: dwie paczki ZIP o tym samym numerze wersji, gotowe do rejestracji w Designer Studio.

- [ ] **Step 1: Zbuduj obie linie SDK**

```bash
dotnet build webcon-action/WebconPdfSplitterAction.csproj -c Release -p:BpsSdk=2025
```

Oczekiwane: `Build succeeded`, kod 0. Ten krok jest osobno, bo dotychczasowe zadania budowaly wylacznie linie 2026 - roznice w API SDK miedzy liniami wychodza dopiero tutaj.

- [ ] **Step 2: Spakuj obie linie z jednego numeru wersji**

```bash
powershell -File webcon-action/package.ps1
```

Oczekiwane w wyjsciu: `Wersja pakietu: <nowa wersja> (linie BPS: 2025, 2026)` oraz na koncu dwie sciezki ZIP.

- [ ] **Step 3: Sprawdz zawartosc paczek**

```bash
powershell -Command "Get-ChildItem webcon-action/Publish/*.zip | Select-Object Name, Length"
```

Oczekiwane: dwa pliki, `-2025r2-` i `-2026r1-`, z tym samym numerem wersji w nazwie.

- [ ] **Step 4: Commit podbitej wersji**

```bash
git add webcon-action/version.txt
git commit -m "chore(webcon): paczki 2025r2 i 2026r1 z akcjami po ID zalacznika"
```

- [ ] **Step 5: Weryfikacja reczna na dev (lista kontrolna)**

Paczki ZIP nie sa commitowane - przekaz je operatorowi. Kolejnosc wdrozenia i scenariusze do przejscia:

1. Wypiac `MergeAttachmentsAction` z obiegow (po wgraniu paczki zglosi brakujacy plugin).
2. Wgrac paczke odpowiednia dla linii BPS serwera.
3. W kazdej instancji `RemovePagesAction` i `ExtractPagesAction` uzupelnic **ID zalacznika zrodlowego**, a w akcji wycinajacej takze **ID kategorii dla nowego zalacznika**. Regula biznesowa zwracajaca ID zalacznika musi istniec wczesniej.
4. Sprawdzic, czy akcja wycinajaca nadal nazywa sie tak, jak byla wpieta (potwierdzenie, ze BPS wiaze po GUID) - jesli instancje sie odpiely, wpiac ponownie.

Scenariusze do przejscia na dev:

- poprawne ID PDF-a z biezacego elementu -> obie akcje koncza sie sukcesem,
- ID zalacznika z INNEGO elementu -> blad, zrodlo nietkniete,
- ID zalacznika, ktory nie jest PDF-em -> blad z nazwa pliku,
- ID nieistniejace oraz pole puste (regula zwrocila pusto) -> bledy konfiguracji,
- `ExtractPagesAction`: nowy zalacznik lezy we wskazanej kategorii elementu docelowego,
- `RemovePagesAction` w trybie nowego zalacznika: wynik dziedziczy kategorie zrodla.

**Jesli `SetFileGroupAsync` odrzuci ustawienie grupy przed `StartNewWorkFlowAsync`** (element nie istnieje jeszcze w bazie - ryzyko nazwane w specu), zastosuj wariant zapasowy: usun wywolanie `SetFileGroupAsync` sprzed startu, a po `StartNewWorkFlowAsync` wczytaj zalacznik utworzonego elementu i zapisz grupe:

```csharp
            var createdManager = new DocumentAttachmentsManager(args.Context);
            var created = await createdManager.GetAttachmentsAsync(new GetAttachmentsParams
            {
                DocumentId = started.CreatedDocumentID,
            });
            foreach (var item in created)
            {
                await item.SetFileGroupAsync(targetCategoryId);
                await createdManager.UpdateAttachmentAsync(new UpdateAttachmentParams { Attachment = item });
            }
```

Zmiane wariantu zapasowego commituj osobno, z opisem, dlaczego pierwsza sciezka nie zadziala.
