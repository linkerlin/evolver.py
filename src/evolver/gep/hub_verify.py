"""Hub verify — verify that a Hub-published asset (service, skill, patch)
is structurally valid, cryptographically consistent, and policy-compliant.

Equivalent to Node's ``evolver/src/gep/hubVerify.js``.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from .hub_review import ReviewComment

logger = logging.getLogger(__name__)


@dataclass
class VerifyResult:
    valid: bool
    errors: list[ReviewComment] = field(default_factory=list)
    warnings: list[ReviewComment] = field(default_factory=list)


def verify_service_schema(data: dict[str, Any]) -> VerifyResult:
    """Verify that a service listing conforms to the ATP schema."""
    errors: list[ReviewComment] = []
    warnings: list[ReviewComment] = []

    required = [
        "service_id",
        "title",
        "description",
        "capabilities",
        "price_per_task",
        "execution_mode",
    ]
    for field_name in required:
        if field_name not in data:
            errors.append(ReviewComment("error", f"Missing required field '{field_name}'."))

    if "price_per_task" in data:
        p = data["price_per_task"]
        if not isinstance(p, (int, float)) or p < 0:
            errors.append(ReviewComment("error", "price_per_task must be a non-negative number."))

    mode = data.get("execution_mode", "")
    if mode and mode not in {"sync", "async", "batch"}:
        errors.append(ReviewComment("error", f"Invalid execution_mode '{mode}'."))

    caps = data.get("capabilities", [])
    if not isinstance(caps, list):
        errors.append(ReviewComment("error", "capabilities must be a list."))

    valid = len(errors) == 0
    logger.info(
        "[HubVerify] service schema valid=%s errors=%d warnings=%d",
        valid,
        len(errors),
        len(warnings),
    )
    return VerifyResult(valid=valid, errors=errors, warnings=warnings)


def verify_skill_bundle(manifest: dict[str, Any], files: dict[str, bytes]) -> VerifyResult:
    """Verify a skill bundle: manifest + file hashes."""
    errors: list[ReviewComment] = []
    warnings: list[ReviewComment] = []

    expected_files = manifest.get("files", [])
    if not expected_files:
        warnings.append(ReviewComment("warning", "Manifest has no 'files' list."))

    for entry in expected_files:
        path = entry.get("path")
        expected_hash = entry.get("sha256")
        if not path or not expected_hash:
            errors.append(ReviewComment("error", "Manifest entry missing path or sha256."))
            continue
        content = files.get(path)
        if content is None:
            errors.append(ReviewComment("error", f"Missing file in bundle: {path}"))
            continue
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            errors.append(
                ReviewComment(
                    "error",
                    f"Hash mismatch for {path}: expected {expected_hash[:12]}… "
                    f"got {actual_hash[:12]}…",
                )
            )

    valid = len(errors) == 0
    logger.info("[HubVerify] skill bundle valid=%s errors=%d", valid, len(errors))
    return VerifyResult(valid=valid, errors=errors, warnings=warnings)


def verify_patch_integrity(diff_text: str, changed_files: list[str]) -> VerifyResult:
    """Verify that a diff text references only the files in *changed_files*."""
    errors: list[ReviewComment] = []
    warnings: list[ReviewComment] = []

    # Parse diff headers to extract referenced files
    import re

    referenced: set[str] = set()
    for match in re.finditer(r"^diff --git a/(\S+) b/\S+", diff_text, re.MULTILINE):
        referenced.add(match.group(1))
    for match in re.finditer(r"^--- a/(\S+)", diff_text, re.MULTILINE):
        referenced.add(match.group(1))
    for match in re.finditer(r"^\+\+\+ b/(\S+)", diff_text, re.MULTILINE):
        referenced.add(match.group(1))

    for f in referenced:
        if f not in changed_files:
            errors.append(ReviewComment("error", f"Diff references untracked file: {f}"))

    valid = len(errors) == 0
    logger.info("[HubVerify] patch integrity valid=%s errors=%d", valid, len(errors))
    return VerifyResult(valid=valid, errors=errors, warnings=warnings)
