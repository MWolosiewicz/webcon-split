import base64
import io
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from pypdf import PdfReader

from webcon_pdf_splitter.classification.llm import (
    DisabledLlmClassifier,
    LlmClassifier,
    OpenAiCompatibleLlmClassifier,
)
from webcon_pdf_splitter.classification.pipeline import ClassificationPipeline
from webcon_pdf_splitter.classification.prompts import PromptProvider
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier, normalize_text
from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.contracts import PageOpResult, PatternPayload, SplitResult
from webcon_pdf_splitter.ocr import (
    PdfTextOcrEngine,
    TesseractPageOcr,
    TextLayerWithOcrFallback,
    alnum_count,
)
from webcon_pdf_splitter.patterns import DocumentPattern, InMemoryPatternRepository
from webcon_pdf_splitter.pdf_io import (
    extract_pages,
    merge_pdfs,
    parse_page_range,
    remove_pages,
    split_pdf,
    validate_pdf,
)


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


_PATTERNS_ADAPTER = TypeAdapter(list[PatternPayload])


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


def _preview(value: str, limit: int) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."


def _log_page_texts(page_texts: list[str], settings: SplitterSettings) -> None:
    """Diagnostyka klasyfikacji: co faktycznie odczytano z kazdej strony.

    Surowy fragment pokazuje jakosc odczytu (warstwa/OCR), znormalizowany
    fragment jest w postaci, w ktorej klasyfikator szuka naglowkow i fraz
    ze slownika - porownywalny 1:1 z konfiguracja wzorcow.
    """
    if not settings.log_page_text:
        return
    for index, text in enumerate(page_texts):
        chars = alnum_count(text)
        if chars == 0:
            logger.info("Strona %s: 0 znakow (pusta)", index + 1)
            continue
        logger.info(
            'Strona %s: %s znakow alnum | surowy(%s): "%s" | znorm(%s): "%s"',
            index + 1,
            chars,
            settings.log_page_text_raw_chars,
            _preview(text, settings.log_page_text_raw_chars),
            settings.log_page_text_norm_chars,
            _preview(normalize_text(text), settings.log_page_text_norm_chars),
        )


def parse_patterns_field(raw: str) -> list[DocumentPattern]:
    try:
        payloads = _PATTERNS_ADAPTER.validate_json(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid patterns payload: {exc}") from exc
    return [
        DocumentPattern(
            document_type=payload.documentType,
            header=payload.header,
            phrases=payload.phrases,
            excluded_phrases=payload.excludedPhrases,
            weight=payload.weight,
            active=True,
        )
        for payload in payloads
    ]


def build_llm_classifier(settings: SplitterSettings) -> LlmClassifier:
    if settings.llm_enabled and settings.llm_endpoint and settings.llm_model:
        return OpenAiCompatibleLlmClassifier(
            endpoint=settings.llm_endpoint,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            prompts=PromptProvider(
                user_prompt_file=settings.llm_prompt_file,
                system_prompt_file=settings.llm_system_prompt_file,
            ),
        )
    return DisabledLlmClassifier()


def build_ocr_engine(settings: SplitterSettings):
    if settings.ocr_enabled:
        return TextLayerWithOcrFallback(
            page_ocr=TesseractPageOcr(
                languages=settings.ocr_languages,
                dpi=settings.ocr_dpi,
                timeout_seconds=settings.ocr_timeout_seconds,
                workers=settings.ocr_workers,
            ),
            min_text_chars=settings.ocr_min_text_chars,
        )
    return PdfTextOcrEngine()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
    with job_log_context(job_id):
        logger.info(
            "Przyjeto '%s' do podzialu (jobId=%s, webconElementId=%s)",
            filename,
            job_id,
            webcon_element_id,
        )
        result = await _split(settings, file, patterns, filename)
    # identyfikator korelacyjny: akcja WEBCON zapisuje go w logu operacji
    result.jobId = job_id
    return result


async def _split(
    settings: SplitterSettings, file: UploadFile, patterns_field: str | None, filename: str
) -> SplitResult:
    if patterns_field is not None:
        try:
            provided = parse_patterns_field(patterns_field)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repository = InMemoryPatternRepository(provided)
    else:
        repository = InMemoryPatternRepository(patterns=[])
    pipeline = ClassificationPipeline(
        rule_classifier=RuleBasedClassifier(repository.list_active_patterns()),
        llm_classifier=build_llm_classifier(settings),
        min_auto_accept_confidence=settings.min_auto_accept_confidence,
        min_review_confidence=settings.min_review_confidence,
    )
    ocr = build_ocr_engine(settings)

    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / filename
        source_path.write_bytes(await file.read())
        try:
            validate_pdf(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        page_texts = ocr.extract_page_texts(str(source_path))
        _log_page_texts(page_texts, settings)
        result = pipeline.split_pages(filename, page_texts)

        output_paths = split_pdf(source_path, Path(tmp) / "output", result.documents)
        for document, output_path in zip(result.documents, output_paths):
            document.fileContentBase64 = base64.b64encode(output_path.read_bytes()).decode("ascii")

        return result


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
