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
    phrase_affinities: set[str] = field(default_factory=set)


def normalize_text(value: str) -> str:
    # OCR output is inconsistent with Polish diacritics, so both the page
    # text and the patterns are folded to plain ASCII before matching.
    decomposed = unicodedata.normalize("NFKD", value.replace("ł", "l").replace("Ł", "L"))
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_only.upper()).strip()


class RuleBasedClassifier:
    def __init__(self, patterns: list[DocumentPattern]) -> None:
        self._patterns = patterns

    @property
    def known_document_types(self) -> list[str]:
        return sorted({pattern.document_type for pattern in self._patterns})

    def classify_page(self, text: str, page_number: int) -> PageClassification:
        normalized = self._normalize(text)
        best: PageClassification | None = None
        affinities: set[str] = set()

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

            if phrase_hits:
                affinities.add(pattern.document_type)

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
