import base64
import io
import logging
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
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.contracts import PageOpResult, PatternPayload, SplitResult
from webcon_pdf_splitter.ocr import (
    PdfTextOcrEngine,
    TesseractPageOcr,
    TextLayerWithOcrFallback,
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


def configure_logging(settings: SplitterSettings) -> None:
    # uvicorn configures only its own loggers; without this, application
    # logger.info(...) calls never reach docker logs.
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


configure_logging(get_settings())

app = FastAPI(title="WEBCON PDF Splitter")


def _require_token(settings: SplitterSettings, authorization: str | None) -> None:
    if not settings.api_token:
        return
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


_PATTERNS_ADAPTER = TypeAdapter(list[PatternPayload])


def _derive_name(original: str, suffix: str) -> str:
    stem = original[:-4] if original.lower().endswith(".pdf") else original
    return f"{stem}{suffix}.pdf"


def _page_count_of(pdf_bytes: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


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

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    job_id = str(uuid4())
    logger.info(
        "Przyjeto '%s' do podzialu (jobId=%s, webconElementId=%s)",
        file.filename,
        job_id,
        webcon_element_id,
    )
    result = await _split(settings, file, patterns)
    # identyfikator korelacyjny: akcja WEBCON zapisuje go w logu operacji
    result.jobId = job_id
    return result


async def _split(
    settings: SplitterSettings, file: UploadFile, patterns_field: str | None
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
        source_path = Path(tmp) / file.filename
        source_path.write_bytes(await file.read())
        try:
            validate_pdf(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        page_texts = ocr.extract_page_texts(str(source_path))
        result = pipeline.split_pages(file.filename, page_texts)

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
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / file.filename
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
        outputFileName=_derive_name(file.filename, "_bez-stron"),
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
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / file.filename
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
        outputFileName=_derive_name(file.filename, "_strony"),
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
            if not upload.filename or not upload.filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="Only PDF files are supported")
            path = Path(tmp) / f"{index:03d}_{upload.filename}"
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
