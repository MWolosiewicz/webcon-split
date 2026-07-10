# Splitter Service

The splitter runs as a local internal service.

Required environment:

- `SPLITTER_DATABASE_CONNECTION_STRING`
- `SPLITTER_WORK_DIR`
- `SPLITTER_MIN_AUTO_ACCEPT_CONFIDENCE=0.90`
- `SPLITTER_MIN_REVIEW_CONFIDENCE=0.70`
- `SPLITTER_LLM_ENABLED=false`
- `SPLITTER_LLM_ENDPOINT`
- `SPLITTER_LLM_MODEL`
- `SPLITTER_API_TOKEN`

Local development command:

```powershell
cd splitter
python -m uvicorn webcon_pdf_splitter.api:app --host 127.0.0.1 --port 8000
```

Production should run behind an internal service account and HTTPS or a protected local network channel.
