"""Local mailbox store — JSONL-backed message persistence.

Equivalent to ``evolver/src/proxy/mailbox/store.js``.
Manages inbound/outbound message queues, cursors, and node state
for the A2A proxy layer.

Design notes (Pythonic)
-----------------------
* Messages are typed ``@dataclass`` instances with Pydantic-style validation.
* Persistence uses **append-only JSONL** (``messages.jsonl``) plus an atomic
  **state snapshot** (``state.json``).
* Writes are serialised with a ``threading.Lock`` — the proxy runs as a
  single process (uvicorn) so an in-process lock is sufficient.
* UUID v7 is implemented inline (no extra dependency) — time-ordered,
  sortable, 48-bit timestamp + version + variant + random.
* ``compact()`` rewrites the JSONL as a clean snapshot to bound file growth.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CHANNEL: str = "evomap-hub"
SCHEMA_VERSION: str = "1.0.0"
PROXY_PROTOCOL_VERSION: str = "1.0.0"

_PRIORITY_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Message:
    id: str
    channel: str = DEFAULT_CHANNEL
    direction: Literal["outbound", "inbound"] = "outbound"
    type: str = ""
    status: Literal["pending", "synced", "delivered", "failed", "rejected"] = "pending"
    payload: dict[str, Any] = field(default_factory=dict)
    priority: Literal["high", "normal", "low"] = "normal"
    ref_id: str | None = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    synced_at: int | None = None
    expires_at: int | None = None
    retry_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        # Filter to known fields to avoid unexpected keys poisoning the store
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# UUID v7 (lightweight, no extra deps)
# ---------------------------------------------------------------------------


def _generate_uuidv7() -> str:
    """Generate an RFC-9562 UUID v7 string.

    High 48 bits = Unix timestamp ms, version = 0b0111, variant = 10,
    remaining 62 bits random.
    """
    ts = int(time.time() * 1000)
    # 16 bytes: [ts>>40, ts>>32, ts>>24, ts>>16, ts>>8, ts, ver+rand, ...]
    rand = random.getrandbits(74)
    b = bytearray(16)
    b[0] = (ts >> 40) & 0xFF
    b[1] = (ts >> 32) & 0xFF
    b[2] = (ts >> 24) & 0xFF
    b[3] = (ts >> 16) & 0xFF
    b[4] = (ts >> 8) & 0xFF
    b[5] = ts & 0xFF
    b[6] = 0x70 | ((rand >> 68) & 0x0F)  # version 7
    b[7] = ((rand >> 60) & 0xFF)
    b[8] = 0x80 | ((rand >> 54) & 0x3F)  # variant 10
    b[9] = (rand >> 46) & 0xFF
    b[10] = (rand >> 38) & 0xFF
    b[11] = (rand >> 30) & 0xFF
    b[12] = (rand >> 22) & 0xFF
    b[13] = (rand >> 14) & 0xFF
    b[14] = (rand >> 6) & 0xFF
    b[15] = rand & 0xFF
    return (
        f"{b[0]:02x}{b[1]:02x}{b[2]:02x}{b[3]:02x}-"
        f"{b[4]:02x}{b[5]:02x}-"
        f"{b[6]:02x}{b[7]:02x}-"
        f"{b[8]:02x}{b[9]:02x}-"
        f"{b[10]:02x}{b[11]:02x}{b[12]:02x}{b[13]:02x}{b[14]:02x}{b[15]:02x}"
    )


# ---------------------------------------------------------------------------
# MailboxStore
# ---------------------------------------------------------------------------


class MailboxStore:
    """Thread-safe local mailbox backed by JSONL + JSON state snapshot."""

    def __init__(self, data_dir: Path | str) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._msg_path = self._dir / "messages.jsonl"
        self._state_path = self._dir / "state.json"
        self._lock = threading.Lock()

        # In-memory indexes
        self._messages: dict[str, Message] = {}
        self._outbound: list[str] = []  # ids of non-terminal outbound
        self._inbound: list[str] = []   # ids of non-terminal inbound

        self._load_state()
        self._rebuild_index()

    # ------------------------------------------------------------------
    # Internal persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        if self._state_path.exists():
            try:
                with open(self._state_path, "r", encoding="utf-8") as f:
                    self._state: dict[str, Any] = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._state = {"schema_version": SCHEMA_VERSION}
        else:
            self._state = {"schema_version": SCHEMA_VERSION}

    def _save_state(self) -> None:
        tmp = self._state_path.with_suffix(f".tmp-{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            tmp.rename(self._state_path)
        except OSError:
            # Windows: target may exist; remove then rename
            if self._state_path.exists():
                self._state_path.unlink()
            tmp.rename(self._state_path)

    def _append_jsonl(self, record: dict[str, Any]) -> None:
        with open(self._msg_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _rebuild_index(self) -> None:
        """Replay messages.jsonl to rebuild in-memory indexes."""
        self._messages.clear()
        self._outbound.clear()
        self._inbound.clear()
        if not self._msg_path.exists():
            return
        with open(self._msg_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("_op") == "update":
                    # Re-apply incremental update
                    msg_id = record.get("id")
                    if msg_id and msg_id in self._messages:
                        existing = self._messages[msg_id]
                        for k, v in record.get("fields", {}).items():
                            if hasattr(existing, k):
                                setattr(existing, k, v)
                else:
                    msg = Message.from_dict(record)
                    self._messages[msg.id] = msg

        # Rebuild queues from final state
        terminal = {"synced", "delivered", "failed", "rejected"}
        for msg in self._messages.values():
            if msg.status not in terminal:
                if msg.direction == "outbound":
                    self._outbound.append(msg.id)
                else:
                    self._inbound.append(msg.id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(
        self,
        *,
        type: str,
        payload: dict[str, Any],
        channel: str = DEFAULT_CHANNEL,
        priority: Literal["high", "normal", "low"] = "normal",
        ref_id: str | None = None,
        expires_at: int | None = None,
    ) -> dict[str, Any]:
        """Create an outbound message."""
        msg = Message(
            id=_generate_uuidv7(),
            channel=channel,
            direction="outbound",
            type=type,
            payload=payload,
            priority=priority,
            ref_id=ref_id,
            expires_at=expires_at,
        )
        with self._lock:
            self._messages[msg.id] = msg
            self._outbound.append(msg.id)
            self._append_jsonl(msg.to_dict())
        return {"message_id": msg.id, "status": msg.status}

    def write_inbound(
        self,
        *,
        id: str,
        type: str,
        payload: dict[str, Any],
        channel: str = DEFAULT_CHANNEL,
        priority: Literal["high", "normal", "low"] = "normal",
        ref_id: str | None = None,
        expires_at: int | None = None,
    ) -> str:
        """Create an inbound message (idempotent)."""
        with self._lock:
            if id in self._messages:
                return id
            msg = Message(
                id=id,
                channel=channel,
                direction="inbound",
                type=type,
                payload=payload,
                priority=priority,
                ref_id=ref_id,
                expires_at=expires_at,
            )
            self._messages[msg.id] = msg
            self._inbound.append(msg.id)
            self._append_jsonl(msg.to_dict())
        return id

    def write_inbound_batch(self, messages: list[dict[str, Any]]) -> list[str]:
        """Batch inbound write."""
        ids: list[str] = []
        with self._lock:
            for data in messages:
                msg_id = data.get("id")
                if msg_id is None or msg_id in self._messages:
                    ids.append(msg_id or "")
                    continue
                msg = Message.from_dict({**data, "direction": "inbound"})
                self._messages[msg.id] = msg
                self._inbound.append(msg.id)
                self._append_jsonl(msg.to_dict())
                ids.append(msg.id)
        return ids

    def get_by_id(self, msg_id: str) -> Message | None:
        return self._messages.get(msg_id)

    def poll(
        self,
        channel: str | None = None,
        type: str | None = None,
        limit: int = 100,
    ) -> list[Message]:
        """Poll inbound messages (newest first)."""
        result: list[Message] = []
        for msg_id in reversed(self._inbound):
            msg = self._messages.get(msg_id)
            if msg is None:
                continue
            if channel is not None and msg.channel != channel:
                continue
            if type is not None and msg.type != type:
                continue
            result.append(msg)
            if len(result) >= limit:
                break
        return result

    def poll_outbound(
        self,
        channel: str | None = None,
        limit: int = 50,
    ) -> list[Message]:
        """Poll pending outbound messages, sorted by priority then FIFO."""
        candidates: list[Message] = []
        for msg_id in self._outbound:
            msg = self._messages.get(msg_id)
            if msg is None or msg.status != "pending":
                continue
            if channel is not None and msg.channel != channel:
                continue
            candidates.append(msg)
        candidates.sort(key=lambda m: (_PRIORITY_RANK.get(m.priority, 1), m.created_at))
        return candidates[:limit]

    def ack(self, message_ids: list[str]) -> int:
        """Mark inbound messages as delivered."""
        count = 0
        with self._lock:
            for msg_id in message_ids:
                msg = self._messages.get(msg_id)
                if msg is None or msg.direction != "inbound":
                    continue
                msg.status = "delivered"
                msg.synced_at = int(time.time() * 1000)
                if msg_id in self._inbound:
                    self._inbound.remove(msg_id)
                self._append_jsonl({"_op": "update", "id": msg_id, "fields": {"status": "delivered", "synced_at": msg.synced_at}})
                count += 1
        return count

    def update_status(
        self,
        msg_id: str,
        status: str,
        *,
        error: str | None = None,
        synced_at: int | None = None,
    ) -> bool:
        with self._lock:
            msg = self._messages.get(msg_id)
            if msg is None:
                return False
            msg.status = status
            if error is not None:
                msg.error = error
            if synced_at is not None:
                msg.synced_at = synced_at
            fields: dict[str, Any] = {"status": status}
            if error is not None:
                fields["error"] = error
            if synced_at is not None:
                fields["synced_at"] = synced_at
            self._append_jsonl({"_op": "update", "id": msg_id, "fields": fields})
            # Remove from active queue if terminal
            if status in {"synced", "delivered", "failed", "rejected"}:
                if msg.direction == "outbound" and msg_id in self._outbound:
                    self._outbound.remove(msg_id)
                if msg.direction == "inbound" and msg_id in self._inbound:
                    self._inbound.remove(msg_id)
        return True

    def increment_retry(self, msg_id: str, error: str | None = None) -> None:
        with self._lock:
            msg = self._messages.get(msg_id)
            if msg is None:
                return
            msg.retry_count += 1
            if error:
                msg.error = error
            self._append_jsonl({"_op": "update", "id": msg_id, "fields": {"retry_count": msg.retry_count, "error": msg.error}})

    def list(
        self,
        *,
        type: str | None = None,
        direction: Literal["outbound", "inbound"] | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        items = list(self._messages.values())
        if direction:
            items = [m for m in items if m.direction == direction]
        if type:
            items = [m for m in items if m.type == type]
        if status:
            items = [m for m in items if m.status == status]
        items.sort(key=lambda m: m.created_at, reverse=True)
        return items[offset : offset + limit]

    def count_pending(self, *, direction: Literal["outbound", "inbound"] | None = None) -> int:
        terminal = {"synced", "delivered", "failed", "rejected"}
        count = 0
        for msg in self._messages.values():
            if msg.status in terminal:
                continue
            if direction and msg.direction != direction:
                continue
            count += 1
        return count

    # ------------------------------------------------------------------
    # Cursors & generic state
    # ------------------------------------------------------------------

    def get_cursor(self, key: str) -> str | None:
        return self._state.get("cursors", {}).get(key)

    def set_cursor(self, key: str, value: str) -> None:
        cursors = self._state.setdefault("cursors", {})
        cursors[key] = value
        self._save_state()

    def get_state(self, key: str) -> Any | None:
        return self._state.get(key)

    def set_state(self, key: str, value: Any) -> None:
        self._state[key] = value
        self._save_state()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def compact(self) -> None:
        """Rewrite messages.jsonl as a clean snapshot."""
        with self._lock:
            tmp = self._msg_path.with_suffix(f".tmp-{os.getpid()}")
            with open(tmp, "w", encoding="utf-8") as f:
                for msg in self._messages.values():
                    f.write(json.dumps(msg.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            try:
                tmp.rename(self._msg_path)
            except OSError:
                if self._msg_path.exists():
                    self._msg_path.unlink()
                tmp.rename(self._msg_path)

    def close(self) -> None:
        """No-op for API compatibility."""
        pass
