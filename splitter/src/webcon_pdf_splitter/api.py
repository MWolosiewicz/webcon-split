from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, HTTPException, UploadFile

from webcon_pdf_splitter.classification.llm import DisabledLlmClassifier
from webcon_pdf_splitter.classification.pipeline import ClassificationPipeline
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.contracts import SplitResult
from webcon_pdf_splitter.db.repository import InMemoryPatternRepository
from webcon_pdf_splitter.ocr import StubOcrEngine
from webcon_pdf_splitter.pdf_io import validate_pdf


app = FastAPI(title="WEBCON PDF Splitter")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/split", response_model=SplitResult)
async def split_pdf_endpoint(file: UploadFile = File(...)) -> SplitResult:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    settings = SplitterSettings()
    repository = InMemoryPatternRepository(patterns=[])
    pipeline = ClassificationPipeline(
        rule_classifier=RuleBasedClassifier(repository.list_active_patterns()),
        llm_classifier=DisabledLlmClassifier(),
        min_auto_accept_confidence=settings.min_auto_accept_confidence,
        min_review_confidence=settings.min_review_confidence,
    )
    ocr = StubOcrEngine()

    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / file.filename
        source_path.write_bytes(await file.read())
        try:
            validate_pdf(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        page_texts = ocr.extract_page_texts(str(source_path))
        return pipeline.split_pages(file.filename, page_texts)
