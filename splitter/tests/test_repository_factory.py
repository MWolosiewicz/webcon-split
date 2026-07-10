from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.db.repository import (
    InMemoryPatternRepository,
    SqlServerPatternRepository,
    build_pattern_repository,
)


def test_factory_returns_in_memory_repository_without_connection_string():
    settings = SplitterSettings(database_connection_string="")

    repository = build_pattern_repository(settings)

    assert isinstance(repository, InMemoryPatternRepository)


def test_factory_returns_sql_repository_with_connection_string():
    settings = SplitterSettings(
        database_connection_string="Driver={ODBC Driver 18 for SQL Server};Server=sql;Database=WebconPdfSplitter;"
    )

    repository = build_pattern_repository(settings)

    assert isinstance(repository, SqlServerPatternRepository)
