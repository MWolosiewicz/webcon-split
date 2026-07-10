from webcon_pdf_splitter.classification.llm import LlmClassifier
from webcon_pdf_splitter.classification.rules import PageClassification, RuleBasedClassifier
from webcon_pdf_splitter.contracts import DetectedDocument, SplitResult


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
        classifications = [
            self._classify_with_fallback(page_texts, index)
            for index in range(len(page_texts))
        ]
        first_pages = [
            classification
            for classification in classifications
            if classification.is_first_page
        ]
        if not first_pages and page_texts:
            first_pages = [
                PageClassification(
                    page_number=1,
                    is_first_page=True,
                    document_type="Nieznany typ dokumentu",
                    confidence=0.20,
                    signals=["forced_first_page"],
                )
            ]

        documents: list[DetectedDocument] = []
        for document_index, first_page in enumerate(first_pages, start=1):
            next_first_page = first_pages[document_index] if document_index < len(first_pages) else None
            end_page = (next_first_page.page_number - 1) if next_first_page else len(page_texts)
            requires_review = first_page.confidence < self._min_auto_accept_confidence
            documents.append(
                DetectedDocument(
                    documentIndex=document_index,
                    documentType=first_page.document_type,
                    confidence=first_page.confidence,
                    requiresReview=requires_review,
                    startPage=first_page.page_number,
                    endPage=end_page,
                    outputFileName=self._file_name(document_index, first_page.document_type, first_page.page_number, end_page),
                    signals=first_page.signals,
                    metadata={},
                )
            )

        status = "requires_review" if any(document.requiresReview for document in documents) else "completed"
        return SplitResult(
            sourceFileName=source_file_name,
            pageCount=len(page_texts),
            status=status,
            documents=documents,
            warnings=[],
        )

    def _classify_with_fallback(self, page_texts: list[str], index: int) -> PageClassification:
        page_number = index + 1
        rule_result = self._rule_classifier.classify_page(page_texts[index], page_number)
        if rule_result.confidence >= self._min_auto_accept_confidence:
            return rule_result

        llm_result = self._llm_classifier.classify_uncertain_page(
            current_text=page_texts[index],
            previous_text=page_texts[index - 1] if index > 0 else "",
            next_text=page_texts[index + 1] if index + 1 < len(page_texts) else "",
            known_document_types=[],
        )
        if llm_result is None or llm_result.confidence <= rule_result.confidence:
            return rule_result

        return PageClassification(
            page_number=page_number,
            is_first_page=llm_result.isFirstPage,
            document_type=llm_result.documentType,
            confidence=llm_result.confidence,
            signals=[f"llm:{code}" for code in llm_result.reasonCodes],
        )

    @staticmethod
    def _file_name(index: int, document_type: str, start_page: int, end_page: int) -> str:
        safe_type = (
            document_type.replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
        )
        return f"{index:03d}_{safe_type}_strony_{start_page:03d}-{end_page:03d}.pdf"
