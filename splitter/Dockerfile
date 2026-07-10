FROM python:3.12-slim

# Sterownik ODBC 18 dla SQL Server (repozytorium Microsoft, Debian 12)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg2 ca-certificates \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
       | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc libgssapi-krb5-2 \
    && apt-get purge -y curl gnupg2 \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home splitter \
    && mkdir -p /app/work \
    && chown splitter:splitter /app/work
USER splitter
ENV SPLITTER_WORK_DIR=/app/work

EXPOSE 8000
CMD ["uvicorn", "webcon_pdf_splitter.api:app", "--host", "0.0.0.0", "--port", "8000"]
