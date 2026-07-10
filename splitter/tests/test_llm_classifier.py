from webcon_pdf_splitter.classification.llm import DisabledLlmClassifier, LlmClassification


def test_disabled_llm_returns_none():
    classifier = DisabledLlmClassifier()

    result = classifier.classify_uncertain_page(
        current_text="ANEKS DO UMOWY",
        previous_text="",
        next_text="",
        known_document_types=["Umowa o prace", "Aneks"],
    )

    assert result is None


def test_llm_classification_requires_valid_confidence():
    result = LlmClassification(
        isFirstPage=True,
        documentType="Aneks",
        isKnownType=True,
        confidence=0.82,
        reasonCodes=["title_indicates_document_type"],
        suggestedNewPatterns=["ANEKS DO UMOWY"],
    )

    assert result.confidence == 0.82
    assert result.isFirstPage is True
