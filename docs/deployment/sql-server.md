# SQL Server Setup

Create a dedicated database named `WebconPdfSplitter` on the SQL Server infrastructure used by WEBCON.

Do not add splitter tables to WEBCON system databases.

Minimum permissions:

- splitter service account: read/write on `WebconPdfSplitter`;
- WEBCON service account: no direct access required unless WEBCON forms read splitter audit tables;
- DBA/admin: schema deployment and maintenance.

Apply schema from:

`splitter/src/webcon_pdf_splitter/db/schema.sql`

Then load the initial HR document types and matching patterns from:

`splitter/src/webcon_pdf_splitter/db/seed.sql`

The seed script is idempotent — existing types and patterns are not duplicated.
Headers and phrases are stored without Polish diacritics because the classifier
folds all text to ASCII before matching.

The splitter switches from the empty in-memory pattern list to this database
as soon as `SPLITTER_DATABASE_CONNECTION_STRING` is set.

## Tryb słownika WEBCON

Gdy skonfigurowano odczyt słowników z procesu WEBCON
(`docs/deployment/webcon-dictionary.md`), tabele `document_type`
i `document_pattern` oraz `seed.sql` są używane wyłącznie w trybie
standalone (praca bez WEBCON-a). Tabele `splitter_job`
i `classification_feedback` są używane zawsze.
