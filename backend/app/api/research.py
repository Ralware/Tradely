"""Local API for the bundled perpetual research dataset and durable CLI runs."""

import csv
import json
import platform
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

research = Path(__file__).resolve().parents[3] / "research"
jobs = research / "optimization" / "ui_runs"
router = APIRouter(prefix="/api/backtests/research")
children = {}
launch_lock = Lock()


class Search(BaseModel):
    mode: Literal["auto", "gpu", "cpu"] = "auto"
    timeframe: Literal["2h", "4h", "1d"] = "2h"
    combinations: int = Field(default=20, ge=1, le=45000)


@router.get("/hardware")
@lru_cache
def hardware():
    device = None
    try:
        import cupy

        if cupy.cuda.runtime.getDeviceCount():
            cupy.zeros(1).sum().item()
            device = cupy.cuda.runtime.getDeviceProperties(0)["name"].decode()
    except (ImportError, RuntimeError, OSError, MemoryError):
        pass
    adapters = [device] if device else []
    if not adapters and sys.platform == "win32":
        try:
            names = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_VideoController).Name",
                ],
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            adapters = names.strip().splitlines()
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "cpu": platform.processor() or platform.machine(),
        "cuda_device": device,
        "adapters": adapters,
    }


@router.post("")
def start(payload: Search):
    job = uuid4()
    directory = jobs / str(job)
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(payload.model_dump_json())
    launch(job, directory, payload, payload.combinations)
    return {"id": job}


def launch(job, directory, payload, count, resume=False):
    with (directory / "run.log").open("a", encoding="utf8") as log:
        child = subprocess.Popen(
            [
                sys.executable,
                str(research / "v42_exhaustive_combination_tester.py"),
                "--timeframe",
                payload.timeframe,
                "--data-cutoff",
                "2026-01-01T00:00:00Z",
                "--execution-mode",
                payload.mode,
                "--max-combinations",
                str(count),
                *(["--resume", "--retry-failed"] if resume else []),
                "--checkpoint-every",
                "1",
                "--cancel-file",
                str(directory / "cancel"),
                "--output",
                str(directory),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    children[job] = child


def job_dir(job: UUID):
    directory = jobs / str(job)
    if not (directory / "request.json").exists():
        raise HTTPException(404, "Unknown research run")
    return directory


@router.get("/{job}")
def status(job: UUID):
    directory = job_dir(job)
    request = directory / "request.json"
    child = children.get(job)
    code = child.poll() if child else None
    manifest = next(directory.glob("results/*/*/run_metadata.json"), None)
    metadata = json.loads(manifest.read_text(encoding="utf8")) if manifest else {}
    checkpoint = manifest.with_name("checkpoint.json") if manifest else None
    state = json.loads(checkpoint.read_text()) if checkpoint and checkpoint.exists() else {}
    count = state.get("checkpoint_total", 0)
    status = metadata.get("status", "starting")
    error = None
    if child and code is None and status not in ("starting", "running"):
        status = "running"
    if child and code is not None:
        children.pop(job, None)
        if status in ("starting", "running") or code not in (0, 130):
            status = "failed"
            (directory / "failed").touch()
    if (directory / "failed").exists() or status in ("complete_with_errors", "worker_pool_failed"):
        status = "failed"
        error = (directory / "run.log").read_text(encoding="utf8", errors="replace")[-1000:]
    if status == "paused_cap_reached":
        status = "completed"
    if status == "running" and manifest and metadata.get("status") == "running":
        duration = time.time() - manifest.stat().st_mtime
        processed = max(0, count - metadata.get("checkpoint_total", 0))
    elif status not in ("starting", "running"):
        duration = metadata.get("elapsed_seconds", 0)
        processed = metadata.get("newly_evaluated", 0)
    else:
        duration = 0
        processed = 0
    rows = []
    if manifest and status not in ("starting", "running"):
        top = manifest.with_name("top_configs.csv")
        if top.exists():
            with top.open(encoding="utf8", newline="") as handle:
                rows = list(csv.DictReader(handle))[:10]
    config = json.loads(request.read_text())
    return {
        "id": job,
        "mode": config["mode"],
        "timeframe": config["timeframe"],
        "status": status,
        "error": error,
        "completed": count,
        "total": config["combinations"],
        "rate": processed / duration if duration > 0 else 0,
        "top": rows,
        "backend": state.get("active_backend"),
        "fallback": state.get("backend_fallback"),
        "cancel_requested": (directory / "cancel").exists(),
    }


@router.post("/{job}/resume")
def resume(job: UUID):
    directory = job_dir(job)
    with launch_lock:
        state = status(job)
        if state["status"] not in ("failed", "interrupted"):
            raise HTTPException(409, "Resume requires an interrupted or failed run")
        payload = Search.model_validate_json((directory / "request.json").read_text())
        manifest = next(directory.glob("results/*/*/run_metadata.json"), None)
        checkpoint = manifest.with_name("checkpoint.json") if manifest else None
        successes = (
            json.loads(checkpoint.read_text()).get("ok_count", 0)
            if checkpoint and checkpoint.exists()
            else 0
        )
        remaining = payload.combinations - successes
        if remaining <= 0:
            raise HTTPException(409, "All requested configurations have completed")
        (directory / "cancel").unlink(missing_ok=True)
        (directory / "failed").unlink(missing_ok=True)
        launch(job, directory, payload, remaining, resume=manifest is not None)
    return {"id": job}


@router.delete("/{job}")
def cancel(job: UUID):
    (job_dir(job) / "cancel").touch()
    return {"cancel_requested": True}


@router.get("/{job}/csv")
def export(job: UUID):
    path = next(job_dir(job).glob("results/*/*/all_results.csv"), None)
    if not path:
        raise HTTPException(409, "Export becomes available after evaluation")
    return FileResponse(path, media_type="text/csv", filename=f"{job}.csv")
