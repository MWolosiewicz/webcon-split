using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

internal static class AttachmentSourceHelper
{
    // Zwraca dokladnie jeden zalacznik PDF nalezacy do dozwolonych kategorii (FileGroup).
    // Kategorie z konfiguracji rozdzielone srednikami; dopasowanie po ID lub nazwie grupy.
    public static async Task<AttachmentData> GetSinglePdfInCategoriesAsync(
        RunCustomActionParams args, string allowedCategoriesRaw)
    {
        var allowed = (allowedCategoriesRaw ?? "")
            .Split(';')
            .Select(value => value.Trim())
            .Where(value => value.Length > 0)
            .ToList();
        if (allowed.Count == 0)
            throw new InvalidOperationException(
                "Nie skonfigurowano dozwolonych kategorii zalacznikow dla tej akcji.");

        var manager = new DocumentAttachmentsManager(args.Context);
        var attachments = await manager.GetAttachmentsAsync(
            new GetAttachmentsParams { DocumentId = args.Context.CurrentDocument.ID });

        bool InAllowed(AttachmentData attachment) =>
            attachment.FileGroup != null &&
            allowed.Any(category =>
                string.Equals(category, attachment.FileGroup.ID, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(category, attachment.FileGroup.DisplayName, StringComparison.OrdinalIgnoreCase));

        var pdfs = attachments
            .Where(a => string.Equals(a.FileExtension?.TrimStart('.'), "pdf", StringComparison.OrdinalIgnoreCase))
            .Where(InAllowed)
            .ToList();

        if (pdfs.Count == 0)
            throw new InvalidOperationException(
                $"Brak zalacznika PDF w dozwolonych kategoriach ({string.Join(", ", allowed)}).");
        if (pdfs.Count > 1)
            throw new InvalidOperationException(
                $"Wiecej niz jeden PDF w dozwolonych kategoriach ({string.Join(", ", allowed)}); zrodlo niejednoznaczne.");
        return pdfs[0];
    }
}
