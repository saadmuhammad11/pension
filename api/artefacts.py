"""Reading a run's artefacts for an HTTP answer: the report, a page image, the event stream.

Factored so the multi-department router (``api.v2``) can serve exactly what the old portal's
routes serve, after its own ownership check, without a second copy of the logic. The old
routes in ``api.server`` keep their bodies; a later tidy can point them here.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from api.runs import RUNS, Run, adopt_from_disk


def get_run(run_id: str) -> Run:
    """The live run, or one rebuilt from its artefacts; 404 only when the disk has nothing."""
    run = RUNS.get(run_id)
    if run is None:
        run = adopt_from_disk(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    return run


def report(run: Run) -> Any:
    """The case report with the officers' checklist actions laid over it, or 409 until it exists."""
    path = run.run_dir / "case_report.json"
    if not path.exists():
        return JSONResponse({"error": "report not ready", "state": run.state}, status_code=409)
    from api.checklist_actions import apply
    return apply(json.loads(path.read_text()), run.run_dir)


def report_dict(run_dir: Path) -> dict | None:
    """The raw report as a dict, or None where the run has not written one (or wrote junk)."""
    path = Path(run_dir) / "case_report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def status(run: Run) -> dict:
    return {"run_id": run.run_id, "state": run.state, "error": run.error,
            "events": len(run.events), "started_at": run.started_at,
            "finished_at": run.finished_at}


def page_image(run: Run, page: int) -> FileResponse:
    manifest_path = run.run_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(404, "this run has no rendered pages")
    for p in json.loads(manifest_path.read_text()).get("pages", []):
        if int(p.get("page", 0)) == page:
            img = run.run_dir / p["image_path"]
            if img.is_file():
                return FileResponse(img, media_type="image/png")
            break
    raise HTTPException(404, f"no rendered image for page {page} of this run")


def signature_image(run: Run, name: str) -> FileResponse:
    if not re.fullmatch(r"[A-Z_]+-p\d+\.jpg", name):
        raise HTTPException(404, "no such signature")
    path = run.run_dir / "signatures" / name
    if not path.exists():
        raise HTTPException(404, "no such signature")
    return FileResponse(path, media_type="image/jpeg")


def bundle(run: Run) -> Any:
    path = run.run_dir / "bundle.json"
    if not path.exists():
        raise HTTPException(404, "this case was submitted as a single PDF, not as a bundle")
    return json.loads(path.read_text(encoding="utf-8"))


def event_stream(run: Run, request: Request) -> EventSourceResponse:
    """Stage events: the backlog first, then live, until the run's ``end`` event."""
    async def stream():
        sent = 0
        while True:
            if await request.is_disconnected():
                return
            with run.lock:
                backlog = run.events[sent:]
            for ev in backlog:
                sent += 1
                yield {"data": json.dumps(ev, ensure_ascii=False)}
                if ev["stage"] == "end":
                    return
            await asyncio.sleep(0.4)

    return EventSourceResponse(stream())
