from dataclasses import dataclass
import logging

from webcon_pdf_splitter.classification.llm import LlmClassification, LlmClassifier
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.contracts import DetectedDocument, SplitResult

logger = logging.getLogger(__name__)

UNKNOWN_DOCUMENT_TYPE = "Nieznany typ dokumentu"


@dataclass
class _Segment:
    document_type: str
    confidence: float
    signals: list[str]
    start_page: int
    end_page: int
    known: bool


class ClassificationPipeline:
    def __init__(
        self,
        rule_classifier: RuleBasedClassifier,
        llm_classifier: LlmClassifier,
        min_auto_accept_confidence: float,
        min_review_confidence: float,
    ) -> None:
        self._rule_classifier = rule_classifier
        self._llm_classifier = llm_classifier
        self._min_auto_accept_confidence = min_auto_accept_confidence
        self._min_review_confidence = min_review_confidence

    def split_pages(self, source_file_name: str, page_texts: list[str]) -> SplitResult:
        known_types = self._rule_classifier.known_document_types
        segments: list[_Segment] = []
        current: _Segment | None = None

        for index, text in enumerate(page_texts):
            page_number = index + 1
            page = self._rule_classifier.classify_page(text, page_number)

            if page.is_first_page:
                current = _Segment(
                    document_type=page.document_type,
                    confidence=page.confidence,
                    signals=page.signals,
                    start_page=page_number,
                    end_page=page_number,
                    known=True,
                )
                segments.append(current)
                continue

            if current is not None and current.known and current.document_type in page.phrase_affinities:
                current.end_page = page_number
                continue

            llm = self._try_llm(page_texts, index, known_types)
            if llm is not None and llm.confidence >= self._min_review_confidence:
                if llm.isFirstPage:
                    current = _Segment(
                        document_type=llm.documentType,
                        confidence=llm.confidence,
                        signals=[f"llm:{code}" for code in llm.reasonCodes],
                        start_page=page_number,
                        end_page=page_number,
                        known=True,
                    )
                    segments.append(current)
                    continue
                if current is not None and current.known and llm.documentType == current.document_type:
                    current.end_page = page_number
                    continue

            if current is not None and not current.known:
                current.end_page = page_number
            else:
                current = _Segment(
                    document_type=UNKNOWN_DOCUMENT_TYPE,
                    confidence=0.20,
                    signals=["unknown_run"],
                    start_page=page_number,
                    end_page=page_number,
                    known=False,
                )
                segments.append(current)

        documents = [
            DetectedDocument(
                documentIndex=document_index,
                documentType=segment.document_type,
                confidence=segment.confidence,
                requiresReview=segment.confidence < self._min_auto_accept_confidence,
                startPage=segment.start_page,
                endPage=segment.end_page,
                outputFileName=self._file_name(
                    document_index, segment.document_type, segment.start_page, segment.end_page
                ),
                signals=segment.signals,
                metadata={},
            )
            for document_index, segment in enumerate(segments, start=1)
        ]
        warnings = [
            f"Strony {segment.start_page}-{segment.end_page}: nierozpoznany dokument"
            for segment in segments
            if not segment.known
        ]

        status = "requires_review" if any(document.requiresReview for document in documents) else "completed"
        return SplitResult(
            sourceFileName=source_file_name,
            pageCount=len(page_texts),
            status=status,
            documents=documents,
            warnings=warnings,
        )

    def _try_llm(
        self, page_texts: list[str], index: int, known_types: list[str]
    ) -> LlmClassification | None:
        try:
            return self._llm_classifier.classify_uncertain_page(
                current_text=page_texts[index],
                previous_text=page_texts[index - 1] if index > 0 else "",
                next_text=page_texts[index + 1] if index + 1 < len(page_texts) else "",
                known_document_types=known_types,
            )
        except Exception:
            logger.warning("LLM classification failed for page %s", index + 1, exc_info=True)
            return None

    @staticmethod
    def _file_name(index: int, document_type: str, start_page: int, end_page: int) -> str:
        safe_type = (
            document_type.replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
        )
        return f"{index:03d}_{safe_type}_strony_{start_page:03d}-{end_page:03d}.pdf"
