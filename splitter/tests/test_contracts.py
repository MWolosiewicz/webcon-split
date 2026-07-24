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
                outputFileName="Umowa_o_prace_strony_001-003.pdf",
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


def test_detected_document_review_reasons_default_and_serialization():
    document = DetectedDocument(
        documentIndex=1,
        documentType="Nieznany typ dokumentu",
        confidence=0.20,
        requiresReview=True,
        startPage=1,
        endPage=2,
        outputFileName="Nieznany_typ_dokumentu_strony_001-002.pdf",
    )
    assert document.reviewReasons == []

    document.reviewReasons = ["nierozpoznany typ dokumentu (zadna regula nie pasowala)"]
    payload = document.model_dump()
    assert payload["reviewReasons"] == [
        "nierozpoznany typ dokumentu (zadna regula nie pasowala)"
    ]


def test_page_op_result_roundtrip():
    from webcon_pdf_splitter.contracts import PageOpResult

    result = PageOpResult(
        outputFileName="out.pdf",
        pageCount=3,
        fileContentBase64="QUJD",
    )
    dumped = result.model_dump()
    assert dumped["outputFileName"] == "out.pdf"
    assert dumped["pageCount"] == 3
    assert dumped["warnings"] == []


def test_detected_document_removed_pages_defaults_empty():
    from webcon_pdf_splitter.contracts import DetectedDocument

    doc = DetectedDocument(
        documentIndex=1,
        documentType="X",
        confidence=0.5,
        requiresReview=False,
        startPage=1,
        endPage=1,
        outputFileName="x.pdf",
    )
    assert doc.removedPages == []
