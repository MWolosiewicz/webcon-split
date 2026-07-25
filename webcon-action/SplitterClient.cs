using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace WebconPdfSplitterAction;

/// <summary>Serwis chwilowo zajety (kolejka pelna) - to nie jest blad elementu.</summary>
public sealed class SplitterBusyException : Exception
{
    public SplitterBusyException(string message) : base(message) { }
}

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

    public async Task<SubmitJobResponse> SubmitAsync(
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
        ApplyHeaders(request, webconElementId);

        using var response = await _httpClient.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();
        // 503 to poprawna praca pod obciazeniem, nie awaria - wolajacy ma
        // ponowic pozniej, a nie oznaczac element jako bledny
        if ((int)response.StatusCode == 503)
            throw new SplitterBusyException($"Kolejka splittera jest pelna: {body}");
        if (!response.IsSuccessStatusCode)
            throw new InvalidOperationException($"Splitter returned {(int)response.StatusCode}: {body}");

        return JsonConvert.DeserializeObject<SubmitJobResponse>(body)
            ?? throw new InvalidOperationException("Splitter returned empty response.");
    }

    public Task<JobStatusResponse?> GetJobStatusAsync(string jobId)
        => GetOrNullAsync<JobStatusResponse>($"/api/jobs/{jobId}");

    public Task<SplitResult?> GetJobResultAsync(string jobId)
        => GetOrNullAsync<SplitResult>($"/api/jobs/{jobId}/result");

    private async Task<T?> GetOrNullAsync<T>(string path) where T : class
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, $"{_baseUrl}{path}");
        ApplyHeaders(request, null);

        using var response = await _httpClient.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();
        // 404 znaczy "zadanie przepadlo" (restart kontenera albo TTL) -
        // wolajacy zleca ponownie, bo zrodlem prawdy jest zalacznik w WEBCONie
        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
            return null;
        if (!response.IsSuccessStatusCode)
            throw new InvalidOperationException($"Splitter returned {(int)response.StatusCode}: {body}");

        return JsonConvert.DeserializeObject<T>(body);
    }

    public async Task DeleteJobAsync(string jobId)
    {
        using var request = new HttpRequestMessage(HttpMethod.Delete, $"{_baseUrl}/api/jobs/{jobId}");
        ApplyHeaders(request, null);
        using var response = await _httpClient.SendAsync(request);
        // brak zadania jest tu stanem docelowym, wiec 404 nie jest bledem
        if (!response.IsSuccessStatusCode
            && response.StatusCode != System.Net.HttpStatusCode.NotFound)
        {
            var body = await response.Content.ReadAsStringAsync();
            throw new InvalidOperationException($"Splitter returned {(int)response.StatusCode}: {body}");
        }
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
        ApplyHeaders(request, webconElementId);

        using var response = await _httpClient.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();
        // przekaz tresc bledu serwisu (HTTP 400 detail) do gornej warstwy, zeby operator wiedzial co poprawic
        if (!response.IsSuccessStatusCode)
            throw new InvalidOperationException($"Splitter returned {(int)response.StatusCode}: {body}");

        return JsonConvert.DeserializeObject<T>(body)
            ?? throw new InvalidOperationException("Splitter returned empty response.");
    }

    private void ApplyHeaders(HttpRequestMessage request, int? webconElementId)
    {
        if (!string.IsNullOrEmpty(_apiToken))
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiToken);
        if (webconElementId.HasValue)
            request.Headers.Add("X-Webcon-Element-Id", webconElementId.Value.ToString());
    }
}
