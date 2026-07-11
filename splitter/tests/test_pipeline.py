from webcon_pdf_splitter.classification.llm import DisabledLlmClassifier
from webcon_pdf_splitter.classification.pipeline import ClassificationPipeline
from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.db.repository import DocumentPattern


def test_pipeline_groups_pages_between_detected_first_pages():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", ["umowy"], [], 1.0, True),
            DocumentPattern("Aneks", "ANEKS DO UMOWY", ["aneksu"], [], 1.0, True),
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


def _make_pipeline(llm_classifier=None):
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                "Umowa o prace", "UMOWA O PRACE", ["pracodawca", "wynagrodzenie"], [], 1.2, True
            ),
            DocumentPattern(
                "Swiadectwo pracy", "SWIADECTWO PRACY", ["okres zatrudnienia"], [], 1.2, True
            ),
        ]
    )
    return ClassificationPipeline(
        rule_classifier=classifier,
        llm_classifier=llm_classifier or DisabledLlmClassifier(),
        min_auto_accept_confidence=0.90,
        min_review_confidence=0.70,
    )


def _assert_full_coverage(result, page_count):
    ranges = sorted((doc.startPage, doc.endPage) for doc in result.documents)
    expected_start = 1
    for start, end in ranges:
        assert start == expected_start
        assert end >= start
        expected_start = end + 1
    assert expected_start == page_count + 1


def test_unknown_run_in_the_middle_becomes_separate_document():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "wynagrodzenie zasadnicze wynosi",
            "zupelnie obce pismo przewodnie",
            "SWIADECTWO PRACY okres zatrudnienia",
        ],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
        ("Nieznany typ dokumentu", 3, 3),
        ("Swiadectwo pracy", 4, 4),
    ]
    unknown = result.documents[1]
    assert unknown.requiresReview is True
    assert unknown.confidence == 0.20
    assert "unknown_run" in unknown.signals
    assert result.warnings == ["Strony 3-3: nierozpoznany dokument"]
    _assert_full_coverage(result, 4)


def test_unknown_pages_at_start_are_not_lost():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "obca strona pierwsza",
            "obca strona druga",
            "UMOWA O PRACE zawarta z pracodawca",
        ],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Nieznany typ dokumentu", 1, 2),
        ("Umowa o prace", 3, 3),
    ]
    _assert_full_coverage(result, 3)


def test_unknown_tail_becomes_separate_document():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "obcy zalacznik bez fraz",
        ],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 1),
        ("Nieznany typ dokumentu", 2, 2),
    ]
    _assert_full_coverage(result, 2)


def test_page_with_foreign_type_phrases_goes_to_unknown_run():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "okres zatrudnienia wynosil trzy lata",
        ],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 1),
        ("Nieznany typ dokumentu", 2, 2),
    ]


def test_fully_unknown_bundle_is_single_unknown_document():
    result = _make_pipeline().split_pages("scan.pdf", ["obca 1", "obca 2"])

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Nieznany typ dokumentu", 1, 2),
    ]
    assert result.status == "requires_review"
    _assert_full_coverage(result, 2)
