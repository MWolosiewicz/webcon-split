using System;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;
using WebCon.WorkFlow.SDK.Tools.Data;
using WebCon.WorkFlow.SDK.Tools.Data.Model;

namespace WebconPdfSplitterAction;

public class SplitPdfAction : CustomAction<SplitPdfActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        // wersja paczki pluginu w logu operacji - pozwala od razu widziec,
        // ktora wersja dodatku faktycznie wykonala akcje
        var pluginVersion = typeof(SplitPdfAction).Assembly.GetName().Version?.ToString() ?? "?";
        try
        {
            var targetWorkflowId = ParseId(Configuration.TargetWorkflowId, "Target workflow ID");
            var targetDocTypeId = ParseId(Configuration.TargetDocTypeId, "Target document type ID");
            var startPathId = ParseId(Configuration.StartPathId, "Start path ID");

            var patterns = await LoadPatternsAsync(args);
            var patternsWarning = patterns.Count == 0
                ? "Warning: patterns data source returned no rows; every page will be classified as unknown. "
                : "";

            var sourceAttachment = await GetSingleSourcePdfAsync(args);
            var pdfContent = await sourceAttachment.GetContentAsync();

            SplitResult result;
            using (var httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(Configuration.TimeoutSeconds) })
            {
                var client = new SplitterClient(httpClient, Configuration.SplitterBaseUrl, Configuration.ApiToken);
                result = await client.SplitAsync(
                    sourceAttachment.FileName,
                    new MemoryStream(pdfContent),
                    args.Context.CurrentDocument.ID,
                    patterns);
            }

            var documentsManager = new DocumentsManager(args.Context);
            var createdIds = new List<int>();

            foreach (var detected in result.Documents)
            {
                // jawne przypisania: konstruktor SDK ma kolejnosc (docTypeID, workFlowID),
                // latwo o pomylke pozycyjna
                var newDocument = await documentsManager.GetNewDocumentAsync(
                    new GetNewDocumentParams
                    {
                        WorkFlowID = targetWorkflowId,
                        DocTypeID = targetDocTypeId,
                        ParentDocumentID = args.Context.CurrentDocument.ID,
                    });

                if (!string.IsNullOrEmpty(detected.FileContentBase64))
                {
                    await newDocument.Attachments.AddNewAsync(
                        detected.OutputFileName,
                        Convert.FromBase64String(detected.FileContentBase64));
                }

                await newDocument.Comment.AddCommentAsync(FormatDetectionComment(detected));

                if (Configuration.RequiresReviewFieldId > 0)
                    await newDocument.SetFieldValueAsync(
                        Configuration.RequiresReviewFieldId, detected.RequiresReview);

                if (Configuration.ReviewReasonsFieldId > 0)
                    await newDocument.SetFieldValueAsync(
                        Configuration.ReviewReasonsFieldId,
                        string.Join(Environment.NewLine, detected.ReviewReasons));

                if (Configuration.ParentElementIdFieldId > 0)
                    await newDocument.SetFieldValueAsync(
                        Configuration.ParentElementIdFieldId, args.Context.CurrentDocument.ID);

                var started = await documentsManager.StartNewWorkFlowAsync(
                    new StartNewWorkFlowParams(newDocument, startPathId));
                createdIds.Add(started.CreatedDocumentID);
            }

            args.LogMessage =
                $"SplitPdfAction v{pluginVersion}. " +
                patternsWarning +
                $"Splitter job {result.JobId}: {result.Status}, pages: {result.PageCount}, " +
                $"documents: {result.Documents.Count}, created elements: {string.Join(", ", createdIds)}";
        }
        catch (Exception ex)
        {
            args.HasErrors = true;
            args.Message = "PDF split failed. Check the technical log for details.";
            args.LogMessage = $"SplitPdfAction v{pluginVersion}. {ex}";
        }
    }

    private async Task<AttachmentData> GetSingleSourcePdfAsync(RunCustomActionParams args)
    {
        var attachmentsManager = new DocumentAttachmentsManager(args.Context);
        var attachments = await attachmentsManager.GetAttachmentsAsync(
            new GetAttachmentsParams { DocumentId = args.Context.CurrentDocument.ID });

        var pdfs = attachments
            .Where(a => string.Equals(a.FileExtension?.TrimStart('.'), "pdf", StringComparison.OrdinalIgnoreCase))
            .ToList();

        if (pdfs.Count == 0)
            throw new InvalidOperationException("The scan bundle has no PDF attachment.");
        if (pdfs.Count > 1)
            throw new InvalidOperationException("The scan bundle has more than one PDF attachment; source file is ambiguous.");

        return pdfs[0];
    }

    private static int ParseId(string configuredValue, string fieldName)
    {
        if (int.TryParse(configuredValue?.Trim(), out var id) && id > 0)
            return id;

        throw new InvalidOperationException(
            $"Configuration field '{fieldName}' must evaluate to a positive integer, got: '{configuredValue}'.");
    }

    private string FormatDetectionComment(DetectedDocument detected)
    {
        var comment =
            $"Type: {detected.DocumentType}; pages {detected.StartPage}-{detected.EndPage}; " +
            $"confidence {detected.Confidence:0.00}; requires review: {detected.RequiresReview}";
        // powody trafiaja do komentarza tylko, gdy nie sa zapisywane w dedykowanym polu
        if (Configuration.ReviewReasonsFieldId <= 0 && detected.ReviewReasons.Count > 0)
            comment += $"; review reasons: {string.Join("; ", detected.ReviewReasons)}";
        return comment;
    }

    private async Task<List<PatternPayload>> LoadPatternsAsync(RunCustomActionParams args)
    {
        var helper = new DataSourcesHelper(args.Context);
        var table = await helper.GetDataTableFromDataSourceAsync(
            new GetDataTableFromDataSourceParams(Configuration.PatternsDataSourceId, null));

        var required = new[] { "DocumentType", "Header", "Phrases", "ExcludedPhrases", "Weight" };
        var missing = required.Where(column => !table.Columns.Contains(column)).ToList();
        if (missing.Count > 0)
            throw new InvalidOperationException(
                $"Patterns data source {Configuration.PatternsDataSourceId} is missing required columns: " +
                $"{string.Join(", ", missing)}. Expected columns: {string.Join(", ", required)}.");

        var patterns = new List<PatternPayload>();
        foreach (DataRow row in table.Rows)
        {
            var header = (row["Header"] as string)?.Trim();
            if (string.IsNullOrEmpty(header))
                continue;

            patterns.Add(new PatternPayload
            {
                DocumentType = (row["DocumentType"] as string)?.Trim() ?? "",
                Header = header!,
                Phrases = SplitPhrases(row["Phrases"]),
                ExcludedPhrases = SplitPhrases(row["ExcludedPhrases"]),
                Weight = row["Weight"] == DBNull.Value || row["Weight"] == null
                    ? 1.0
                    : Convert.ToDouble(row["Weight"], CultureInfo.InvariantCulture),
            });
        }
        return patterns;
    }

    private static List<string> SplitPhrases(object? value) =>
        value is string text
            ? text.Split(';').Select(phrase => phrase.Trim()).Where(phrase => phrase.Length > 0).ToList()
            : new List<string>();
}
