from webcon_pdf_splitter.classification.llm import DisabledLlmClassifier
from webcon_pdf_splitter.classification.pipeline import ClassificationPipeline
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.db.repository import DocumentPattern


def test_pipeline_groups_pages_between_detected_first_pages():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", [], [], 1.0, True),
            DocumentPattern("Aneks", "ANEKS DO UMOWY", [], [], 1.0, True),
        ]
    )
    pipeline = ClassificationPipeline(
        rule_classifier=classifier,
        llm_classifier=DisabledLlmClassifier(),
        min_auto_accept_confidence=0.90,
        min_review_confidence=0.70,
    )

    result = pipeline.split_pages(
        source_file_name="scan.pdf",
        page_texts=[
            "UMOWA O PRACE",
            "ciag dalszy umowy",
            "ANEKS DO UMOWY",
            "ciag dalszy aneksu",
        ],
    )

    assert len(result.documents) == 2
    assert result.documents[0].startPage == 1
    assert result.documents[0].endPage == 2
    assert result.documents[1].startPage == 3
    assert result.documents[1].endPage == 4
