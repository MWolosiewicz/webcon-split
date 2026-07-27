using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class ExtractPagesActionConfig : SplitterConnectionConfig
{
    [ConfigEditableText(
        DisplayName = "ID zalacznika zrodlowego",
        Description = "ID zalacznika PDF biezacego elementu, z ktorego wycinamy strony. " +
                      "Zwykle regula biznesowa albo pole formularza zwracajace ID zalacznika.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 10)]
    public string SourceAttachmentId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Zakres stron do wyciecia",
        Description = "Strony 1-based, inclusive, np. '3-5'. Mozna przeciagnac tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 11)]
    public string PageRange { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "ID obiegu docelowego",
        Description = "ID obiegu, w ktorym ma powstac nowy element weryfikacyjny. Liczba lub tag/stala.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 12)]
    public string TargetWorkflowId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "ID typu formularza docelowego",
        Description = "ID typu formularza nowego elementu. Liczba lub tag/stala.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 13)]
    public string TargetDocTypeId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "ID sciezki startowej",
        Description = "ID sciezki, ktora nowy element ma wystartowac. Liczba lub tag/stala.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 14)]
    public string StartPathId { get; set; } = "";

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
}
