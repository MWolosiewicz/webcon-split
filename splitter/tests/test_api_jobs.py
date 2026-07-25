import io
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from webcon_pdf_splitter import api


def _pdf_bytes(pages=2):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def client():
    with TestClient(api.app) as test_client:
        yield test_client


def _submit(client, name="paczka.pdf"):
    return client.post(
        "/api/split", files={"file": (name, _pdf_bytes(), "application/pdf")}
    )


def test_zlecenie_zwraca_202_z_identyfikatorem(client):
    response = _submit(client)

    assert response.status_code == 202
    body = response.json()
    assert body["jobId"]
    # pierwsze zlecenie jest albo w kolejce na pozycji 1, albo juz zdjete
    # przez workera (pozycja 0) - kazda inna wartosc to blad liczenia
    assert body["position"] in (0, 1)


def test_status_nie_zawiera_base64(client):
    # status jest odpytywany co takt akcji cyklicznej - gdyby niosl base64,
    # kazde odpytanie ciagneloby przez siec cala paczke
    job_id = _submit(client).json()["jobId"]
    assert _wait_for(
        lambda: client.get(f"/api/jobs/{job_id}").json()["status"] in ("done", "failed")
    )

    body = client.get(f"/api/jobs/{job_id}").json()

    assert "fileContentBase64" not in json.dumps(body)
    assert body["status"] == "done"
    assert body["documentCount"] >= 1


def test_wynik_zawiera_pelny_splitresult(client):
    job_id = _submit(client).json()["jobId"]
    assert _wait_for(
        lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "done"
    )

    body = client.get(f"/api/jobs/{job_id}/result").json()

    assert body["sourceFileName"] == "paczka.pdf"
    assert body["jobId"] == job_id
    assert body["documents"][0]["fileContentBase64"]


def test_delete_zwalnia_zadanie(client):
    job_id = _submit(client).json()["jobId"]
    assert _wait_for(
        lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "done"
    )

    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_nieznane_zadanie_daje_404_na_wszystkich_endpointach(client):
    assert client.get("/api/jobs/brak").status_code == 404
    assert client.get("/api/jobs/brak/result").status_code == 404
    assert client.delete("/api/jobs/brak").status_code == 404


def test_wynik_niedostepny_dopoki_zadanie_trwa(client, monkeypatch):
    trzymaj = threading.Event()
    monkeypatch.setattr(api, "run_job", lambda job: trzymaj.wait(timeout=3))
    job_id = _submit(client).json()["jobId"]
    try:
        assert _wait_for(
            lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "running"
        )
        assert client.get(f"/api/jobs/{job_id}/result").status_code == 409
    finally:
        trzymaj.set()


def test_health_odpowiada_gdy_worker_mieli(client, monkeypatch):
    # regresja na chorobe sprzed zmiany: synchroniczny OCR na petli zdarzen
    # zamrazal caly proces, lacznie z healthcheckiem kontenera
    trzymaj = threading.Event()
    monkeypatch.setattr(api, "run_job", lambda job: trzymaj.wait(timeout=3))
    job_id = _submit(client).json()["jobId"]
    try:
        assert _wait_for(
            lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "running"
        )

        assert client.get("/health").status_code == 200
        assert client.get("/health").json() == {"status": "ok"}
    finally:
        trzymaj.set()


def test_pelna_kolejka_daje_503_z_retry_after(tmp_path, monkeypatch):
    from webcon_pdf_splitter.config import SplitterSettings

    # limit ustawiamy konfiguracja PRZED startem lifespan - kolejka powstaje
    # dopiero tam
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SplitterSettings(
            _env_file=None, work_dir=str(tmp_path), max_queue_size=1
        ),
    )
    trzymaj = threading.Event()
    monkeypatch.setattr(api, "run_job", lambda job: trzymaj.wait(timeout=5))

    with TestClient(api.app) as client:
        try:
            # pierwsza paczke zdejmuje worker; kolejne zapelniaja jedyne
            # miejsce w kolejce, az submit zacznie odbijac
            assert _submit(client, "a.pdf").status_code == 202
            assert _wait_for(lambda: _submit(client, "b.pdf").status_code == 503)
            response = _submit(client, "c.pdf")

            assert response.status_code == 503
            assert response.headers["Retry-After"]
        finally:
            trzymaj.set()


