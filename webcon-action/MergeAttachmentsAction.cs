using System;
using System.Collections.Generic;
using System.Globalization;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

public class MergeAttachmentsAction : CustomAction<MergeAttachmentsActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        var pluginVersion = typeof(MergeAttachmentsAction).Assembly.GetName().Version?.ToString() ?? "?";
        try
        {
            var itemListId = Configuration.ItemList?.ItemListId ?? 0;
            if (itemListId <= 0)
                throw new InvalidOperationException("Nie wskazano listy pozycji w konfiguracji akcji.");
            var attachmentColumnId = Configuration.ItemList?.ListColumns?.Count > 0
                ? Configuration.ItemList.ListColumns[0].AttachmentIdColumnId
                : 0;
            if (attachmentColumnId <= 0)
                throw new InvalidOperationException("Nie wskazano kolumny z ID zalacznika w konfiguracji akcji.");

            var itemList = args.Context.CurrentDocument.ItemsLists.GetByID(itemListId);
            if (itemList == null)
                throw new InvalidOperationException(
                    $"Nie znaleziono listy pozycji o ID {itemListId}.");

            var manager = new DocumentAttachmentsManager(args.Context);
            var inputs = new List<MergeInput>();
            foreach (var row in itemList.Rows)
            {
                var rawValue = row.GetCellValue(attachmentColumnId, EntityValueFormat.PairID);
                var idText = rawValue?.ToString()?.Trim();
                if (string.IsNullOrEmpty(idText))
                    continue; // pomijamy puste wiersze (niewybrany zalacznik)
                if (!int.TryParse(idText, NumberStyles.Integer, CultureInfo.InvariantCulture, out var attachmentId))
                    throw new InvalidOperationException(
                        $"Wartosc '{idText}' w wierszu listy pozycji nie jest poprawnym ID zalacznika.");

                var attachment = await manager.GetAttachmentAsync(attachmentId, false);
                var content = await attachment.GetContentAsync();
                inputs.Add(new MergeInput { FileName = attachment.FileName, Content = content });
            }

            if (inputs.Count == 0)
                throw new InvalidOperationException(
                    "Lista pozycji nie wskazuje zadnego zalacznika do sklejenia.");

            var client = new SplitterClient(
                Configuration.SplitterBaseUrl, Configuration.ApiToken, Configuration.TimeoutSeconds);
            var result = await client.MergeAsync(inputs, args.Context.CurrentDocument.ID);

            var outputBytes = Convert.FromBase64String(result.FileContentBase64);
            var newAttachment = await manager.GetNewAttachmentAsync(Configuration.OutputFileName, outputBytes);
            await manager.AddAttachmentAsync(new AddAttachmentParams
            {
                DocumentId = args.Context.CurrentDocument.ID,
                Attachment = newAttachment,
            });

            args.LogMessage =
                $"MergeAttachmentsAction v{pluginVersion}. Sklejono {inputs.Count} zalacznikow " +
                $"w '{Configuration.OutputFileName}' ({result.PageCount} stron).";
        }
        catch (Exception ex)
        {
            args.HasErrors = true;
            args.Message = $"Sklejanie zalacznikow nie powiodlo sie: {ex.Message}";
            args.LogMessage = $"MergeAttachmentsAction v{pluginVersion}. {ex}";
        }
    }
}
