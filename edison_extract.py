"""Edison ANALYSIS response extractors (standalone copy for demo app).

Adapted from ConsultantPlatform sprint-17 scripts and research router.
No imports from the main application.
"""

from __future__ import annotations

from typing import Any

_MAX_CELL_OUTPUT_CHARS = 4000
_MAX_INLINE_IMAGE_BYTES = 1_500_000


def trajectory_id_from_create(create_result: Any) -> str:
    if isinstance(create_result, str):
        return create_result
    task_id = getattr(create_result, "task_id", None)
    if task_id is not None:
        return str(task_id)
    trajectory_id = getattr(create_result, "trajectory_id", None)
    if trajectory_id is not None:
        return str(trajectory_id)
    if isinstance(create_result, dict):
        for key in ("trajectory_id", "task_id", "id"):
            if create_result.get(key):
                return str(create_result[key])
    raise ValueError(
        f"Could not resolve trajectory id from create_task response: {create_result!r}"
    )


def data_storage_entry_id(upload: object) -> str:
    if hasattr(upload, "data_storage"):
        entry = getattr(upload, "data_storage")
        entry_id = getattr(entry, "id", None)
        if entry_id is not None:
            return str(entry_id)
    if isinstance(upload, dict):
        if upload.get("entry_id"):
            return str(upload["entry_id"])
        data_storage = upload.get("data_storage") or {}
        if isinstance(data_storage, dict) and data_storage.get("id"):
            return str(data_storage["id"])
    raise ValueError(f"Could not resolve entry id from upload response: {upload!r}")


def build_runtime_config(entry_id: str) -> dict[str, Any]:
    return {
        "environment_config": {
            "data_storage_uris": [f"data_entry:{entry_id}"],
        }
    }


def extract_nb_cells(verbose_result: Any) -> list[dict[str, Any]] | None:
    try:
        return verbose_result.environment_frame["state"]["state"]["nb_state"]["cells"]
    except (AttributeError, KeyError, TypeError):
        return None


def normalise_outputs(raw_outputs: list[Any]) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for out in raw_outputs or []:
        if not isinstance(out, dict):
            continue
        kind = out.get("output_type") or ""
        entry: dict[str, Any] = {"output_type": kind}
        if kind == "stream":
            text = out.get("text", "")
            if isinstance(text, list):
                text = "".join(text)
            entry["name"] = out.get("name") or "stdout"
            entry["text"] = (str(text) or "")[:_MAX_CELL_OUTPUT_CHARS]
        elif kind in {"execute_result", "display_data"}:
            data = out.get("data") or {}
            if not isinstance(data, dict):
                continue
            payload: dict[str, Any] = {}
            text_val = data.get("text/plain")
            if isinstance(text_val, list):
                text_val = "".join(text_val)
            if text_val:
                payload["text/plain"] = str(text_val)[:_MAX_CELL_OUTPUT_CHARS]
            html_val = data.get("text/html")
            if isinstance(html_val, list):
                html_val = "".join(html_val)
            if html_val:
                payload["text/html"] = str(html_val)[:_MAX_CELL_OUTPUT_CHARS]
            for img_mime in ("image/png", "image/jpeg"):
                img_val = data.get(img_mime)
                if isinstance(img_val, list):
                    img_val = "".join(img_val)
                if img_val and isinstance(img_val, str):
                    if len(img_val) <= _MAX_INLINE_IMAGE_BYTES * 2:
                        payload[img_mime] = img_val
                    break
            if payload:
                entry["data"] = payload
            else:
                continue
        elif kind == "error":
            entry["ename"] = out.get("ename", "Error")
            entry["evalue"] = str(out.get("evalue", ""))[:_MAX_CELL_OUTPUT_CHARS]
            tb = out.get("traceback")
            if isinstance(tb, list):
                entry["traceback"] = "\n".join(str(line) for line in tb)[
                    :_MAX_CELL_OUTPUT_CHARS
                ]
        else:
            continue
        normalised.append(entry)
    return normalised


def normalise_notebook_cells(raw_cells: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for idx, cell in enumerate(raw_cells or []):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        outputs = normalise_outputs(cell.get("outputs") or [])
        meta = cell.get("metadata") or {}
        display_text = ""
        if isinstance(meta, dict):
            display_text = str(meta.get("display_text") or meta.get("display") or "")
        has_error = any(o.get("output_type") == "error" for o in outputs)
        result.append(
            {
                "index": idx,
                "execution_count": cell.get("execution_count"),
                "code": str(source or ""),
                "display_text": display_text,
                "outputs": outputs,
                "status": "error" if has_error else "ok",
            }
        )
    return result


def extract_analysis_answer(verbose_result: Any) -> str:
    try:
        answer = verbose_result.environment_frame["state"]["state"]["answer"]
        if isinstance(answer, str) and answer.strip():
            return answer
    except (AttributeError, KeyError, TypeError):
        pass
    try:
        agent_state = verbose_result.agent_state or []
        if agent_state:
            messages = agent_state[-1]["state"]["transition"]["agent_state"]["messages"]
            for msg in reversed(messages):
                if not isinstance(msg, dict):
                    continue
                if msg.get("role") == "assistant" and msg.get("content"):
                    content = msg["content"]
                    if isinstance(content, str) and content.strip():
                        return content
                    if isinstance(content, list):
                        joined = " ".join(
                            c.get("text", "") for c in content if isinstance(c, dict)
                        ).strip()
                        if joined:
                            return joined
    except (AttributeError, KeyError, TypeError, IndexError):
        pass
    return ""


def extract_output_data(verbose_result: Any) -> list[dict[str, Any]]:
    try:
        info = verbose_result.environment_frame["state"]["info"]
        out = info.get("output_data") or []
        if isinstance(out, list):
            return [item for item in out if isinstance(item, dict)]
    except (AttributeError, KeyError, TypeError):
        pass
    return []


def extract_analysis_payload(verbose_result: Any) -> dict[str, Any]:
    raw_cells = extract_nb_cells(verbose_result) or []
    cells = normalise_notebook_cells(raw_cells)
    answer = extract_analysis_answer(verbose_result)
    output_data = extract_output_data(verbose_result)
    error_cells = sum(1 for c in cells if c.get("status") == "error")
    return {
        "answer": answer,
        "notebook_cells": cells,
        "output_data": output_data,
        "stats": {
            "cell_count": len(cells),
            "error_cell_count": error_cells,
            "artifact_count": len(output_data),
        },
    }


def partial_notebook_cells(verbose_result: Any) -> list[dict[str, Any]]:
    return normalise_notebook_cells(extract_nb_cells(verbose_result) or [])


def polling_message_analysis(elapsed: int, cells: list[dict[str, Any]]) -> str:
    if not cells:
        return (
            "Submitting to Edison Analysis…"
            if elapsed < 30
            else "Edison is provisioning the notebook kernel…"
        )
    last = cells[-1]
    label = last.get("display_text") or "Running notebook cell"
    return f"Cell #{last.get('execution_count', '?')}: {label}"
