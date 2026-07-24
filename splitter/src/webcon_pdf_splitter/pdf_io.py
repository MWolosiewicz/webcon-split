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


def remove_pages(source_path: Path, pages: list[int]) -> bytes:
    reader = PdfReader(str(source_path))
    to_remove = set(pages)
    keep = [i for i in range(len(reader.pages)) if (i + 1) not in to_remove]
    if not keep:
        raise ValueError("Usuniecie tych stron zostawiloby pusty dokument")
    writer = PdfWriter()
    for index in keep:
        writer.add_page(reader.pages[index])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def extract_pages(source_path: Path, pages: list[int]) -> bytes:
    reader = PdfReader(str(source_path))
    writer = PdfWriter()
    for page in sorted(set(pages)):
        writer.add_page(reader.pages[page - 1])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def merge_pdfs(source_paths: list[Path]) -> bytes:
    if not source_paths:
        raise ValueError("Brak plikow PDF do sklejenia")
    writer = PdfWriter()
    for path in source_paths:
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


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
        removed = set(document.removedPages)
        for page_index in range(document.startPage - 1, document.endPage):
            if (page_index + 1) in removed:
                continue
            writer.add_page(reader.pages[page_index])
        output_path = output_dir / document.outputFileName
        with output_path.open("wb") as handle:
            writer.write(handle)
        output_paths.append(output_path)
    return output_paths
