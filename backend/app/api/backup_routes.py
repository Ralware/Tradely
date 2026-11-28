"""HTTP surface for portable backups and database maintenance.

Restores are destructive by design, so the endpoint requires an explicit
``confirm`` flag and always creates a local safety snapshot first (unless it is a
dry run).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.backup.manager import BackupBusy, BackupError, BackupLimitExceeded
from app.services.database_maintenance import (
    duplicate_candle_report,
    snapshot_storage_stats,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])


class CreateRequest(BaseModel):
    targets: Literal["local", "git", "both"] = "local"
    force: bool = False
    reason: str = Field(default="api", max_length=120)


class PathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class RestoreRequest(PathRequest):
    overwrite: bool = False
    dry_run: bool = False
    confirm: bool = False


def _manager(request: Request) -> Any:
    manager = getattr(request.app.state, "backup_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Backup manager is unavailable")
    return manager


def _safe_backup_path(manager: Any, raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = manager.repo_root / candidate
    resolved = candidate.resolve()
    roots = [
        manager.git_dir.resolve(),
        manager.local_dir.resolve(),
        (manager.local_dir / "quarantine").resolve(),
    ]
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise HTTPException(
            status_code=400,
            detail="Backup path must live inside the configured backup directories",
        )
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Backup file not found")
    return resolved


@router.get("/status")
def backup_status(request: Request) -> dict[str, Any]:
    manager = _manager(request)
    return manager.status()


@router.post("/create")
async def create_backup(request: Request, body: CreateRequest) -> dict[str, Any]:
    manager = _manager(request)
    try:
        results = await run_in_threadpool(
            manager.create,
            force=body.force,
            targets=body.targets,
            reason=body.reason,
        )
    except BackupLimitExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except BackupBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (BackupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"results": [result.as_dict() for result in results]}


@router.post("/verify")
def verify_backup(request: Request, body: PathRequest) -> dict[str, Any]:
    manager = _manager(request)
    path = _safe_backup_path(manager, body.path)
    try:
        return manager.verify(path)
    except BackupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/restore")
async def restore_backup_endpoint(request: Request, body: RestoreRequest) -> dict[str, Any]:
    manager = _manager(request)
    path = _safe_backup_path(manager, body.path)
    if not body.dry_run and not body.confirm:
        raise HTTPException(
            status_code=428,
            detail="Restore requires confirm=true because it writes to the active database",
        )
    try:
        return await run_in_threadpool(
            manager.restore,
            path,
            overwrite=body.overwrite,
            dry_run=body.dry_run,
            create_safety=not body.dry_run,
        )
    except BackupBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BackupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/prune")
def prune_backups(request: Request) -> dict[str, Any]:
    manager = _manager(request)
    try:
        return manager.prune()
    except BackupBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/storage")
def backup_storage(request: Request) -> dict[str, Any]:
    manager = _manager(request)
    return {
        "analytics_snapshots": snapshot_storage_stats(manager.db),
        "duplicate_candles": duplicate_candle_report(manager.db),
    }
