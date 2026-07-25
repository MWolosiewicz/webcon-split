using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class CollectSplitJobActionConfig : SplitJobFieldsConfig
{
    [ConfigEditableDataSourceID(
        DisplayName = "Patterns data source ID",
        Description = "Zrodlo wzorcow - uzywane przy ponownym zleceniu, gdy zadanie przepadlo.",
        IsRequired = true,
        Order = 13)]
    public int PatternsDataSourceId { get; set; }

    [ConfigEditableText(
        DisplayName = "Target workflow ID (HR document)",
        Description = "ID obiegu, w ktorym maja powstawac elementy dokumentow HR.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 30)]
    public string TargetWorkflowId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Target document type ID (HR document)",
        Description = "ID typu formularza dla elementow dokumentow HR.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 31)]
    public string TargetDocTypeId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Start path ID (HR document workflow)",
        Description = "ID sciezki przejscia, ktora nowy element ma wystartowac.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 32)]
    public string StartPathId { get; set; } = "";

    [ConfigEditableFormFieldID(
        DisplayName = "Requires review field ID",
        Description = "Opcjonalne: pole tak/nie w obiegu docelowym na flage weryfikacji. Puste = nie zapisuj.",
        Order = 33)]
    public int? RequiresReviewFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Review reasons field ID",
        Description = "Opcjonalne: pole tekstowe na powody weryfikacji (jeden na linie). " +
                      "Ustawione = powody nie dubluja sie w komentarzu. Puste = powody do komentarza.",
        Order = 34)]
    public int? ReviewReasonsFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Parent element ID field ID",
        Description = "Opcjonalne: pole na ID elementu nadrzednego (paczki skanow). Puste = nie zapisuj. " +
                      "Relacja systemowa rodzic-dziecko jest ustawiana zawsze.",
        Order = 35)]
    public int? ParentElementIdFieldId { get; set; }

    [ConfigEditableInteger(
        DisplayName = "Max attempts",
        Description = "Po ilu NIEUDANYCH probach (404 lub failed) element jest oznaczany jako bledny. " +
                      "Zajetosc serwisu (503) i brak polaczenia sie nie licza.",
        DefaultValue = 3,
        MinValue = 1,
        MaxValue = 20,
        Order = 36)]
    public int MaxAttempts { get; set; } = 3;
}
