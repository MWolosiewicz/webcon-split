import logging

from webcon_pdf_splitter.classification.llm import DisabledLlmClassifier, LlmClassification
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


def test_unmatched_middle_page_is_glued_and_flagged_without_llm():
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
        ("Umowa o prace", 1, 3),
        ("Swiadectwo pracy", 4, 4),
    ]
    umowa = result.documents[0]
    assert umowa.requiresReview is True
    assert "glued_unknown_page:3" in umowa.signals
    assert result.warnings == [
        "Strona 3: brak dopasowania - doklejona do dokumentu 'Umowa o prace', wymagana weryfikacja"
    ]
    assert result.status == "requires_review"
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


def test_unmatched_tail_is_glued_and_flagged_without_llm():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "obcy zalacznik bez fraz",
        ],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]
    assert result.documents[0].requiresReview is True
    assert "glued_unknown_page:2" in result.documents[0].signals
    _assert_full_coverage(result, 2)


def test_page_with_foreign_type_phrases_is_glued_and_flagged():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        [
            "UMOWA O PRACE zawarta z pracodawca",
            "okres zatrudnienia wynosil trzy lata",
        ],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]
    assert result.documents[0].requiresReview is True


def test_fully_unknown_bundle_is_single_unknown_document():
    result = _make_pipeline().split_pages("scan.pdf", ["obca 1", "obca 2"])

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Nieznany typ dokumentu", 1, 2),
    ]
    assert result.status == "requires_review"
    _assert_full_coverage(result, 2)


class _StubLlm:
    def __init__(self, responses=None, error=None):
        self._responses = responses or {}
        self._error = error
        self.calls = []

    def classify_uncertain_page(self, current_text, previous_text, next_text, known_document_types):
        self.calls.append({"text": current_text, "known_types": known_document_types})
        if self._error is not None:
            raise self._error
        return self._responses.get(current_text)


def test_llm_promotes_unknown_page_to_known_first_page():
    stub = _StubLlm(
        responses={
            "PISMO PRZEWODNIE tresc": LlmClassification(
                isFirstPage=True,
                documentType="Pismo przewodnie",
                isKnownType=False,
                confidence=0.85,
                reasonCodes=["layout"],
            )
        }
    )
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "PISMO PRZEWODNIE tresc"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 1),
        ("Pismo przewodnie", 2, 2),
    ]
    assert result.documents[1].requiresReview is True
    assert result.documents[1].signals == ["llm:layout"]
    assert stub.calls[0]["known_types"] == ["Swiadectwo pracy", "Umowa o prace"]


def test_llm_confirms_continuation_of_current_document():
    stub = _StubLlm(
        responses={
            "strona bez zadnych fraz": LlmClassification(
                isFirstPage=False,
                documentType="Umowa o prace",
                isKnownType=True,
                confidence=0.80,
            )
        }
    )
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "strona bez zadnych fraz"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]


def test_llm_error_glues_page_with_forced_review():
    stub = _StubLlm(error=RuntimeError("llm down"))
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "strona bez zadnych fraz"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]
    assert result.documents[0].requiresReview is True


def test_llm_low_confidence_glues_page_with_forced_review():
    stub = _StubLlm(
        responses={
            "strona bez zadnych fraz": LlmClassification(
                isFirstPage=True,
                documentType="Pismo",
                isKnownType=False,
                confidence=0.50,
            )
        }
    )
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "strona bez zadnych fraz"],
    )

    assert [(d.documentType, d.startPage, d.endPage) for d in result.documents] == [
        ("Umowa o prace", 1, 2),
    ]
    assert result.documents[0].requiresReview is True


def test_logs_page_decisions_and_summary(caplog):
    with caplog.at_level(logging.INFO, logger="webcon_pdf_splitter.classification.pipeline"):
        _make_pipeline().split_pages(
            "scan.pdf",
            ["UMOWA O PRACE zawarta z pracodawca", "obcy zalacznik bez fraz"],
        )

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        m.startswith("Strona 1: pierwsza strona 'Umowa o prace' (regula, confidence")
        for m in messages
    )
    assert (
        "Strona 2: brak dopasowania -> doklejona do 'Umowa o prace', wymuszona weryfikacja"
        in messages
    )
    assert any(
        m.startswith("Dokument 1: 'Umowa o prace', strony 1-2,") and "weryfikacja: TAK" in m
        for m in messages
    )
    assert (
        "Podzial 'scan.pdf' zakonczony: 2 stron, 1 dokumentow, status=requires_review"
        in messages
    )


def test_logs_llm_and_unknown_decisions(caplog):
    stub = _StubLlm(
        responses={
            "PISMO PRZEWODNIE tresc": LlmClassification(
                isFirstPage=True,
                documentType="Pismo przewodnie",
                isKnownType=False,
                confidence=0.85,
                reasonCodes=["layout"],
            )
        }
    )
    with caplog.at_level(logging.INFO, logger="webcon_pdf_splitter.classification.pipeline"):
        _make_pipeline(llm_classifier=stub).split_pages(
            "scan.pdf",
            ["obca strona", "UMOWA O PRACE zawarta z pracodawca", "PISMO PRZEWODNIE tresc"],
        )

    messages = [record.getMessage() for record in caplog.records]
    assert "Strona 1: brak dopasowania -> nowy nieznany segment" in messages
    assert (
        "Strona 3: LLM -> pierwsza strona 'Pismo przewodnie' (confidence 0.85, reasonCodes: layout)"
        in messages
    )


def test_review_reasons_empty_for_auto_accepted_document():
    result = _make_pipeline().split_pages(
        "scan.pdf", ["UMOWA O PRACE zawarta z pracodawca"]
    )

    doc = result.documents[0]
    assert doc.requiresReview is False
    assert doc.reviewReasons == []


def test_review_reasons_for_glued_page():
    result = _make_pipeline().split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "obcy zalacznik bez fraz"],
    )

    doc = result.documents[0]
    assert doc.requiresReview is True
    assert doc.reviewReasons == ["strona 2 doklejona bez dopasowania do wzorca"]


def test_review_reasons_for_low_confidence_document():
    stub = _StubLlm(
        responses={
            "PISMO PRZEWODNIE tresc": LlmClassification(
                isFirstPage=True,
                documentType="Pismo przewodnie",
                isKnownType=False,
                confidence=0.85,
                reasonCodes=["layout"],
            )
        }
    )
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "PISMO PRZEWODNIE tresc"],
    )

    pismo = result.documents[1]
    assert pismo.requiresReview is True
    assert pismo.reviewReasons == [
        "pewnosc 0.85 ponizej progu auto-akceptacji 0.90"
    ]


def test_review_reasons_for_unknown_document():
    result = _make_pipeline().split_pages("scan.pdf", ["obca 1", "obca 2"])

    doc = result.documents[0]
    assert doc.requiresReview is True
    assert doc.reviewReasons == [
        "nierozpoznany typ dokumentu (zadna regula nie pasowala)",
        "pewnosc 0.20 ponizej progu auto-akceptacji 0.90",
    ]


def test_llm_not_called_for_affine_continuation_pages():
    stub = _StubLlm()
    result = _make_pipeline(llm_classifier=stub).split_pages(
        "scan.pdf",
        ["UMOWA O PRACE zawarta z pracodawca", "wynagrodzenie zasadnicze"],
    )

    assert len(result.documents) == 1
    assert stub.calls == []
