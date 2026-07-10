import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import FastAPI, File, Header, HTTPException, UploadFile

from webcon_pdf_splitter.classification.llm import DisabledLlmClassifier
from webcon_pdf_splitter.classification.pipeline import ClassificationPipeline
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.contracts import FeedbackRequest, SplitResult
from webcon_pdf_splitter.db.repository import (
    FeedbackEntry,
    SplitterJob,
    build_feedback_repository,
    build_job_repository,
    build_pattern_repository,
)
from webcon_pdf_splitter.ocr import PdfTextOcrEngine
from webcon_pdf_splitter.pdf_io import split_pdf, validate_pdf


app = FastAPI(title="WEBCON PDF Splitter")


def get_settings() -> SplitterSettings:
    return SplitterSettings()


def _require_token(settings: SplitterSettings, authorization: str | None) -> None:
    if not settings.api_token:
        return
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/split", response_model=SplitResult)
async def split_pdf_endpoint(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> SplitResult:
    settings = get_settings()
    _require_token(settings, authorization)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    jobs = build_job_repository(settings)
    job_id = str(uuid4())
    jobs.create_job(
        SplitterJob(
            job_id=job_id,
            source_file_name=file.filename,
            status="processing",
            webcon_element_id=webcon_element_id,
        )
    )

    try:
        result = await _split(settings, file)
    except HTTPException as exc:
        jobs.finish_job(job_id, "failed", None, None, technical_error=str(exc.detail)[:2000])
        raise
    except Exception as exc:
        jobs.finish_job(job_id, "failed", None, None, technical_error=str(exc)[:2000])
        raise

    result.jobId = job_id
    jobs.finish_job(job_id, result.status, result.pageCount, len(result.documents))
    return result


async def _split(settings: SplitterSettings, file: UploadFile) -> SplitResult:
    repository = build_pattern_repository(settings)
    pipeline = ClassificationPipeline(
        rule_classifier=RuleBasedClassifier(repository.list_active_patterns()),
        llm_classifier=DisabledLlmClassifier(),
        min_auto_accept_confidence=settings.min_auto_accept_confidence,
        min_review_confidence=settings.min_review_confidence,
    )
    ocr = PdfTextOcrEngine()

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


@app.post("/api/feedback")
def add_feedback(
    request: FeedbackRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    settings = get_settings()
    _require_token(settings, authorization)

    repository = build_feedback_repository(settings)
    repository.add_feedback(
        FeedbackEntry(
            page_number=request.pageNumber,
            job_id=request.jobId,
            webcon_element_id=request.webconElementId,
            system_document_type=request.systemDocumentType,
            operator_document_type=request.operatorDocumentType,
            system_is_first_page=request.systemIsFirstPage,
            operator_is_first_page=request.operatorIsFirstPage,
            operator_login=request.operatorLogin,
        )
    )
    return {"status": "ok"}
