using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

public class SplitPdfAction : CustomAction<SplitPdfActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        try
        {
            var sourceAttachment = await GetSingleSourcePdfAsync(args);
            var pdfContent = await sourceAttachment.GetContentAsync();

            SplitResult result;
            using (var httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(Configuration.TimeoutSeconds) })
            {
                var client = new SplitterClient(httpClient, Configuration.SplitterBaseUrl, Configuration.ApiToken);
                result = await client.SplitAsync(sourceAttachment.FileName, new MemoryStream(pdfContent));
            }

            var documentsManager = new DocumentsManager(args.Context);
            var createdIds = new List<int>();

            foreach (var detected in result.Documents)
            {
                var newDocument = await documentsManager.GetNewDocumentAsync(
                    new GetNewDocumentParams(Configuration.TargetWorkflowId, Configuration.TargetDocTypeId)
                    {
                        ParentDocumentID = args.Context.CurrentDocument.ID,
                    });

                if (!string.IsNullOrEmpty(detected.FileContentBase64))
                {
                    await newDocument.Attachments.AddNewAsync(
                        detected.OutputFileName,
                        Convert.FromBase64String(detected.FileContentBase64));
                }

                await newDocument.Comment.AddCommentAsync(FormatDetectionComment(detected));

                var started = await documentsManager.StartNewWorkFlowAsync(
                    new StartNewWorkFlowParams(newDocument, Configuration.StartPathId));
                createdIds.Add(started.CreatedDocumentID);
            }

            args.LogMessage =
                $"Splitter: {result.Status}, pages: {result.PageCount}, " +
                $"documents: {result.Documents.Count}, created elements: {string.Join(", ", createdIds)}";
        }
        catch (Exception ex)
        {
            args.HasErrors = true;
            args.Message = "PDF split failed. Check the technical log for details.";
            args.LogMessage = ex.ToString();
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

    private static string FormatDetectionComment(DetectedDocument detected) =>
        $"Type: {detected.DocumentType}; pages {detected.StartPage}-{detected.EndPage}; " +
        $"confidence {detected.Confidence:0.00}; requires review: {detected.RequiresReview}";
}
