using System;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace WebconPdfSplitterAction;

public sealed class SplitterClient
{
    private readonly HttpClient _httpClient;
    private readonly string _baseUrl;

    public SplitterClient(HttpClient httpClient, string baseUrl)
    {
        _httpClient = httpClient;
        _baseUrl = baseUrl.TrimEnd('/');
    }

    public async Task<SplitResult> SplitAsync(string fileName, Stream pdfStream)
    {
        using var content = new MultipartFormDataContent();
        using var fileContent = new StreamContent(pdfStream);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        content.Add(fileContent, "file", fileName);

        using var response = await _httpClient.PostAsync($"{_baseUrl}/api/split", content);
        var body = await response.Content.ReadAsStringAsync();
        response.EnsureSuccessStatusCode();

        return JsonConvert.DeserializeObject<SplitResult>(body)
            ?? throw new InvalidOperationException("Splitter returned empty response.");
    }
}
