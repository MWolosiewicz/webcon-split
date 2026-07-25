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
