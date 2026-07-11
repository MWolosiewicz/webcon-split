from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.db.repository import DocumentPattern


def test_classifier_detects_known_header_as_first_page():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                document_type="Umowa o prace",
                header="UMOWA O PRACE",
                phrases=["pracownik", "pracodawca"],
                excluded_phrases=[],
                weight=1.0,
                active=True,
            )
        ]
    )

    result = classifier.classify_page(
        "UMOWA O PRACE zawarta pomiedzy pracodawca i pracownik",
        page_number=1,
    )

    assert result.is_first_page is True
    assert result.document_type == "Umowa o prace"
    assert result.confidence >= 0.90
    assert "header_match:UMOWA O PRACE" in result.signals


def test_classifier_marks_unknown_page_as_continuation_with_low_confidence():
    classifier = RuleBasedClassifier(patterns=[])

    result = classifier.classify_page("dalsza tresc dokumentu bez naglowka", page_number=2)

    assert result.is_first_page is False
    assert result.document_type == "Nieznany typ dokumentu"
    assert result.confidence < 0.70


def test_classify_page_reports_phrase_affinities_without_header():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", ["pracodawca"], [], 1.0, True),
            DocumentPattern("Swiadectwo pracy", "SWIADECTWO PRACY", ["okres zatrudnienia"], [], 1.0, True),
        ]
    )

    result = classifier.classify_page("dalszy ciag: pracodawca zapewnia...", page_number=2)

    assert result.document_type == "Nieznany typ dokumentu"
    assert result.phrase_affinities == {"Umowa o prace"}


def test_excluded_phrase_blocks_affinity():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", ["pracodawca"], ["aneks"], 1.0, True),
        ]
    )

    result = classifier.classify_page("aneks: pracodawca zmienia warunki", page_number=2)

    assert result.phrase_affinities == set()


def test_known_document_types_are_sorted_and_unique():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", [], [], 1.0, True),
            DocumentPattern("Umowa o prace", "UMOWA", [], [], 1.0, True),
            DocumentPattern("Aneks", "ANEKS", [], [], 1.0, True),
        ]
    )

    assert classifier.known_document_types == ["Aneks", "Umowa o prace"]
