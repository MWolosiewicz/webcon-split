import base64
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, Header, HTTPException, UploadFile

from webcon_pdf_splitter.classification.llm import DisabledLlmClassifier
from webcon_pdf_splitter.classification.pipeline import ClassificationPipeline
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.contracts import SplitResult
from webcon_pdf_splitter.db.repository import build_pattern_repository
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
) -> SplitResult:
    settings = get_settings()
    _require_token(settings, authorization)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

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
