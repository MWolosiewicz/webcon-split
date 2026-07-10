using WebCon.WorkFlow.SDK.Common;
using WebCon.WorkFlow.SDK.ConfigAttributes;

namespace WebconPdfSplitterAction;

public class SplitPdfActionConfig : PluginConfiguration
{
    [ConfigEditableText(DisplayName = "Splitter base URL", DefaultText = "http://localhost:8000")]
    public string SplitterBaseUrl { get; set; } = "http://localhost:8000";

    [ConfigEditableText(DisplayName = "Splitter API token", IsPasswordField = true)]
    public string ApiToken { get; set; } = "";

    [ConfigEditableInteger(DisplayName = "Target workflow ID (HR document)")]
    public int TargetWorkflowId { get; set; }

    [ConfigEditableInteger(DisplayName = "Target document type ID (HR document)")]
    public int TargetDocTypeId { get; set; }

    [ConfigEditableInteger(DisplayName = "Start path ID (HR document workflow)")]
    public int StartPathId { get; set; }

    [ConfigEditableInteger(DisplayName = "Timeout in seconds", DefaultValue = 300)]
    public int TimeoutSeconds { get; set; } = 300;
}
