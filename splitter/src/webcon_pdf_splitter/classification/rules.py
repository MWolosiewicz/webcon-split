from dataclasses import dataclass, field
import re
import unicodedata

from webcon_pdf_splitter.patterns import DocumentPattern


@dataclass(frozen=True)
class PageClassification:
    page_number: int
    is_first_page: bool
    document_type: str
    confidence: float
    signals: list[str] = field(default_factory=list)
    # typ dokumentu -> frazy, ktore trafily, w oryginalnym brzmieniu ze slownika.
    # Sam numer strony nie mowi operatorowi, ktora pozycje slownika poprawic;
    # dopiero fraza wskazuje wiersz do zmiany.
    phrase_affinities: dict[str, list[str]] = field(default_factory=dict)


def normalize_text(value: str) -> str:
    # OCR output is inconsistent with Polish diacritics, so both the page
    # text and the patterns are folded to plain ASCII before matching.
    decomposed = unicodedata.normalize("NFKD", value.replace("ł", "l").replace("Ł", "L"))
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_only.upper()).strip()


# OCR czesto myli te cyfry z literami. Sprowadzamy je do liter wylacznie na
# potrzeby dopasowania naglowka - inaczej naglowek zepsuty przez OCR nie
# zostaje rozpoznany i strona po cichu trafia jako doklejka do poprzedniego
# dokumentu. Frazy i wlasciwy tekst strony pozostaja bez zmian.
_OCR_DIGIT_TO_LETTER = str.maketrans({"0": "O", "1": "I", "5": "S"})


def fold_ocr_digits(value: str) -> str:
    return value.translate(_OCR_DIGIT_TO_LETTER)


class RuleBasedClassifier:
    def __init__(self, patterns: list[DocumentPattern]) -> None:
        self._patterns = patterns

    @property
    def known_document_types(self) -> list[str]:
        return sorted({pattern.document_type for pattern in self._patterns})

    def classify_page(self, text: str, page_number: int) -> PageClassification:
        normalized = self._normalize(text)
        header_zone = fold_ocr_digits(normalized[:1200])
        best: PageClassification | None = None
        affinities: dict[str, list[str]] = {}

        for pattern in self._patterns:
            header = self._normalize(pattern.header)
            if not header:
                continue

            header_match = fold_ocr_digits(header) in header_zone
            matched_phrases = [
                phrase for phrase in pattern.phrases if self._normalize(phrase) in normalized
            ]
            phrase_hits = len(matched_phrases)
            excluded_hit = any(
                self._normalize(phrase) in normalized for phrase in pattern.excluded_phrases
            )

            if excluded_hit:
                continue

            if matched_phrases:
                # kilka wierszy slownika moze dzielic ten sam typ (rozne
                # naglowki) - frazy sumujemy, nie nadpisujemy; duplikaty
                # odpadaja, zeby ta sama fraza nie pojawila sie dwa razy
                known = affinities.setdefault(pattern.document_type, [])
                known.extend(phrase for phrase in matched_phrases if phrase not in known)

            score = 0.0
            signals: list[str] = []
            if header_match:
                # naglowek 0.80 x waga + frazy 0.10 x trafienia x waga:
                # przy wadze 1.0 sam naglowek daje 0.80 (prog auto-akceptacji),
                # naglowek + 2 frazy pelne 1.0
                score += 0.80 * pattern.weight
                signals.append(f"header_match:{pattern.header}")
            if phrase_hits:
                score += 0.10 * phrase_hits * pattern.weight
                signals.append(f"phrase_hits:{phrase_hits}")

            confidence = max(0.0, min(score, 1.0))
            candidate = PageClassification(
                page_number=page_number,
                is_first_page=confidence >= 0.70,
                document_type=pattern.document_type,
                confidence=confidence,
                signals=signals,
            )
            if best is None or candidate.confidence > best.confidence:
                best = candidate

        if best is None or best.confidence < 0.50:
            return PageClassification(
                page_number=page_number,
                is_first_page=False,
                document_type="Nieznany typ dokumentu",
                confidence=0.20,
                signals=["no_pattern_match"],
                phrase_affinities=affinities,
            )

        return PageClassification(
            page_number=best.page_number,
            is_first_page=best.is_first_page,
            document_type=best.document_type,
            confidence=best.confidence,
            signals=best.signals,
            phrase_affinities=affinities,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return normalize_text(value)
