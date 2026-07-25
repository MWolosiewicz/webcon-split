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
    # jobId wraca teraz z 202, a logi przetwarzania powstaja w watku
    # roboczym - przed odczytem stderr trzeba poczekac na koniec zadania
    import time

    api.configure_logging(SplitterSettings(_env_file=None))
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    with TestClient(api.app) as client:
        response = client.post(
            "/api/split",
            files={"file": ("paczka.pdf", buffer.getvalue(), "application/pdf")},
        )

        assert response.status_code == 202
        job_id = response.json()["jobId"]
        deadline = time.time() + 10
        while time.time() < deadline:
            if client.get(f"/api/jobs/{job_id}").json()["status"] in ("done", "failed"):
                break
            time.sleep(0.02)

    err = capsys.readouterr().err
    assert f"[job={job_id}]" in err
