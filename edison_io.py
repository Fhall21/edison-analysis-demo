"""Edison client I/O: CSV uploads, SSE polling, artifact fetch."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from fastapi import HTTPException, UploadFile

from edison_extract import (
    extract_analysis_payload,
    extract_output_data,
    partial_notebook_cells,
    polling_message_analysis,
)

POLL_INTERVAL = 5.0
MAX_WAIT_SECONDS = 45 * 60
TERMINAL_STATUSES = frozenset({"success", "failed", "fail", "cancelled", "truncated"})
MAX_FILES = 50
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_INLINE_ARTIFACT_BYTES = 2_000_000


async def save_uploads(files: list[UploadFile]) -> tuple[Path, list[str]]:
    if not files:
        raise HTTPException(status_code=422, detail="At least one CSV file is required")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=422, detail=f"Too many files (max {MAX_FILES})")

    tmp_dir = Path(tempfile.mkdtemp(prefix="edison-demo-upload-"))
    saved: list[str] = []
    total_bytes = 0
    try:
        for uf in files:
            filename = (uf.filename or "").strip()
            if not filename:
                raise HTTPException(status_code=422, detail="Empty filename in upload")
            if not filename.lower().endswith(".csv"):
                raise HTTPException(
                    status_code=422,
                    detail=f"Only CSV files supported (got {filename!r})",
                )
            safe = os.path.basename(filename)
            target = tmp_dir / safe
            size = 0
            with target.open("wb") as fh:
                while True:
                    chunk = await uf.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise HTTPException(
                            status_code=422,
                            detail=f"File {filename} exceeds 50 MB limit",
                        )
                    total_bytes += len(chunk)
                    if total_bytes > MAX_TOTAL_BYTES:
                        raise HTTPException(
                            status_code=422,
                            detail="Upload exceeds 200 MB total limit",
                        )
                    fh.write(chunk)
            saved.append(safe)
            await uf.close()
        if not saved:
            raise HTTPException(status_code=422, detail="No CSV files saved")
        return tmp_dir, saved
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


async def fetch_storage_bytes(
    client: Any,
    entry_id: str,
    *,
    timeout: float = 120.0,
) -> tuple[bytes, str | None]:
    """Fetch raw bytes and optional filename from Edison storage."""
    fetched = await asyncio.wait_for(
        client.afetch_data_from_storage(data_storage_id=entry_id),
        timeout=timeout,
    )
    content_bytes: bytes | None = None
    filename: str | None = None
    if isinstance(fetched, (bytes, bytearray)):
        content_bytes = bytes(fetched)
    elif hasattr(fetched, "content"):
        raw = getattr(fetched, "content")
        content_bytes = bytes(raw) if raw is not None else None
        filename = getattr(fetched, "filename", None)

    if content_bytes is None:
        raise ValueError("Empty artifact content")
    return content_bytes, filename


def _apply_inline_content(
    artifact: dict[str, Any],
    content_bytes: bytes,
    mime: str,
    filename: str,
) -> None:
    artifact["size_bytes"] = len(content_bytes)
    if len(content_bytes) > MAX_INLINE_ARTIFACT_BYTES:
        return
    if mime.startswith("image/"):
        artifact["inline_data_url"] = (
            f"data:{mime};base64," + base64.b64encode(content_bytes).decode("ascii")
        )
    elif mime.startswith("text/") or filename.lower().endswith(".csv"):
        try:
            artifact["inline_text"] = content_bytes.decode("utf-8")[:200_000]
        except UnicodeDecodeError:
            pass


async def fetch_artifacts(client: Any, verbose_result: Any) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for item in extract_output_data(verbose_result):
        entry_id = item.get("entry_id")
        filename = item.get("filename") or item.get("name") or "artifact"
        mime, _ = mimetypes.guess_type(filename)
        mime = mime or "application/octet-stream"
        artifact: dict[str, Any] = {
            "entry_id": entry_id,
            "filename": filename,
            "mime_type": mime,
        }
        if not entry_id:
            artifacts.append(artifact)
            continue
        try:
            content_bytes, _ = await fetch_storage_bytes(client, entry_id)
            _apply_inline_content(artifact, content_bytes, mime, filename)
        except Exception as exc:
            artifact["error"] = str(exc)
        artifacts.append(artifact)
    return artifacts


async def poll_stream(
    task_id: str,
    api_key: str,
    sse_event: Callable[[str, dict[str, Any]], str],
) -> AsyncIterator[str]:
    from edison_client import EdisonClient

    client = EdisonClient(api_key=api_key)
    start = time.perf_counter()
    deadline = start + MAX_WAIT_SECONDS

    yield sse_event("submitted", {"task_id": task_id})

    while time.perf_counter() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed = int(time.perf_counter() - start)

        try:
            verbose = await asyncio.wait_for(
                client.aget_task(task_id, verbose=True),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            continue
        except Exception as exc:
            yield sse_event("error", {"message": f"Polling error: {exc}"})
            return

        status = (getattr(verbose, "status", None) or "unknown").lower()

        if status == "success":
            payload = extract_analysis_payload(verbose)
            try:
                payload["artifacts"] = await fetch_artifacts(client, verbose)
            except Exception as exc:
                payload["artifacts"] = []
                payload.setdefault("warnings", []).append(str(exc))
            yield sse_event("complete", payload)
            return

        if status in TERMINAL_STATUSES and status != "success":
            yield sse_event("error", {"message": f"Edison task ended: {status}"})
            return

        cells = partial_notebook_cells(verbose)
        yield sse_event(
            "polling",
            {
                "elapsed_seconds": elapsed,
                "message": polling_message_analysis(elapsed, cells),
                "notebook_cells": cells,
            },
        )

    yield sse_event("error", {"message": "Analysis timed out"})
