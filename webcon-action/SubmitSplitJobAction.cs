using System;
using System.Threading.Tasks;
using WebCon.WorkFlow.SDK.ActionPlugins;
using WebCon.WorkFlow.SDK.ActionPlugins.Model;

namespace WebconPdfSplitterAction;

/// <summary>
/// Zleca podzial paczki i konczy sie od razu - nie czeka na OCR.
/// Nieudane zlecenie (kolejka pelna, serwis niedostepny) NIE jest bledem
/// elementu: paczka i tak przechodzi do kroku przetwarzania, a akcja
/// odbierajaca ponowi zlecenie przy kolejnym takcie.
/// </summary>
public class SubmitSplitJobAction : CustomAction<SubmitSplitJobActionConfig>
{
    public override async Task RunAsync(RunCustomActionParams args)
    {
        // wersja paczki pluginu w logu operacji - pozwala od razu widziec,
        // ktora wersja dodatku faktycznie wykonala akcje
        var pluginVersion = typeof(SubmitSplitJobAction).Assembly.GetName().Version?.ToString() ?? "?";
        try
        {
            // Zerowanie liczy sie TYLKO tutaj - to wejscie paczki w obieg
            // przetwarzania. Ponowienie zlecane przez akcje cykliczna musi
            // zachowac oba liczniki, dlatego nie ma tego we wspoldzielonym
            // SplitJobSubmitter.
            //
            // Bez tego operator cofajacy paczke z kroku Blad (albo puszczajacy
            // ja ponownie po Podzielonej) dostawalby ciche pominiecie
            // dokumentow: warunek documentIndex <= lastCreated przeskakiwalby
            // wszystkie dokumenty utworzone w poprzednim podejsciu, a paczka
            // konczylaby "pomyslnie" z zerem elementow potomnych.
            SplitJobSubmitter.RequireFields(Configuration);

            await SplitJobSubmitter.SetFieldAsync(args, Configuration.AttemptsFieldId, 0);
            await SplitJobSubmitter.SetFieldAsync(args, Configuration.LastCreatedIndexFieldId, 0);
            // pole wyniku MUSI byc wyczyszczone: to na nim opiera sie przejscie
            // sciezka po stronie WEBCON, wiec pozostawiona wartosc BLAD albo
            // GOTOWE natychmiast wypchnelaby element z kroku przetwarzania
            await SplitJobSubmitter.SetFieldAsync(args, Configuration.OutcomeFieldId, "");

            // Data PRZED wyslaniem, nie po udanym zleceniu. Dozorca (akcja na
            // timeout) mierzy czas od wejscia paczki w przetwarzanie i tylko
            // on potrafi wypchnac na Blad awarie trwala - zly token, literowke
            // w adresie. Takie zlecenie nigdy sie nie udaje, wiec przy zapisie
            // "po sukcesie" data zostawala pusta, warunek dozorcy nigdy nie byl
            // spelniony i paczka probowala w kolko, bezterminowo. Jedyna
            // sytuacja, w ktorej dozorca byl naprawde potrzebny, byla dokladnie
            // ta, w ktorej nie dzialal.
            await SplitJobSubmitter.SetFieldAsync(
                args, Configuration.SubmittedAtFieldId, DateTime.Now);

            var message = await SplitJobSubmitter.SubmitAsync(
                args, Configuration, Configuration.PatternsDataSourceId);
            args.LogMessage = $"SubmitSplitJobAction v{pluginVersion}. {message}";
        }
        catch (Exception ex)
        {
            // tu trafiaja wylacznie bledy konfiguracji i zalacznikow -
            // niedostepnosc splittera jest obsluzona wewnatrz SubmitAsync
            args.HasErrors = true;
            args.Message = "Nie udalo sie zlecic podzialu. Sprawdz log techniczny.";
            args.LogMessage = $"SubmitSplitJobAction v{pluginVersion}. {ex}";
        }
    }
}
