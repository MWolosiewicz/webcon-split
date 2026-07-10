using System.Collections.Generic;

namespace WebconPdfSplitterAction;

public sealed class SplitResult
{
    public string SourceFileName { get; set; } = "";
    public int PageCount { get; set; }
    public string Status { get; set; } = "";
    public List<DetectedDocument> Documents { get; set; } = new();
    public List<string> Warnings { get; set; } = new();
}

public sealed class DetectedDocument
{
    public int DocumentIndex { get; set; }
    public string DocumentType { get; set; } = "";
    public double Confidence { get; set; }
    public bool RequiresReview { get; set; }
    public int StartPage { get; set; }
    public int EndPage { get; set; }
    public string OutputFileName { get; set; } = "";
    public List<string> Signals { get; set; } = new();
    public Dictionary<string, object> Metadata { get; set; } = new();
}
