"""Ewaluacja promptu LLM na syntetycznych przypadkach.

Wymaga zywego endpointu zgodnego z OpenAI Chat Completions (np. LM Studio).
Nie jest czescia pytest. Przyklady:

    python scripts/llm_eval.py                          # domyslny endpoint/model
    python scripts/llm_eval.py --list                   # wypisz przypadki bez wolania LLM
    python scripts/llm_eval.py --prompt-file scripts/prompts_baseline/user-prompt.txt
    python scripts/llm_eval.py --cases wniosek-po-swiadectwie --out wyniki.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from webcon_pdf_splitter.classification.llm import OpenAiCompatibleLlmClassifier
from webcon_pdf_splitter.classification.prompts import PromptProvider

CASES_DIR = Path(__file__).resolve().parent / "eval_cases"


def load_cases(only_ids: list[str]) -> list[dict]:
    cases = []
    for path in sorted(CASES_DIR.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        if only_ids and case["id"] not in only_ids:
            continue
        cases.append(case)
    return cases


def run_case(classifier: OpenAiCompatibleLlmClassifier, case: dict) -> dict:
    start = time.monotonic()
    try:
        verdict = classifier.classify_uncertain_page(
            current_text=case["aktualna_strona"],
            previous_text=case["poprzednia_strona"],
            next_text=case["nastepna_strona"],
            known_document_types=case["znane_typy"],
            current_document_type=case["typ_biezacego_dokumentu"],
        )
    except Exception as exc:  # blad HTTP/parsowania = FAIL z opisem
        return {
            "id": case["id"],
            "pass": False,
            "seconds": round(time.monotonic() - start, 1),
            "error": str(exc),
            "mismatches": [],
            "guard": [],
        }
    seconds = round(time.monotonic() - start, 1)
    mismatches = []
    for key, expected in case["oczekiwane"].items():
        got = getattr(verdict, key)
        if got != expected:
            mismatches.append(f"{key}: oczekiwano {expected!r}, otrzymano {got!r}")
    guard = list(verdict.inconsistencyReasons)
    return {
        "id": case["id"],
        "pass": not mismatches and not guard,
        "seconds": seconds,
        "error": None,
        "mismatches": mismatches,
        "guard": guard,
        "verdict": verdict.model_dump(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://192.168.1.147:1234/v1")
    parser.add_argument("--model", default="qwen2.5-7b-instruct-1m")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--prompt-file", default="")
    parser.add_argument("--system-prompt-file", default="")
    parser.add_argument("--cases", nargs="*", default=[], help="filtr po id przypadkow")
    parser.add_argument("--out", default="", help="zapisz szczegolowe wyniki do JSON")
    parser.add_argument("--list", action="store_true", help="wypisz przypadki i zakoncz")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if not cases:
        print("Brak przypadkow (sprawdz --cases / katalog eval_cases)")
        return 2
    if args.list:
        for case in cases:
            print(f"{case['id']}: {case['opis']}")
        return 0

    classifier = OpenAiCompatibleLlmClassifier(
        endpoint=args.endpoint,
        model=args.model,
        timeout_seconds=args.timeout,
        prompts=PromptProvider(
            user_prompt_file=args.prompt_file,
            system_prompt_file=args.system_prompt_file,
        ),
    )

    results = []
    for case in cases:
        result = run_case(classifier, case)
        results.append(result)
        status = "PASS" if result["pass"] else "FAIL"
        print(f"[{status}] {result['id']} ({result['seconds']}s)")
        if result["error"]:
            print(f"       blad: {result['error']}")
        for mismatch in result["mismatches"]:
            print(f"       {mismatch}")
        for reason in result["guard"]:
            print(f"       straznik odrzucil: {reason}")

    passed = sum(1 for r in results if r["pass"])
    total_seconds = round(sum(r["seconds"] for r in results), 1)
    print(f"\nWynik: {passed}/{len(results)} PASS, laczny czas {total_seconds}s")

    if args.out:
        Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Szczegoly zapisane do {args.out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
