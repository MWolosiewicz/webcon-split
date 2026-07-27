using System;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

internal static class AttachmentSourceHelper
{
    /// <summary>
    /// Zwraca zalacznik PDF wskazany po ID - typowo z reguly biznesowej
    /// wystawionej na pole konfiguracji akcji.
    ///
    /// Kontrola przynaleznosci do biezacego elementu nie jest tu ostroznoscia
    /// na wyrost: regula zwraca sama liczbe, a GetAttachmentAsync siega do
    /// calej bazy. Bez niej bledne ID w trybie "podmien zawartosc w miejscu"
    /// nadpisaloby zalacznik CUDZEGO elementu - po cichu i nieodwracalnie.
    /// </summary>
    public static async Task<AttachmentData> GetPdfByIdAsync(
        RunCustomActionParams args, string rawAttachmentId)
    {
        var attachmentId = ConfigHelper.ParsePositiveInt(
            rawAttachmentId, "ID zalacznika zrodlowego");

        var manager = new DocumentAttachmentsManager(args.Context);
        // jawne przypisania zamiast pozycyjnego GetAttachmentAsync(id, bool);
        // SkipPermissionsCheck = false, bo akcje reczne wykonuje klikajacy
        // uzytkownik i to jego uprawnienia maja decydowac
        var attachment = await manager.GetAttachmentAsync(new GetAttachmentParams
        {
            AttachmentId = attachmentId,
            SkipPermissionsCheck = false,
        });

        if (attachment == null)
            throw new InvalidOperationException(
                $"Nie znaleziono zalacznika o ID {attachmentId} " +
                "(nie istnieje albo uzytkownik nie ma do niego uprawnien).");

        var currentDocumentId = args.Context.CurrentDocument.ID;
        if (attachment.DocumentID != currentDocumentId)
            throw new InvalidOperationException(
                $"Zalacznik ID {attachmentId} nalezy do elementu " +
                $"{attachment.DocumentID?.ToString() ?? "nieznanego"}, a nie do biezacego " +
                $"({currentDocumentId}). Sprawdz regule wskazujaca ID zalacznika.");

        var extension = attachment.FileExtension?.TrimStart('.') ?? "";
        if (!string.Equals(extension, "pdf", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException(
                $"Zalacznik '{attachment.FileName}' (ID {attachmentId}) nie jest plikiem PDF.");

        return attachment;
    }
}
