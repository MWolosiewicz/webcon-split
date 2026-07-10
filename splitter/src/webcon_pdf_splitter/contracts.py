from typing import Any, Literal

from pydantic import BaseModel, Field


SplitStatus = Literal["completed", "requires_review", "failed"]


class SplitRequest(BaseModel):
    sourceFileName: str
    webconElementId: int | None = None


class DetectedDocument(BaseModel):
    documentIndex: int = Field(ge=1)
    documentType: str
    confidence: float = Field(ge=0.0, le=1.0)
    requiresReview: bool
    startPage: int = Field(ge=1)
    endPage: int = Field(ge=1)
    outputFileName: str
    signals: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SplitResult(BaseModel):
    sourceFileName: str
    pageCount: int = Field(ge=0)
    status: SplitStatus
    documents: list[DetectedDocument]
    warnings: list[str] = Field(default_factory=list)
