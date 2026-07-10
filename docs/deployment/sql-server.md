# SQL Server Setup

Create a dedicated database named `WebconPdfSplitter` on the SQL Server infrastructure used by WEBCON.

Do not add splitter tables to WEBCON system databases.

Minimum permissions:

- splitter service account: read/write on `WebconPdfSplitter`;
- WEBCON service account: no direct access required unless WEBCON forms read splitter audit tables;
- DBA/admin: schema deployment and maintenance.

Apply schema from:

`splitter/src/webcon_pdf_splitter/db/schema.sql`
