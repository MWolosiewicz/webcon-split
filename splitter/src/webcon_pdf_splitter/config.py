import logging

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

EMPTY_PAGE_MODES = ("keep", "report", "remove")


def normalize_empty_page_mode(value: str) -> str:
    """Nieznana wartosc trybu -> 'keep' (bezpieczny stan) + ostrzezenie.

    Swiadome odstepstwo od fail-fast: dla parametru decydujacego o USUWANIU
    stron lepszy jest bezpieczny stan niz zatrzymany serwis. Parametry
    liczbowe zostaja fail-fast (walidacja pydantic).
    """
    mode = (value or "").strip().lower()
    if mode in EMPTY_PAGE_MODES:
        return mode
    logger.warning(
        "Nieznany tryb SPLITTER_EMPTY_PAGE_MODE='%s' - uzywam 'keep' "
        "(nic nie bedzie usuwane). Dozwolone: %s",
        value,
        ", ".join(EMPTY_PAGE_MODES),
    )
    return "keep"


class SplitterSettings(BaseSettings):
    # extra="ignore": nieznane zmienne SPLITTER_* w .env (np. po usunieciu
    # opcji w nowszej wersji) nie moga wywracac startu serwisu
    model_config = SettingsConfigDict(env_prefix="SPLITTER_", env_file=".env", extra="ignore")

    work_dir: str = Field(default="./work")
    min_auto_accept_confidence: float = Field(default=0.80)
    min_review_confidence: float = Field(default=0.70)
    llm_enabled: bool = Field(default=False)
    llm_endpoint: str = Field(default="")
    llm_model: str = Field(default="")
    llm_timeout_seconds: int = Field(default=30)
    llm_prompt_file: str = Field(default="")
    llm_system_prompt_file: str = Field(default="")
    api_token: str = Field(default="")
    log_level: str = Field(default="INFO")
    log_page_text: bool = Field(default=True)
    log_page_text_raw_chars: int = Field(default=1200)
    log_page_text_norm_chars: int = Field(default=300)
    ocr_enabled: bool = Field(default=True)
    ocr_min_text_chars: int = Field(default=25)
    ocr_languages: str = Field(default="pol+eng")
    ocr_dpi: int = Field(default=300)
    ocr_timeout_seconds: int = Field(default=30)
    ocr_workers: int = Field(default=2)
    empty_page_mode: str = Field(default="keep")
    empty_page_max_alnum: int = Field(default=0)
    empty_page_max_share: float = Field(default=0.5)
    blank_detect_dpi: int = Field(default=60)
    blank_max_ink_ratio: float = Field(default=0.002)
    blank_margin_ratio: float = Field(default=0.04)
