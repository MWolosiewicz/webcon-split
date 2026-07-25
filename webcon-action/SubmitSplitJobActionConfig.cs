using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class SubmitSplitJobActionConfig : SplitJobFieldsConfig
{
    [ConfigEditableDataSourceID(
        DisplayName = "Patterns data source ID",
        Description = "Zrodlo danych zwracajace aktywne wzorce rozpoznawania. " +
                      "Wymagane kolumny: DocumentType, Header, Phrases, ExcludedPhrases, Weight.",
        IsRequired = true,
        Order = 13)]
    public int PatternsDataSourceId { get; set; }
}
