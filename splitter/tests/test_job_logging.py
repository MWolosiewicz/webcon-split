import io
import logging

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from webcon_pdf_splitter import api
from webcon_pdf_splitter.config import SplitterSettings


def test_job_log_context_prefixes_lines_inside_context(capsys):
    api.configure_logging(SplitterSettings(_env_file=None))
    logger = logging.getLogger("webcon_pdf_splitter.testjob")

    with api.job_log_context("11111111-2222-3333"):
        logger.info("wpis w trakcie zadania")
    logger.info("wpis poza zadaniem")

    lines = capsys.readouterr().err.strip().splitlines()
    inside = next(line for line in lines if "wpis w trakcie zadania" in line)
    outside = next(line for line in lines if "wpis poza zadaniem" in line)
    assert "[job=11111111-2222-3333]" in inside
    assert "[job=" not in outside


def test_split_endpoint_logs_carry_returned_job_id(capsys):
    api.configure_logging(SplitterSettings(_env_file=None))
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    client = TestClient(api.app)
    response = client.post(
        "/api/split",
        files={"file": ("paczka.pdf", buffer.getvalue(), "application/pdf")},
    )

    assert response.status_code == 200
    job_id = response.json()["jobId"]
    err = capsys.readouterr().err
    assert f"[job={job_id}]" in err
