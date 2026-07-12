import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from webcon_pdf_splitter.contracts import DetectedDocument


def parse_page_range(spec: str, page_count: int) -> list[int]:
    """Parsuje zakres stron 1-based, np. '2-4,7'. Zwraca posortowane, unikalne."""
    if spec is None or not spec.strip():
        raise ValueError("Zakres stron jest pusty")
    pages: set[int] = set()
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_s, _, end_s = token.partition("-")
            try:
                start, end = int(start_s.strip()), int(end_s.strip())
            except ValueError as exc:
                raise ValueError(f"Nieprawidlowy fragment zakresu: '{token}'") from exc
            if start > end:
                raise ValueError(f"Odwrocony zakres: '{token}'")
            pages.update(range(start, end + 1))
        else:
            try:
                pages.add(int(token))
            except ValueError as exc:
                raise ValueError(f"Nieprawidlowy numer strony: '{token}'") from exc
    if not pages:
        raise ValueError("Zakres stron jest pusty")
    for page in sorted(pages):
        if page < 1 or page > page_count:
            raise ValueError(f"Strona {page} poza dokumentem (1-{page_count})")
    return sorted(pages)


def validate_pdf(path: Path) -> int:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("PDF is encrypted")
    return len(reader.pages)


def split_pdf(source_path: Path, output_dir: Path, documents: list[DetectedDocument]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(source_path))
    output_paths: list[Path] = []
    for document in documents:
        writer = PdfWriter()
        for page_index in range(document.startPage - 1, document.endPage):
            writer.add_page(reader.pages[page_index])
        output_path = output_dir / document.outputFileName
        with output_path.open("wb") as handle:
            writer.write(handle)
        output_paths.append(output_path)
    return output_paths
