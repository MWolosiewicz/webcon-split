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
    private readonly string? _apiToken;

    public SplitterClient(HttpClient httpClient, string baseUrl, string? apiToken = null)
    {
        _httpClient = httpClient;
        _baseUrl = baseUrl.TrimEnd('/');
        _apiToken = apiToken;
    }

    public async Task<SplitResult> SplitAsync(string fileName, Stream pdfStream)
    {
        using var content = new MultipartFormDataContent();
        using var fileContent = new StreamContent(pdfStream);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        content.Add(fileContent, "file", fileName);

        using var request = new HttpRequestMessage(HttpMethod.Post, $"{_baseUrl}/api/split") { Content = content };
        if (!string.IsNullOrEmpty(_apiToken))
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiToken);

        using var response = await _httpClient.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();
        response.EnsureSuccessStatusCode();

        return JsonConvert.DeserializeObject<SplitResult>(body)
            ?? throw new InvalidOperationException("Splitter returned empty response.");
    }
}
