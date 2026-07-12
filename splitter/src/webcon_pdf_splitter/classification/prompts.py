import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Wstrzykiwany z kodu jako {format_json}, zeby szablon w pliku nie mogl
# rozjechac sie z walidacja Pydantic w LlmClassification.
FORMAT_JSON = (
    '{"isFirstPage": true|false, "documentType": "<nazwa typu dokumentu>", '
    '"isKnownType": true|false, "confidence": <liczba od 0.0 do 1.0>, '
    '"reasonCodes": ["<krotki_kod_powodu>"], "suggestedNewPatterns": ["<fraza>"]}'
)

DEFAULT_SYSTEM_PROMPT = (
    "Jestes klasyfikatorem stron w paczkach zeskanowanych dokumentow HR. "
    "Oceniasz jedna strone na raz. Odpowiadasz wylacznie jednym poprawnym "
    "obiektem JSON, bez markdown i bez zadnego tekstu poza JSON."
)

DEFAULT_USER_PROMPT = """\
ZADANIE: Zdecyduj, czy AKTUALNA_STRONA zaczyna NOWY dokument, czy jest
KONTYNUACJA biezacego dokumentu typu "{typ_biezacego_dokumentu}".

WSKAZOWKI:
- Nowy dokument zwykle zaczyna sie od wyraznego tytulu lub naglowka.
  Tytul moze miec rozna forme: pelna nazwa dokumentu, kod lub symbol
  formularza, naglowek firmowy. NIE zakladaj, ze tytul musi byc
  wielkimi literami.
- Nowy dokument czesto dotyczy innej sprawy, innej osoby lub innej daty
  niz poprzednia strona.
- Jesli POPRZEDNIA_STRONA konczy sie podpisami lub formulami koncowymi,
  poprzedni dokument prawdopodobnie sie skonczyl i AKTUALNA_STRONA
  zaczyna nowy dokument.
- Kontynuacja zwykle: zaczyna sie w polowie zdania, listy lub tabeli;
  kontynuuje watek z POPRZEDNIA_STRONA; zawiera numeracje stron (np. 2/3).
- Strona bedaca zalacznikiem do biezacego dokumentu (np. "Zalacznik nr 1
  do umowy") to KONTYNUACJA biezacego dokumentu.
- Sam fakt, ze strona zawiera slowa typowe dla dokumentow HR
  (np. "pracownik", "wynagrodzenie"), NIE oznacza kontynuacji.

JAK WYPELNIC ODPOWIEDZ:
- Strona zaczyna NOWY dokument -> ustaw isFirstPage=true oraz
  documentType = typ tego nowego dokumentu.
- Strona jest KONTYNUACJA -> ustaw isFirstPage=false oraz
  documentType = "{typ_biezacego_dokumentu}".
- isKnownType=true TYLKO wtedy, gdy documentType wystepuje DOKLADNIE
  na liscie ZNANE_TYPY (identyczna pisownia). Kazdy typ spoza listy
  to isKnownType=false.
- documentType nigdy nie moze byc null ani pusty. Jesli nie rozpoznajesz
  typu, opisz go wlasnymi slowami, ustaw isKnownType=false i obniz
  confidence.
- confidence to ulamek od 0.0 do 1.0, nie procent.

FORMAT ODPOWIEDZI: {format_json}

ZNANE_TYPY={znane_typy}
TYP_BIEZACEGO_DOKUMENTU={typ_biezacego_dokumentu}
POPRZEDNIA_STRONA={poprzednia_strona}
AKTUALNA_STRONA={aktualna_strona}
NASTEPNA_STRONA={nastepna_strona}
"""


def build_context(
    current_text: str,
    previous_text: str,
    next_text: str,
    known_document_types: list[str],
    current_document_type: str,
) -> dict[str, str]:
    return {
        "znane_typy": json.dumps(known_document_types, ensure_ascii=False),
        "typ_biezacego_dokumentu": current_document_type or "BRAK",
        "poprzednia_strona": previous_text[:2000],
        "aktualna_strona": current_text[:4000],
        "nastepna_strona": next_text[:2000],
        "format_json": FORMAT_JSON,
    }


class PromptProvider:
    """Laduje szablony promptow z plikow przy kazdym renderze (hot-reload).

    Brak pliku, blad odczytu albo nieznany placeholder w szablonie nigdy nie
    wywracaja zadania — zawsze jest fallback na wbudowany prompt.
    """

    def __init__(self, user_prompt_file: str = "", system_prompt_file: str = "") -> None:
        self._user_prompt_file = user_prompt_file
        self._system_prompt_file = system_prompt_file
        self._last_logged: dict[str, str] = {}

    def render_user(self, context: dict[str, str]) -> str:
        return self._render(self._user_prompt_file, DEFAULT_USER_PROMPT, context, "user")

    def render_system(self, context: dict[str, str]) -> str:
        return self._render(
            self._system_prompt_file, DEFAULT_SYSTEM_PROMPT, context, "system"
        )

    def _render(
        self, file_path: str, default_template: str, context: dict[str, str], kind: str
    ) -> str:
        template = self._load(file_path, default_template, kind)
        try:
            return template.format(**context)
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "Szablon %s promptu z pliku '%s' zawiera nieznany placeholder (%s); "
                "uzywam wbudowanego promptu",
                kind,
                file_path,
                exc,
            )
            return default_template.format(**context)

    def _load(self, file_path: str, default_template: str, kind: str) -> str:
        if not file_path:
            return default_template
        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "Nie mozna odczytac pliku %s promptu '%s' (%s); uzywam wbudowanego promptu",
                kind,
                file_path,
                exc,
            )
            return default_template
        if self._last_logged.get(kind) != content:
            self._last_logged[kind] = content
            logger.info(
                "Prompt %s z pliku '%s' (%s znakow)", kind, file_path, len(content)
            )
        return content
