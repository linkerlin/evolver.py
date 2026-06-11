"""Validator reporter — format and submit validation reports to the Hub.

Equivalent to Node's ``evolver/src/gep/validator/reporter.js``.

Formats sandbox results into the Hub's expected report schema and
submits them. On network failure, reports are queued locally and
retried in batches when connectivity is restored.

Report schema
-------------
```json
{
  "task_id": "...",
  "validator_node_id": "...",
  "status": "passed|failed|error|timeout",
  "score": 0..1,
  "execution_log": "...",
  "execution_time_ms": 1234,
  "sandbox_version": "..."
}
```

Queue
-----
Local queue: ``memory/validator-reports-queue.jsonl``

Retry policy
------------
* Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s max.
* Max retries: 10 per report.
* Batch size: 10 reports per submission.

Design notes
------------
* Uses ``httpx`` for HTTP calls with 15 s timeout.
* Queue is thread-safe via module-level lock.
* All writes are append-only JSONL.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

QUEUE_PATH = Path("memory") / "validator-reports-queue.jsonl"
MAX_RETRIES = 10
BATCH_SIZE = 10
BASE_BACKOFF = 1.0
MAX_BACKOFF = 60.0

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------


def _queue_path() -> Path:
    return get_workspace_root() / QUEUE_PATH


def _load_queue(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or _queue_path()
    if not p.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        entries.append(obj)
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.debug("[ValidatorReporter] Failed to load queue: %s", exc)
    return entries


def _append_to_queue(report: dict[str, Any], path: Path | None = None) -> None:
    p = path or _queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False) + "\n")


def _rewrite_queue(entries: list[dict[str, Any]], path: Path | None = None) -> None:
    p = path or _queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        tmp.replace(p)


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


def _node_id() -> str:
    return os.environ.get("EVOLVER_AGENT_ID", "unknown")


def _submit_single(report: dict[str, Any]) -> bool:
    """Submit a single report to the Hub. Returns True on success."""
    try:
        import httpx

        payload = {
            "task_id": report["task_id"],
            "validator_node_id": _node_id(),
            "status": report.get("status", "error"),
            "score": report.get("score", 0.0),
            "execution_log": report.get("execution_log", ""),
            "execution_time_ms": report.get("execution_time_ms", 0),
            "sandbox_version": report.get("sandbox_version", "unknown"),
        }
        resp = httpx.post(
            "http://127.0.0.1:19820/a2a/validator/report",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15.0,
        )
        if resp.status_code in (200, 201, 202):
            return True
        logger.debug("[ValidatorReporter] Hub returned %d", resp.status_code)
    except Exception as exc:
        logger.debug("[ValidatorReporter] Submit failed: %s", exc)
    return False


def _submit_batch(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Submit a batch of reports. Returns the list of failed reports."""
    failed: list[dict[str, Any]] = []
    for report in reports:
        if _submit_single(report):
            continue
        report["_retries"] = report.get("_retries", 0) + 1
        report["_last_attempt"] = time.time()
        failed.append(report)
    return failed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def submit_report(report: dict[str, Any]) -> bool:
    """Submit *report* to the Hub.

    On failure, queues the report for later retry.
    Returns ``True`` if the initial submission succeeded.
    """
    if _submit_single(report):
        return True

    # Queue for retry
    queued = dict(report)
    queued["_retries"] = 0
    queued["_last_attempt"] = time.time()
    _append_to_queue(queued)
    logger.info("[ValidatorReporter] Queued report for task %s", report.get("task_id", "unknown"))
    return False


def flush_queue(
    *,
    max_batch_size: int = BATCH_SIZE,
    path: Path | None = None,
) -> tuple[int, int]:
    """Attempt to submit all queued reports.

    Returns ``(submitted_count, remaining_count)``.
    """
    entries = _load_queue(path=path)
    if not entries:
        return 0, 0

    now = time.time()
    # Filter out entries that have exceeded max retries
    eligible: list[dict[str, Any]] = []
    dropped = 0
    for entry in entries:
        retries = entry.get("_retries", 0)
        if retries >= MAX_RETRIES:
            dropped += 1
            continue
        last_attempt = entry.get("_last_attempt", 0)
        backoff = min(MAX_BACKOFF, BASE_BACKOFF * (2**retries))
        if (now - last_attempt) >= backoff:
            eligible.append(entry)

    if not eligible:
        return 0, len(entries) - dropped

    submitted = 0
    remaining: list[dict[str, Any]] = []

    # Process in batches
    for i in range(0, len(eligible), max_batch_size):
        batch = eligible[i : i + max_batch_size]
        failed = _submit_batch(batch)
        submitted += len(batch) - len(failed)
        remaining.extend(failed)

    # Rebuild queue: remaining eligible + non-eligible + dropped
    non_eligible = [e for e in entries if e not in eligible and e.get("_retries", 0) < MAX_RETRIES]
    remaining.extend(non_eligible)

    _rewrite_queue(remaining, path=path)
    logger.info("[ValidatorReporter] Flushed %d/%d reports", submitted, len(entries))
    return submitted, len(remaining)
