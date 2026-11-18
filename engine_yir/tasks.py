"""Yir's one shape: a Job you submit, poll until terminal, then read once."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from .transport import ProviderError

RequestFn = Callable[..., dict]
EmitFn = Callable[[str], None]

TERMINAL = ("succeeded", "failed", "cancelled")
#: Yir answers a status request as soon as the Job changes, or after this many seconds.
LONG_POLL_SECONDS = "20"


def submit(request: RequestFn, path: str, body: dict, *,
           emit: EmitFn = lambda _msg: None, prefix: str = "") -> dict:
    """Create a Job; returns ``{"id": ..., "status": ...}``.

    One Idempotency-Key per submission: a retry of this same request returns the
    original Job instead of a second, separately charged one.
    """
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    record = request("POST", path, body, headers=headers)
    job_id = str(record.get("id") or "") if isinstance(record, dict) else ""
    if not job_id:
        raise ProviderError(200, "Yir accepted the request but returned no Job id")
    emit(f"{prefix} 🧾 Job {job_id} queued")
    return {"id": job_id, "status": record.get("status") or "queued"}


def await_job(request: RequestFn, job: dict, *, poll_interval: float,
              timeout: float, emit: EmitFn = lambda _msg: None, prefix: str = "") -> dict:
    """Poll the Job's status until terminal; return the whole succeeded Job."""
    job_id = str(job.get("id") or "")
    started = time.monotonic()
    last = str(job.get("status") or "")
    while True:
        if timeout and time.monotonic() - started > timeout:
            raise ProviderError(
                0,
                f"Job {job_id} did not finish within {timeout:.0f}s — it keeps "
                f"running at Yir; collect it later with GET /v1/jobs/{job_id}",
            )
        if poll_interval:
            time.sleep(poll_interval)
        record = request("GET", f"v1/jobs/{job_id}/status", params={"wait": LONG_POLL_SECONDS})
        status = str(record.get("status") or "")
        if status != last:
            last = status
            emit(f"{prefix} ⏳ Job {status}")
        if status in TERMINAL:
            break
    if status != "succeeded":
        error = record.get("error")
        detail = str(error.get("message") or "") if isinstance(error, dict) else str(error or "")
        raise ProviderError(200, f"Job {job_id} {status} — {detail}" if detail else f"Job {job_id} {status}")
    emit(f"{prefix} ✅ Job succeeded")
    return request("GET", f"v1/jobs/{job_id}")


def assets_from(record: dict) -> list[dict]:
    """The result: the first of ``result.files``, a temporary URL to download at once."""
    result = record.get("result")
    files = result.get("files") if isinstance(result, dict) else None
    url = files[0].get("url") if files and isinstance(files[0], dict) else None
    return [{"url": str(url)}] if url else []
