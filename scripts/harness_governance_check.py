#!/usr/bin/env python3
"""Harness/evaluator governance PR gate.

Behavioral port of ``evolver/scripts/harness-governance-check.js`` (v1.93.0).
Includes both Node-style paths (``src/gep/``) and Python paths (``src/evolver/gep/``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SENSITIVE_PATH_RE = re.compile(
    r"^(?:"
    r"CONTRIBUTING\.md|"
    r"\.github/pull_request_template\.md|"
    r"\.github/workflows/(?:test\.yml|evolver\.yml)|"
    r"scripts/harness-governance-check\.js|"
    r"scripts/harness_governance_check\.py|"
    r"test/harnessGovernanceCheck\.test\.js|"
    r"tests/(?:scripts/)?test_harness_governance_check\.py|"
    r"src/evolve\.js|"
    r"src/evolve/|"
    r"src/adapters/|"
    r"src/experiment/|"
    r"src/gep/|"
    r"src/proxy/(?:router|trace)/|"
    r"src/proxy/inject\.js|"
    r"src/evolver/evolve\.py|"
    r"src/evolver/evolve/|"
    r"src/evolver/adapters/|"
    r"src/evolver/experiment/|"
    r"src/evolver/gep/|"
    r"src/evolver/proxy/(?:router|trace)/|"
    r"src/evolver/proxy/inject\.py|"
    r"assets/gep/|"
    r"src/evolver/assets/gep/"
    r")"
)
_SENSITIVE_PATH_RE = SENSITIVE_PATH_RE


def strip_html_comments(text: Any) -> str:
    return re.sub(r"<!--[\s\S]*?-->", "", str(text or ""))


def _line_value(body: str, label: str) -> str | None:
    escaped = re.escape(label)
    match = re.search(rf"^{escaped}:\s*(.*)$", body, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def is_substantive_value(value: Any) -> bool:
    if not value:
        return False
    normalized = str(value).strip()
    if not normalized:
        return False
    if re.search(r"[<>]", normalized):
        return False
    if re.match(
        r"^n/?a\.?(?:$|[\s:;,.\-\u2013\u2014])",
        normalized,
        flags=re.IGNORECASE,
    ):
        return False
    return True


def _value_matches(body: str, label: str, pattern: re.Pattern[str]) -> bool:
    value = _line_value(body, label)
    return bool(is_substantive_value(value) and value is not None and pattern.search(value))


def changed_files_touch_governance_surface(files: list[str]) -> bool:
    return any(SENSITIVE_PATH_RE.match(f) for f in files)


def validate_governance_packet(body: Any, changed_files: list[str]) -> list[str]:
    """Return a list of error messages (empty when the gate passes / N/A)."""
    stripped = strip_html_comments(body)
    errors: list[str] = []
    if not changed_files_touch_governance_surface(changed_files):
        return errors

    if not re.search(
        r"^##+\s+Harness/evaluator governance",
        stripped,
        flags=re.IGNORECASE | re.MULTILINE,
    ):
        errors.append(
            "missing ## Harness/evaluator governance — add the PR-template section "
            "from CONTRIBUTING.md"
        )

    required: list[tuple[str, str, str]] = [
        (
            "Upstream governance surface",
            r"\S",
            "name the Evolver harness/evaluator surface; template placeholders and "
            "bare N/A are not accepted for sensitive diffs",
        ),
        (
            "Downstream EvoX impact",
            r"\S",
            "state whether EvoX downstream behavior or contracts are affected; "
            "template placeholders and bare N/A are not accepted",
        ),
        (
            "Rollout-local scope",
            r"\S",
            "state the proposal/shadow/cohort boundary before promotion",
        ),
        (
            "Promotion boundary",
            r"\S",
            "state how rollout becomes default behavior",
        ),
        (
            "Evaluator mismatch sets",
            r"\S",
            "cover observation/action/repair/verification/evidence/belief deltas "
            "or explain why each is not changed",
        ),
        (
            "Non-regression evidence",
            r"\S",
            "link tests, shadow runs, replay, or doc-only rationale",
        ),
        (
            "Fix-severity review",
            r"^(low|medium|high|critical)\b",
            "classify the strongest fix severity",
        ),
        (
            "Owner approval",
            r"\S",
            "name the owning module/reviewer requirement",
        ),
        (
            "Security boundary",
            r"\S",
            "state data/tool/host/network/secrets impact",
        ),
        (
            "Rollback",
            r"\S",
            "state how to disable/revert/quarantine",
        ),
        (
            "Live promotion",
            r"^no$",
            "state exactly 'Live promotion: no'",
        ),
        (
            "Autonomous evaluator self-editing",
            r"^no$",
            "state exactly 'Autonomous evaluator self-editing: no'",
        ),
    ]

    for label, pattern, hint in required:
        if not _value_matches(stripped, label, re.compile(pattern, flags=re.IGNORECASE)):
            errors.append(f"missing {label} — {hint}")
    return errors


def _read_body(*, body_file: str | None = None, event_file: str | None = None) -> str:
    if body_file:
        return Path(body_file).read_text(encoding="utf-8")
    if event_file:
        event = json.loads(Path(event_file).read_text(encoding="utf-8"))
        if isinstance(event, dict):
            pr = event.get("pull_request")
            if isinstance(pr, dict):
                return str(pr.get("body") or "")
        return ""
    if os.environ.get("PR_BODY_FILE"):
        return Path(os.environ["PR_BODY_FILE"]).read_text(encoding="utf-8")
    if os.environ.get("PR_BODY"):
        return str(os.environ["PR_BODY"])
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def _read_changed_files(*, changed_file: str | None = None) -> list[str]:
    raw = ""
    if changed_file:
        raw = Path(changed_file).read_text(encoding="utf-8")
    elif os.environ.get("PR_CHANGED_FILES_FILE"):
        raw = Path(os.environ["PR_CHANGED_FILES_FILE"]).read_text(encoding="utf-8")
    elif os.environ.get("PR_CHANGED_FILES"):
        raw = str(os.environ["PR_CHANGED_FILES"])
    return [s.strip().replace("\\", "/") for s in raw.splitlines() if s.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness/evaluator governance PR gate")
    parser.add_argument("--body", dest="body_file", default=None, help="PR body file")
    parser.add_argument(
        "--changed", dest="changed_file", default=None, help="Changed files list"
    )
    parser.add_argument(
        "--event", dest="event_file", default=None, help="GitHub event JSON"
    )
    args = parser.parse_args(argv)
    try:
        body = _read_body(body_file=args.body_file, event_file=args.event_file)
        changed_files = _read_changed_files(changed_file=args.changed_file)
        errors = validate_governance_packet(body, changed_files)
    except Exception as exc:
        print(f"Harness/evaluator governance gate ERROR: {exc}", file=sys.stderr)
        return 2

    if errors:
        print("Harness/evaluator governance gate FAILED.", file=sys.stderr)
        for err in errors:
            print(f"- {err}", file=sys.stderr)
        print("Changed sensitive files:", file=sys.stderr)
        for f in changed_files:
            if _SENSITIVE_PATH_RE.match(f):
                print(f"- {f}", file=sys.stderr)
        return 1

    if changed_files_touch_governance_surface(changed_files):
        print("Harness/evaluator governance gate: PASSED")
    else:
        print("Harness/evaluator governance gate: not applicable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
