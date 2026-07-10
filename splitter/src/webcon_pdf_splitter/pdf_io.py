from pathlib import Path

from pypdf import PdfReader, PdfWriter

from webcon_pdf_splitter.contracts import DetectedDocument


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
