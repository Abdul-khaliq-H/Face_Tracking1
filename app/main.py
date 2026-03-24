from __future__ import annotations

import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.processor import process_video

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

MAX_WORKERS = int(os.getenv("PROCESSOR_WORKERS", "2"))
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

StatusType = Literal["queued", "processing", "completed", "failed"]


@dataclass
class Job:
    job_id: str
    filename: str
    status: StatusType = "queued"
    progress: int = 0
    stage: str = "Queued"
    error: str | None = None
    output_file: str | None = None
    _future_id: str | None = field(default=None, repr=False)


jobs: dict[str, Job] = {}
jobs_lock = Lock()

app = FastAPI(title="FaceTrack SaaS", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



def update_job(job_id: str, **kwargs) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        for key, value in kwargs.items():
            setattr(job, key, value)



def run_job(job_id: str, input_path: Path, output_path: Path) -> None:
    update_job(job_id, status="processing", progress=1, stage="Worker started")

    try:
        process_video(
            input_path,
            output_path,
            on_progress=lambda pct, stage: update_job(job_id, progress=pct, stage=stage),
        )
        update_job(
            job_id,
            status="completed",
            progress=100,
            stage="Completed",
            output_file=str(output_path.name),
        )
    except Exception as exc:  # noqa: BLE001
        update_job(job_id, status="failed", stage="Failed", error=str(exc))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...)) -> dict[str, str]:
    allowed_ext = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
    suffix = Path(file.filename or "").suffix.lower()

    if suffix not in allowed_ext:
        raise HTTPException(status_code=400, detail="Unsupported video format")

    job_id = uuid.uuid4().hex
    input_path = UPLOADS_DIR / f"{job_id}{suffix}"
    output_path = OUTPUTS_DIR / f"{job_id}.mp4"

    with input_path.open("wb") as out_file:
        shutil.copyfileobj(file.file, out_file)

    job = Job(job_id=job_id, filename=file.filename or input_path.name)
    with jobs_lock:
        jobs[job_id] = job

    executor.submit(run_job, job_id, input_path, output_path)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return asdict(job)


@app.get("/api/jobs/{job_id}/result")
def get_result(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status != "completed" or not job.output_file:
            raise HTTPException(status_code=400, detail="Result is not ready")

    output_path = OUTPUTS_DIR / job.output_file
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")

    return FileResponse(
        path=output_path,
        media_type="video/mp4",
        filename=f"{job_id}_tracked.mp4",
    )


app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")
