using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model;

namespace WebconPdfSplitterAction;

/// <summary>
/// Akcja cykliczna na kroku przetwarzania: odpytuje o status zadania,
/// a po jego zakonczeniu tworzy dokumenty potomne.
///
/// Brak jobId, 404 i wygasly wynik prowadza do TEJ SAMEJ sciezki
/// (zlec ponownie) - zrodlem prawdy jest zalacznik w WEBCONie.
/// Licznik prob rosnie tylko przy 404/failed; zajetosc uslugi nie jest
/// awaria i nie moze wypchnac elementu na sciezke bledu.
/// </summary>
public class CollectSplitJobAction : CustomAction<CollectSplitJobActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        var pluginVersion = typeof(CollectSplitJobAction).Assembly.GetName().Version?.ToString() ?? "?";
        try
        {
            args.LogMessage = $"CollectSplitJobAction v{pluginVersion}. " + await HandleAsync(args);
        }
        catch (Exception ex)
        {
            args.HasErrors = true;
            args.Message = "Odbior wyniku podzialu nie powiodl sie. Sprawdz log techniczny.";
            args.LogMessage = $"CollectSplitJobAction v{pluginVersion}. {ex}";
        }
    }

    private async Task<string> HandleAsync(RunCustomActionParams args)
    {
        var jobId = SplitJobSubmitter.GetField(args, Configuration.JobIdFieldId, "");
        if (string.IsNullOrWhiteSpace(jobId))
            return await SplitJobSubmitter.SubmitAsync(
                args, Configuration, Configuration.PatternsDataSourceId);

        using var httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(Configuration.TimeoutSeconds) };
        var client = new SplitterClient(httpClient, Configuration.SplitterBaseUrl, Configuration.ApiToken);

        JobStatusResponse? status;
        try
        {
            status = await client.GetJobStatusAsync(jobId);
        }
        catch (HttpRequestException ex)
        {
            // splitter niedostepny - to nie awaria elementu; sprobujemy
            // przy nastepnym takcie (licznik prob nie rosnie)
            await SplitJobSubmitter.SetFieldAsync(
                args, Configuration.StatusFieldId, "splitter niedostepny, ponowienie");
            return $"Odpytanie zadania {jobId} nieudane (brak polaczenia): {ex.Message}";
        }
        catch (TaskCanceledException ex)
        {
            await SplitJobSubmitter.SetFieldAsync(
                args, Configuration.StatusFieldId, "splitter nie odpowiada, ponowienie");
            return $"Odpytanie zadania {jobId} nieudane (timeout): {ex.Message}";
        }

        if (status == null)
            return await HandleLostJobAsync(args, jobId);

        switch (status.Status)
        {
            case "queued":
                await SplitJobSubmitter.SetFieldAsync(
                    args, Configuration.StatusFieldId, $"{status.Position}. w kolejce");
                return $"Zadanie {jobId} czeka w kolejce (pozycja {status.Position}).";

            case "running":
                await SplitJobSubmitter.SetFieldAsync(
                    args, Configuration.StatusFieldId,
                    $"przetwarzanie ({status.RunningSeconds:0} s)");
                return $"Zadanie {jobId} w toku ({status.RunningSeconds:0} s).";

            case "failed":
                return await FailAsync(args, jobId, status.Error ?? "nieznany blad");

            case "done":
                return await CollectAsync(args, client, jobId, status);

            default:
                return $"Zadanie {jobId} ma nieznany status '{status.Status}' - czekam.";
        }
    }

    private async Task<string> HandleLostJobAsync(RunCustomActionParams args, string jobId)
    {
        var attempts = SplitJobSubmitter.GetField(args, Configuration.AttemptsFieldId, 0) + 1;
        await SplitJobSubmitter.SetFieldAsync(args, Configuration.AttemptsFieldId, attempts);
        if (attempts >= Configuration.MaxAttempts)
            return await MoveToErrorAsync(
                args, $"Zadanie {jobId} przepadlo {attempts} raz(y) - limit prob wyczerpany.");

        // wyczyszczenie jobId sprowadza element do stanu "brak zadania",
        // ktory nastepny takt obsluzy ponownym zleceniem
        await SplitJobSubmitter.SetFieldAsync(args, Configuration.JobIdFieldId, "");
        await SplitJobSubmitter.SetFieldAsync(
            args, Configuration.StatusFieldId, $"zadanie przepadlo, ponowienie ({attempts})");
        return $"Zadanie {jobId} nieznane splitterowi - zlecenie zostanie powtorzone (proba {attempts}).";
    }

    private async Task<string> FailAsync(RunCustomActionParams args, string jobId, string error)
    {
        var attempts = SplitJobSubmitter.GetField(args, Configuration.AttemptsFieldId, 0) + 1;
        await SplitJobSubmitter.SetFieldAsync(args, Configuration.AttemptsFieldId, attempts);
        if (attempts >= Configuration.MaxAttempts)
            return await MoveToErrorAsync(args, $"Zadanie {jobId} zakonczone bledem: {error}");

        await SplitJobSubmitter.SetFieldAsync(args, Configuration.JobIdFieldId, "");
        await SplitJobSubmitter.SetFieldAsync(
            args, Configuration.StatusFieldId, $"blad, ponowienie ({attempts}): {error}");
        return $"Zadanie {jobId} zakonczone bledem, ponowienie (proba {attempts}): {error}";
    }

    private async Task<string> CollectAsync(
        RunCustomActionParams args, SplitterClient client, string jobId, JobStatusResponse status)
    {
        var result = await client.GetJobResultAsync(jobId);
        if (result == null)
            return await HandleLostJobAsync(args, jobId);

        var targetWorkflowId = ParseId(Configuration.TargetWorkflowId, "Target workflow ID");
        var targetDocTypeId = ParseId(Configuration.TargetDocTypeId, "Target document type ID");
        var startPathId = ParseId(Configuration.StartPathId, "Start path ID");
        // wznowienie po awarii: pomijamy dokumenty utworzone w poprzednim podejsciu
        var lastCreated = SplitJobSubmitter.GetField(args, Configuration.LastCreatedIndexFieldId, 0);

        var documentsManager = new DocumentsManager(args.Context);
        var createdIds = new List<int>();

        foreach (var detected in result.Documents.OrderBy(d => d.DocumentIndex))
        {
            if (detected.DocumentIndex <= lastCreated)
                continue;

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
                await newDocument.Attachments.AddNewAsync(
                    detected.OutputFileName, Convert.FromBase64String(detected.FileContentBase64));

            await newDocument.Comment.AddCommentAsync(FormatDetectionComment(detected));

            var requiresReviewFieldId = Configuration.RequiresReviewFieldId.GetValueOrDefault();
            if (requiresReviewFieldId > 0)
                await newDocument.SetFieldValueAsync(requiresReviewFieldId, detected.RequiresReview);

            var reviewReasonsFieldId = Configuration.ReviewReasonsFieldId.GetValueOrDefault();
            if (reviewReasonsFieldId > 0)
                await newDocument.SetFieldValueAsync(
                    reviewReasonsFieldId, string.Join(Environment.NewLine, detected.ReviewReasons));

            var parentElementIdFieldId = Configuration.ParentElementIdFieldId.GetValueOrDefault();
            if (parentElementIdFieldId > 0)
                await newDocument.SetFieldValueAsync(
                    parentElementIdFieldId, args.Context.CurrentDocument.ID);

            var started = await documentsManager.StartNewWorkFlowAsync(
                new StartNewWorkFlowParams(newDocument, startPathId));
            createdIds.Add(started.CreatedDocumentID);
            // zapisujemy po KAZDYM dziecku - pad w polowie petli nie moze
            // spowodowac duplikatow przy nastepnym takcie
            await SplitJobSubmitter.SetFieldAsync(
                args, Configuration.LastCreatedIndexFieldId, detected.DocumentIndex);
        }

        // kasujemy zadanie DOPIERO po zapisaniu dzieci - inaczej pad
        // w polowie odbioru oznaczalby utrate wyniku
        await client.DeleteJobAsync(jobId);
        await SplitJobSubmitter.SetFieldAsync(
            args, Configuration.StatusFieldId,
            $"{status.DocumentCount} dok., {status.DocumentsRequiringReview} do weryfikacji");

        await MovePathAsync(args, ParseId(Configuration.DonePathId, "Done path ID"));

        var warningsText = result.Warnings.Count > 0
            ? " Warnings: " + string.Join(" | ", result.Warnings) + "."
            : "";
        return $"Zadanie {jobId}: {result.Status}, stron: {result.PageCount}, " +
               $"dokumentow: {result.Documents.Count}, utworzono elementy: " +
               $"{string.Join(", ", createdIds)}{warningsText}";
    }

    private async Task<string> MoveToErrorAsync(RunCustomActionParams args, string reason)
    {
        await SplitJobSubmitter.SetFieldAsync(args, Configuration.StatusFieldId, reason);
        await MovePathAsync(args, ParseId(Configuration.ErrorPathId, "Error path ID"));
        return reason;
    }

    private static async Task MovePathAsync(RunCustomActionParams args, int pathId)
    {
        // Sygnatura zweryfikowana refleksja (WEBCON.BPS.2026.SDK 26.1.6.209):
        // nie ma CurrentDocument.MoveToNextStepAsync - przejscie sciezka robi
        // DocumentsManager.MoveDocumentToNextStepAsync(MoveDocumentToNextStepParams),
        // a CurrentDocumentData dziedziczy z ExistingDocumentData, wiec mozna
        // ja podac wprost jako Document.
        var manager = new DocumentsManager(args.Context);
        await manager.MoveDocumentToNextStepAsync(
            new MoveDocumentToNextStepParams
            {
                Document = args.Context.CurrentDocument,
                PathID = pathId,
            });
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
        if (detected.RemovedPages.Count > 0)
            comment += $"; usunieto puste strony: {string.Join(", ", detected.RemovedPages)}";
        // sygnaly to odpowiedz na pytanie "dlaczego taki typ i taka pewnosc" -
        // do niedawna byly przesylane i wyrzucane; operator weryfikujacy
        // dokument potrzebuje ich na formularzu, nie w docker logs
        if (detected.Signals.Count > 0)
            comment += $"; sygnaly: {string.Join(", ", detected.Signals)}";
        // powody trafiaja do komentarza tylko, gdy nie sa zapisywane w polu.
        // GetValueOrDefault() jest tu KONIECZNE: dla int? wyrazenie `null <= 0`
        // daje w C# false, wiec bez tego powody przestalyby trafiac do
        // komentarza przy niewypelnionym polu
        if (Configuration.ReviewReasonsFieldId.GetValueOrDefault() <= 0 && detected.ReviewReasons.Count > 0)
            comment += $"; review reasons: {string.Join("; ", detected.ReviewReasons)}";
        return comment;
    }
}
