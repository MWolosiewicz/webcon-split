import json
import logging
from typing import Protocol

from pydantic import BaseModel, Field
import requests

logger = logging.getLogger(__name__)


def extract_json_object(content: str) -> str:
    """Local models often wrap JSON in markdown fences or prose."""
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end < start:
        raise ValueError(f"LLM response contains no JSON object: {content[:200]}")
    return content[start : end + 1]


class LlmClassification(BaseModel):
    isFirstPage: bool
    documentType: str
    isKnownType: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasonCodes: list[str] = Field(default_factory=list)
    suggestedNewPatterns: list[str] = Field(default_factory=list)
    # niepuste = werdykt odrzucony jako wewnetrznie sprzeczny; nie moze
    # decydowac o podziale, ale tresc trafia do reviewReasons jako podpowiedz
    inconsistencyReasons: list[str] = Field(default_factory=list)


def find_inconsistencies(
    classification: LlmClassification,
    current_document_type: str,
    known_document_types: list[str],
) -> list[str]:
    """Wylacznie logiczna spojnosc odpowiedzi modelu - zero heurystyk
    wygladu strony (tytuly, wielkie litery itp.)."""
    reasons: list[str] = []
    if not classification.isFirstPage:
        if not current_document_type:
            reasons.append("kontynuacja bez biezacego dokumentu")
        elif (
            classification.documentType
            and classification.documentType != current_document_type
        ):
            reasons.append(
                f"kontynuacja z typem '{classification.documentType}' "
                f"innym niz biezacy '{current_document_type}'"
            )
    if classification.isKnownType and classification.documentType not in known_document_types:
        reasons.append(
            f"isKnownType=true dla typu '{classification.documentType}' "
            "spoza znanych typow"
        )
    return reasons


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
        payload = {
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
        }
        url = f"{self._endpoint}/chat/completions"
        response = requests.post(url, json=payload, timeout=self._timeout_seconds)
        if response.status_code == 400:
            # np. LM Studio: "'response_format.type' must be 'json_schema' or 'text'"
            logger.info(
                "LLM endpoint rejected the request (%s); retrying without response_format",
                response.text[:200],
            )
            payload = {key: value for key, value in payload.items() if key != "response_format"}
            response = requests.post(url, json=payload, timeout=self._timeout_seconds)
        if not response.ok:
            raise RuntimeError(f"LLM HTTP {response.status_code}: {response.text[:500]}")
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(extract_json_object(content))
        if not data.get("documentType"):
            # werdykt bez typu nie moze decydowac o podziale, ale isFirstPage
            # i sugerowane frazy sa cenne jako podpowiedz dla operatora
            logger.info("LLM returned no documentType; keeping the verdict only as a hint")
            data["documentType"] = ""
        confidence = data.get("confidence")
        if isinstance(confidence, (int, float)) and confidence > 1:
            # niektore modele zwracaja procenty zamiast ulamka 0-1
            data["confidence"] = confidence / 100 if confidence <= 100 else 1.0
        return LlmClassification.model_validate(data)

    @staticmethod
    def _build_prompt(
        current_text: str,
        previous_text: str,
        next_text: str,
        known_document_types: list[str],
    ) -> str:
        return (
            "Ustal, czy AKTUALNA_STRONA jest pierwsza strona nowego dokumentu HR, "
            "czy kontynuacja poprzedniego dokumentu. "
            "Zwroc TYLKO jeden obiekt JSON, bez zadnego innego tekstu, dokladnie w formacie: "
            '{"isFirstPage": true|false, "documentType": "<nazwa typu dokumentu>", '
            '"isKnownType": true|false, "confidence": <liczba od 0.0 do 1.0>, '
            '"reasonCodes": ["<krotki_kod_powodu>"], "suggestedNewPatterns": ["<fraza>"]}. '
            "Jesli typ pasuje do ktoregos ze ZNANE_TYPY, uzyj dokladnie tej nazwy "
            "i ustaw isKnownType=true. documentType nigdy nie moze byc null.\n\n"
            f"ZNANE_TYPY={known_document_types}\n\n"
            f"POPRZEDNIA_STRONA={previous_text[:2000]}\n\n"
            f"AKTUALNA_STRONA={current_text[:4000]}\n\n"
            f"NASTEPNA_STRONA={next_text[:2000]}"
        )
