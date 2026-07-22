import pytest

from webcon_pdf_splitter.classification.rules import RuleBasedClassifier
from webcon_pdf_splitter.patterns import DocumentPattern


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


def test_header_alone_with_default_weight_reaches_auto_accept():
    # naglowek = 0.80 x waga; przy domyslnej wadze 1.0 sam naglowek daje
    # rowno 0.80 i przechodzi prog auto-akceptacji (0.80)
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                document_type="Swiadectwo pracy",
                header="SWIADECTWO PRACY",
                phrases=["okres zatrudnienia"],
                excluded_phrases=[],
                weight=1.0,
                active=True,
            )
        ]
    )

    result = classifier.classify_page("SWIADECTWO PRACY wydane dnia", page_number=1)

    assert result.is_first_page is True
    assert result.confidence == pytest.approx(0.80)


def test_header_plus_one_phrase_scores_090():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                document_type="Umowa o prace",
                header="UMOWA O PRACE",
                phrases=["pracodawca"],
                excluded_phrases=[],
                weight=1.0,
                active=True,
            )
        ]
    )

    result = classifier.classify_page(
        "UMOWA O PRACE zawarta przez pracodawca", page_number=1
    )

    assert result.confidence == pytest.approx(0.90)


def test_header_plus_two_phrases_reach_full_confidence():
    # frazy = 0.10 x trafienia x waga; naglowek + 2 frazy przy wadze 1.0
    # daja rowno 1.0
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                document_type="Umowa o prace",
                header="UMOWA O PRACE",
                phrases=["pracodawca", "pracownik"],
                excluded_phrases=[],
                weight=1.0,
                active=True,
            )
        ]
    )

    result = classifier.classify_page(
        "UMOWA O PRACE zawarta pomiedzy pracodawca a pracownik", page_number=1
    )

    assert result.confidence == pytest.approx(1.0)


def test_confidence_is_capped_at_one():
    # naglowek z duza waga + frazy nie moze przekroczyc 1.0
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                document_type="Umowa o prace",
                header="UMOWA O PRACE",
                phrases=["pracodawca", "pracownik", "wynagrodzenie"],
                excluded_phrases=[],
                weight=1.2,
                active=True,
            )
        ]
    )

    result = classifier.classify_page(
        "UMOWA O PRACE: pracodawca, pracownik, wynagrodzenie", page_number=1
    )

    assert result.confidence == pytest.approx(1.0)


def test_phrase_bonus_scales_with_weight():
    # 1 fraza bez naglowka przy wadze 1.2 -> 0.10 x 1 x 1.2 = 0.12
    # (ponizej 0.50, wiec strona pozostaje nieznana - liczy sie powinowactwo)
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                document_type="Umowa o prace",
                header="UMOWA O PRACE",
                phrases=["pracodawca"],
                excluded_phrases=[],
                weight=1.2,
                active=True,
            )
        ]
    )

    result = classifier.classify_page("dalszy ciag: pracodawca...", page_number=2)

    assert result.document_type == "Nieznany typ dokumentu"
    assert result.phrase_affinities == {"Umowa o prace"}


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


@pytest.mark.parametrize(
    "ocr_text",
    [
        "SWIADECTW0 PRACY wydane dnia",  # O -> 0
        "SW1ADECTWO PRACY wydane dnia",  # I -> 1
        "5WIADECTWO PRACY wydane dnia",  # S -> 5
    ],
)
def test_header_recognized_despite_ocr_digit_confusion(ocr_text):
    # OCR czesto myli litery z cyframi (O<->0, I<->1, S<->5). Naglowek
    # zepsuty w ten sposob nadal powinien zostac rozpoznany - inaczej
    # strona po cichu trafia jako doklejka do poprzedniego dokumentu.
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern(
                document_type="Swiadectwo pracy",
                header="SWIADECTWO PRACY",
                phrases=["okres zatrudnienia"],
                excluded_phrases=[],
                weight=1.0,
                active=True,
            )
        ]
    )

    result = classifier.classify_page(ocr_text, page_number=3)

    assert result.is_first_page is True
    assert result.document_type == "Swiadectwo pracy"
    assert result.confidence == pytest.approx(0.80)


def test_known_document_types_are_sorted_and_unique():
    classifier = RuleBasedClassifier(
        patterns=[
            DocumentPattern("Umowa o prace", "UMOWA O PRACE", [], [], 1.0, True),
            DocumentPattern("Umowa o prace", "UMOWA", [], [], 1.0, True),
            DocumentPattern("Aneks", "ANEKS", [], [], 1.0, True),
        ]
    )

    assert classifier.known_document_types == ["Aneks", "Umowa o prace"]
