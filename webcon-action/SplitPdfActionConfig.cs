using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class SplitPdfActionConfig : PluginConfiguration
{
    [ConfigEditableText(
        DisplayName = "Splitter base URL",
        Description = "Adres lokalnego serwisu PDF Splitter, np. http://localhost:8000 lub http://serwer:8000. " +
                      "Serwis musi byc osiagalny z serwera WEBCON BPS (WorkflowService), nie z przegladarki. " +
                      "Mozna przeciagnac stala globalna z panelu po prawej.",
        DefaultText = "http://localhost:8000",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 1)]
    public string SplitterBaseUrl { get; set; } = "http://localhost:8000";

    [ConfigEditableText(
        DisplayName = "Splitter API token",
        Description = "Token uwierzytelniajacy wysylany jako naglowek 'Authorization: Bearer ...'. " +
                      "Musi byc identyczny z SPLITTER_API_TOKEN w konfiguracji serwisu. " +
                      "Mozna przeciagnac stala globalna z panelu po prawej. " +
                      "Zostaw puste tylko, jesli serwis dziala bez tokenu (niezalecane).",
        IsPasswordField = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 2)]
    public string ApiToken { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Target workflow ID (HR document)",
        Description = "ID obiegu, w ktorym maja powstawac elementy dokumentow HR. " +
                      "Wpisz liczbe albo przeciagnij tag/stala z panelu po prawej " +
                      "(wartosc po podstawieniu musi byc liczba calkowita). " +
                      "ID znajdziesz w Designer Studio we wlasciwosciach obiegu.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 3)]
    public string TargetWorkflowId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Target document type ID (HR document)",
        Description = "ID typu formularza (typu dokumentu) dla elementow dokumentow HR. " +
                      "Wpisz liczbe albo przeciagnij tag/stala z panelu po prawej. " +
                      "ID znajdziesz w Designer Studio we wlasciwosciach typu formularza.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 4)]
    public string TargetDocTypeId { get; set; } = "";

    [ConfigEditableText(
        DisplayName = "Start path ID (HR document workflow)",
        Description = "ID sciezki przejscia, ktora nowy element dokumentu HR ma wystartowac " +
                      "(sciezka wychodzaca z kroku startowego obiegu docelowego). " +
                      "Wpisz liczbe albo przeciagnij tag/stala z panelu po prawej.",
        IsRequired = true,
        TagEvaluationMode = EvaluationMode.Default,
        Order = 5)]
    public string StartPathId { get; set; } = "";

    [ConfigEditableInteger(
        DisplayName = "Timeout in seconds",
        Description = "Maksymalny czas oczekiwania na odpowiedz splittera. Duze paczki z OCR moga " +
                      "wymagac kilku minut; domyslnie 300 s.",
        DefaultValue = 300,
        MinValue = 10,
        MaxValue = 3600,
        Order = 6)]
    public int TimeoutSeconds { get; set; } = 300;

    [ConfigEditableDataSourceID(
        DisplayName = "Patterns data source ID",
        Description = "Zrodlo danych zwracajace aktywne wzorce rozpoznawania ze slownika typow dokumentow. " +
                      "Wymagane kolumny: DocumentType, Header, Phrases, ExcludedPhrases, Weight. " +
                      "Frazy rozdzielane srednikami. Szczegoly: README.md (Integracja z WEBCON).",
        IsRequired = true,
        Order = 7)]
    public int PatternsDataSourceId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Requires review field ID",
        Description = "Opcjonalne: pole formularza typu tak/nie w obiegu docelowym, w ktore akcja " +
                      "zapisze, czy dokument wymaga weryfikacji operatora. " +
                      "Zostaw puste, aby nie zapisywac.",
        Order = 8)]
    public int RequiresReviewFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Review reasons field ID",
        Description = "Opcjonalne: pole tekstowe (najlepiej wieloliniowe) w obiegu docelowym, " +
                      "w ktore akcja zapisze powody weryfikacji, jeden na linie. " +
                      "Gdy ustawione, powody nie sa dublowane w komentarzu elementu. " +
                      "Zostaw puste, aby powody trafialy do komentarza.",
        Order = 9)]
    public int ReviewReasonsFieldId { get; set; }
}
