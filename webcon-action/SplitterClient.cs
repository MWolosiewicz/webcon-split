using System;
using System.Collections.Generic;
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

    public async Task<SplitResult> SplitAsync(
        string fileName,
        Stream pdfStream,
        int? webconElementId = null,
        IReadOnlyList<PatternPayload>? patterns = null)
    {
        using var content = new MultipartFormDataContent();
        using var fileContent = new StreamContent(pdfStream);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        content.Add(fileContent, "file", fileName);
        if (patterns != null)
            content.Add(new StringContent(JsonConvert.SerializeObject(patterns)), "patterns");

        using var request = new HttpRequestMessage(HttpMethod.Post, $"{_baseUrl}/api/split") { Content = content };
        if (!string.IsNullOrEmpty(_apiToken))
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiToken);
        if (webconElementId.HasValue)
            request.Headers.Add("X-Webcon-Element-Id", webconElementId.Value.ToString());

        using var response = await _httpClient.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();
        response.EnsureSuccessStatusCode();

        return JsonConvert.DeserializeObject<SplitResult>(body)
            ?? throw new InvalidOperationException("Splitter returned empty response.");
    }

    public Task<PageOpResult> RemovePagesAsync(
        string fileName, Stream pdfStream, string pageRange, int? webconElementId = null)
        => PostPagesAsync("/api/pages/remove", fileName, pdfStream, pageRange, webconElementId);

    public Task<PageOpResult> ExtractPagesAsync(
        string fileName, Stream pdfStream, string pageRange, int? webconElementId = null)
        => PostPagesAsync("/api/pages/extract", fileName, pdfStream, pageRange, webconElementId);

    private async Task<PageOpResult> PostPagesAsync(
        string path, string fileName, Stream pdfStream, string pageRange, int? webconElementId)
    {
        using var content = new MultipartFormDataContent();
        var fileContent = new StreamContent(pdfStream);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        content.Add(fileContent, "file", fileName);
        content.Add(new StringContent(pageRange), "pages");
        return await PostAsync<PageOpResult>(path, content, webconElementId);
    }

    public async Task<PageOpResult> MergeAsync(
        IReadOnlyList<MergeInput> files, int? webconElementId = null)
    {
        using var content = new MultipartFormDataContent();
        foreach (var file in files)
        {
            var part = new ByteArrayContent(file.Content);
            part.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
            content.Add(part, "files", file.FileName);
        }
        return await PostAsync<PageOpResult>("/api/merge", content, webconElementId);
    }

    private async Task<T> PostAsync<T>(
        string path, MultipartFormDataContent content, int? webconElementId)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, $"{_baseUrl}{path}") { Content = content };
        if (!string.IsNullOrEmpty(_apiToken))
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiToken);
        if (webconElementId.HasValue)
            request.Headers.Add("X-Webcon-Element-Id", webconElementId.Value.ToString());

        using var response = await _httpClient.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();
        // przekaz tresc bledu serwisu (HTTP 400 detail) do gornej warstwy, zeby operator wiedzial co poprawic
        if (!response.IsSuccessStatusCode)
            throw new InvalidOperationException($"Splitter returned {(int)response.StatusCode}: {body}");

        return JsonConvert.DeserializeObject<T>(body)
            ?? throw new InvalidOperationException("Splitter returned empty response.");
    }
}
