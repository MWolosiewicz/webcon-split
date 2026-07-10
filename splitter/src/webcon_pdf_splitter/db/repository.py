from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import TYPE_CHECKING, Protocol

import pyodbc

if TYPE_CHECKING:
    from webcon_pdf_splitter.config import SplitterSettings


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


def build_pattern_repository(settings: "SplitterSettings") -> PatternRepository:
    if settings.database_connection_string:
        return SqlServerPatternRepository(settings.database_connection_string)
    return InMemoryPatternRepository(patterns=[])


@dataclass
class SplitterJob:
    job_id: str
    source_file_name: str
    status: str
    webcon_element_id: int | None = None
    page_count: int | None = None
    detected_document_count: int | None = None
    technical_error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None


@dataclass(frozen=True)
class FeedbackEntry:
    page_number: int
    job_id: str | None = None
    webcon_element_id: int | None = None
    system_document_type: str | None = None
    operator_document_type: str | None = None
    system_is_first_page: bool | None = None
    operator_is_first_page: bool | None = None
    operator_login: str | None = None


class JobRepository(Protocol):
    def create_job(self, job: SplitterJob) -> None:
        ...

    def finish_job(
        self,
        job_id: str,
        status: str,
        page_count: int | None,
        detected_document_count: int | None,
        technical_error: str | None = None,
    ) -> None:
        ...


class FeedbackRepository(Protocol):
    def add_feedback(self, entry: FeedbackEntry) -> None:
        ...


class InMemoryJobRepository:
    def __init__(self) -> None:
        self.jobs: list[SplitterJob] = []

    def create_job(self, job: SplitterJob) -> None:
        self.jobs.append(job)

    def finish_job(
        self,
        job_id: str,
        status: str,
        page_count: int | None,
        detected_document_count: int | None,
        technical_error: str | None = None,
    ) -> None:
        for job in self.jobs:
            if job.job_id == job_id:
                job.status = status
                job.page_count = page_count
                job.detected_document_count = detected_document_count
                job.technical_error = technical_error
                job.finished_at = datetime.now(timezone.utc)


class InMemoryFeedbackRepository:
    def __init__(self) -> None:
        self.entries: list[FeedbackEntry] = []

    def add_feedback(self, entry: FeedbackEntry) -> None:
        self.entries.append(entry)


class SqlServerJobRepository:
    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string

    def create_job(self, job: SplitterJob) -> None:
        query = """
            INSERT INTO dbo.splitter_job (splitter_job_id, webcon_element_id, source_file_name, status)
            VALUES (?, ?, ?, ?)
        """
        with pyodbc.connect(self._connection_string) as connection:
            connection.cursor().execute(
                query, job.job_id, job.webcon_element_id, job.source_file_name, job.status
            )
            connection.commit()

    def finish_job(
        self,
        job_id: str,
        status: str,
        page_count: int | None,
        detected_document_count: int | None,
        technical_error: str | None = None,
    ) -> None:
        query = """
            UPDATE dbo.splitter_job
            SET status = ?, page_count = ?, detected_document_count = ?,
                technical_error = ?, finished_at = SYSUTCDATETIME()
            WHERE splitter_job_id = ?
        """
        with pyodbc.connect(self._connection_string) as connection:
            connection.cursor().execute(
                query, status, page_count, detected_document_count, technical_error, job_id
            )
            connection.commit()


class SqlServerFeedbackRepository:
    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string

    def add_feedback(self, entry: FeedbackEntry) -> None:
        query = """
            INSERT INTO dbo.classification_feedback (
                splitter_job_id, webcon_package_element_id, page_number,
                system_document_type, operator_document_type,
                system_is_first_page, operator_is_first_page, operator_login
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        with pyodbc.connect(self._connection_string) as connection:
            connection.cursor().execute(
                query,
                entry.job_id,
                entry.webcon_element_id,
                entry.page_number,
                entry.system_document_type,
                entry.operator_document_type,
                entry.system_is_first_page,
                entry.operator_is_first_page,
                entry.operator_login,
            )
            connection.commit()


def build_job_repository(settings: "SplitterSettings") -> JobRepository:
    if settings.database_connection_string:
        return SqlServerJobRepository(settings.database_connection_string)
    return InMemoryJobRepository()


def build_feedback_repository(settings: "SplitterSettings") -> FeedbackRepository:
    if settings.database_connection_string:
        return SqlServerFeedbackRepository(settings.database_connection_string)
    return InMemoryFeedbackRepository()


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
