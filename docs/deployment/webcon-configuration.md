# WEBCON Configuration

Target environment: WEBCON BPS 2026.1.

## SDK plugin

The custom action is built against `WEBCON.BPS.2026.SDK.Libraries` (26.1.6.209),
targeting .NET Standard 2.0. The entry point is
`WebconPdfSplitterAction.SplitPdfAction : CustomAction<SplitPdfActionConfig>`.

Action configuration fields (set in Designer Studio):

- Splitter base URL (e.g. `http://localhost:8000`);
- Splitter API token (sent as `Authorization: Bearer`, must match `SPLITTER_API_TOKEN`);
- Target workflow ID and document type ID for created HR document elements;
- Start path ID for the HR document workflow;
- Timeout in seconds (default 300).

Deployment steps:

1. build `webcon-action/WebconPdfSplitterAction.csproj`;
2. sign the assembly with an SNK key and package it with a plugin manifest
   (GUID, assembly name, class reference) using WEBCON BPS SDK Tools;
3. register the package in Designer Studio;
4. add the custom action "Podziel PDF" on the scan bundle workflow path.

Create a process for scan bundles with:

- original PDF attachment;
- processing status;
- page count;
- detected document count;
- technical log reference;
- relation to created HR document elements.

Create a process for HR documents with:

- single split PDF attachment;
- document type;
- source page range;
- confidence;
- review status;
- source scan bundle reference.

Configure the custom action "Podziel PDF" to:

1. read the selected bundle PDF;
2. call the local splitter service;
3. create HR document elements;
4. attach split PDFs;
5. route low-confidence documents to review.
