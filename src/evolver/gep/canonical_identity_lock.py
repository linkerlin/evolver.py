"""Process-identity-aware canonical file lock.

Equivalent to ``evolver/src/canonicalIdentityLock.js`` (v1.92.0, readable).

Uses a directory lock at ``{nodeIdFile}.tuple.lock`` with a tokenized owner
file ``owner.{token}.json`` carrying ``pid`` + optional ``processStartIdentity``
(Linux boot_id + starttime ticks / Darwin boottime + lstart) so PID reuse
cannot reclaim a live successor's lock. Abandoned locks (dead owner, aged
empty/malformed dirs) are recovered; legacy fixed ``owner.json`` fails closed.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import math
import os
import re
import secrets
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
DEFAULT_LOCK_WAIT_MS = 10
DEFAULT_LOCK_TIMEOUT_MS = 10_000
UNKNOWN_OWNER_STALE_MS = 60_000

_held_locks: dict[str, dict[str, int]] = {}
# Test hooks / timing (mirrors Node module-level mutables).
_test_hooks: dict[str, Any] = {
    "wait_ms": DEFAULT_LOCK_WAIT_MS,
    "timeout_ms": DEFAULT_LOCK_TIMEOUT_MS,
    "before_abandoned_unlink": None,
    "process_start_identity_reader": None,
}

_OWNER_NAME_RE = re.compile(r"^owner\.([a-zA-Z0-9-]+)\.json$")
_LINUX_BOOT_ID_RE = re.compile(r"^[a-f0-9-]{36}$", re.IGNORECASE)


class CanonicalIdentityLockError(OSError):
    """Lock error with a Node-compatible ``code`` attribute."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _sleep_ms(ms: float) -> None:
    if ms <= 0:
        return
    time.sleep(ms / 1000.0)


def process_is_alive(pid: int) -> bool | None:  # noqa: PLR0911
    """Return True if *pid* is alive, False if dead, None if indeterminate."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            process_query_limited = 0x1000
            handle = kernel32.OpenProcess(process_query_limited, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            # ERROR_INVALID_PARAMETER (87) typically means the PID is gone.
            err = kernel32.GetLastError()
            if err in (87, 6):  # INVALID_PARAMETER / INVALID_HANDLE
                return False
            return None
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _read_linux_process_start_identity(pid: int) -> str | None:  # noqa: PLR0911
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        stat_contents = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not _LINUX_BOOT_ID_RE.match(boot_id):
        return None
    open_paren = stat_contents.find("(")
    close_paren = stat_contents.rfind(")")
    if open_paren <= 0 or close_paren <= open_paren:
        return None
    try:
        stat_pid = int(stat_contents[:open_paren].strip())
    except ValueError:
        return None
    if stat_pid != pid:
        return None
    fields_after_comm = stat_contents[close_paren + 1 :].strip().split()
    # starttime is field 22 overall → index 19 after comm (fields 3..22).
    if len(fields_after_comm) < 20:
        return None
    start_time_ticks = fields_after_comm[19]
    if not start_time_ticks.isdigit():
        return None
    return f"linux:{boot_id}:{start_time_ticks}"


def _run_darwin_cmd(file: str, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            [file, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
            env={**os.environ, "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not isinstance(result.stdout, str):
        return None
    return result.stdout.strip()


def _read_darwin_process_start_identity(pid: int) -> str | None:
    boot_output = _run_darwin_cmd("/usr/sbin/sysctl", ["-n", "kern.boottime"])
    boot_match = re.search(r"\{\s*sec\s*=\s*(\d+)\s*,\s*usec\s*=\s*(\d+)\s*\}", boot_output or "")
    if not boot_match:
        return None
    process_output = _run_darwin_cmd(
        "/bin/ps",
        ["-o", "pid=", "-o", "lstart=", "-p", str(pid)],
    )
    process_match = re.match(r"^(\d+)\s+(.+)$", process_output or "")
    if not process_match or int(process_match.group(1)) != pid:
        return None
    started_at = re.sub(r"\s+", " ", process_match.group(2).strip())
    if not started_at:
        return None
    return f"darwin:{boot_match.group(1)}.{boot_match.group(2)}:{started_at}"


def read_process_start_identity(pid: int) -> str | None:
    """Return a platform process-start identity string, or None if unavailable."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    reader = _test_hooks.get("process_start_identity_reader")
    if callable(reader):
        value = reader(pid)
        return value if isinstance(value, str) and value else None
    if sys.platform.startswith("linux"):
        return _read_linux_process_start_identity(pid)
    if sys.platform == "darwin":
        return _read_darwin_process_start_identity(pid)
    return None


