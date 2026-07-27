using System;
using System.IO;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;

namespace WebconPdfSplitterAction;

public class ExtractPagesAction : CustomAction<ExtractPagesActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        var pluginVersion = typeof(ExtractPagesAction).Assembly.GetName().Version?.ToString() ?? "?";
        try
        {
            var targetWorkflowId = ConfigHelper.ParsePositiveInt(
                Configuration.TargetWorkflowId, "ID obiegu docelowego");
            var targetDocTypeId = ConfigHelper.ParsePositiveInt(
                Configuration.TargetDocTypeId, "ID typu formularza docelowego");
            var startPathId = ConfigHelper.ParsePositiveInt(
                Configuration.StartPathId, "ID sciezki startowej");
            // walidacja PRZED utworzeniem elementu - pusta kategoria wykryta
            // dopiero po StartNewWorkFlowAsync zostawilaby w obiegu wystartowany
            // element potomny, ktorego nikt nie zamowil
            var targetCategoryId = Configuration.TargetAttachmentCategoryId?.Trim() ?? "";
            if (targetCategoryId.Length == 0)
                throw new InvalidOperationException(
                    "Pole konfiguracji 'ID kategorii dla nowego zalacznika' jest puste.");

            var source = await AttachmentSourceHelper.GetPdfByIdAsync(
                args, Configuration.SourceAttachmentId);
            var pdfContent = await source.GetContentAsync();

            PageOpResult? removeResult = null;
            var client = new SplitterClient(
                Configuration.SplitterBaseUrl, Configuration.ApiToken, Configuration.TimeoutSeconds);
            var extractResult = await client.ExtractPagesAsync(
                source.FileName, new MemoryStream(pdfContent), Configuration.PageRange,
                args.Context.CurrentDocument.ID);

            if (Configuration.RemoveFromSource)
                removeResult = await client.RemovePagesAsync(
                    source.FileName, new MemoryStream(pdfContent), Configuration.PageRange,
                    args.Context.CurrentDocument.ID);

            var documentsManager = new DocumentsManager(args.Context);
            // jawne przypisania: konstruktor SDK ma kolejnosc (docTypeID, workFlowID),
            // latwo o pomylke pozycyjna
            var newDocument = await documentsManager.GetNewDocumentAsync(
                new GetNewDocumentParams
                {
                    WorkFlowID = targetWorkflowId,
                    DocTypeID = targetDocTypeId,
                    ParentDocumentID = args.Context.CurrentDocument.ID,
                    // Spolka jawnie, mimo ze ta akcja dziala w kontekscie
                    // klikajacego uzytkownika. Dokumentacja SDK dla CompanyID
                    // mowi "If not set default is taken" - i jest to domyslna
                    // spolka KONTEKSTU, nie dokumentu nadrzednego. Gdyby
                    // dziedziczyla po rodzicu, poprawka w akcji odbierajacej
                    // (60589bc) nie bylaby potrzebna, bo ParentDocumentID byl
                    // tam ustawiony od poczatku. U uzytkownika przypisanego do
                    // kilku spolek dokument potomny trafialby wiec do innej
                    // spolki niz zrodlo.
                    //
                    // SkipPermissionsCheck celowo NIE jest ustawiany: te akcje
                    // wywoluje uzytkownik i to jego uprawnienia maja decydowac.
                    // W akcji odbierajacej jest inaczej tylko dlatego, ze tam
                    // wykonawca jest konto serwisowe WEBCON.
                    CompanyID = args.Context.CurrentDocument.CompanyID,
                });

            // AddNewAsync zwraca AttachmentData, wiec grupe plikow ustawiamy na
            // zwroconym obiekcie - tak samo, jak RemovePagesAction robi to dla
            // zalacznika biezacego elementu
            var newAttachment = await newDocument.Attachments.AddNewAsync(
                extractResult.OutputFileName,
                Convert.FromBase64String(extractResult.FileContentBase64));
            await newAttachment.SetFileGroupAsync(targetCategoryId);
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
                $"ExtractPagesAction v{pluginVersion}. Zrodlo '{source.FileName}' (ID {source.ID}); " +
                $"wyciete strony '{Configuration.PageRange}' ({extractResult.PageCount} stron); " +
                $"utworzono element {started.CreatedDocumentID}, kategoria zalacznika '{targetCategoryId}'; " +
                $"zrodlo: {(Configuration.RemoveFromSource ? "strony usuniete" : "nietkniete")}.";
        }
        catch (Exception ex)
        {
            args.HasErrors = true;
            args.Message = $"Wyciecie stron do nowego elementu nie powiodlo sie: {ex.Message}";
            args.LogMessage = $"ExtractPagesAction v{pluginVersion}. {ex}";
        }
    }

}
