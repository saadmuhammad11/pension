"""In-process registry for scan-reading runs, so the UI can show progress.

Reading a case is two vision-model calls per page. On a real thirteen-page file that is
well over a minute, and the old endpoint held the request open for all of it: the officer
clicked "Read and open" and got a dead screen with no way to tell a slow model from a hung
one. So the request now starts a job and returns at once, the pipeline runs on a worker
thread, and the UI polls this registry.

Deliberately in-process and in-memory, like `CaseRepository`'s live side: a job is only
interesting while the page that started it is open, and it is meaningless after a restart.
Nothing here is persisted, and nothing here is a queue — if this ever needs to survive a
restart or spread across workers, it wants a real broker, not a bigger dict.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# How long a finished job stays readable. The UI polls every second or so and collects its
# result immediately; this is slack for a reload or a slow network, not a cache.
TTL_SECONDS = 15 * 60


@dataclass
class Job:
    id: str
    state: str = "running"              # running | done | error
    stage: str = "queued"
    message: str = "Starting"
    done: int = 0                       # pages finished
    total: int = 0                      # pages in the upload
    page: Optional[int] = None          # page currently under the model
    artefact: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    result: Optional[dict] = None       # on success: whatever the runner returned
    detail: Optional[str] = None        # on failure: the message the officer sees
    status_code: int = 500              # on failure: what the sync endpoint would have sent

    def view(self) -> dict:
        """The JSON the UI polls. Elapsed is served rather than derived in the browser so a
        clock skew between machines cannot show a negative timer."""
        end = self.finished_at or time.time()
        return {
            "jobId": self.id, "state": self.state, "stage": self.stage,
            "message": self.message, "done": self.done, "total": self.total,
            "page": self.page, "artefact": self.artefact,
            "elapsed": round(end - self.started_at, 1),
            **({"result": self.result} if self.result is not None else {}),
            **({"detail": self.detail, "statusCode": self.status_code}
               if self.detail is not None else {}),
        }


class JobRegistry:
    def __init__(self, ttl_seconds: float = TTL_SECONDS):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    # ── reading ──────────────────────────────────────────────────────────────
    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    # ── running ──────────────────────────────────────────────────────────────
    def start(self, runner: Callable[[Callable[[dict], None]], Any], *,
              total: int = 0) -> Job:
        """Run `runner` on a worker thread and return the job immediately.

        `runner` is handed a progress callback to pass down to the pipeline. Whatever it
        returns becomes the job's result; whatever it raises becomes the job's error, with
        NotImplementedError mapped to 503 — that is the "no vision model configured" case,
        and it is a service-availability answer, not a bug.
        """
        self._sweep()
        job = Job(id="job-" + uuid.uuid4().hex[:10], total=total)
        with self._lock:
            self._jobs[job.id] = job

        def report(ev: dict) -> None:
            with self._lock:
                job.stage = ev.get("stage", job.stage)
                job.message = ev.get("message", job.message)
                job.total = ev.get("total", job.total) or job.total
                if ev.get("done") is not None:
                    job.done = ev["done"]
                job.page = ev.get("page")
                if ev.get("artefact"):
                    job.artefact = ev["artefact"]

        def work() -> None:
            try:
                result = runner(report)
            except NotImplementedError as e:
                self._fail(job, "Reading the scans needs the vision model. Set GPF_VLLM_URLS "
                                "to the DGX Spark's vLLM server. (" + str(e) + ")", 503)
            except Exception as e:                      # noqa: BLE001 - surfaced to the officer
                self._fail(job, f"{type(e).__name__}: {e}", 500)
            else:
                with self._lock:
                    job.state, job.stage = "done", "done"
                    job.message = "Read"
                    job.result = result
                    job.page = None
                    job.finished_at = time.time()

        threading.Thread(target=work, name=f"reading-{job.id}", daemon=True).start()
        return job

    def _fail(self, job: Job, detail: str, status_code: int) -> None:
        with self._lock:
            job.state, job.stage = "error", "error"
            job.message = detail
            job.detail = detail
            job.status_code = status_code
            job.page = None
            job.finished_at = time.time()

    # ── housekeeping ─────────────────────────────────────────────────────────
    def _sweep(self) -> None:
        """Drop finished jobs past their TTL. Called on start rather than on a timer, so an
        idle process holds no threads of its own."""
        cutoff = time.time() - self._ttl
        with self._lock:
            for jid in [j.id for j in self._jobs.values()
                        if j.finished_at and j.finished_at < cutoff]:
                del self._jobs[jid]
