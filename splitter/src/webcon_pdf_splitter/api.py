import base64
import io
import logging
import secrets
import shutil
import time
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse
from pypdf import PdfReader
from starlette.concurrency import run_in_threadpool

from webcon_pdf_splitter import metrics
from webcon_pdf_splitter.config import SplitterSettings
from webcon_pdf_splitter.contracts import (
    JobStatusResponse,
    PageOpResult,
    SplitResult,
    SubmitJobResponse,
)
from webcon_pdf_splitter.jobs import (
    Job,
    JobStore,
    JobWorker,
    QueueFullError,
    empty_stats,
)
from webcon_pdf_splitter.pdf_io import (
    extract_pages,
    merge_pdfs,
    parse_page_range,
    remove_pages,
    validate_pdf,
)
from webcon_pdf_splitter.processing import build_ocr_engine, parse_patterns_field, process


logger = logging.getLogger(__name__)


def get_settings() -> SplitterSettings:
    return SplitterSettings()


# jobId biezacego zadania /api/split - przy rownoleglych zadaniach logi
# roznych paczek przeplataja sie w docker logs; prefiks [job=...] pozwala
# je rozdzielic i skorelowac z logiem operacji akcji WEBCON
_JOB_ID: ContextVar[str] = ContextVar("job_id", default="")


class _JobIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        job_id = _JOB_ID.get()
        record.job_id = f" [job={job_id}]" if job_id else ""
        return True


@contextmanager
def job_log_context(job_id: str):
    token = _JOB_ID.set(job_id)
    try:
        yield
    finally:
        _JOB_ID.reset(token)


def configure_logging(settings: SplitterSettings) -> None:
    # uvicorn configures only its own loggers; without this, application
    # logger.info(...) calls never reach docker logs.
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s%(job_id)s: %(message)s",
        force=True,
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(_JobIdFilter())


configure_logging(get_settings())


# Kolejka i workery zyja w pamieci procesu i powstaja w lifespan - swiadomie
# bez trwalego magazynu: zrodlem prawdy jest zalacznik w WEBCONie, wiec po
# restarcie kontenera nieznane zadanie (404) prowadzi do ponownego zlecenia.
_job_store: JobStore | None = None
_workers: list[JobWorker] = []


def get_job_store() -> JobStore:
    if _job_store is None:
        raise RuntimeError("Kolejka zadan nie zostala uruchomiona")
    return _job_store


def run_job(job: Job) -> SplitResult:
    """Wykonanie zadania w watku roboczym - z kontekstem logu i metryk."""
    settings = get_settings()
    started = time.perf_counter()
    with job_log_context(job.job_id), metrics.request_collector() as request_metrics:
        logger.info(
            "Start przetwarzania '%s' (webconElementId=%s)",
            job.filename,
            job.element_id,
        )
        # ocr wstrzykniety jawnie (a nie budowany wewnatrz process()),
        # zeby monkeypatch build_ocr_engine w testach nadal dzialal na
        # warstwie HTTP - patrz test_split_patterns.py
        result = process(
            settings,
            job.source_path,
            job.filename,
            job.patterns_field,
            ocr=build_ocr_engine(settings),
        )
        request_metrics.pages = result.pageCount
        request_metrics.documents = len(result.documents)
        request_metrics.documents_requiring_review = sum(
            1 for document in result.documents if document.requiresReview
        )
        request_metrics.duration_seconds = time.perf_counter() - started
        metrics.registry.record(request_metrics)
        logger.info(
            "Metryki zadania: %s stron (OCR: %s), wywolania LLM: %s, "
            "dokumenty: %s (weryfikacja: %s), czas %.1f s",
            request_metrics.pages,
            request_metrics.ocr_pages,
            request_metrics.llm_calls,
            request_metrics.documents,
            request_metrics.documents_requiring_review,
            request_metrics.duration_seconds,
        )
    # identyfikator korelacyjny: akcja WEBCON zapisuje go w logu operacji
    result.jobId = job.job_id
    return result


def _sweep_work_dir(settings: SplitterSettings) -> None:
    """Kasuje pliki po poprzednim wcieleniu kontenera.

    Kolejka zyje w pamieci, wiec po restarcie zadne z tych zadan juz nie
    istnieje - ich pliki zostalyby na dysku na zawsze. work_dir jest
    katalogiem wylacznie serwisu (patrz Dockerfile/README), stad zamiatamy
    calosc.
    """
    work_dir = Path(settings.work_dir)
    if not work_dir.exists():
        return
    for leftover in work_dir.iterdir():
        try:
            if leftover.is_dir():
                shutil.rmtree(leftover, ignore_errors=True)
            else:
                leftover.unlink(missing_ok=True)
        except OSError:
            logger.warning("Nie udalo sie usunac %s", leftover, exc_info=True)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    global _job_store
    settings = get_settings()
    _sweep_work_dir(settings)
    Path(settings.work_dir).mkdir(parents=True, exist_ok=True)
    _job_store = JobStore(
        max_queue_size=settings.max_queue_size,
        result_ttl_seconds=settings.job_result_ttl_seconds,
    )
    for index in range(max(1, settings.worker_count)):
        # lambda z globalnym lookupem run_job - podmiana api.run_job
        # w testach dziala takze dla juz wystartowanych workerow
        worker = JobWorker(
            _job_store,
            processor=lambda job: run_job(job),
            name=f"job-worker-{index + 1}",
        )
        worker.start()
        _workers.append(worker)
    logger.info("Kolejka zadan uruchomiona (workerow: %s)", len(_workers))
    yield
    for worker in _workers:
        worker.stop()
    for worker in _workers:
        worker.join(timeout=5)
    _workers.clear()
    _job_store = None


