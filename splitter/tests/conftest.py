import time

import pytest

from webcon_pdf_splitter import api
from webcon_pdf_splitter.config import SplitterSettings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Tests must never read .env or touch a real database.

    work_dir wskazuje na katalog tymczasowy: lifespan zamiata work_dir przy
    starcie i zapisuje tam pliki zadan, wiec nie moze celowac w ./work
    dewelopera.
    """
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SplitterSettings(_env_file=None, work_dir=str(tmp_path / "work")),
    )


def split_and_wait(client, files, data=None, headers=None, timeout=10.0):
    """Zlecenie + oczekiwanie + pobranie wyniku - kontrakt po wprowadzeniu kolejki.

    Zastepuje dawne synchroniczne odczytanie wyniku wprost z POST /api/split.
    Wymaga klienta z uruchomionym lifespan (with TestClient(...) as client).
    """
    response = client.post("/api/split", files=files, data=data or {}, headers=headers or {})
    assert response.status_code == 202, response.text
    job_id = response.json()["jobId"]
    status = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        if status in ("done", "failed"):
            break
        time.sleep(0.02)
    assert status == "done", client.get(f"/api/jobs/{job_id}").json()
    return client.get(f"/api/jobs/{job_id}/result").json()