def owner_is_provably_dead(owner: dict[str, Any]) -> bool:
    alive = process_is_alive(int(owner["pid"]))
    if alive is False:
        return True
    if alive is not True or not owner.get("processStartIdentity"):
        return False
    current = read_process_start_identity(int(owner["pid"]))
    return bool(current and current != owner["processStartIdentity"])


def _read_owner(owner_file: Path) -> dict[str, Any] | None:
    try:
        parsed = json.loads(owner_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    raw_pid = parsed.get("pid")
    try:
        pid = int(raw_pid) if raw_pid is not None else -1
    except (TypeError, ValueError):
        return None
    token = parsed.get("token") if isinstance(parsed.get("token"), str) else ""
    process_start = (
        parsed.get("processStartIdentity")
        if isinstance(parsed.get("processStartIdentity"), str)
        else ""
    )
    if pid <= 0 or not token:
        return None
    return {"pid": pid, "token": token, "processStartIdentity": process_start}


def _discover_owner(lock_dir: Path) -> dict[str, Any] | None:
    try:
        names = os.listdir(lock_dir)
    except OSError:
        return None
    if len(names) != 1:
        return None
    match = _OWNER_NAME_RE.match(names[0])
    if not match:
        return None
    token = match.group(1)
    owner_file = lock_dir / names[0]
    try:
        contents = owner_file.read_bytes()
    except OSError:
        return None
    owner = _read_owner(owner_file)
    if not owner or owner["token"] != token:
        return {
            "kind": "malformed",
            "owner": None,
            "ownerFile": str(owner_file),
            "token": token,
            "contents": contents,
        }
    return {
        "kind": "valid",
        "owner": owner,
        "ownerFile": str(owner_file),
        "token": token,
        "contents": contents,
    }


def _read_lock_identity(lock_dir: Path) -> dict[str, Any] | None:
    try:
        st = lock_dir.stat()
    except FileNotFoundError:
        return None
    # Prefer high-resolution mtime when available (Python 3.12+ st_mtime_ns).
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))
    return {
        "dev": str(getattr(st, "st_dev", 0)),
        "ino": str(getattr(st, "st_ino", 0)),
        "mtimeNs": str(mtime_ns),
        "mtimeMs": float(st.st_mtime * 1000.0),
    }


