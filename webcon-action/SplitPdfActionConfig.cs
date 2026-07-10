using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class SplitPdfActionConfig : PluginConfiguration
{
    [ConfigEditableText(
        DisplayName = "Splitter base URL",
        Description = "Adres lokalnego serwisu PDF Splitter, np. http://localhost:8000 lub http://serwer:8000. " +
                      "Serwis musi byc osiagalny z serwera WEBCON BPS (WorkflowService), nie z przegladarki.",
        DefaultText = "http://localhost:8000",
        IsRequired = true,
        Order = 1)]
    public string SplitterBaseUrl { get; set; } = "http://localhost:8000";

    [ConfigEditableText(
        DisplayName = "Splitter API token",
        Description = "Token uwierzytelniajacy wysylany jako naglowek 'Authorization: Bearer ...'. " +
                      "Musi byc identyczny z SPLITTER_API_TOKEN w konfiguracji serwisu. " +
                      "Zostaw puste tylko, jesli serwis dziala bez tokenu (niezalecane).",
        IsPasswordField = true,
        Order = 2)]
    public string ApiToken { get; set; } = "";

    [ConfigEditableInteger(
        DisplayName = "Target workflow ID (HR document)",
        Description = "ID obiegu, w ktorym maja powstawac elementy dokumentow HR. " +
                      "Znajdziesz je w Designer Studio we wlasciwosciach obiegu (pole ID).",
        IsRequired = true,
        MinValue = 1,
        Order = 3)]
    public int TargetWorkflowId { get; set; }

    [ConfigEditableInteger(
        DisplayName = "Target document type ID (HR document)",
        Description = "ID typu formularza (typu dokumentu) dla elementow dokumentow HR. " +
                      "Znajdziesz je w Designer Studio we wlasciwosciach typu formularza.",
        IsRequired = true,
        MinValue = 1,
        Order = 4)]
    public int TargetDocTypeId { get; set; }

    [ConfigEditableInteger(
        DisplayName = "Start path ID (HR document workflow)",
        Description = "ID sciezki przejscia, ktora nowy element dokumentu HR ma wystartowac " +
                      "(sciezka wychodzaca z kroku startowego obiegu docelowego).",
        IsRequired = true,
        MinValue = 1,
        Order = 5)]
    public int StartPathId { get; set; }

    [ConfigEditableInteger(
        DisplayName = "Timeout in seconds",
        Description = "Maksymalny czas oczekiwania na odpowiedz splittera. Duze paczki z OCR moga " +
                      "wymagac kilku minut; domyslnie 300 s.",
        DefaultValue = 300,
        MinValue = 10,
        MaxValue = 3600,
        Order = 6)]
    public int TimeoutSeconds { get; set; } = 300;
}
