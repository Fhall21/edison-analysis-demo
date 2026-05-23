#!/usr/bin/env python3
"""Standalone Edison Data Analysis demo — FastAPI + SSE, no auth."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import time
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

from edison_extract import (
    build_runtime_config,
    data_storage_entry_id,
    trajectory_id_from_create,
)
from edison_io import fetch_storage_bytes, poll_stream, save_uploads

ROOT = Path(__file__).resolve().parent
SAMPLE_DIR = ROOT / "sample_data"
STATIC_DIR = ROOT / "static"

ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH)


def get_edison_api_key() -> str:
    """Read .env on each call so key edits apply without restarting uvicorn."""
    load_dotenv(ENV_PATH, override=True)
    return (os.environ.get("EDISON_API_KEY") or "").strip()


DEFAULT_QUERY = (
    "What are the main themes in this HR data, and which areas need immediate attention?"
)

app = FastAPI(title="Edison Analysis Demo", version="0.1.0")


def require_api_key() -> str:
    key = get_edison_api_key()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Set EDISON_API_KEY in .env (copy from .env.example)",
        )
    return key


def sse_event(event_type: str, data: dict[str, Any]) -> str:
    return f"data: {json.dumps({'type': event_type, 'data': data}, separators=(',', ':'))}\n\n"


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "edison_configured": bool(get_edison_api_key()),
        "sample_csv_count": len(list(SAMPLE_DIR.glob("*.csv"))) if SAMPLE_DIR.is_dir() else 0,
    }


@app.post("/api/analyze")
async def start_analysis(
    query: str = Form(DEFAULT_QUERY),
    use_sample: bool = Form(False),
    files: list[UploadFile] = File(default=[]),
) -> dict[str, str]:
    """Upload CSVs (or use bundled sample), create Edison ANALYSIS task."""
    from edison_client import EdisonClient, JobNames

    api_key = require_api_key()
    client = EdisonClient(api_key=api_key)
    tmp_dir: Path | None = None

    try:
        if use_sample:
            if not SAMPLE_DIR.is_dir() or not list(SAMPLE_DIR.glob("*.csv")):
                raise HTTPException(status_code=404, detail="No sample_data/*.csv found")
            csv_dir = SAMPLE_DIR
        else:
            tmp_dir, _saved = await save_uploads(files)
            csv_dir = tmp_dir

        collection_name = f"demo-{'sample' if use_sample else 'upload'}-{int(time.time())}"
        upload = await client.astore_file_content(
            name=collection_name,
            file_path=str(csv_dir),
            description="Edison analysis demo CSV collection",
            as_collection=True,
        )
        entry_id = data_storage_entry_id(upload)

        create_result = await client.acreate_task(
            {
                "name": JobNames.ANALYSIS,
                "query": query.strip() or DEFAULT_QUERY,
                "runtime_config": build_runtime_config(entry_id),
            }
        )
        task_id = trajectory_id_from_create(create_result)
        return {"task_id": task_id, "data_entry_id": entry_id}
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/api/stream/{task_id}")
async def stream_task(task_id: str) -> StreamingResponse:
    if not task_id.strip():
        raise HTTPException(status_code=422, detail="task_id required")
    api_key = require_api_key()

    async def generate() -> AsyncIterator[str]:
        async for frame in poll_stream(task_id, api_key, sse_event):
            yield frame

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/artifacts/{entry_id}")
async def download_artifact(entry_id: str) -> Response:
    from edison_client import EdisonClient

    client = EdisonClient(api_key=require_api_key())
    try:
        content_bytes, fetched_name = await fetch_storage_bytes(client, entry_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    filename = fetched_name or f"{entry_id}.bin"
    mime, _ = mimetypes.guess_type(filename)
    return Response(
        content=content_bytes,
        media_type=mime or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
