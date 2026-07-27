using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class RemovePagesActionConfig : SplitterConnectionConfig
{
    [ConfigEditableText(
        DisplayName = "ID zalacznika zrodlowego",
        Description = "ID zalacznika PDF biezacego elementu, na ktorym akcja ma dzialac. " +
                      "Zwykle regula biznesowa albo pole formularza zwracajace ID zalacznika.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 10)]
    public string SourceAttachmentId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Zakres stron do usuniecia",
        Description = "Strony 1-based, inclusive, np. '2-4,7'. Mozna przeciagnac tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 11)]
    public string PageRange { get; set; } = "";

    [ConfigEditableBool(
        DisplayName = "Podmien zawartosc w miejscu",
        Description = "Wlaczone: usuwa strony z istniejacego zalacznika (nadpisuje). " +
                      "Wylaczone: dodaje nowy zalacznik z wynikiem, oryginal zostaje.",
        Order = 12)]
    public bool ReplaceInPlace { get; set; }
}
