from typing import Protocol

from pydantic import BaseModel, Field
import requests


class LlmClassification(BaseModel):
    isFirstPage: bool
    documentType: str
    isKnownType: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasonCodes: list[str] = Field(default_factory=list)
    suggestedNewPatterns: list[str] = Field(default_factory=list)


class LlmClassifier(Protocol):
    def classify_uncertain_page(
        self,
        current_text: str,
        previous_text: str,
        next_text: str,
        known_document_types: list[str],
    ) -> LlmClassification | None:
        ...


class DisabledLlmClassifier:
    def classify_uncertain_page(
        self,
        current_text: str,
        previous_text: str,
        next_text: str,
        known_document_types: list[str],
    ) -> LlmClassification | None:
        return None


class OpenAiCompatibleLlmClassifier:
    def __init__(self, endpoint: str, model: str, timeout_seconds: int = 30) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    def classify_uncertain_page(
        self,
        current_text: str,
        previous_text: str,
        next_text: str,
        known_document_types: list[str],
    ) -> LlmClassification | None:
        prompt = self._build_prompt(current_text, previous_text, next_text, known_document_types)
        response = requests.post(
            f"{self._endpoint}/chat/completions",
            json={
                "model": self._model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": "Klasyfikujesz strony dokumentow HR. Odpowiadasz tylko poprawnym JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return LlmClassification.model_validate_json(content)

    @staticmethod
    def _build_prompt(
        current_text: str,
        previous_text: str,
        next_text: str,
        known_document_types: list[str],
    ) -> str:
        return (
            "Ustal, czy AKTUALNA_STRONA jest pierwsza strona dokumentu HR. "
            "Zwroc JSON z polami: isFirstPage, documentType, isKnownType, confidence, "
            "reasonCodes, suggestedNewPatterns.\n\n"
            f"ZNANE_TYPY={known_document_types}\n\n"
            f"POPRZEDNIA_STRONA={previous_text[:2000]}\n\n"
            f"AKTUALNA_STRONA={current_text[:4000]}\n\n"
            f"NASTEPNA_STRONA={next_text[:2000]}"
        )
