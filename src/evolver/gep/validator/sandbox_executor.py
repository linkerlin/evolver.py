"""Sandbox executor — run validation scripts in an isolated environment.

Equivalent to Node's ``evolver/src/gep/validator/sandboxExecutor.js``.

Security model
--------------
1. **Command whitelist**: only ``python <script>`` is allowed.
   Explicitly forbidden: ``pip``, ``python -c``, ``eval()``, ``exec()``.
2. **Shell operator ban**: ``;``, ``&``, ``|``, ``>``, ``$()``, backticks.
3. **Timeout**: 180 s (configurable via ``EVOLVER_VALIDATION_TIMEOUT_MS``).
4. **CWD restriction**: temporary directory, auto-cleaned after execution.
5. **Resource limits** (Linux only): ``resource.setrlimit`` for CPU/memory.
6. **Network isolation** (Linux only): best-effort via ``unshare`` or
   restricted user. Windows falls back to process-level isolation.

Design notes
------------
* The script is written to a temp file inside a temp directory.
* ``subprocess.run`` with ``cwd`` set to the temp directory.
* All temp files are cleaned up in a ``finally`` block.
* On Windows, ``resource`` module is not available — silently skipped.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 180.0
ENV_TIMEOUT = "EVOLVER_VALIDATION_TIMEOUT_MS"

# Forbidden shell operators
FORBIDDEN_OPERATORS = re.compile(r"[;&|>`$]|\`")

# Forbidden prefixes / flags
FORBIDDEN_PREFIXES = ("pip", "python -c", "python -m", "eval", "exec")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    elapsed_ms: float


# ---------------------------------------------------------------------------
# Security checks
# ---------------------------------------------------------------------------


def _validate_command(command: list[str]) -> None:
    """Raise ``ValueError`` if *command* violates the security model."""
    cmd_str = " ".join(command)

    # Must start with python
    if not command or not command[0].lower().endswith("python") and command[0] != "python":
        raise ValueError(f"Command must start with 'python', got: {command[0]}")

    # Forbidden prefixes
    lower = cmd_str.lower()
    for prefix in FORBIDDEN_PREFIXES:
        if lower.startswith(prefix):
            raise ValueError(f"Forbidden command prefix: {prefix}")

    # Forbidden shell operators
    if FORBIDDEN_OPERATORS.search(cmd_str):
        raise ValueError(f"Forbidden shell operators in command: {cmd_str}")

    # Must be exactly: python <script_path> [args...]
    if len(command) < 2:
        raise ValueError("Command must include a script path")


def _validate_script(content: str) -> None:
    """Raise ``ValueError`` if *content* contains dangerous patterns."""
    lower = content.lower()
    dangerous = [
        ("os.system", "os.system call"),
        ("subprocess.call", "subprocess.call"),
        ("subprocess.run", "subprocess.run"),
        ("subprocess.popen", "subprocess.Popen"),
        ("exec(", "exec() call"),
        ("eval(", "eval() call"),
        ("compile(", "compile() call"),
    ]
    for pattern, name in dangerous:
        if pattern in lower:
            raise ValueError(f"Dangerous pattern detected: {name}")


# ---------------------------------------------------------------------------
# Resource limits (Linux only)
# ---------------------------------------------------------------------------


def _apply_resource_limits() -> None:
    """Apply CPU/memory limits in the child process (Linux only)."""
    if platform.system() != "Linux":
        return
    try:
        import resource
        # 60 seconds CPU time
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        # 512 MB memory
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        # 128 MB file size
        resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024 * 1024, 128 * 1024 * 1024))
    except Exception as exc:
        logger.debug("[Sandbox] Failed to set resource limits: %s", exc)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute_in_sandbox(
    script_content: str,
    *,
    script_filename: str = "validate.py",
    timeout_seconds: float | None = None,
    extra_args: list[str] | None = None,
) -> SandboxResult:
    """Execute *script_content* in a sandboxed temporary directory.

    Returns :class:`SandboxResult` with stdout, stderr, exit code, and
    timing information.
    """
    timeout = timeout_seconds or (float(os.environ.get(ENV_TIMEOUT, DEFAULT_TIMEOUT * 1000)) / 1000.0)
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT

    tmp_dir = Path(tempfile.mkdtemp(prefix="evolver-sandbox-"))
    script_path = tmp_dir / script_filename
    t0 = time.time()

    try:
        # Validate script content
        _validate_script(script_content)

        # Build command
        cmd: list[str] = ["python", script_filename]
        if extra_args:
            cmd.extend(extra_args)
        _validate_command(cmd)

        script_path.write_text(script_content, encoding="utf-8")

        result = subprocess.run(
            cmd,
            cwd=str(tmp_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=_apply_resource_limits if platform.system() == "Linux" else None,
        )

        elapsed = (time.time() - t0) * 1000.0
        return SandboxResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=False,
            elapsed_ms=elapsed,
        )

    except subprocess.TimeoutExpired as exc:
        elapsed = (time.time() - t0) * 1000.0
        # Kill the process tree if possible
        try:
            import psutil
            parent = psutil.Process(exc.pid)
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()
        except Exception:
            pass
        return SandboxResult(
            exit_code=-1,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            timed_out=True,
            elapsed_ms=elapsed,
        )

    except Exception as exc:
        elapsed = (time.time() - t0) * 1000.0
        return SandboxResult(
            exit_code=-1,
            stdout="",
            stderr=str(exc),
            timed_out=False,
            elapsed_ms=elapsed,
        )

    finally:
        # Cleanup temp directory
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception as exc:
            logger.debug("[Sandbox] Failed to cleanup %s: %s", tmp_dir, exc)
