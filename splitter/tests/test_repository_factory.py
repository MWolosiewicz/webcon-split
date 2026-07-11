from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.db.repository import (
    InMemoryPatternRepository,
    SqlServerPatternRepository,
    WebconDictionaryPatternRepository,
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


def _webcon_kwargs():
    return dict(
        webcon_db_connection_string="Driver={ODBC Driver 18 for SQL Server};Server=sql;Database=BPS_Content;",
        webcon_dict_form_type_id=123,
        webcon_dict_col_type_name="WFD_AttText1",
        webcon_dict_col_type_active="WFD_AttBool1",
        webcon_dict_col_pattern_header="DET_Att1",
        webcon_dict_col_pattern_phrases="DET_Att2",
        webcon_dict_col_pattern_excluded="DET_Att3",
        webcon_dict_col_pattern_weight="DET_Value1",
        webcon_dict_col_pattern_active="DET_Bool1",
    )


def test_factory_prefers_webcon_dictionary_when_configured():
    settings = SplitterSettings(database_connection_string="", **_webcon_kwargs())

    repository = build_pattern_repository(settings)

    assert isinstance(repository, WebconDictionaryPatternRepository)


def test_factory_prefers_webcon_dictionary_over_own_database():
    settings = SplitterSettings(
        database_connection_string="Driver={ODBC Driver 18 for SQL Server};Server=sql;Database=WebconPdfSplitter;",
        **_webcon_kwargs(),
    )

    repository = build_pattern_repository(settings)

    assert isinstance(repository, WebconDictionaryPatternRepository)


def test_factory_ignores_webcon_mode_without_form_type_id():
    kwargs = _webcon_kwargs()
    kwargs["webcon_dict_form_type_id"] = 0
    settings = SplitterSettings(database_connection_string="", **kwargs)

    repository = build_pattern_repository(settings)

    assert isinstance(repository, InMemoryPatternRepository)