def _same_owner(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    return bool(
        left
        and right
        and left.get("pid") == right.get("pid")
        and left.get("token") == right.get("token")
        and left.get("processStartIdentity") == right.get("processStartIdentity")
    )


def _same_lock_identity(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    return bool(
        left
        and right
        and left.get("dev") == right.get("dev")
        and left.get("ino") == right.get("ino")
        and left.get("mtimeNs") == right.get("mtimeNs")
    )


def _same_discovered_owner(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if not left or not right or left.get("kind") != right.get("kind"):
        return False
    if left.get("ownerFile") != right.get("ownerFile") or left.get("token") != right.get("token"):
        return False
    left_c = left.get("contents")
    right_c = right.get("contents")
    if not isinstance(left_c, (bytes, bytearray)) or not isinstance(right_c, (bytes, bytearray)):
        return False
    if bytes(left_c) != bytes(right_c):
        return False
    if left.get("kind") == "valid":
        return _same_owner(left.get("owner"), right.get("owner"))
    return True


def _current_abandoned_snapshot_matches(lock_dir: Path, expected: dict[str, Any] | None) -> bool:
    if not expected:
        return False
    identity = _read_lock_identity(lock_dir)
    if not _same_lock_identity(identity, expected.get("identity")):
        return False
    if expected.get("kind") == "empty":
        try:
            return len(os.listdir(lock_dir)) == 0
        except OSError:
            return False
    return _same_discovered_owner(_discover_owner(lock_dir), expected)


def _remove_abandoned_lock(  # noqa: PLR0911, PLR0912
    lock_dir: Path, expected: dict[str, Any]
) -> bool:
    if not _current_abandoned_snapshot_matches(lock_dir, expected):
        return False

    if expected.get("kind") == "valid":
        owner = expected.get("owner")
        if not isinstance(owner, dict) or not owner_is_provably_dead(owner):
            return False
    elif time.time() * 1000.0 - float(expected["identity"]["mtimeMs"]) <= UNKNOWN_OWNER_STALE_MS:
        return False

    hook = _test_hooks.get("before_abandoned_unlink")
    if callable(hook):
        hook({"lockDir": str(lock_dir), "expected": expected})

    if not _current_abandoned_snapshot_matches(lock_dir, expected):
        return False

    if expected.get("kind") == "empty":
        try:
            lock_dir.rmdir()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    owner_file = Path(str(expected["ownerFile"]))
    try:
        # Tokenized owner path is the deletion CAS against ABA successors.
        owner_file.unlink()
    except OSError:
        return False

    emptied_identity = _read_lock_identity(lock_dir)
    try:
        lock_dir.rmdir()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        # Restore owner marker if directory still empty & same identity.
        try:
            after = _read_lock_identity(lock_dir)
            if _same_lock_identity(after, emptied_identity) and len(os.listdir(lock_dir)) == 0:
                owner_file.write_bytes(bytes(expected["contents"]))
                with contextlib.suppress(OSError):
                    os.chmod(owner_file, PRIVATE_FILE_MODE)
        except OSError:
            pass
        return False


def _abandoned_lock_snapshot(lock_dir: Path) -> dict[str, Any] | None:  # noqa: PLR0911
    identity = _read_lock_identity(lock_dir)
    if not identity:
        return None
    discovered = _discover_owner(lock_dir)
    if not discovered:
        try:
            if len(os.listdir(lock_dir)) != 0:
                return None
        except OSError:
            return None
        if time.time() * 1000.0 - float(identity["mtimeMs"]) <= UNKNOWN_OWNER_STALE_MS:
            return None
        return {"kind": "empty", "identity": identity}
    if discovered.get("kind") == "malformed":
        if time.time() * 1000.0 - float(identity["mtimeMs"]) <= UNKNOWN_OWNER_STALE_MS:
            return None
        return {**discovered, "identity": identity}
    owner = discovered.get("owner")
    if not isinstance(owner, dict) or not owner_is_provably_dead(owner):
        return None
    return {**discovered, "identity": identity}


def _prepare_owner_file(lock_dir: Path, token: str) -> Path:
    prepared = Path(f"{lock_dir}.owner.{token}.tmp")
    process_start = read_process_start_identity(os.getpid()) or ""
    payload = {
        "pid": os.getpid(),
        "token": token,
        "processStartIdentity": process_start,
    }
    try:
        # Exclusive create (wx equivalent).
        fd = os.open(
            prepared,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            PRIVATE_FILE_MODE,
        )
        try:
            os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            with contextlib.suppress(OSError):
                os.fsync(fd)
        finally:
            os.close(fd)

        owner = _read_owner(prepared)
        if (
            not owner
            or owner["token"] != token
            or owner["pid"] != os.getpid()
            or owner["processStartIdentity"] != process_start
        ):
            raise CanonicalIdentityLockError(
                "failed to prepare canonical identity lock owner",
                code="CANONICAL_IDENTITY_LOCK_OWNER_INVALID",
            )
        return prepared
    except Exception:
        with contextlib.suppress(OSError):
            prepared.unlink(missing_ok=True)
        raise


def _release_canonical_identity_lock(lock_dir: Path, owner_file: Path, token: str) -> None:
    owner = _read_owner(owner_file)
    if not owner or owner["token"] != token:
        raise CanonicalIdentityLockError(
            "canonical identity lock ownership was lost",
            code="CANONICAL_IDENTITY_LOCK_LOST",
        )

    release_dir = Path(f"{lock_dir}.release.{token}")
    os.rename(lock_dir, release_dir)
    release_owner = release_dir / owner_file.name
    moved = _read_owner(release_owner)
    if not moved or moved["token"] != token:
        with contextlib.suppress(OSError):
            os.rename(release_dir, lock_dir)
        raise CanonicalIdentityLockError(
            "canonical identity lock ownership was lost",
            code="CANONICAL_IDENTITY_LOCK_LOST",
        )
    release_owner.unlink()
    release_dir.rmdir()


def acquire_canonical_identity_lock(node_id_file: str | Path) -> Callable[[], None]:
    """Acquire the directory lock for *node_id_file*; return a release callable."""
    canonical_file = Path(node_id_file).resolve()
    lock_dir = Path(f"{canonical_file}.tuple.lock")
    token = f"{os.getpid()}-{secrets.token_hex(12)}"
    owner_file = lock_dir / f"owner.{token}.json"
    started_at = time.time() * 1000.0
    prepared_owner: Path | None = None

    canonical_file.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(canonical_file.parent, PRIVATE_DIR_MODE)

    prepared_owner = _prepare_owner_file(lock_dir, token)
    wait_ms = float(_test_hooks["wait_ms"])
    timeout_ms = float(_test_hooks["timeout_ms"])
    try:
        while True:
            try:
                lock_dir.mkdir(mode=PRIVATE_DIR_MODE)
                assert prepared_owner is not None
                try:
                    os.rename(prepared_owner, owner_file)
                    prepared_owner = None
                except OSError:
                    with contextlib.suppress(OSError):
                        lock_dir.rmdir()
                    raise

                def release_lock(
                    _lock_dir: Path = lock_dir,
                    _owner_file: Path = owner_file,
                    _token: str = token,
                ) -> None:
                    _release_canonical_identity_lock(_lock_dir, _owner_file, _token)

                return release_lock
            except FileExistsError:
                abandoned = _abandoned_lock_snapshot(lock_dir)
                if abandoned and _remove_abandoned_lock(lock_dir, abandoned):
                    continue
                if time.time() * 1000.0 - started_at > timeout_ms:
                    raise CanonicalIdentityLockError(
                        "timed out waiting for canonical identity lock",
                        code="CANONICAL_IDENTITY_LOCK_TIMEOUT",
                    ) from None
                _sleep_ms(wait_ms)
            except OSError as exc:
                # Windows may raise PermissionError / WinError for EEXIST races.
                if getattr(exc, "errno", None) in (getattr(os, "EEXIST", 17), 17) or (
                    getattr(exc, "winerror", None) == 183  # ERROR_ALREADY_EXISTS
                ):
                    abandoned = _abandoned_lock_snapshot(lock_dir)
                    if abandoned and _remove_abandoned_lock(lock_dir, abandoned):
                        continue
                    if time.time() * 1000.0 - started_at > timeout_ms:
                        raise CanonicalIdentityLockError(
                            "timed out waiting for canonical identity lock",
                            code="CANONICAL_IDENTITY_LOCK_TIMEOUT",
                        ) from None
                    _sleep_ms(wait_ms)
                    continue
                raise
    finally:
        if prepared_owner is not None:
            with contextlib.suppress(OSError):
                prepared_owner.unlink(missing_ok=True)


def with_canonical_identity_lock[T](node_id_file: str | Path, operation: Callable[[], T]) -> T:
    """Run *operation* under the shared lock; nested same-process calls reenter."""
    if not callable(operation):
        raise TypeError("operation must be a function")
    key = str(Path(node_id_file).resolve())
    held = _held_locks.get(key)
    if held is not None:
        held["depth"] += 1
        try:
            return operation()
        finally:
            held["depth"] -= 1

    release = acquire_canonical_identity_lock(key)
    _held_locks[key] = {"depth": 1}
    try:
        return operation()
    finally:
        _held_locks.pop(key, None)
        release()


# --- Test hooks (mirror Node private APIs) -----------------------------------


def _set_canonical_identity_lock_timing_for_testing(
    options: dict[str, Any] | None = None,
) -> None:
    next_opts = options or {}
    wait = next_opts.get("waitMs")
    timeout = next_opts.get("timeoutMs")
    _test_hooks["wait_ms"] = (
        float(wait)
        if isinstance(wait, (int, float)) and wait >= 0 and math.isfinite(float(wait))
        else DEFAULT_LOCK_WAIT_MS
    )
    _test_hooks["timeout_ms"] = (
        float(timeout)
        if isinstance(timeout, (int, float)) and timeout >= 0 and math.isfinite(float(timeout))
        else DEFAULT_LOCK_TIMEOUT_MS
    )


def _reset_canonical_identity_lock_timing_for_testing() -> None:
    _test_hooks["wait_ms"] = DEFAULT_LOCK_WAIT_MS
    _test_hooks["timeout_ms"] = DEFAULT_LOCK_TIMEOUT_MS


def _set_before_abandoned_lock_unlink_for_testing(
    callback: Callable[[dict[str, Any]], None] | None,
) -> None:
    _test_hooks["before_abandoned_unlink"] = callback if callable(callback) else None


def _set_process_start_identity_reader_for_testing(
    callback: Callable[[int], str | None] | None,
) -> None:
    _test_hooks["process_start_identity_reader"] = callback if callable(callback) else None


__all__ = [
    "CanonicalIdentityLockError",
    "_reset_canonical_identity_lock_timing_for_testing",
    "_set_before_abandoned_lock_unlink_for_testing",
    "_set_canonical_identity_lock_timing_for_testing",
    "_set_process_start_identity_reader_for_testing",
    "acquire_canonical_identity_lock",
    "owner_is_provably_dead",
    "process_is_alive",
    "read_process_start_identity",
    "with_canonical_identity_lock",
]
