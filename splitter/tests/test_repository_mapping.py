from webcon_pdf_splitter.patterns import DocumentPattern, InMemoryPatternRepository


def test_in_memory_repository_returns_only_active_patterns():
    repository = InMemoryPatternRepository(
        patterns=[
            DocumentPattern(
                document_type="Umowa o prace",
                header="UMOWA O PRACE",
                phrases=["pracownik", "pracodawca"],
                excluded_phrases=[],
                weight=1.0,
                active=True,
            ),
            DocumentPattern(
                document_type="Nieaktywny",
                header="NIEAKTYWNY",
                phrases=[],
                excluded_phrases=[],
                weight=1.0,
                active=False,
            ),
        ]
    )

    patterns = repository.list_active_patterns()

    assert len(patterns) == 1
    assert patterns[0].document_type == "Umowa o prace"
