using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class MergeAttachmentsActionConfig : SplitterConnectionConfig, IConfigEditableItemList
{
    [ConfigEditableItemList(
        DisplayName = "Lista pozycji z zalacznikami",
        Description = "Lista pozycji, w ktorej kazdy wiersz wskazuje jeden zalacznik do sklejenia. " +
                      "Kolejnosc wierszy = kolejnosc sklejania.")]
    public int ItemListId { get; set; }

    [ConfigEditableItemListColumnID(
        DisplayName = "Kolumna z ID zalacznika",
        Description = "Kolumna typu picker (zrodlo danych zwracajace ID i nazwy zalacznikow formularza). " +
                      "Akcja czyta zapisane ID zalacznika z kazdego wiersza.",
        IsRequired = true,
        // uwaga: 'ChoosePicer' to nazwa wartosci w SDK (literowka producenta) - oznacza kolumne typu picker
        ItemListColumnTypes = ItemListColumnTypes.ChoosePicer)]
    public int AttachmentIdColumnId { get; set; }

    [ConfigEditableText(
        DisplayName = "Nazwa pliku wynikowego",
        Description = "Nazwa sklejonego PDF dodawanego do biezacego elementu, np. 'scalony.pdf'.",
        DefaultText = "scalony.pdf",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 13)]
    public string OutputFileName { get; set; } = "scalony.pdf";
}
