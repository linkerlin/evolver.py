"""Unified workspace SQLite read-index in WAL mode (算子即基因 P1-4).

Consolidates scattered workspace telemetry — signal frequencies, operator/gene
dispatch & promotion hit rates, 4-way variant attribution (`helped` / `hurt` /
`noop` / `confounded`), episode lookup headers, and daily budget snapshots — into
a single stdlib ``sqlite3`` WAL database at ``~/.evolver/workspaces/<id>/index.sqlite``
(or ``$EVOLUTION_DIR/index.sqlite`` when an isolated test overrides ``EVOLUTION_DIR``).

Design invariants:
- **Pure read-index**: ``events.jsonl`` and ``episodes/`` remain the immutable
  write-once sources of truth; ``index.sqlite`` is an incremental, idempotent,
  rebuildable projection that never calls ``record_episode`` or mutates source
  ledgers.
- **Sub-millisecond incremental sync**: byte-offset cursor on ``events.jsonl``
  plus set-difference sync on ``episodes/index.json`` keeps steady-state updates
  fast and Windows-handle-safe (explicit connection close on every call).
- **Zero new environment variables**: honors the ``EVOLVER_* <= 35`` charter cap.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final[str] = "1"

_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS meta_kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signal_stats (
    signal        TEXT PRIMARY KEY,
    total_count   INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_seen_at  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS operator_stats (
    gene_id      TEXT PRIMARY KEY,
    dispatches   INTEGER NOT NULL DEFAULT 0,
    promoted     INTEGER NOT NULL DEFAULT 0,
    failed       INTEGER NOT NULL DEFAULT 0,
    helped       INTEGER NOT NULL DEFAULT 0,
    hurt         INTEGER NOT NULL DEFAULT 0,
    noop         INTEGER NOT NULL DEFAULT 0,
    confounded   INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS episode_index (
    episode_id         TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL DEFAULT '',
    event_id           TEXT NOT NULL DEFAULT '',
    gene_id            TEXT NOT NULL DEFAULT '',
    outcome_status     TEXT NOT NULL DEFAULT '',
    attribution_status TEXT NOT NULL DEFAULT '',
    wall_time_ms       INTEGER,
    recorded_at        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_episode_run_id ON episode_index(run_id);
CREATE INDEX IF NOT EXISTS idx_episode_gene_id ON episode_index(gene_id);
"""


def index_db_path(repo_root: Path | None = None, *, db_path: Path | None = None) -> Path:
    """Resolve the canonical ``index.sqlite`` path for the active workspace."""
    if db_path is not None:
        return Path(db_path).resolve()

    from evolver.gep.paths import get_evolution_dir, get_workspace_state_dir

    state_dir = get_workspace_state_dir(repo_root).resolve()
    evo_override = os.environ.get("EVOLUTION_DIR", "").strip()
    if evo_override:
        evo_dir = get_evolution_dir().resolve()
        try:
            evo_dir.relative_to(state_dir)
        except ValueError:
            # Isolated test environment overriding EVOLUTION_DIR outside state_dir
            return evo_dir / "index.sqlite"
    return state_dir / "index.sqlite"


@contextlib.contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=3.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=3000;")
        conn.executescript(_DDL)
        yield conn
        conn.commit()
    except Exception:
        with contextlib.suppress(Exception):
            conn.rollback()
        raise
    finally:
        conn.close()


