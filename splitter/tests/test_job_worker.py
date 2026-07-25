import threading
import time

from webcon_pdf_splitter.jobs import JobStore, JobWorker


def _wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _submit(store, name="a.pdf"):
    job, _ = store.submit(
        element_id=None, source_path=f"/tmp/{name}", filename=name, patterns_field=None
    )
    return job


def test_zadanie_przechodzi_do_done():
    store = JobStore()
    job = _submit(store)
    worker = JobWorker(store, processor=lambda _: "WYNIK")
    worker.start()
    try:
        assert _wait_for(lambda: store.get(job.job_id).status == "done")
        assert store.get(job.job_id).result == "WYNIK"
    finally:
        worker.stop()
        worker.join(timeout=2)


def test_wyjatek_zadania_nie_zabija_workera():
    # test krytyczny: bez tego jedna zla paczka zatrzymuje kolejke na zawsze,
    # i to po cichu - nikt nie dostaje sygnalu, ze nic sie juz nie dzieje
    store = JobStore()
    zle = _submit(store, "zle.pdf")
    dobre = _submit(store, "dobre.pdf")

    def processor(job):
        if job.filename == "zle.pdf":
            raise RuntimeError("nieczytelny PDF")
        return "WYNIK"

    worker = JobWorker(store, processor=processor)
    worker.start()
    try:
        assert _wait_for(lambda: store.get(dobre.job_id).status == "done")
        assert store.get(zle.job_id).status == "failed"
        assert "nieczytelny PDF" in store.get(zle.job_id).error
        assert worker.is_alive()
    finally:
        worker.stop()
        worker.join(timeout=2)


def test_plik_zrodlowy_znika_takze_po_bledzie(tmp_path):
    source = tmp_path / "a.pdf"
    source.write_bytes(b"%PDF-1.4")
    store = JobStore()
    job, _ = store.submit(
        element_id=None, source_path=str(source), filename="a.pdf", patterns_field=None
    )

    worker = JobWorker(store, processor=lambda _: (_ for _ in ()).throw(RuntimeError("bum")))
    worker.start()
    try:
        assert _wait_for(lambda: store.get(job.job_id).status == "failed")
        assert not source.exists()
    finally:
        worker.stop()
        worker.join(timeout=2)


def test_stop_konczy_watek():
    store = JobStore()
    worker = JobWorker(store, processor=lambda _: None)
    worker.start()
    worker.stop()
    worker.join(timeout=2)

    assert not worker.is_alive()


def test_zadanie_jest_oznaczone_jako_running_w_trakcie():
    store = JobStore()
    job = _submit(store)
    trzymaj = threading.Event()

    def processor(_):
        trzymaj.wait(timeout=2)
        return "WYNIK"

    worker = JobWorker(store, processor=processor)
    worker.start()
    try:
        assert _wait_for(lambda: store.get(job.job_id).status == "running")
    finally:
        trzymaj.set()
        worker.stop()
        worker.join(timeout=2)


def test_blad_przy_usunianiu_pliku_nie_zabija_workera(monkeypatch):
    """Test regresyjny: blad usuwania nie przerywa petli workera."""
    from pathlib import Path

    store = JobStore()
    pierwsze = _submit(store, "pierwsze.pdf")
    drugie = _submit(store, "drugie.pdf")

    # Processor dla obu zadan powoduje sukces
    def processor(job):
        return "WYNIK"

    # Monkeypatch: Path.unlink dla pierwszego zadania rzuca PermissionError
    original_unlink = Path.unlink

    def unlink_with_permission_error(self, missing_ok=False):
        if "pierwsze.pdf" in str(self):
            raise PermissionError("Plik jest zablokowany")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_with_permission_error)

    worker = JobWorker(store, processor=processor)
    worker.start()
    try:
        # Czekamy az pierwsze zadanie zostanie oznaczone jako done
        assert _wait_for(lambda: store.get(pierwsze.job_id).status == "done")
        # Czekamy az drugie zadanie zostanie oznaczone jako done
        assert _wait_for(lambda: store.get(drugie.job_id).status == "done")
        # Worker jest nadal zyw
        assert worker.is_alive()
    finally:
        worker.stop()
        worker.join(timeout=2)