app = FastAPI(title="WEBCON PDF Splitter", lifespan=lifespan)


def _require_token(settings: SplitterSettings, authorization: str | None) -> None:
    if not settings.api_token:
        return
    # compare_digest zamiast "!=": zwykle porownanie napisow konczy sie na
    # pierwszym roznym znaku, wiec czas odpowiedzi zdradza, ile poczatkowych
    # znakow tokenu zgadlo sie z prawidlowym.
    #
    # Porownujemy BAJTY, nie napisy - compare_digest odmawia porownania
    # napisow spoza ASCII (TypeError), a token z ogonkami zamienialby wtedy
    # kazde 401 w 500.
    expected = f"Bearer {settings.api_token}".encode("utf-8")
    supplied = (authorization or "").encode("utf-8")
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


def _normalize_upload_filename(raw: str | None) -> str:
    """Odzyskuje prawdziwa nazwe pliku z uploadu.

    .NET (MultipartFormDataContent w akcjach WEBCON) koduje nie-ASCII nazwy
    jako RFC 2047 (=?utf-8?B?...?=) w polu filename, a parser Starlette nie
    czyta pola filename*. Przegladarki/httpx wysylaja surowe UTF-8 - wtedy
    dekodowanie jest no-opem. Dodatkowo odcinamy sciezki (basename).
    """
    if not raw:
        return ""
    name = raw
    if name.startswith("=?") and name.rstrip().endswith("?="):
        from email.header import decode_header

        try:
            decoded_parts = decode_header(name)
            name = "".join(
                part.decode(charset or "utf-8") if isinstance(part, bytes) else part
                for part, charset in decoded_parts
            )
        except Exception:  # nieparsowalne naglowki zostawiamy jak sa
            name = raw
    # tylko nazwa pliku - bez skladnikow sciezki z klienta
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    return name.strip()


def _derive_name(original: str, suffix: str) -> str:
    stem = original[:-4] if original.lower().endswith(".pdf") else original
    return f"{stem}{suffix}.pdf"


def _page_count_of(pdf_bytes: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


UPLOAD_CHUNK_BYTES = 1024 * 1024


def save_upload(source, destination: Path, chunk_size: int = UPLOAD_CHUNK_BYTES) -> None:
    """Przepisuje przyslany plik na dysk porcjami.

    Synchroniczna z rozmyslu - wola ja run_in_threadpool. Zapis na dysk jest
    operacja blokujaca, wiec wykonany wprost w endpokcie async wstrzymywalby
    obsluge WSZYSTKICH pozostalych zapytan na czas zrzutu pliku.

    Porcjami, a nie jednym read(): wczytanie calej paczki do pamieci przy
    kilku rownoczesnych wysylkach sumuje sie w RAM procesu.
    """
    with destination.open("wb") as target:
        shutil.copyfileobj(source, target, chunk_size)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics_endpoint(authorization: str | None = Header(default=None)) -> dict:
    # Dwa poziomy w jednej odpowiedzi: liczniki skumulowane od startu procesu
    # (odsetek weryfikacji - glowny wskaznik strojenia slownika i progow) oraz
    # "queue" z biezacym stanem kolejki, czyli odpowiedz na pytanie zadawane
    # przy problemie na produkcji: ile paczek czeka i od kiedy.
    _require_token(get_settings(), authorization)
    snapshot = metrics.registry.snapshot()
    # kolejka powstaje w lifespan - przed nim (sonda konfiguracji, testy)
    # oddajemy zera zamiast wywracac endpoint
    snapshot["queue"] = _job_store.stats() if _job_store is not None else empty_stats()
    return snapshot


@app.post("/api/split", response_model=SubmitJobResponse, status_code=202)
async def split_pdf_endpoint(
    file: UploadFile = File(...),
    patterns: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
):
    settings = get_settings()
    _require_token(settings, authorization)

    filename = _normalize_upload_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    # wzorce parsujemy od razu: to blad konfiguracji, tani do wykrycia,
    # a zwrocony jako 400 trafia wprost do logu operacji akcji WEBCON;
    # walidacja samego PDF-a biegnie w workerze (status failed)
    if patterns is not None:
        try:
            parse_patterns_field(patterns)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    work_dir = Path(settings.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    source_path = work_dir / f"{uuid4().hex}_{filename}"
    # jawny seek zamiast polegania na tym, gdzie parser multipartu zostawil
    # wskaznik po zlozeniu czesci
    await file.seek(0)
    await run_in_threadpool(save_upload, file.file, source_path)

    store = get_job_store()
    try:
        job, created = store.submit(
            element_id=webcon_element_id,
            source_path=str(source_path),
            filename=filename,
            patterns_field=patterns,
        )
    except QueueFullError as exc:
        source_path.unlink(missing_ok=True)
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc)},
            headers={"Retry-After": "60"},
        )
    if not created:
        # zadanie dla tego elementu juz biegnie - swiezy upload jest zbedny
        source_path.unlink(missing_ok=True)
        logger.info(
            "Element %s ma juz aktywne zadanie %s - zlecenie pominiete",
            webcon_element_id,
            job.job_id,
        )
    else:
        logger.info(
            "Przyjeto '%s' do kolejki (jobId=%s, webconElementId=%s)",
            filename,
            job.job_id,
            webcon_element_id,
        )
    return SubmitJobResponse(jobId=job.job_id, position=store.position(job.job_id))


