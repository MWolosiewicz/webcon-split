using System;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;
using WebCon.WorkFlow.SDK.Documents;
using WebCon.WorkFlow.SDK.Documents.Model.Attachments;
using WebCon.WorkFlow.SDK.Tools.Data;
using WebCon.WorkFlow.SDK.Tools.Data.Model;

namespace WebconPdfSplitterAction;

/// <summary>
/// Zlecenie paczki do splittera. Wspoldzielone przez akcje zlecajaca
/// (na przejsciu sciezka) i odbierajaca (gdy element nie ma jeszcze zadania).
///
/// Sygnatury SDK zweryfikowane refleksja na WEBCON.BPS.2026.SDK 26.1.6.209:
/// - CurrentDocumentData.SetFieldValueAsync(Int32, Object, CultureInfo)
/// - CurrentDocumentData.GetFieldValue(Int32, EntityValueFormat)
/// (CultureInfo/EntityValueFormat sa opcjonalne - istniejacy kod repo
/// wola SetFieldValueAsync dwuargumentowo).
/// </summary>
public static class SplitJobSubmitter
{
    public static async Task<string> SubmitAsync(
        RunCustomActionParams args, SplitJobFieldsConfig config, int patternsDataSourceId)
    {
        var elementId = args.Context.CurrentDocument.ID;
        var patterns = await LoadPatternsAsync(args, patternsDataSourceId);
        var patternsWarning = patterns.Count == 0
            ? "Warning: patterns data source returned no rows; every page will be classified as unknown. "
            : "";

        var attachment = await GetSingleSourcePdfAsync(args);
        var pdfContent = await attachment.GetContentAsync();

        using var httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(config.TimeoutSeconds) };
        var client = new SplitterClient(httpClient, config.SplitterBaseUrl, config.ApiToken);

        try
        {
            var submitted = await client.SubmitAsync(
                attachment.FileName, new MemoryStream(pdfContent), elementId, patterns);

            await SetFieldAsync(args, config.JobIdFieldId, submitted.JobId);
            await SetFieldAsync(args, config.SubmittedAtFieldId, DateTime.Now);
            await SetFieldAsync(args, config.StatusFieldId,
                submitted.Position > 0 ? $"{submitted.Position}. w kolejce" : "przetwarzanie");

            return patternsWarning + $"Zlecono zadanie {submitted.JobId} (pozycja {submitted.Position}).";
        }
        catch (SplitterBusyException ex)
        {
            // zajetosc to nie awaria - licznik prob NIE rosnie, element czeka
            // na kolejny takt akcji odbierajacej
            await SetFieldAsync(args, config.StatusFieldId, "kolejka pelna, ponowienie");
            return patternsWarning + $"Kolejka splittera pelna - ponowienie pozniej. {ex.Message}";
        }
        catch (HttpRequestException ex)
        {
            // brak polaczenia tez nie zwieksza licznika: restart kontenera
            // albo okno serwisowe mija samo
            await SetFieldAsync(args, config.StatusFieldId, "splitter niedostepny, ponowienie");
            return patternsWarning + $"Zlecenie nieudane (brak polaczenia), ponowienie pozniej: {ex.Message}";
        }
        catch (TaskCanceledException ex)
        {
            // timeout HTTP przy zlecaniu = serwis nie odbiera; traktuj jak
            // niedostepnosc, nie jak blad elementu
            await SetFieldAsync(args, config.StatusFieldId, "splitter nie odpowiada, ponowienie");
            return patternsWarning + $"Zlecenie nieudane (timeout), ponowienie pozniej: {ex.Message}";
        }
    }

    public static async Task SetFieldAsync(RunCustomActionParams args, int? fieldId, object value)
    {
        // GetValueOrDefault(): pole niewypelnione w Designer Studio to null,
        // ktore ma znaczyc "nie zapisuj" - tak samo jak 0
        var id = fieldId.GetValueOrDefault();
        if (id <= 0)
            return;
        await args.Context.CurrentDocument.SetFieldValueAsync(id, value);
    }

    public static T GetField<T>(RunCustomActionParams args, int? fieldId, T fallback)
    {
        var id = fieldId.GetValueOrDefault();
        if (id <= 0)
            return fallback;
        var raw = args.Context.CurrentDocument.GetFieldValue(id);
        if (raw == null || raw == DBNull.Value || string.IsNullOrWhiteSpace(raw.ToString()))
            return fallback;
        return (T)Convert.ChangeType(raw, typeof(T), CultureInfo.InvariantCulture);
    }

    private static async Task<AttachmentData> GetSingleSourcePdfAsync(RunCustomActionParams args)
    {
        var manager = new DocumentAttachmentsManager(args.Context);
        var attachments = await manager.GetAttachmentsAsync(
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

    private static async Task<List<PatternPayload>> LoadPatternsAsync(
        RunCustomActionParams args, int dataSourceId)
    {
        var helper = new DataSourcesHelper(args.Context);
        var table = await helper.GetDataTableFromDataSourceAsync(
            new GetDataTableFromDataSourceParams(dataSourceId, null));

        var required = new[] { "DocumentType", "Header", "Phrases", "ExcludedPhrases", "Weight" };
        var missing = required.Where(column => !table.Columns.Contains(column)).ToList();
        if (missing.Count > 0)
            throw new InvalidOperationException(
                $"Patterns data source {dataSourceId} is missing required columns: " +
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
