from webcon_pdf_splitter.contracts import DetectedDocument, SplitResult


def test_split_result_serializes_required_fields():
    result = SplitResult(
        sourceFileName="scan.pdf",
        pageCount=3,
        status="requires_review",
        documents=[
            DetectedDocument(
                documentIndex=1,
                documentType="Umowa o prace",
                confidence=0.91,
                requiresReview=False,
                startPage=1,
                endPage=3,
                outputFileName="001_Umowa_o_prace_strony_001-003.pdf",
                signals=["header_match:UMOWA O PRACE"],
                metadata={"employeeName": "Jan Kowalski"},
            )
        ],
        warnings=[],
    )

    payload = result.model_dump()

    assert payload["sourceFileName"] == "scan.pdf"
    assert payload["documents"][0]["startPage"] == 1
    assert payload["documents"][0]["requiresReview"] is False
