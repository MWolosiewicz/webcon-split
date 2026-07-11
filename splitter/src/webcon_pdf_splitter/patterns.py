from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentPattern:
    document_type: str
    header: str
    phrases: list[str]
    excluded_phrases: list[str]
    weight: float
    active: bool


class InMemoryPatternRepository:
    def __init__(self, patterns: list[DocumentPattern]) -> None:
        self._patterns = patterns

    def list_active_patterns(self) -> list[DocumentPattern]:
        return [pattern for pattern in self._patterns if pattern.active]
