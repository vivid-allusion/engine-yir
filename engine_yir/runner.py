"""Bounded parallel batches: at most ``concurrency`` jobs in flight.

Split out of ``engine.py`` so the sequential path stays readable. The contract
the Generator relies on is unchanged: results come back in input order, one
entry per saved file or per failure, exactly as a one-at-a-time run.

Two rules that are not obvious:

* a queued item is checked against the stop flag **before** it calls the
  provider, so a fatal error stops the batch instead of finishing it;
* the stop flag is set under a lock — the workers are threads, and "check then
  set" on a plain attribute is a race that loses work.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from . import errorlog
from .datatypes import InputFile, OutputFile


def run_batch(engine, inputs: list[InputFile]) -> list[OutputFile]:
    """Run every input through ``engine`` with the profile's concurrency."""
    workers = max(1, int(engine._concurrency))
    if workers == 1 or len(inputs) <= 1:
        return engine._run_serial(inputs)

    stop = threading.Event()
    lock = threading.Lock()
    results: list[list[OutputFile]] = [[] for _ in inputs]

    def failed(index: int, item: InputFile, message: str, stage: str,
               error: Exception | None = None) -> list[OutputFile]:
        rel_dir = str(item.metadata.get("relative_dir", "") or "")
        dest_dir = engine._output_dir / rel_dir if rel_dir else engine._output_dir
        log = errorlog.write_error_log(
            dest_dir=dest_dir, stem=item.path.stem, index=index, item=item, current=index + 1,
            total=len(inputs), profile=engine._profile, api_key=engine._resolve_api_key(),
            expected=None, stage=stage, error_msg=message, error=error)
        media_type = engine._media_type()
        return [OutputFile(source_path=item.path, status="error", error_msg=message,
                           media_type=media_type, metadata={"error_log": str(log)} if log else {})]

    def work(index: int, item: InputFile) -> None:
        if stop.is_set():
            results[index] = failed(
                index, item, "Skipped: the batch stopped after an unrecoverable error", "skipped")
            return
        try:
            results[index] = engine._run_one(index, len(inputs), item, stop)
        except Exception as exc:  # noqa: BLE001 - a worker must never vanish
            results[index] = failed(index, item, str(exc), "unexpected error", exc)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, index, item) for index, item in enumerate(inputs)]
        for future in futures:
            future.result()

    flat: list[OutputFile] = []
    for group in results:
        flat.extend(group)
    return flat


__all__ = ["run_batch"]
