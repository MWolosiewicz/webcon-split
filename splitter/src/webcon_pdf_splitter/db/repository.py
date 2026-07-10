from dataclasses import dataclass
import json
from typing import Protocol

import pyodbc


@dataclass(frozen=True)
class DocumentPattern:
    document_type: str
    header: str
    phrases: list[str]
    excluded_phrases: list[str]
    weight: float
    active: bool


class PatternRepository(Protocol):
    def list_active_patterns(self) -> list[DocumentPattern]:
        ...


class InMemoryPatternRepository:
    def __init__(self, patterns: list[DocumentPattern]) -> None:
        self._patterns = patterns

    def list_active_patterns(self) -> list[DocumentPattern]:
        return [pattern for pattern in self._patterns if pattern.active]


class SqlServerPatternRepository:
    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string

    def list_active_patterns(self) -> list[DocumentPattern]:
        query = """
            SELECT dt.name, dp.header, dp.phrases_json, dp.excluded_phrases_json, dp.weight, dp.is_active
            FROM dbo.document_pattern dp
            JOIN dbo.document_type dt ON dt.document_type_id = dp.document_type_id
            WHERE dt.is_active = 1 AND dp.is_active = 1
        """
        with pyodbc.connect(self._connection_string) as connection:
            rows = connection.cursor().execute(query).fetchall()

        return [
            DocumentPattern(
                document_type=row[0],
                header=row[1],
                phrases=json.loads(row[2]),
                excluded_phrases=json.loads(row[3]),
                weight=float(row[4]),
                active=bool(row[5]),
            )
            for row in rows
        ]
