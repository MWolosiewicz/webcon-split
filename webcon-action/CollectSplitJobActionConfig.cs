using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class CollectSplitJobActionConfig : SplitJobFieldsConfig
{
    [ConfigEditableDataSourceID(
        DisplayName = "Zrodlo danych ze wzorcami",
        Description = "Zrodlo wzorcow - uzywane przy ponownym zleceniu, gdy zadanie przepadlo.",
        IsRequired = true,
        Order = 13)]
    public int PatternsDataSourceId { get; set; }

    [ConfigEditableText(
        DisplayName = "ID obiegu docelowego (Dokument HR)",
        Description = "ID obiegu, w ktorym maja powstawac elementy dokumentow HR.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 30)]
    public string TargetWorkflowId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "ID typu formularza docelowego (Dokument HR)",
        Description = "ID typu formularza dla elementow dokumentow HR.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 31)]
    public string TargetDocTypeId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "ID sciezki startowej (obieg Dokument HR)",
        Description = "ID sciezki przejscia, ktora nowy element ma wystartowac.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 32)]
    public string StartPathId { get; set; } = "";

    [ConfigEditableFormFieldID(
        DisplayName = "Pole na flage weryfikacji",
        Description = "Opcjonalne: pole tak/nie w obiegu docelowym na flage weryfikacji. Puste = nie zapisuj.",
        Order = 33)]
    public int? RequiresReviewFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Pole na powody weryfikacji",
        Description = "Opcjonalne: pole tekstowe na powody weryfikacji (jeden na linie). " +
                      "Ustawione = powody nie dubluja sie w komentarzu. Puste = powody do komentarza.",
        Order = 34)]
    public int? ReviewReasonsFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Pole na ID elementu nadrzednego",
        Description = "Opcjonalne: pole na ID elementu nadrzednego (paczki skanow). Puste = nie zapisuj. " +
                      "Relacja systemowa rodzic-dziecko jest ustawiana zawsze.",
        Order = 35)]
    public int? ParentElementIdFieldId { get; set; }

    [ConfigEditableBool(
        DisplayName = "Pomijaj sprawdzanie uprawnien przy tworzeniu dokumentow",
        Description = "Zalecane WLACZONE dla akcji cyklicznej. Akcja dziala jako konto " +
                      "serwisowe WEBCON, ktore zwykle nie ma uprawnien do startowania " +
                      "elementow w spolce paczki - wylaczone konczy sie bledem " +
                      "'uzytkownik nie ma uprawnien do startowania elementow workflow'. " +
                      "Obieg docelowy i tak wskazujesz w konfiguracji powyzej.",
        Order = 39)]
    public bool SkipPermissionsCheck { get; set; } = true;

    [ConfigEditableInteger(
        DisplayName = "Maksymalna liczba prob",
        Description = "Po ilu NIEUDANYCH probach (404 lub failed) element jest oznaczany jako bledny. " +
                      "Zajetosc serwisu (503) i brak polaczenia sie nie licza.",
        DefaultValue = 3,
        MinValue = 1,
        MaxValue = 20,
        Order = 36)]
    public int MaxAttempts { get; set; } = 3;
}
