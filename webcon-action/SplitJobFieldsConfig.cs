using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

// Pola paczki obslugujace kolejke zadan - wspolne dla akcji zlecajacej
// i odbierajacej. Wszystkie sa int? (patrz uwaga nizej: przy typie int
// Designer Studio wysyla dla niewypelnionego pola pusty string i SDK
// wywraca akcje jeszcze przed jej uruchomieniem).
//
// Kolejnosc: najpierw trzy pola WYMAGANE, potem opcjonalne. Wynik siedzial
// wczesniej na koncu, za czterema opcjonalnymi, i przez to bywal przeoczany
// przy konfiguracji - a jego pominiecie nie zglasza sie samo (SetFieldAsync
// na pustym ID jest cichym no-opem). Od teraz pilnuje tego takze
// SplitJobSubmitter.RequireFields, wolany przez OBIE akcje.
public class SplitJobFieldsConfig : SplitterConnectionConfig
{
    [ConfigEditableFormFieldID(
        DisplayName = "Pole na identyfikator zadania",
        Description = "Pole tekstowe na identyfikator zadania zwrocony przez splitter. WYMAGANE.",
        Order = 20)]
    public int? JobIdFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Pole na date zlecenia",
        Description = "Pole daty i czasu z momentem wejscia paczki w przetwarzanie. " +
                      "Podstawa dla akcji na timeout (dozorcy), ktora wypycha zablokowana " +
                      "paczke na Blad. WYMAGANE.",
        Order = 21)]
    public int? SubmittedAtFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Pole na wynik przetwarzania",
        Description = "Pole tekstowe na wynik: '" + SplitJobOutcome.Done +
                      "' albo '" + SplitJobOutcome.Error + "' (puste = jeszcze trwa). " +
                      "Na tym polu opiera sie przejscie sciezka po stronie WEBCON. WYMAGANE.",
        Order = 22)]
    public int? OutcomeFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Pole na status dla operatora",
        Description = "Pole tekstowe na status (pozycja w kolejce, tresc bledu). Puste = nie zapisuj.",
        Order = 23)]
    public int? StatusFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Pole na liczbe prob",
        Description = "Pole liczbowe z liczba nieudanych prob (404/failed; zajetosc sie nie liczy). " +
                      "Puste = brak ochrony przed petla ponowien.",
        Order = 24)]
    public int? AttemptsFieldId { get; set; }

    [ConfigEditableFormFieldID(
        DisplayName = "Pole na indeks ostatniego utworzonego dokumentu",
        Description = "Pole liczbowe: indeks ostatniego utworzonego dokumentu potomnego. " +
                      "Pozwala wznowic odbior po awarii bez duplikatow. Puste = brak wznawiania.",
        Order = 25)]
    public int? LastCreatedIndexFieldId { get; set; }
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
