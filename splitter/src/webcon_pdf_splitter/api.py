import base64
import io
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pypdf import PdfReader

from webcon_pdf_splitter import metrics
from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.contracts import PageOpResult, SplitResult
from webcon_pdf_splitter.pdf_io import (
    extract_pages,
    merge_pdfs,
    parse_page_range,
    remove_pages,
    validate_pdf,
)
from webcon_pdf_splitter.processing import build_ocr_engine, parse_patterns_field, process


logger = logging.getLogger(__name__)


def get_settings() -> SplitterSettings:
    return SplitterSettings()


# jobId biezacego zadania /api/split - przy rownoleglych zadaniach logi
# roznych paczek przeplataja sie w docker logs; prefiks [job=...] pozwala
# je rozdzielic i skorelowac z logiem operacji akcji WEBCON
_JOB_ID: ContextVar[str] = ContextVar("job_id", default="")


class _JobIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        job_id = _JOB_ID.get()
        record.job_id = f" [job={job_id}]" if job_id else ""
        return True


@contextmanager
def job_log_context(job_id: str):
    token = _JOB_ID.set(job_id)
    try:
        yield
    finally:
        _JOB_ID.reset(token)


def configure_logging(settings: SplitterSettings) -> None:
    # uvicorn configures only its own loggers; without this, application
    # logger.info(...) calls never reach docker logs.
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s%(job_id)s: %(message)s",
        force=True,
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(_JobIdFilter())


configure_logging(get_settings())

app = FastAPI(title="WEBCON PDF Splitter")


def _require_token(settings: SplitterSettings, authorization: str | None) -> None:
    if not settings.api_token:
        return
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


def _normalize_upload_filename(raw: str | None) -> str:
    """Odzyskuje prawdziwa nazwe pliku z uploadu.

    .NET (MultipartFormDataContent w akcjach WEBCON) koduje nie-ASCII nazwy
    jako RFC 2047 (=?utf-8?B?...?=) w polu filename, a parser Starlette nie
    czyta pola filename*. Przegladarki/httpx wysylaja surowe UTF-8 - wtedy
    dekodowanie jest no-opem. Dodatkowo odcinamy sciezki (basename).
    """
    if not raw:
        return ""
    name = raw
    if name.startswith("=?") and name.rstrip().endswith("?="):
        from email.header import decode_header

        try:
            decoded_parts = decode_header(name)
            name = "".join(
                part.decode(charset or "utf-8") if isinstance(part, bytes) else part
                for part, charset in decoded_parts
            )
        except Exception:  # nieparsowalne naglowki zostawiamy jak sa
            name = raw
    # tylko nazwa pliku - bez skladnikow sciezki z klienta
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    return name.strip()


def _derive_name(original: str, suffix: str) -> str:
    stem = original[:-4] if original.lower().endswith(".pdf") else original
    return f"{stem}{suffix}.pdf"


def _page_count_of(pdf_bytes: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics_endpoint(authorization: str | None = Header(default=None)) -> dict:
    # liczniki skumulowane od startu procesu (w pamieci): odsetek weryfikacji
    # to glowny wskaznik strojenia slownika i progow
    _require_token(get_settings(), authorization)
    return metrics.registry.snapshot()


@app.post("/api/split", response_model=SplitResult)
async def split_pdf_endpoint(
    file: UploadFile = File(...),
    patterns: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> SplitResult:
    settings = get_settings()
    _require_token(settings, authorization)

    filename = _normalize_upload_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    job_id = str(uuid4())
    started = time.perf_counter()
    with job_log_context(job_id), metrics.request_collector() as request_metrics:
        logger.info(
            "Przyjeto '%s' do podzialu (jobId=%s, webconElementId=%s)",
            filename,
            job_id,
            webcon_element_id,
        )
        result = await _split(settings, file, patterns, filename)
        request_metrics.pages = result.pageCount
        request_metrics.documents = len(result.documents)
        request_metrics.documents_requiring_review = sum(
            1 for document in result.documents if document.requiresReview
        )
        request_metrics.duration_seconds = time.perf_counter() - started
        metrics.registry.record(request_metrics)
        logger.info(
            "Metryki zadania: %s stron (OCR: %s), wywolania LLM: %s, "
            "dokumenty: %s (weryfikacja: %s), czas %.1f s",
            request_metrics.pages,
            request_metrics.ocr_pages,
            request_metrics.llm_calls,
            request_metrics.documents,
            request_metrics.documents_requiring_review,
            request_metrics.duration_seconds,
        )
    # identyfikator korelacyjny: akcja WEBCON zapisuje go w logu operacji
    result.jobId = job_id
    return result


async def _split(
    settings: SplitterSettings, file: UploadFile, patterns_field: str | None, filename: str
) -> SplitResult:
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / filename
        source_path.write_bytes(await file.read())
        try:
            # ocr wstrzykniety jawnie (a nie budowany wewnatrz process()),
            # zeby monkeypatch build_ocr_engine w testach nadal dzialal na
            # warstwie HTTP - patrz test_split_patterns.py
            return process(settings, str(source_path), filename, patterns_field, ocr=build_ocr_engine(settings))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/pages/remove", response_model=PageOpResult)
async def remove_pages_endpoint(
    file: UploadFile = File(...),
    pages: str = Form(...),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> PageOpResult:
    settings = get_settings()
    _require_token(settings, authorization)
    filename = _normalize_upload_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / filename
        source_path.write_bytes(await file.read())
        try:
            page_count = validate_pdf(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            selected = parse_page_range(pages, page_count)
            output = remove_pages(source_path, selected)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PageOpResult(
        outputFileName=_derive_name(filename, "_bez-stron"),
        pageCount=_page_count_of(output),
        fileContentBase64=base64.b64encode(output).decode("ascii"),
    )


@app.post("/api/pages/extract", response_model=PageOpResult)
async def extract_pages_endpoint(
    file: UploadFile = File(...),
    pages: str = Form(...),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> PageOpResult:
    settings = get_settings()
    _require_token(settings, authorization)
    filename = _normalize_upload_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / filename
        source_path.write_bytes(await file.read())
        try:
            page_count = validate_pdf(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            selected = parse_page_range(pages, page_count)
            output = extract_pages(source_path, selected)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PageOpResult(
        outputFileName=_derive_name(filename, "_strony"),
        pageCount=_page_count_of(output),
        fileContentBase64=base64.b64encode(output).decode("ascii"),
    )


@app.post("/api/merge", response_model=PageOpResult)
async def merge_endpoint(
    files: list[UploadFile] = File(...),
    output_file_name: str = Form(default="merged.pdf"),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> PageOpResult:
    settings = get_settings()
    _require_token(settings, authorization)
    if not files:
        raise HTTPException(status_code=400, detail="No files to merge")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        paths: list[Path] = []
        for index, upload in enumerate(files):
            upload_name = _normalize_upload_filename(upload.filename)
            if not upload_name.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="Only PDF files are supported")
            path = Path(tmp) / f"{index:03d}_{upload_name}"
            path.write_bytes(await upload.read())
            try:
                validate_pdf(path)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            paths.append(path)
        try:
            output = merge_pdfs(paths)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PageOpResult(
        outputFileName=output_file_name,
        pageCount=_page_count_of(output),
        fileContentBase64=base64.b64encode(output).decode("ascii"),
    )
