from dataclasses import dataclass, field
import re
import unicodedata

from webcon_pdf_splitter.db.repository import DocumentPattern


@dataclass(frozen=True)
class PageClassification:
    page_number: int
    is_first_page: bool
    document_type: str
    confidence: float
    signals: list[str] = field(default_factory=list)


class RuleBasedClassifier:
    def __init__(self, patterns: list[DocumentPattern]) -> None:
        self._patterns = patterns

    def classify_page(self, text: str, page_number: int) -> PageClassification:
        normalized = self._normalize(text)
        best: PageClassification | None = None

        for pattern in self._patterns:
            header = self._normalize(pattern.header)
            if not header:
                continue

            header_match = header in normalized[:1200]
            phrase_hits = sum(
                1 for phrase in pattern.phrases if self._normalize(phrase) in normalized
            )
            excluded_hit = any(
                self._normalize(phrase) in normalized for phrase in pattern.excluded_phrases
            )

            if excluded_hit:
                continue

            score = 0.0
            signals: list[str] = []
            if header_match:
                score += 0.78 * pattern.weight
                signals.append(f"header_match:{pattern.header}")
            if phrase_hits:
                score += min(0.18, phrase_hits * 0.06)
                signals.append(f"phrase_hits:{phrase_hits}")

            confidence = max(0.0, min(score, 0.99))
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
            )

        return best

    @staticmethod
    def _normalize(value: str) -> str:
        # OCR output is inconsistent with Polish diacritics, so both the page
        # text and the patterns are folded to plain ASCII before matching.
        decomposed = unicodedata.normalize("NFKD", value.replace("ł", "l").replace("Ł", "L"))
        ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", ascii_only.upper()).strip()
