import base64
import logging
import re
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from webcon_pdf_splitter.blank_pages import BlankPageDetector
from webcon_pdf_splitter.classification.llm import (
    DisabledLlmClassifier,
    LlmClassifier,
    OpenAiCompatibleLlmClassifier,
)
from webcon_pdf_splitter.classification.pipeline import ClassificationPipeline
from webcon_pdf_splitter.classification.prompts import PromptProvider
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier, normalize_text
from webcon_pdf_splitter.config import SplitterSettings, normalize_empty_page_mode
from webcon_pdf_splitter.contracts import PatternPayload, SplitResult
from webcon_pdf_splitter.ocr import (
    PdfTextOcrEngine,
    TesseractPageOcr,
    TextLayerWithOcrFallback,
    alnum_count,
)
from webcon_pdf_splitter.patterns import DocumentPattern, InMemoryPatternRepository
from webcon_pdf_splitter.pdf_io import split_pdf, validate_pdf

logger = logging.getLogger(__name__)

_PATTERNS_ADAPTER = TypeAdapter(list[PatternPayload])


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


def build_blank_detector(settings: SplitterSettings) -> BlankPageDetector:
    return BlankPageDetector(
        dpi=settings.blank_detect_dpi,
        max_ink_ratio=settings.blank_max_ink_ratio,
        margin_ratio=settings.blank_margin_ratio,
    )


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
            blank_detector=build_blank_detector(settings),
        )
    # bez OCR nie ma renderu, wiec nie ma tez oceny obrazu - zadna strona
    # nie zostanie uznana za pusta (patrz README)
    return PdfTextOcrEngine()


def _preview(value: str, limit: int) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."


def _log_page_texts(page_texts: list[str], settings: SplitterSettings) -> None:
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


def process(
    settings: SplitterSettings,
    pdf_path: str,
    filename: str,
    patterns_field: str | None,
    *,
    ocr=None,
) -> SplitResult:
    """Rdzen przetwarzania: PDF na dysku -> podzielone dokumenty.

    Synchroniczny i wolny od FastAPI - wola go watek roboczy kolejki,
    wiec nie moze zalezec od UploadFile ani od petli zdarzen.

    Parametr ocr jest opcjonalny (domyslnie budowany z settings przez
    build_ocr_engine) - warstwa HTTP wstrzykuje wlasny silnik w testach
    (monkeypatch build_ocr_engine), dlatego zostawiamy tu furtke zamiast
    zaszywac budowanie silnika na sztywno.
    """
    repository = InMemoryPatternRepository(
        parse_patterns_field(patterns_field) if patterns_field is not None else []
    )
    mode = normalize_empty_page_mode(settings.empty_page_mode)
    if mode != "keep" and not settings.ocr_enabled:
        logger.warning(
            "SPLITTER_EMPTY_PAGE_MODE=%s wymaga wlaczonego OCR "
            "(SPLITTER_OCR_ENABLED=true) - bez niego nic nie bedzie usuwane",
            mode,
        )
    pipeline = ClassificationPipeline(
        rule_classifier=RuleBasedClassifier(repository.list_active_patterns()),
        llm_classifier=build_llm_classifier(settings),
        min_auto_accept_confidence=settings.min_auto_accept_confidence,
        min_review_confidence=settings.min_review_confidence,
        empty_page_mode=mode,
        empty_page_max_alnum=settings.empty_page_max_alnum,
        empty_page_max_share=settings.empty_page_max_share,
    )
    if ocr is None:
        ocr = build_ocr_engine(settings)

    source = Path(pdf_path)
    validate_pdf(source)

    page_reads = ocr.read_pages(str(source))
    page_texts = [read.text for read in page_reads]
    blank_pages = {index for index, read in enumerate(page_reads) if read.blank}
    _log_page_texts(page_texts, settings)
    result = pipeline.split_pages(filename, page_texts, blank_pages=blank_pages)

    output_paths = split_pdf(source, source.parent / "output", result.documents)
    for document, output_path in zip(result.documents, output_paths):
        document.fileContentBase64 = base64.b64encode(output_path.read_bytes()).decode("ascii")

    return result
