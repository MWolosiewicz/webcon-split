from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.db.repository import DocumentPattern


def _classifier_with_header(header: str) -> RuleBasedClassifier:
    return RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                document_type="Umowa o prace",
                header=header,
                phrases=[],
                excluded_phrases=[],
                weight=1.2,
                active=True,
            )
        ]
    )


def test_page_with_polish_diacritics_matches_ascii_header():
    classifier = _classifier_with_header("UMOWA O PRACE")

    result = classifier.classify_page("UMOWA O PRACĘ zawarta dnia...", page_number=1)

    assert result.document_type == "Umowa o prace"
    assert result.is_first_page is True


def test_header_with_diacritics_matches_ocr_text_without_them():
    classifier = _classifier_with_header("ŚWIADECTWO PRACY")

    result = classifier.classify_page("SWIADECTWO PRACY wydane pracownikowi", page_number=1)

    assert result.is_first_page is True
