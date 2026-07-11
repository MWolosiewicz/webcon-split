FROM python:3.12-slim

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
