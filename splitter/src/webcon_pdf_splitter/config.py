from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SplitterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPLITTER_", env_file=".env")

    database_connection_string: str = Field(default="")
    work_dir: str = Field(default="./work")
    min_auto_accept_confidence: float = Field(default=0.90)
    min_review_confidence: float = Field(default=0.70)
    llm_enabled: bool = Field(default=False)
    llm_endpoint: str = Field(default="")
    llm_model: str = Field(default="")
    llm_timeout_seconds: int = Field(default=30)
    api_token: str = Field(default="")
