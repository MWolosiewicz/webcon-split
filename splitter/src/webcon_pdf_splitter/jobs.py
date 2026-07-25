import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Full, Queue

from webcon_pdf_splitter.contracts import SplitResult

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "running")


class QueueFullError(Exception):
    """Kolejka osiagnela SPLITTER_MAX_QUEUE_SIZE - warstwa HTTP odda 503."""


def _unlink_quietly(path: str) -> None:
    """Kasuje plik, nigdy nie rzucajac.

    missing_ok tlumi tylko FileNotFoundError; kazdy inny OSError (plik
    zablokowany, brak praw) nie moze przerwac petli workera ani zapytania
    HTTP - sprzatanie jest skutkiem ubocznym, nie celem operacji.
    """
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        logger.warning(
            "Nie udalo sie usunac pliku zrodlowego %s - praca trwa dalej",
            path,
            exc_info=True,
        )


@dataclass
class Job:
    job_id: str
    element_id: int | None
    source_path: str
    filename: str
    patterns_field: str | None
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: SplitResult | None = None
    error: str | None = None

    @property
    def running_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.time()
        return round(end - self.started_at, 1)


class JobStore:
    """Kolejka FIFO zadan podzialu wraz z rejestrem ich stanu.

    Stan zyje wylacznie w pamieci procesu - swiadomie. Zrodlem prawdy jest
    zalacznik w WEBCONie, wiec po restarcie kontenera nieznane zadanie (404)
    prowadzi do ponownego zlecenia, a nie do utraty pracy.
    """

    def __init__(self, max_queue_size: int = 50, result_ttl_seconds: int = 3600) -> None:
        self._queue: Queue = Queue(maxsize=max_queue_size)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._result_ttl_seconds = result_ttl_seconds

    def submit(
        self, *, element_id: int | None, source_path: str, filename: str,
        patterns_field: str | None,
    ) -> tuple[Job, bool]:
        """Zwraca (zadanie, czy_utworzono_nowe).

        Gdy dla elementu istnieje juz aktywne zadanie, oddaje je zamiast
        tworzyc drugie: zlecenie mogl doleciec, a odpowiedz zginac po drodze -
        bez tego paczka podzielilaby sie dwukrotnie.
        """
        with self._lock:
            self._purge_expired_locked()
            if element_id is not None:
                for existing in self._jobs.values():
                    if existing.element_id == element_id and existing.status in ACTIVE_STATUSES:
                        return existing, False
            job = Job(
                job_id=str(uuid.uuid4()),
                element_id=element_id,
                source_path=source_path,
                filename=filename,
                patterns_field=patterns_field,
            )
            self._jobs[job.job_id] = job
        try:
            self._queue.put_nowait(job.job_id)
        except Full:
            with self._lock:
                self._jobs.pop(job.job_id, None)
            raise QueueFullError(
                "Kolejka zadan jest pelna - sprobuj ponownie za chwile"
            ) from None
        return job, True

    def next_job(self, timeout: float = 0.5) -> Job | None:
        try:
            job_id = self._queue.get(timeout=timeout)
        except Empty:
            return None
        with self._lock:
            return self._jobs.get(job_id)

    def _expired_locked(self, job: Job) -> bool:
        return job.finished_at is not None and (
            time.time() - job.finished_at > self._result_ttl_seconds
        )

    def _purge_expired_locked(self) -> None:
        """Kasuje wszystkie wygasle zadania, nie tylko to odpytywane.

        Bez tego pamiec wraca wylacznie dla zadan, o ktore ktos jeszcze
        zapyta - a WEBCON przestaje pytac o zadanie zakonczone bledem albo
        o element wypchniety na blad przez dozorce. Wyniki (base64 calych
        paczek) zostawaly wtedy w RAM az do restartu kontenera.
        """
        expired = [
            job_id for job_id, job in self._jobs.items() if self._expired_locked(job)
        ]
        for job_id in expired:
            job = self._jobs.pop(job_id, None)
            if job is not None:
                _unlink_quietly(job.source_path)
        if expired:
            logger.info("Usunieto %s wygaslych zadan", len(expired))

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            self._purge_expired_locked()
            return self._jobs.get(job_id)

    def position(self, job_id: str) -> int:
        """Miejsce w kolejce liczone od 1; 0 dla zadania juz zdjetego."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "queued":
                return 0
            earlier = 0
            for other_id in self._jobs:
                if other_id == job_id:
                    break
                if self._jobs[other_id].status == "queued":
                    earlier += 1
            return earlier + 1

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "running"
                job.started_at = time.time()

    def mark_done(self, job_id: str, result: SplitResult | None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "done"
                job.result = result
                job.finished_at = time.time()

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "failed"
                job.error = error
                job.finished_at = time.time()

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        _unlink_quietly(job.source_path)
        return True


class JobWorker(threading.Thread):
    """Watek konsumujacy kolejke zadan po jednym na raz.

    Zadna porazka pojedynczego zadania nie moze przerwac petli - inaczej
    kolejka staje na zawsze i nic tego nie zglasza.
    """

    def __init__(self, store: JobStore, processor, name: str = "job-worker") -> None:
        super().__init__(name=name, daemon=True)
        self._store = store
        self._processor = processor
        self._stopped = threading.Event()

    def stop(self) -> None:
        self._stopped.set()

    def run(self) -> None:
        while not self._stopped.is_set():
            job = self._store.next_job(timeout=0.2)
            if job is None:
                continue
            self._run_one(job)

    def _run_one(self, job: Job) -> None:
        self._store.mark_running(job.job_id)
        try:
            result = self._processor(job)
        except Exception as exc:
            logger.warning(
                "Zadanie %s zakonczone bledem: %s", job.job_id, exc, exc_info=True
            )
            self._store.mark_failed(job.job_id, str(exc))
        else:
            self._store.mark_done(job.job_id, result)
        finally:
            _unlink_quietly(job.source_path)
