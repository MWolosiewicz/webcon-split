import time

import pytest

from webcon_pdf_splitter.jobs import JobStore, QueueFullError


def _submit(store, name="a.pdf", element_id=None):
    return store.submit(
        element_id=element_id,
        source_path=f"/tmp/{name}",
        filename=name,
        patterns_field=None,
    )


def test_zadania_wychodza_w_kolejnosci_wejscia():
    store = JobStore()
    first, _ = _submit(store, "a.pdf")
    second, _ = _submit(store, "b.pdf")
    third, _ = _submit(store, "c.pdf")

    assert [store.next_job(timeout=0.1).job_id for _ in range(3)] == [
        first.job_id,
        second.job_id,
        third.job_id,
    ]


def test_pozycja_odzwierciedla_miejsce_w_kolejce():
    store = JobStore()
    first, _ = _submit(store, "a.pdf")
    second, _ = _submit(store, "b.pdf")

    assert store.position(first.job_id) == 1
    assert store.position(second.job_id) == 2

    store.mark_running(store.next_job(timeout=0.1).job_id)

    assert store.position(second.job_id) == 1


def test_pelna_kolejka_zglasza_queue_full():
    store = JobStore(max_queue_size=2)
    _submit(store, "a.pdf")
    _submit(store, "b.pdf")

    with pytest.raises(QueueFullError):
        _submit(store, "c.pdf")


def test_drugie_zlecenie_tego_samego_elementu_zwraca_to_samo_zadanie():
    store = JobStore()
    first, created_first = _submit(store, "a.pdf", element_id=77)
    second, created_second = _submit(store, "a.pdf", element_id=77)

    assert created_first is True
    assert created_second is False
    assert second.job_id == first.job_id


def test_deduplikacja_nie_obejmuje_zadan_zakonczonych():
    store = JobStore()
    first, _ = _submit(store, "a.pdf", element_id=77)
    store.mark_running(first.job_id)
    store.mark_done(first.job_id, result=None)

    second, created = _submit(store, "a.pdf", element_id=77)

    assert created is True
    assert second.job_id != first.job_id


def test_rozne_elementy_nie_sa_deduplikowane():
    store = JobStore()
    first, _ = _submit(store, "a.pdf", element_id=1)
    second, created = _submit(store, "b.pdf", element_id=2)

    assert created is True
    assert second.job_id != first.job_id


def test_wynik_wygasa_po_ttl():
    store = JobStore(result_ttl_seconds=0)
    job, _ = _submit(store)
    store.mark_running(job.job_id)
    store.mark_done(job.job_id, result=None)
    time.sleep(0.01)

    assert store.get(job.job_id) is None


def test_wygasle_zadanie_znika_bez_odpytywania_o_nie():
    # REGRESJA: wygasanie dzialalo leniwie, tylko dla pytanego job_id -
    # zadanie zakonczone bledem (o ktore WEBCON juz nie pyta) zostawalo
    # w pamieci z pelnym wynikiem base64 az do restartu kontenera
    store = JobStore(result_ttl_seconds=0)
    porzucone, _ = _submit(store, "porzucone.pdf")
    store.mark_running(porzucone.job_id)
    store.mark_failed(porzucone.job_id, "nieczytelny PDF")
    time.sleep(0.01)

    # zlecenie innej paczki musi posprzatac wygasle zadania
    _submit(store, "nowe.pdf")

    assert store.get(porzucone.job_id) is None
    assert porzucone.job_id not in store._jobs


def test_zadanie_w_toku_nie_wygasa():
    store = JobStore(result_ttl_seconds=0)
    job, _ = _submit(store)
    store.mark_running(job.job_id)

    assert store.get(job.job_id) is not None


def test_delete_usuwa_zadanie():
    store = JobStore()
    job, _ = _submit(store)

    assert store.delete(job.job_id) is True
    assert store.get(job.job_id) is None
    assert store.delete(job.job_id) is False


def test_mark_failed_zapisuje_tresc_bledu():
    store = JobStore()
    job, _ = _submit(store)
    store.mark_running(job.job_id)
    store.mark_failed(job.job_id, "Nieczytelny PDF")

    stored = store.get(job.job_id)
    assert stored.status == "failed"
    assert stored.error == "Nieczytelny PDF"


def test_next_job_zwraca_none_gdy_kolejka_pusta():
    assert JobStore().next_job(timeout=0.01) is None


def test_statystyki_licza_zadania_wedlug_statusu():
    store = JobStore()
    czeka, _ = _submit(store, "czeka.pdf")
    biegnie, _ = _submit(store, "biegnie.pdf")
    zepsute, _ = _submit(store, "zepsute.pdf")
    gotowe, _ = _submit(store, "gotowe.pdf")
    store.mark_running(biegnie.job_id)
    store.mark_failed(zepsute.job_id, "nieczytelny PDF")
    store.mark_done(gotowe.job_id, result=None)

    stats = store.stats()

    assert stats["queued"] == 1
    assert stats["running"] == 1
    assert stats["failed"] == 1
    assert stats["done"] == 1


def test_statystyki_podaja_wiek_najstarszego_oczekujacego():
    # to jest wskaznik "czy kolejka rosnie" - sama liczba czekajacych nie
    # odroznia zdrowego ogona od paczki, ktora utknela na godzine
    store = JobStore()
    stary, _ = _submit(store, "stary.pdf")
    stary.created_at -= 30
    _submit(store, "swiezy.pdf")

    assert store.stats()["oldest_queued_seconds"] >= 30


def test_wiek_najstarszego_jest_zerem_gdy_nikt_nie_czeka():
    store = JobStore()
    job, _ = _submit(store)
    store.mark_running(job.job_id)

    assert store.stats()["oldest_queued_seconds"] == 0.0
