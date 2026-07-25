using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class SplitPdfActionConfig : SplitterConnectionConfig
{
    [ConfigEditableText(
        DisplayName = "Target workflow ID (HR document)",
        Description = "ID obiegu, w ktorym maja powstawac elementy dokumentow HR. " +
                      "Wpisz liczbe albo przeciagnij tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 10)]
    public string TargetWorkflowId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Target document type ID (HR document)",
        Description = "ID typu formularza dla elementow dokumentow HR. " +
                      "Wpisz liczbe albo przeciagnij tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 11)]
    public string TargetDocTypeId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Start path ID (HR document workflow)",
        Description = "ID sciezki przejscia, ktora nowy element ma wystartowac. " +
                      "Wpisz liczbe albo przeciagnij tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 12)]
    public string StartPathId { get; set; } = "";

    [ConfigEditableDataSourceID(
        DisplayName = "Patterns data source ID",
        Description = "Zrodlo danych zwracajace aktywne wzorce rozpoznawania. " +
                      "Wymagane kolumny: DocumentType, Header, Phrases, ExcludedPhrases, Weight.",
        IsRequired = true,
        Order = 13)]
    public int PatternsDataSourceId { get; set; }

    // UWAGA: pola opcjonalne MUSZA byc nullowalne (int?). Przy typie `int`
    // Designer Studio wysyla dla niewypelnionego pola pusty string, a SDK
    // wywraca akcje jeszcze przed jej uruchomieniem:
    //   Invalid configuration. PropertyName: "...", type: "Int32",
    //   invalid value: "" - The input string '' was not in a correct format.
    // Wartosci czytamy przez GetValueOrDefault(), zeby `null` znaczylo to samo
    // co 0 ("nie zapisuj") - patrz SplitPdfAction.

    [ConfigEditableFormFieldID(
        DisplayName = "Requires review field ID",
        Description = "Opcjonalne: pole tak/nie w obiegu docelowym na flage weryfikacji. Puste = nie zapisuj.",
        Order = 14)]
    public int? RequiresReviewFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Review reasons field ID",
        Description = "Opcjonalne: pole tekstowe na powody weryfikacji (jeden na linie). " +
                      "Ustawione = powody nie dubluja sie w komentarzu. Puste = powody do komentarza.",
        Order = 15)]
    public int? ReviewReasonsFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Parent element ID field ID",
        Description = "Opcjonalne: pole w obiegu docelowym, do ktorego akcja wpisze ID elementu " +
                      "nadrzednego (paczki skanow). Puste = nie zapisuj. Relacja systemowa " +
                      "rodzic-dziecko jest ustawiana zawsze, niezaleznie od tego pola.",
        Order = 16)]
    public int? ParentElementIdFieldId { get; set; }
}
