using System.Collections.Generic;
using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class MergeAttachmentsActionConfig : SplitterConnectionConfig
{
    [ConfigEditableItemList(
        DisplayName = "Lista pozycji z zalacznikami",
        Description = "Lista pozycji, w ktorej kazdy wiersz wskazuje jeden zalacznik do sklejenia. " +
                      "Kolejnosc wierszy = kolejnosc sklejania.")]
    public MergeItemListConfig ItemList { get; set; } = new();

    [ConfigEditableText(
        DisplayName = "Nazwa pliku wynikowego",
        Description = "Nazwa sklejonego PDF dodawanego do biezacego elementu, np. 'scalony.pdf'.",
        DefaultText = "scalony.pdf",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 13)]
    public string OutputFileName { get; set; } = "scalony.pdf";
}

// Portal wymaga, by wlasciwosc z [ConfigEditableItemList] byla klasa
// implementujaca IConfigEditableItemList<TColumns>.
public class MergeItemListConfig : IConfigEditableItemList<MergeItemListColumns>
{
    public int ItemListId { get; set; }
    public List<MergeItemListColumns> ListColumns { get; set; } = new();
}

public class MergeItemListColumns
{
    [ConfigEditableItemListColumnID(
        DisplayName = "Kolumna z ID zalacznika",
        Description = "Kolumna typu picker (zrodlo danych zwracajace ID i nazwy zalacznikow formularza). " +
                      "Akcja czyta zapisane ID zalacznika z kazdego wiersza.",
        IsRequired = true,
        // uwaga: 'ChoosePicer' to nazwa wartosci w SDK (literowka producenta) - oznacza kolumne typu picker
        ItemListColumnTypes = ItemListColumnTypes.ChoosePicer)]
    public int AttachmentIdColumnId { get; set; }
}
