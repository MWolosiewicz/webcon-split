using System;
using System.Globalization;

namespace WebconPdfSplitterAction;

internal static class ConfigHelper
{
    /// <summary>
    /// Dodatnia liczba calkowita z pola konfiguracji akcji.
    ///
    /// Wspolne dla wszystkich akcji. Wczesniej kazda miala wlasna kopie i
    /// kopie rozjechaly sie jezykiem komunikatu - a to jest tekst, ktory
    /// administrator czyta w logu operacji przy blednej konfiguracji, wiec
    /// polowa po angielsku byla realna niedogodnoscia, nie kosmetyka.
    ///
    /// InvariantCulture jest tu bez znaczenia dla samego parsowania (dla
    /// liczb calkowitych NumberStyles.Integer i tak nie dopuszcza separatora
    /// grup), ale zdejmuje zaleznosc od kultury watku hosta BPS.
    /// </summary>
    public static int ParsePositiveInt(string configuredValue, string fieldName)
    {
        if (int.TryParse(configuredValue?.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var id)
            && id > 0)
            return id;

        throw new InvalidOperationException(
            $"Pole konfiguracji '{fieldName}' musi byc dodatnia liczba calkowita, otrzymano: '{configuredValue}'.");
    }
}
