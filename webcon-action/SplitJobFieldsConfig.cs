using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

// Pola paczki obslugujace kolejke zadan - wspolne dla akcji zlecajacej
// i odbierajacej. Wszystkie sa int? (patrz uwaga nizej: przy typie int
// Designer Studio wysyla dla niewypelnionego pola pusty string i SDK
// wywraca akcje jeszcze przed jej uruchomieniem).
public class SplitJobFieldsConfig : SplitterConnectionConfig
{
    [ConfigEditableFormFieldID(
        DisplayName = "Job ID field ID",
        Description = "Pole tekstowe na identyfikator zadania zwrocony przez splitter. WYMAGANE.",
        Order = 20)]
    public int? JobIdFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Submitted at field ID",
        Description = "Pole daty i czasu z momentem zlecenia. Podstawa dla akcji na timeout. WYMAGANE.",
        Order = 21)]
    public int? SubmittedAtFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Status field ID",
        Description = "Pole tekstowe na status dla operatora (pozycja w kolejce, tresc bledu). Puste = nie zapisuj.",
        Order = 22)]
    public int? StatusFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Attempts field ID",
        Description = "Pole liczbowe z liczba nieudanych prob (404/failed; zajetosc sie nie liczy). " +
                      "Puste = brak ochrony przed petla ponowien.",
        Order = 23)]
    public int? AttemptsFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Last created document index field ID",
        Description = "Pole liczbowe: indeks ostatniego utworzonego dokumentu potomnego. " +
                      "Pozwala wznowic odbior po awarii bez duplikatow. Puste = brak wznawiania.",
        Order = 24)]
    public int? LastCreatedIndexFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Outcome field ID",
        Description = "Pole tekstowe na wynik przetwarzania: '" + SplitJobOutcome.Done +
                      "' albo '" + SplitJobOutcome.Error + "' (puste = jeszcze trwa). " +
                      "Na tym polu opiera sie przejscie sciezka po stronie WEBCON. WYMAGANE.",
        Order = 25)]
    public int? OutcomeFieldId { get; set; }
}

/// <summary>
/// Wartosci pola wyniku. Akcja NIE przenosi elementu sciezka - SDK na to nie
/// pozwala: proba wywolania MoveDocumentToNextStepAsync na wlasnym elemencie
/// konczy sie "Workflow instance is being saved", bo WEBCON trzyma go otwartego
/// do zapisu przez caly czas wykonania akcji. Zamiast tego akcja zapisuje tu
/// wynik, a przejscie wykonuje mechanizm WEBCON warunkiem na tym polu.
/// </summary>
public static class SplitJobOutcome
{
    public const string Done = "GOTOWE";
    public const string Error = "BLAD";
}
