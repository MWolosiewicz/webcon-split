using System;
using System.Globalization;
using System.IO;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

public class ExtractPagesToNewFormAction : CustomAction<ExtractPagesToNewFormActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        var pluginVersion = typeof(ExtractPagesToNewFormAction).Assembly.GetName().Version?.ToString(3) ?? "?";
        try
        {
            var targetWorkflowId = ParseId(Configuration.TargetWorkflowId, "Target workflow ID");
            var targetDocTypeId = ParseId(Configuration.TargetDocTypeId, "Target document type ID");
            var startPathId = ParseId(Configuration.StartPathId, "Start path ID");

            var source = await AttachmentSourceHelper.GetSinglePdfInCategoriesAsync(
                args, Configuration.AllowedCategories);
            var pdfContent = await source.GetContentAsync();

            PageOpResult extractResult;
            PageOpResult? removeResult = null;
            using (var httpClient = new System.Net.Http.HttpClient
                   { Timeout = TimeSpan.FromSeconds(Configuration.TimeoutSeconds) })
            {
                var client = new SplitterClient(httpClient, Configuration.SplitterBaseUrl, Configuration.ApiToken);
                extractResult = await client.ExtractPagesAsync(
                    source.FileName, new MemoryStream(pdfContent), Configuration.PageRange,
                    args.Context.CurrentDocument.ID);

                if (Configuration.RemoveFromSource)
                    removeResult = await client.RemovePagesAsync(
                        source.FileName, new MemoryStream(pdfContent), Configuration.PageRange,
                        args.Context.CurrentDocument.ID);
            }

            var documentsManager = new DocumentsManager(args.Context);
            var newDocument = await documentsManager.GetNewDocumentAsync(
                new GetNewDocumentParams(targetWorkflowId, targetDocTypeId)
                {
                    ParentDocumentID = args.Context.CurrentDocument.ID,
                });

            await newDocument.Attachments.AddNewAsync(
                extractResult.OutputFileName,
                Convert.FromBase64String(extractResult.FileContentBase64));
            await newDocument.Comment.AddCommentAsync(
                $"Wyciete ze zrodla '{source.FileName}', strony '{Configuration.PageRange}'.");

            var started = await documentsManager.StartNewWorkFlowAsync(
                new StartNewWorkFlowParams(newDocument, startPathId));

            if (removeResult != null)
            {
                var manager = new DocumentAttachmentsManager(args.Context);
                source.SetContent(Convert.FromBase64String(removeResult.FileContentBase64));
                await manager.UpdateAttachmentAsync(new UpdateAttachmentParams { Attachment = source });
            }

            args.LogMessage =
                $"ExtractPagesToNewFormAction v{pluginVersion}. Zrodlo '{source.FileName}' (ID {source.ID}); " +
                $"wyciete strony '{Configuration.PageRange}' ({extractResult.PageCount} stron); " +
                $"utworzono element {started.CreatedDocumentID}; " +
                $"zrodlo: {(Configuration.RemoveFromSource ? "strony usuniete" : "nietkniete")}.";
        }
        catch (Exception ex)
        {
            args.HasErrors = true;
            args.Message = $"Wyciecie stron do nowego elementu nie powiodlo sie: {ex.Message}";
            args.LogMessage = $"ExtractPagesToNewFormAction v{pluginVersion}. {ex}";
        }
    }

    private static int ParseId(string configuredValue, string fieldName)
    {
        if (int.TryParse(configuredValue?.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var id) && id > 0)
            return id;
        throw new InvalidOperationException(
            $"Pole konfiguracji '{fieldName}' musi byc dodatnia liczba calkowita, otrzymano: '{configuredValue}'.");
    }
}
