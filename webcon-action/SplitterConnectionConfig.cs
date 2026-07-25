using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

// Wspolna konfiguracja polaczenia z serwisem PDF Splitter dla wszystkich akcji.
public class SplitterConnectionConfig : PluginConfiguration
{
    [ConfigEditableText(
        DisplayName = "Adres serwisu splittera",
        Description = "Adres lokalnego serwisu PDF Splitter, np. http://localhost:8000. " +
                      "Musi byc osiagalny z serwera WEBCON BPS (WorkflowService).",
        DefaultText = "http://localhost:8000",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 1)]
    public string SplitterBaseUrl { get; set; } = "http://localhost:8000";

    [ConfigEditableText(
        DisplayName = "Token API splittera",
        Description = "Token wysylany jako 'Authorization: Bearer ...'. Identyczny z SPLITTER_API_TOKEN. " +
                      "Zostaw puste tylko, jesli serwis dziala bez tokenu (niezalecane).",
        IsPasswordField = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 2)]
    public string ApiToken { get; set; } = "";

    [ConfigEditableInteger(
        DisplayName = "Limit czasu odpowiedzi (sekundy)",
        Description = "Maksymalny czas oczekiwania na odpowiedz serwisu; domyslnie 300 s.",
        DefaultValue = 300,
        MinValue = 10,
        MaxValue = 3600,
        Order = 3)]
    public int TimeoutSeconds { get; set; } = 300;
}
