using System;
using System.IO;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

public class RemovePagesAction : CustomAction<RemovePagesActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        var pluginVersion = typeof(RemovePagesAction).Assembly.GetName().Version?.ToString() ?? "?";
        try
        {
            var source = await AttachmentSourceHelper.GetSinglePdfInCategoriesAsync(
                args, Configuration.AllowedCategories);
            var pdfContent = await source.GetContentAsync();

            var client = new SplitterClient(
                Configuration.SplitterBaseUrl, Configuration.ApiToken, Configuration.TimeoutSeconds);
            var result = await client.RemovePagesAsync(
                source.FileName,
                new MemoryStream(pdfContent),
                Configuration.PageRange,
                args.Context.CurrentDocument.ID);

            var outputBytes = Convert.FromBase64String(result.FileContentBase64);
            var manager = new DocumentAttachmentsManager(args.Context);

            if (Configuration.ReplaceInPlace)
            {
                source.SetContent(outputBytes);
                await manager.UpdateAttachmentAsync(new UpdateAttachmentParams { Attachment = source });
            }
            else
            {
                var newAttachment = await manager.GetNewAttachmentAsync(result.OutputFileName, outputBytes);
                if (source.FileGroup != null)
                    await newAttachment.SetFileGroupAsync(source.FileGroup.ID);
                await manager.AddAttachmentAsync(new AddAttachmentParams
                {
                    DocumentId = args.Context.CurrentDocument.ID,
                    Attachment = newAttachment,
                });
            }

            args.LogMessage =
                $"RemovePagesAction v{pluginVersion}. Zrodlo '{source.FileName}' (ID {source.ID}); " +
                $"usunieto strony '{Configuration.PageRange}'; wynik {result.PageCount} stron; " +
                $"tryb: {(Configuration.ReplaceInPlace ? "podmiana w miejscu" : "nowy zalacznik")}.";
        }
        catch (Exception ex)
        {
            args.HasErrors = true;
            args.Message = $"Usuwanie stron nie powiodlo sie: {ex.Message}";
            args.LogMessage = $"RemovePagesAction v{pluginVersion}. {ex}";
        }
    }
}
