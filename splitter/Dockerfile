FROM python:3.12-slim

WORKDIR /app

# Tesseract OCR (binarka + polski model) dla fallbacku skanow bez warstwy
# tekstowej. eng wchodzi z pakietem bazowym tesseract-ocr.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-pol \
    && rm -rf /var/lib/apt/lists/*

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