def _get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta_kv WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row is not None else default


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta_kv(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _reset_tables(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM signal_stats")
    conn.execute("DELETE FROM operator_stats")
    conn.execute("DELETE FROM episode_index")
    conn.execute("DELETE FROM meta_kv")
    _set_meta(conn, "schema_version", SCHEMA_VERSION)


def _ingest_event_row(conn: sqlite3.Connection, ev: dict[str, Any]) -> None:
    if ev.get("type") not in (None, "EvolutionEvent"):
        return
    outcome = ev.get("outcome") if isinstance(ev.get("outcome"), dict) else {}
    status = str((outcome or {}).get("status") or "")
    is_ok = status == "success"
    is_fail = status in ("failed", "rejected", "error")
    ts = str(ev.get("timestamp") or "")

    raw_signals = ev.get("signals")
    if isinstance(raw_signals, list):
        seen_heads: set[str] = set()
        for item in raw_signals:
            sig = str(item or "").strip()
            if not sig:
                continue
            head = sig.split(":", 1)[0].strip()
            if not head or head in seen_heads:
                continue
            seen_heads.add(head)
            conn.execute(
                """
                INSERT INTO signal_stats(
                    signal, total_count, success_count, failure_count, last_seen_at
                )
                VALUES(?, 1, ?, ?, ?)
                ON CONFLICT(signal) DO UPDATE SET
                    total_count = signal_stats.total_count + 1,
                    success_count = signal_stats.success_count + excluded.success_count,
                    failure_count = signal_stats.failure_count + excluded.failure_count,
                    last_seen_at = CASE
                        WHEN excluded.last_seen_at != '' THEN excluded.last_seen_at
                        ELSE signal_stats.last_seen_at
                    END
                """,
                (head, 1 if is_ok else 0, 1 if is_fail else 0, ts),
            )

    gene_id = str(ev.get("gene_id") or "").strip()
    if gene_id:
        conn.execute(
            """
            INSERT INTO operator_stats(gene_id, dispatches, promoted, failed, last_used_at)
            VALUES(?, 1, ?, ?, ?)
            ON CONFLICT(gene_id) DO UPDATE SET
                dispatches = operator_stats.dispatches + 1,
                promoted = operator_stats.promoted + excluded.promoted,
                failed = operator_stats.failed + excluded.failed,
                last_used_at = CASE
                    WHEN excluded.last_used_at != '' THEN excluded.last_used_at
                    ELSE operator_stats.last_used_at
                END
            """,
            (gene_id, 1 if is_ok else 0, 1 if is_fail else 0, ts),
        )


def _ingest_episode_body(conn: sqlite3.Connection, ep_id: str, body: dict[str, Any]) -> bool:
    exists = conn.execute(
        "SELECT 1 FROM episode_index WHERE episode_id = ?",
        (ep_id,),
    ).fetchone()
    if exists is not None:
        return False

    from evolver.gep.episode_record import attach_component_attribution

    enriched = attach_component_attribution(body)
    gates = enriched.get("gates") if isinstance(enriched.get("gates"), dict) else {}
    attr = (
        (gates or {}).get("attribution")
        if isinstance((gates or {}).get("attribution"), dict)
        else {}
    )
    attr_status = str((attr or {}).get("status") or "")
    bb = (gates or {}).get("blackbox") if isinstance((gates or {}).get("blackbox"), dict) else {}
    wall_ms_raw = (bb or {}).get("wall_time_ms")
    wall_ms = int(wall_ms_raw) if isinstance(wall_ms_raw, int | float) else None

    gene = enriched.get("gene") if isinstance(enriched.get("gene"), dict) else {}
    gene_id = str((gene or {}).get("id") or enriched.get("gene_id") or "").strip()
    outcome = enriched.get("outcome") if isinstance(enriched.get("outcome"), dict) else {}
    outcome_status = str((outcome or {}).get("status") or "")
    run_id = str(enriched.get("run_id") or "")
    event_id = str(enriched.get("event_id") or "")
    recorded_at = str(enriched.get("timestamp") or "")

    conn.execute(
        """
        INSERT INTO episode_index(
            episode_id, run_id, event_id, gene_id,
            outcome_status, attribution_status, wall_time_ms, recorded_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ep_id, run_id, event_id, gene_id, outcome_status, attr_status, wall_ms, recorded_at),
    )

    if gene_id and attr_status in ("helped", "hurt", "noop", "confounded"):
        col = attr_status
        conn.execute(
            f"""
            INSERT INTO operator_stats(gene_id, dispatches, {col}, last_used_at)
            VALUES(?, 0, 1, ?)
            ON CONFLICT(gene_id) DO UPDATE SET
                {col} = operator_stats.{col} + 1,
                last_used_at = CASE
                    WHEN excluded.last_used_at != '' THEN excluded.last_used_at
                    ELSE operator_stats.last_used_at
                END
            """,
            (gene_id, recorded_at),
        )
    return True


def sync_index_db(
    *,
    repo_root: Path | None = None,
    db_path: Path | None = None,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    """Incrementally synchronize ``events.jsonl``, ``episodes/``, and budget into SQLite."""
    from evolver.gep import episode_record
    from evolver.gep.paths import get_evolution_dir, get_gep_assets_dir

    path = index_db_path(repo_root, db_path=db_path)
    events_path = get_gep_assets_dir() / "events.jsonl"
    budget_path = get_evolution_dir() / "daily_budget.json"

    new_events = 0
    new_episodes = 0

    with _connect(path) as conn:
        journal_row = conn.execute("PRAGMA journal_mode;").fetchone()
        journal_mode = str(journal_row[0]).lower() if journal_row else "unknown"

        ver = _get_meta(conn, "schema_version", "")
        if force_rebuild or ver != SCHEMA_VERSION:
            _reset_tables(conn)

        # 1. Incremental byte-offset sync over events.jsonl
        prev_offset = int(_get_meta(conn, "events_offset", "0") or 0)
        if events_path.is_file():
            cur_size = events_path.stat().st_size
            if cur_size < prev_offset:
                # Truncated or rotated: rebuild cleanly from zero
                _reset_tables(conn)
                prev_offset = 0
            if cur_size > prev_offset:
                with events_path.open("rb") as fh:
                    fh.seek(prev_offset)
                    chunk = fh.read()
                    end_offset = fh.tell()
                for raw_line in chunk.decode("utf-8", errors="replace").splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(ev, dict):
                        _ingest_event_row(conn, ev)
                        new_events += 1
                _set_meta(conn, "events_offset", str(end_offset))
        elif prev_offset > 0:
            _reset_tables(conn)

        # 2. Incremental idempotent sync over episodes/
        with contextlib.suppress(Exception):
            ep_headers = episode_record.list_episodes()
            existing_ids = {
                str(r["episode_id"])
                for r in conn.execute("SELECT episode_id FROM episode_index").fetchall()
            }
            for item in ep_headers:
                if not isinstance(item, dict):
                    continue
                ep_id = str(item.get("id") or "").strip()
                if not ep_id or ep_id in existing_ids:
                    continue
                body = episode_record.load_episode(ep_id)
                if isinstance(body, dict) and _ingest_episode_body(conn, ep_id, body):
                    new_episodes += 1

        # 3. Snapshot daily budget state if present
        if budget_path.is_file():
            with contextlib.suppress(OSError):
                _set_meta(conn, "daily_budget", budget_path.read_text(encoding="utf-8")[:4000])

        now_iso = datetime.datetime.now(datetime.UTC).isoformat()
        _set_meta(conn, "last_sync_at", now_iso)

    return {
        "ok": True,
        "db_path": str(path),
        "journal_mode": journal_mode,
        "new_events": new_events,
        "new_episodes": new_episodes,
    }


def query_top_signals(
    limit: int = 10,
    *,
    repo_root: Path | None = None,
    db_path: Path | None = None,
    auto_sync: bool = True,
) -> list[dict[str, Any]]:
    """Return top workspace signal families ordered by frequency."""
    if auto_sync:
        with contextlib.suppress(Exception):
            sync_index_db(repo_root=repo_root, db_path=db_path)
    path = index_db_path(repo_root, db_path=db_path)
    if not path.is_file():
        return []
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT signal, total_count, success_count, failure_count, last_seen_at
            FROM signal_stats
            ORDER BY total_count DESC, signal ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    return [dict(r) for r in rows]


def query_operator_stats(
    gene_id: str | None = None,
    *,
    limit: int = 20,
    repo_root: Path | None = None,
    db_path: Path | None = None,
    auto_sync: bool = True,
) -> list[dict[str, Any]]:
    """Return per-operator dispatch, promotion hit rate, and 4-way attribution counts."""
    if auto_sync:
        with contextlib.suppress(Exception):
            sync_index_db(repo_root=repo_root, db_path=db_path)
    path = index_db_path(repo_root, db_path=db_path)
    if not path.is_file():
        return []
    with _connect(path) as conn:
        if gene_id:
            rows = conn.execute(
                """
                SELECT o.*,
                       (SELECT ROUND(AVG(e.wall_time_ms), 1)
                        FROM episode_index e
                        WHERE e.gene_id = o.gene_id AND e.wall_time_ms IS NOT NULL) AS avg_wall_ms
                FROM operator_stats o
                WHERE o.gene_id = ?
                """,
                (gene_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT o.*,
                       (SELECT ROUND(AVG(e.wall_time_ms), 1)
                        FROM episode_index e
                        WHERE e.gene_id = o.gene_id AND e.wall_time_ms IS NOT NULL) AS avg_wall_ms
                FROM operator_stats o
                ORDER BY o.helped DESC, o.promoted DESC, o.dispatches DESC, o.gene_id ASC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        disp = int(d.get("dispatches") or 0)
        prom = int(d.get("promoted") or 0)
        d["hit_rate"] = round(prom / disp, 3) if disp > 0 else None
        out.append(d)
    return out


def query_attribution_summary(
    *,
    repo_root: Path | None = None,
    db_path: Path | None = None,
    auto_sync: bool = True,
) -> dict[str, int]:
    """Aggregate 4-way episode attribution counts from ``episode_index``."""
    if auto_sync:
        with contextlib.suppress(Exception):
            sync_index_db(repo_root=repo_root, db_path=db_path)
    counts = {"helped": 0, "hurt": 0, "noop": 0, "confounded": 0, "total": 0}
    path = index_db_path(repo_root, db_path=db_path)
    if not path.is_file():
        return counts
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT attribution_status, COUNT(*) AS n
            FROM episode_index
            GROUP BY attribution_status
            """
        ).fetchall()
    for r in rows:
        n = int(r["n"] or 0)
        counts["total"] += n
        st = str(r["attribution_status"] or "")
        if st in ("helped", "hurt", "noop", "confounded"):
            counts[st] += n
    return counts


def index_summary(
    *,
    repo_root: Path | None = None,
    db_path: Path | None = None,
    auto_sync: bool = True,
) -> dict[str, Any]:
    """Compact diagnostic summary of the unified workspace SQLite index."""
    sync_res = (
        sync_index_db(repo_root=repo_root, db_path=db_path)
        if auto_sync
        else {"db_path": str(index_db_path(repo_root, db_path=db_path))}
    )
    path = index_db_path(repo_root, db_path=db_path)
    if not path.is_file():
        return {
            "ok": False,
            "db_path": str(path),
            "signals_tracked": 0,
            "operators_tracked": 0,
            "episodes_indexed": 0,
        }
    with _connect(path) as conn:
        sig_n = int(conn.execute("SELECT COUNT(*) FROM signal_stats").fetchone()[0])
        op_n = int(conn.execute("SELECT COUNT(*) FROM operator_stats").fetchone()[0])
        ep_n = int(conn.execute("SELECT COUNT(*) FROM episode_index").fetchone()[0])
        budget_raw = _get_meta(conn, "daily_budget", "")
        last_sync = _get_meta(conn, "last_sync_at", "")

    budget: dict[str, Any] | None = None
    if budget_raw:
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(budget_raw)
            if isinstance(parsed, dict):
                budget = parsed

    return {
        "ok": True,
        "db_path": str(path),
        "journal_mode": sync_res.get("journal_mode", "wal"),
        "signals_tracked": sig_n,
        "operators_tracked": op_n,
        "episodes_indexed": ep_n,
        "attribution": query_attribution_summary(
            repo_root=repo_root, db_path=path, auto_sync=False
        ),
        "daily_budget": budget,
        "last_sync_at": last_sync,
    }


__all__ = [
    "SCHEMA_VERSION",
    "index_db_path",
    "index_summary",
    "query_attribution_summary",
    "query_operator_stats",
    "query_top_signals",
    "sync_index_db",
]
