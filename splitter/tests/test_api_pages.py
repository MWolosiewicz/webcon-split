import base64
import io

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from webcon_pdf_splitter import api
from webcon_pdf_splitter.api import app
from webcon_pdf_splitter.config import SplitterSettings


def _pdf_bytes(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _decode_pages(payload) -> int:
    content = base64.b64decode(payload["fileContentBase64"])
    return len(PdfReader(io.BytesIO(content)).pages)


def test_remove_pages_endpoint_drops_pages():
    client = TestClient(app)
    response = client.post(
        "/api/pages/remove",
        data={"pages": "2,4"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(5)), "application/pdf")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageCount"] == 3
    assert _decode_pages(payload) == 3


def test_remove_pages_endpoint_rejects_bad_range():
    client = TestClient(app)
    response = client.post(
        "/api/pages/remove",
        data={"pages": "9-10"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(5)), "application/pdf")},
    )
    assert response.status_code == 400


def test_extract_pages_endpoint_keeps_pages():
    client = TestClient(app)
    response = client.post(
        "/api/pages/extract",
        data={"pages": "2-3"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(6)), "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["pageCount"] == 2


def test_pages_endpoint_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr(
        api, "get_settings", lambda: SplitterSettings(_env_file=None, api_token="sekret")
    )
    client = TestClient(app)
    response = client.post(
        "/api/pages/remove",
        data={"pages": "1"},
        files={"file": ("doc.pdf", io.BytesIO(_pdf_bytes(2)), "application/pdf")},
    )
    assert response.status_code == 401


def test_merge_endpoint_concatenates_in_order():
    client = TestClient(app)
    response = client.post(
        "/api/merge",
        data={"output_file_name": "scalony.pdf"},
        files=[
            ("files", ("b.pdf", io.BytesIO(_pdf_bytes(3)), "application/pdf")),
            ("files", ("a.pdf", io.BytesIO(_pdf_bytes(2)), "application/pdf")),
        ],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["outputFileName"] == "scalony.pdf"
    assert payload["pageCount"] == 5
    assert _decode_pages(payload) == 5


def test_merge_endpoint_rejects_non_pdf():
    client = TestClient(app)
    response = client.post(
        "/api/merge",
        files=[("files", ("note.txt", io.BytesIO(b"hello"), "text/plain"))],
    )
    assert response.status_code == 400


# .NET MultipartFormDataContent koduje nie-ASCII nazwy plikow jako RFC 2047
# (=?utf-8?B?...?=) w polu filename; parser Starlette ignoruje filename*.
# Serwis musi odkodowac taka nazwe, inaczej polskie znaki daja HTTP 400.
_DOTNET_DISPOSITION = (
    'Content-Disposition: form-data; name=file; '
    'filename="=?utf-8?B?emHFm3dpYWRjemVuaWVfxYLEhWthIMW7w7PFgsSHLnBkZg==?="; '
    "filename*=utf-8''za%C5%9Bwiadczenie_%C5%82%C4%85ka%20%C5%BB%C3%B3%C5%82%C4%87.pdf"
)


def _dotnet_style_body(boundary: str, pdf: bytes, pages: str) -> bytes:
    return (
        f"--{boundary}\r\nContent-Type: application/pdf\r\n{_DOTNET_DISPOSITION}\r\n\r\n".encode()
        + pdf
        + f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=pages\r\n\r\n{pages}\r\n--{boundary}--\r\n".encode()
    )


def test_remove_pages_accepts_dotnet_rfc2047_polish_filename():
    client = TestClient(app)
    boundary = "testboundary123"
    response = client.post(
        "/api/pages/remove",
        content=_dotnet_style_body(boundary, _pdf_bytes(3), "2"),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageCount"] == 2
    assert payload["outputFileName"] == "zaświadczenie_łąka Żółć_bez-stron.pdf"


def test_split_accepts_dotnet_rfc2047_polish_filename():
    client = TestClient(app)
    boundary = "testboundary456"
    body = (
        f"--{boundary}\r\nContent-Type: application/pdf\r\n{_DOTNET_DISPOSITION}\r\n\r\n".encode()
        + _pdf_bytes(2)
        + f"\r\n--{boundary}--\r\n".encode()
    )
    response = client.post(
        "/api/split",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 200
    assert response.json()["sourceFileName"] == "zaświadczenie_łąka Żółć.pdf"