def _require_job(job_id: str) -> Job:
    job = get_job_store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nieznane zadanie")
    return job


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def job_status_endpoint(
    job_id: str, authorization: str | None = Header(default=None)
) -> JobStatusResponse:
    _require_token(get_settings(), authorization)
    job = _require_job(job_id)
    result = job.result
    return JobStatusResponse(
        jobId=job.job_id,
        status=job.status,
        position=get_job_store().position(job.job_id),
        runningSeconds=job.running_seconds,
        pageCount=result.pageCount if result else 0,
        documentCount=len(result.documents) if result else 0,
        documentsRequiringReview=(
            sum(1 for document in result.documents if document.requiresReview)
            if result
            else 0
        ),
        warnings=result.warnings if result else [],
        error=job.error,
    )


@app.get("/api/jobs/{job_id}/result", response_model=SplitResult)
def job_result_endpoint(
    job_id: str, authorization: str | None = Header(default=None)
) -> SplitResult:
    _require_token(get_settings(), authorization)
    job = _require_job(job_id)
    if job.status != "done" or job.result is None:
        raise HTTPException(
            status_code=409,
            detail=f"Zadanie nie jest zakonczone (status: {job.status})",
        )
    return job.result


@app.delete("/api/jobs/{job_id}", status_code=204)
def job_delete_endpoint(
    job_id: str, authorization: str | None = Header(default=None)
) -> Response:
    _require_token(get_settings(), authorization)
    if not get_job_store().delete(job_id):
        raise HTTPException(status_code=404, detail="Nieznane zadanie")
    return Response(status_code=204)


@app.post("/api/pages/remove", response_model=PageOpResult)
async def remove_pages_endpoint(
    file: UploadFile = File(...),
    pages: str = Form(...),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> PageOpResult:
    settings = get_settings()
    _require_token(settings, authorization)
    filename = _normalize_upload_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / filename
        source_path.write_bytes(await file.read())
        try:
            page_count = validate_pdf(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            selected = parse_page_range(pages, page_count)
            output = remove_pages(source_path, selected)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PageOpResult(
        outputFileName=_derive_name(filename, "_bez-stron"),
        pageCount=_page_count_of(output),
        fileContentBase64=base64.b64encode(output).decode("ascii"),
    )


@app.post("/api/pages/extract", response_model=PageOpResult)
async def extract_pages_endpoint(
    file: UploadFile = File(...),
    pages: str = Form(...),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> PageOpResult:
    settings = get_settings()
    _require_token(settings, authorization)
    filename = _normalize_upload_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        source_path = Path(tmp) / filename
        source_path.write_bytes(await file.read())
        try:
            page_count = validate_pdf(source_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            selected = parse_page_range(pages, page_count)
            output = extract_pages(source_path, selected)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PageOpResult(
        outputFileName=_derive_name(filename, "_strony"),
        pageCount=_page_count_of(output),
        fileContentBase64=base64.b64encode(output).decode("ascii"),
    )


@app.post("/api/merge", response_model=PageOpResult)
async def merge_endpoint(
    files: list[UploadFile] = File(...),
    output_file_name: str = Form(default="merged.pdf"),
    authorization: str | None = Header(default=None),
    webcon_element_id: int | None = Header(default=None, alias="X-Webcon-Element-Id"),
) -> PageOpResult:
    settings = get_settings()
    _require_token(settings, authorization)
    if not files:
        raise HTTPException(status_code=400, detail="No files to merge")
    with TemporaryDirectory(dir=settings.work_dir if Path(settings.work_dir).exists() else None) as tmp:
        paths: list[Path] = []
        for index, upload in enumerate(files):
            upload_name = _normalize_upload_filename(upload.filename)
            if not upload_name.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="Only PDF files are supported")
            path = Path(tmp) / f"{index:03d}_{upload_name}"
            path.write_bytes(await upload.read())
            try:
                validate_pdf(path)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            paths.append(path)
        try:
            output = merge_pdfs(paths)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PageOpResult(
        outputFileName=output_file_name,
        pageCount=_page_count_of(output),
        fileContentBase64=base64.b64encode(output).decode("ascii"),
    )