def test_powtorne_zlecenie_tego_samego_elementu_nie_tworzy_drugiego(
    client, monkeypatch
):
    trzymaj = threading.Event()
    monkeypatch.setattr(api, "run_job", lambda job: trzymaj.wait(timeout=3))
    try:
        headers = {"X-Webcon-Element-Id": "4242"}
        first = client.post(
            "/api/split",
            files={"file": ("a.pdf", _pdf_bytes(), "application/pdf")},
            headers=headers,
        ).json()
        second = client.post(
            "/api/split",
            files={"file": ("a.pdf", _pdf_bytes(), "application/pdf")},
            headers=headers,
        ).json()

        assert second["jobId"] == first["jobId"]
    finally:
        trzymaj.set()


def test_plik_nie_pdf_odrzucony_od_razu(client):
    response = client.post(
        "/api/split", files={"file": ("skan.png", b"nie-pdf", "image/png")}
    )

    assert response.status_code == 400


def test_zle_wzorce_odrzucone_od_razu(client):
    # blad konfiguracji ma wracac synchronicznie (400), nie jako failed
    # w zadaniu - trafia wprost do logu operacji akcji WEBCON
    response = client.post(
        "/api/split",
        files={"file": ("a.pdf", _pdf_bytes(), "application/pdf")},
        data={"patterns": "{nie-json}"},
    )

    assert response.status_code == 400


def test_uszkodzony_pdf_konczy_zadanie_statusem_failed(client):
    # walidacja pliku biegnie w workerze: zlecenie wraca 202, a blad
    # jest widoczny w statusie zadania
    response = client.post(
        "/api/split", files={"file": ("zepsuty.pdf", b"nie-pdf", "application/pdf")}
    )

    assert response.status_code == 202
    job_id = response.json()["jobId"]
    assert _wait_for(
        lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "failed"
    )
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["error"]


def test_work_dir_pusty_po_pelnym_cyklu_zadania(tmp_path, monkeypatch):
    # REGRESJA: pliki wynikowe podzialu ladowaly we wspolnym work_dir/output,
    # ktorego nikt nie kasowal - katalog rosl az do restartu kontenera
    from webcon_pdf_splitter.config import SplitterSettings

    work_dir = tmp_path / "work"
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SplitterSettings(_env_file=None, work_dir=str(work_dir)),
    )

    with TestClient(api.app) as client:
        job_id = _submit(client).json()["jobId"]
        assert _wait_for(
            lambda: client.get(f"/api/jobs/{job_id}").json()["status"] == "done"
        )
        assert client.delete(f"/api/jobs/{job_id}").status_code == 204

        leftovers = sorted(str(p.relative_to(work_dir)) for p in work_dir.rglob("*"))
        assert leftovers == [], f"work_dir nie zostal posprzatany: {leftovers}"


def test_dwa_workery_nie_mieszaja_wynikow_paczek(tmp_path, monkeypatch):
    # REGRESJA: nazwa pliku wynikowego to {typ}_strony_{od}-{do}.pdf, bez
    # jobId. We wspolnym katalogu dwa zadania z dokumentem tego samego typu
    # i zakresu nadpisywaly sie nawzajem - do jednej paczki mogl trafic PDF
    # z cudzej paczki
    import base64

    from pypdf import PdfReader

    from webcon_pdf_splitter.config import SplitterSettings

    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SplitterSettings(
            _env_file=None, work_dir=str(tmp_path / "work"), worker_count=2
        ),
    )

    with TestClient(api.app) as client:
        # rozna liczba stron = rozpoznawalny odcisk kazdej paczki
        jobs = {}
        for pages in (2, 5):
            response = client.post(
                "/api/split",
                files={"file": (f"p{pages}.pdf", _pdf_bytes(pages), "application/pdf")},
            )
            jobs[pages] = response.json()["jobId"]

        for pages, job_id in jobs.items():
            assert _wait_for(
                lambda jid=job_id: client.get(f"/api/jobs/{jid}").json()["status"]
                == "done"
            )
            result = client.get(f"/api/jobs/{job_id}/result").json()
            assert result["pageCount"] == pages
            content = base64.b64decode(result["documents"][0]["fileContentBase64"])
            assert len(PdfReader(io.BytesIO(content)).pages) == pages


def test_zamiatanie_work_dir_przy_starcie(tmp_path, monkeypatch):
    from webcon_pdf_splitter.config import SplitterSettings

    sierota = tmp_path / "sierota.pdf"
    sierota.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SplitterSettings(_env_file=None, work_dir=str(tmp_path)),
    )

    with TestClient(api.app):
        assert not sierota.exists()
