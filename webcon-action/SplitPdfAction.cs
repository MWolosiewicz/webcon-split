using System;
using System.Net.Http;
using System.Threading.Tasks;

namespace WebconPdfSplitterAction;

public sealed class SplitPdfAction
{
    public string SplitterBaseUrl { get; set; } = "http://localhost:8000";

    public async Task<SplitResult> ExecuteForPdfStreamAsync(string fileName, System.IO.Stream pdfStream)
    {
        using var httpClient = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(5)
        };
        var client = new SplitterClient(httpClient, SplitterBaseUrl);
        return await client.SplitAsync(fileName, pdfStream);
    }
}
