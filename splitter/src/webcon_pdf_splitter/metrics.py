"""Metryki dzialania serwisu.

Dwa poziomy, oba w pamieci procesu (serwis pozostaje bezstanowy):
- per zadanie: kolektor w contextvar, zbierany w trakcie /api/split
  i logowany jedna linia podsumowania;
- skumulowane od startu procesu: rejestr pod GET /metrics - pozwala
  sledzic, czy zmiany slownika/progow obnizaja odsetek weryfikacji.

Komponenty (OCR, LLM) raportuja przez add_*; poza aktywnym zadaniem
wywolania sa no-opem, wiec recznie uzywane moduly nic nie kosztuja.
"""

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class RequestMetrics:
    pages: int = 0
    ocr_pages: int = 0
    llm_calls: int = 0
    documents: int = 0
    documents_requiring_review: int = 0
    duration_seconds: float = 0.0


_CURRENT: ContextVar[RequestMetrics | None] = ContextVar(
    "request_metrics", default=None
)


@contextmanager
def request_collector():
    collected = RequestMetrics()
    token = _CURRENT.set(collected)
    try:
        yield collected
    finally:
        _CURRENT.reset(token)


def add_ocr_pages(count: int) -> None:
    collected = _CURRENT.get()
    if collected is not None:
        collected.ocr_pages += count


def add_llm_call() -> None:
    collected = _CURRENT.get()
    if collected is not None:
        collected.llm_calls += 1


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._zero()

    def _zero(self) -> None:
        self._split_requests = 0
        self._pages = 0
        self._ocr_pages = 0
        self._llm_calls = 0
        self._documents = 0
        self._documents_requiring_review = 0
        self._processing_seconds = 0.0

    def reset(self) -> None:
        with self._lock:
            self._zero()

    def record(self, request: RequestMetrics) -> None:
        with self._lock:
            self._split_requests += 1
            self._pages += request.pages
            self._ocr_pages += request.ocr_pages
            self._llm_calls += request.llm_calls
            self._documents += request.documents
            self._documents_requiring_review += request.documents_requiring_review
            self._processing_seconds += request.duration_seconds

    def snapshot(self) -> dict:
        with self._lock:
            review_rate = (
                round(self._documents_requiring_review / self._documents, 4)
                if self._documents
                else 0.0
            )
            return {
                "uptime_seconds": round(time.time() - self._started_at, 1),
                "split_requests_total": self._split_requests,
                "pages_total": self._pages,
                "ocr_pages_total": self._ocr_pages,
                "llm_calls_total": self._llm_calls,
                "documents_total": self._documents,
                "documents_requiring_review_total": self._documents_requiring_review,
                "review_rate": review_rate,
                "processing_seconds_total": round(self._processing_seconds, 3),
            }


registry = MetricsRegistry()
