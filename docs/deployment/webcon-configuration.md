# WEBCON Configuration

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
