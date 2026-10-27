"""Policy enforcement engine — safety gate before solidify.

Equivalent to ``evolver/src/gep/policyCheck.js`` (obfuscated core).
Runs a suite of checks before allowing a mutation to be solidified:
blast-radius limits, secret leak detection, protected-path guards,
and rollback safety.

Design notes (Pythonic)
-----------------------
* Returns a structured ``PolicyReport`` dataclass so callers can decide
  whether to abort, warn, or proceed.
* Uses ``pathlib.Path`` for all path checks.
* Secret scanning delegates to :mod:`evolver.gep.sanitize`.
* Rollback safety verifies that tracked changes can be reverted without
  losing user data.
"""

from __future__ import annotations

import ast
import contextlib
import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from evolver.config import BLAST_RADIUS_HARD_CAP_FILES, BLAST_RADIUS_HARD_CAP_LINES
from evolver.gep.git_ops import (
    git_list_changed_files,
    git_list_untracked_files,
    is_critical_protected_path,
)
from evolver.gep.paths import get_workspace_root
from evolver.gep.sanitize import full_leak_check
from evolver.gep.validator.sandbox_executor import (
    ALLOWED_EXECUTABLES,
    assert_node_command_safe,
    parse_command,
)

logger = logging.getLogger(__name__)

# Additional paths that should never be modified by evolver itself
_SELF_PROTECTED_PREFIXES = ("evolver/",)

#: Harness2 (§3.2 / Appendix E.2) component cost hierarchy, ordered from lowest
#: per-turn runtime footprint to highest.
COMPONENT_COST_HIERARCHY: Final[tuple[str, ...]] = (
    "skill",
    "script",
    "subagent",
    "hook",
    "always_on_text",
)
ALWAYS_ON_FILENAMES: Final[frozenset[str]] = frozenset(
    {"AGENTS.md", "CLAUDE.md", "systemprompt.md", "guardrails.md"}
)
MAX_ALWAYS_ON_NET_GROWTH_CHARS: Final[int] = 1200

#: Harness2 (Appendix G) Selector 6-axis deliverable conformance checklist.
DELIVERABLE_CONFORMANCE_AXES: Final[tuple[str, ...]] = (
    "delivery",
    "conformance",
    "fidelity",
    "internal_consistency",
    "operational_fitness",
    "finish",
)

_SKILL_PATH_RE: Final = re.compile(
    r"(?:^|/)(?:skills|\.agents/skills|\.claude/skills)/([A-Za-z0-9_.-]+)/SKILL\.md$"
)
_SCRIPT_REF_RE: Final = re.compile(
    r"\b((?:(?:skills|\.agents/skills|\.claude/skills)/[A-Za-z0-9_.-]+/)?"
    r"scripts/[A-Za-z0-9_./-]+\.py)\b"
)
_FENCED_CODE_RE: Final = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE: Final = re.compile(r"`[^`\n]+`")
_RAW_TEMPLATE_BRACE_RE: Final = re.compile(r"\{\{|\}\}|\{%|%\}")
_UNCOMPUTED_FORMULA_RE: Final = re.compile(
    r"(?:^|[\s,|;:])(?:=[A-Z]{2,}\s*\(|#REF!|#DIV/0!|#VALUE!|#NAME\?|#N/A\b)",
    re.MULTILINE,
)
_PLACEHOLDER_RE: Final = re.compile(
    r"(?:\b(?:TODO|TBD|FIXME|XXX)\b|<placeholder>|\[TODO\])",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Validation-command gate
# ---------------------------------------------------------------------------


def is_validation_command_allowed(cmd: object) -> bool:
    """Return whether a Hub-issued validation command can run in the sandbox.

    The publish-side gate: must agree exactly with the validator-side gate
    (``sandbox_executor.assert_node_command_safe`` + allowlist) so a gene can
    never ship a validation command that dies in every validator sandbox
    (evolver issues #607/#608/#609). Same contract as Node's
    ``policyCheck.isValidationCommandAllowed``.
    """
    if not isinstance(cmd, str) or not cmd.strip():
        return False
    try:
        executable, args = parse_command(cmd)
        if executable not in ALLOWED_EXECUTABLES:
            return False
        assert_node_command_safe(executable, args)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PolicyViolation:
    rule: str
    severity: str  # critical | warning
    message: str


@dataclass
class PolicyReport:
    ok: bool
    violations: list[PolicyViolation] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(v.severity == "critical" for v in self.violations)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_policy(
    *,
    diff_text: str | None = None,
    changed_files: Sequence[str] | None = None,
    untracked_files: Sequence[str] | None = None,
    max_files: int | None = None,
    max_lines: int | None = None,
    check_component_integrity: bool = False,
    check_template_braces: bool = False,
    require_skill_trigger: bool = False,
    max_always_on_growth_chars: int = MAX_ALWAYS_ON_NET_GROWTH_CHARS,
) -> PolicyReport:
    """Run the full policy-check suite.

    Parameters
    ----------
    diff_text:
        Raw git diff text (used for secret scanning).
    changed_files:
        List of changed file paths (relative). If omitted, computed from git.
    untracked_files:
        List of untracked file paths (relative). If omitted, computed from git.
    max_files:
        Hard cap on number of files touched. Defaults to ``BLAST_RADIUS_HARD_CAP_FILES``.
    max_lines:
        Hard cap on lines changed. Defaults to ``BLAST_RADIUS_HARD_CAP_LINES``.
    check_component_integrity:
        When True, also runs Harness2's three-rule static component integrity
        validator and always-on prose budget check.
    """
    violations: list[PolicyViolation] = []
    cwd = get_workspace_root()

    changed = list(changed_files) if changed_files is not None else git_list_changed_files(cwd)
    untracked = (
        list(untracked_files) if untracked_files is not None else git_list_untracked_files(cwd)
    )
    all_files = list(dict[str, Any].fromkeys(changed + untracked))  # preserve order, dedup

    # 1. Blast radius
    _check_blast_radius(all_files, changed, untracked, max_files, max_lines, violations)

    # 2. Protected paths (critical files + self-protection)
    _check_protected_paths(all_files, cwd, violations)

    # 3. Secret leak detection
    _check_secret_leaks(diff_text, violations)

    # 4. Rollback safety (stash path)
    _check_rollback_safety(changed, untracked, violations)

    # 5. Optional Harness2 component integrity & cost hierarchy gate
    if check_component_integrity:
        integrity = validate_harness_component_integrity(
            cwd,
            all_files,
            diff_text=diff_text,
            check_template_braces=check_template_braces,
            require_skill_trigger=require_skill_trigger,
            max_always_on_growth_chars=max_always_on_growth_chars,
        )
        violations.extend(integrity["violations"])

    report = PolicyReport(
        ok=not any(v.severity == "critical" for v in violations), violations=violations
    )
    if not report.ok:
        logger.warning(
            "[PolicyCheck] %d critical violation(s) found",
            len([v for v in violations if v.severity == "critical"]),
        )
    return report


def validate_harness_component_integrity(
    root: Path,
    changed_files: Sequence[str],
    *,
    diff_text: str | None = None,
    check_template_braces: bool = True,
    require_skill_trigger: bool = True,
    max_always_on_growth_chars: int = MAX_ALWAYS_ON_NET_GROWTH_CHARS,
) -> dict[str, Any]:
    """Enforce Harness2's Three Rules That Discard the Whole Proposal + Cost Hierarchy.

    1. **Skill Trigger & Frontmatter**: Every modified ``skills/<name>/SKILL.md``
       must carry YAML frontmatter with ``name: <name>`` matching its directory
       and a non-empty ``description:``. When ``require_skill_trigger=True`` and
       at least one always-on instruction file exists in *root*, the skill name
       must be referenced so it is reachable.
    2. **Referenced Script Integrity**: Every ``scripts/<name>.py`` referenced
       in modified files or diff additions must exist under *root* and compile
       cleanly via :func:`ast.parse`.
    3. **Template Safety & Always-On Budget**: Modified always-on instruction
       files must not contain unescaped ``{{`` / ``{%`` template braces outside
       code blocks (when ``check_template_braces=True``), and net growth past
       ``max_always_on_growth_chars`` emits a warning steering edits down the
       :data:`COMPONENT_COST_HIERARCHY` (``Skill > Script > Subagent > Hook > Always-On Text``).
    """
    violations: list[PolicyViolation] = []
    norm_files = [str(f).replace("\\", "/").lstrip("/") for f in changed_files if str(f).strip()]

    always_on_texts: dict[str, str] = {}
    for candidate_name in ALWAYS_ON_FILENAMES:
        candidate_path = root / candidate_name
        if candidate_path.is_file():
            with contextlib.suppress(OSError):
                always_on_texts[candidate_name] = candidate_path.read_text(
                    encoding="utf-8", errors="replace"
                )

    script_refs: set[str] = set()
    if diff_text:
        for line in diff_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                for match in _SCRIPT_REF_RE.finditer(line):
                    script_refs.add(match.group(1))

    for rel in norm_files:
        file_path = root / rel
        content = ""
        if file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""

        # Collect script references from modified markdown / skill / config files
        if rel.endswith((".md", ".json", ".yaml", ".yml", ".txt")):
            for match in _SCRIPT_REF_RE.finditer(content):
                script_refs.add(match.group(1))

        # Rule 1: Skill frontmatter & trigger reachability
        skill_match = _SKILL_PATH_RE.search(rel)
        if skill_match and file_path.is_file():
            dir_name = skill_match.group(1)
            fm_name, fm_desc = _parse_skill_frontmatter(content)
            if fm_name != dir_name:
                violations.append(
                    PolicyViolation(
                        rule="skill_frontmatter_name_mismatch",
                        severity="critical",
                        message=(
                            f"Skill {rel} frontmatter name {fm_name!r} does not match "
                            f"directory {dir_name!r}."
                        ),
                    )
                )
            if not fm_desc:
                violations.append(
                    PolicyViolation(
                        rule="skill_frontmatter_missing_description",
                        severity="critical",
                        message=f"Skill {rel} frontmatter is missing a non-empty description.",
                    )
                )
            if require_skill_trigger and always_on_texts:
                reachable = any(dir_name in text for text in always_on_texts.values())
                if not reachable:
                    violations.append(
                        PolicyViolation(
                            rule="unreachable_skill_trigger",
                            severity="critical",
                            message=(
                                f"Skill {dir_name!r} ({rel}) is not referenced in any "
                                f"always-on file ({sorted(always_on_texts)})."
                            ),
                        )
                    )

        # Rule 3a: Unescaped template braces in always-on files
        base_name = Path(rel).name
        if check_template_braces and base_name in ALWAYS_ON_FILENAMES and content:
            stripped = _INLINE_CODE_RE.sub("", _FENCED_CODE_RE.sub("", content))
            if _RAW_TEMPLATE_BRACE_RE.search(stripped):
                violations.append(
                    PolicyViolation(
                        rule="raw_template_braces",
                        severity="critical",
                        message=(
                            f"Always-on file {rel} contains raw template braces "
                            "outside code fences."
                        ),
                    )
                )

    # Rule 2: Referenced scripts exist and compile
    for script_rel in sorted(script_refs):
        script_path = root / script_rel
        if not script_path.is_file():
            violations.append(
                PolicyViolation(
                    rule="missing_referenced_script",
                    severity="critical",
                    message=f"Referenced script does not exist on disk: {script_rel}",
                )
            )
            continue
        try:
            source = script_path.read_text(encoding="utf-8", errors="replace")
            ast.parse(source, filename=script_rel)
        except SyntaxError as exc:
            violations.append(
                PolicyViolation(
                    rule="referenced_script_syntax_error",
                    severity="critical",
                    message=f"Referenced script {script_rel} failed syntax check: {exc.msg}",
                )
            )

    # Rule 3b: Always-on prose growth budget
    always_on_delta = _compute_always_on_net_growth(diff_text or "", norm_files)
    if always_on_delta > max_always_on_growth_chars:
        violations.append(
            PolicyViolation(
                rule="always_on_prose_bloat",
                severity="warning",
                message=(
                    f"Always-on instruction net growth ({always_on_delta} chars) exceeds "
                    f"budget ({max_always_on_growth_chars} chars). Prefer "
                    "Skill > Script > Subagent > Hook > Always-On Text."
                ),
            )
        )

    critical_count = sum(1 for v in violations if v.severity == "critical")
    return {
        "ok": critical_count == 0,
        "critical_count": critical_count,
        "always_on_net_growth_chars": always_on_delta,
        "referenced_scripts": sorted(script_refs),
        "cost_hierarchy": list(COMPONENT_COST_HIERARCHY),
        "violations": violations,
    }


def check_deliverable_conformance(
    content: str,
    *,
    required_headers: Sequence[str] = (),
    required_sections: Sequence[str] = (),
    required_terms: Sequence[str] = (),
    forbidden_terms: Sequence[str] = (),
    expected_key_values: dict[str, str | int | float] | None = None,
    forbid_uncomputed_formulas: bool = True,
    forbid_placeholders: bool = True,
) -> dict[str, Any]:
    """Harness2 (Appendix G) 6-axis Deliverable Conformance verifier.

    Checks a deliverable string across six axes:
    ``delivery``, ``conformance``, ``fidelity``, ``internal_consistency``,
    ``operational_fitness``, and ``finish``.
    """
    text = content if isinstance(content, str) else ""
    issues: list[dict[str, str]] = []
    axes: dict[str, bool] = dict.fromkeys(DELIVERABLE_CONFORMANCE_AXES, True)

    # 1. DELIVERY: non-empty output
    if not text.strip():
        axes["delivery"] = False
        issues.append({"axis": "delivery", "detail": "Deliverable content is empty."})

    # 2. CONFORMANCE: required headers and section order
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    first_line = lines[0] if lines else ""
    for header in required_headers:
        if header not in first_line and header not in text:
            axes["conformance"] = False
            issues.append({"axis": "conformance", "detail": f"Missing required header: {header!r}"})
    last_pos = -1
    for section in required_sections:
        pos = text.find(section)
        if pos == -1:
            axes["conformance"] = False
            issues.append(
                {"axis": "conformance", "detail": f"Missing required section: {section!r}"}
            )
        elif pos < last_pos:
            axes["conformance"] = False
            issues.append(
                {
                    "axis": "conformance",
                    "detail": f"Section {section!r} appears out of required order.",
                }
            )
        else:
            last_pos = pos

    # 3. FIDELITY: required domain terms preserved, forbidden terms absent
    for term in required_terms:
        if term not in text:
            axes["fidelity"] = False
            issues.append({"axis": "fidelity", "detail": f"Missing required term: {term!r}"})
    for bad_term in forbidden_terms:
        if bad_term in text:
            axes["fidelity"] = False
            issues.append({"axis": "fidelity", "detail": f"Forbidden term present: {bad_term!r}"})

    # 4. INTERNAL CONSISTENCY: expected key/value or reconciliation totals match
    if isinstance(expected_key_values, dict):
        for key, expected_val in expected_key_values.items():
            pattern = re.compile(
                rf"{re.escape(str(key))}\s*[:=|]\s*{re.escape(str(expected_val))}\b"
            )
            if not pattern.search(text):
                axes["internal_consistency"] = False
                issues.append(
                    {
                        "axis": "internal_consistency",
                        "detail": f"Expected {key}={expected_val} not consistently matched.",
                    }
                )

    # 5. OPERATIONAL FITNESS: no uncomputed spreadsheet formulas or error cells
    if forbid_uncomputed_formulas:
        formula_match = _UNCOMPUTED_FORMULA_RE.search(text)
        if formula_match:
            matched_formula = formula_match.group(0).strip()
            axes["operational_fitness"] = False
            issues.append(
                {
                    "axis": "operational_fitness",
                    "detail": f"Uncomputed formula or error literal: {matched_formula!r}",
                }
            )

    # 6. FINISH: no leftover TODO / TBD / placeholder tokens
    if forbid_placeholders:
        placeholder_match = _PLACEHOLDER_RE.search(text)
        if placeholder_match:
            axes["finish"] = False
            issues.append(
                {
                    "axis": "finish",
                    "detail": f"Unfinished placeholder token: {placeholder_match.group(0)!r}",
                }
            )

    failed_axes = [axis for axis in DELIVERABLE_CONFORMANCE_AXES if not axes[axis]]
    return {
        "ok": len(failed_axes) == 0,
        "axes": axes,
        "failed_axes": failed_axes,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Internal checks
# ---------------------------------------------------------------------------


def _parse_skill_frontmatter(content: str) -> tuple[str, str]:
    """Extract ``(name, description)`` from YAML frontmatter of a SKILL.md."""
    text = content.lstrip("\ufeff")
    if not text.startswith("---"):
        return "", ""
    lines = text.splitlines()
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return "", ""
    name_val = ""
    desc_val = ""
    for line in lines[1:end_idx]:
        if ":" not in line:
            continue
        key, raw_val = line.split(":", 1)
        k = key.strip().lower()
        val = raw_val.strip().strip("\"'")
        if k == "name":
            name_val = val
        elif k == "description":
            desc_val = val
    return name_val, desc_val


def _compute_always_on_net_growth(diff_text: str, changed_files: Sequence[str]) -> int:
    """Compute net character additions across always-on prompt files in *diff_text*."""
    if not diff_text:
        return 0
    touches_always_on = any(Path(f).name in ALWAYS_ON_FILENAMES for f in changed_files)
    if not touches_always_on and not any(name in diff_text for name in ALWAYS_ON_FILENAMES):
        return 0
    added = 0
    removed = 0
    in_always_on = not bool(re.search(r"(?m)^diff --git ", diff_text)) and touches_always_on
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            in_always_on = any(
                line.endswith(f"/{name}") or line.endswith(f" b/{name}")
                for name in ALWAYS_ON_FILENAMES
            )
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target.startswith("b/"):
                target = target[2:]
            in_always_on = Path(target).name in ALWAYS_ON_FILENAMES
            continue
        if not in_always_on or line.startswith(("---", "@@")):
            continue
        if line.startswith("+"):
            added += len(line) - 1
        elif line.startswith("-"):
            removed += len(line) - 1
    return max(0, added - removed)


def _check_blast_radius(
    all_files: list[str],
    changed: list[str],
    untracked: list[str],
    max_files: int | None,
    max_lines: int | None,
    violations: list[PolicyViolation],
) -> None:
    file_cap = max_files if max_files is not None else BLAST_RADIUS_HARD_CAP_FILES
    line_cap = max_lines if max_lines is not None else BLAST_RADIUS_HARD_CAP_LINES

    if len(all_files) > file_cap:
        violations.append(
            PolicyViolation(
                rule="blast_radius_files",
                severity="critical",
                message=f"Touched {len(all_files)} files (cap={file_cap})",
            )
        )

    # Count lines in changed + untracked files
    cwd = get_workspace_root()
    total_lines = 0
    for rel in changed + untracked:
        p = cwd / rel
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                total_lines += sum(1 for _ in f)
        except OSError:
            pass

    if total_lines > line_cap:
        violations.append(
            PolicyViolation(
                rule="blast_radius_lines",
                severity="critical",
                message=f"Touched {total_lines} lines (cap={line_cap})",
            )
        )


def _check_protected_paths(
    all_files: list[str],
    cwd: Path,
    violations: list[PolicyViolation],
) -> None:
    for rel in all_files:
        # Critical files
        if is_critical_protected_path(rel):
            violations.append(
                PolicyViolation(
                    rule="protected_path",
                    severity="critical",
                    message=f"Modification of protected path blocked: {rel}",
                )
            )
            continue

        # Self-protection: evolver/ directory
        norm_rel = rel.replace("\\", "/")
        for prefix in _SELF_PROTECTED_PREFIXES:
            if norm_rel.startswith(prefix):
                violations.append(
                    PolicyViolation(
                        rule="self_protection",
                        severity="critical",
                        message=f"Modification of evolver own source blocked: {rel}",
                    )
                )
                break

        # Secret files
        name = Path(rel).name.lower()
        if name == ".env" or name.endswith(".key") or "secret" in name:
            violations.append(
                PolicyViolation(
                    rule="secret_file",
                    severity="critical",
                    message=f"Modification of secret file blocked: {rel}",
                )
            )


def _check_secret_leaks(diff_text: str | None, violations: list[PolicyViolation]) -> None:
    if not diff_text:
        return
    leak_report = full_leak_check(diff_text)
    if not leak_report["safe"]:
        for leak in leak_report.get("pattern_leaks", []):
            violations.append(
                PolicyViolation(
                    rule="secret_leak",
                    severity="critical",
                    message=(
                        f"Potential secret leak detected: {leak['type']} at offset {leak['start']}"
                    ),
                )
            )
        for leak in leak_report.get("env_leaks", []):
            violations.append(
                PolicyViolation(
                    rule="env_leak",
                    severity="critical",
                    message=f"Env value leak detected: {leak['key']}",
                )
            )


def _check_rollback_safety(
    changed: list[str],
    untracked: list[str],
    violations: list[PolicyViolation],
) -> None:
    mode = os.environ.get("EVOLVER_ROLLBACK_MODE", "stash").lower().strip()
    if mode == "none":
        violations.append(
            PolicyViolation(
                rule="rollback_mode_none",
                severity="warning",
                message="Rollback mode is 'none' — changes cannot be auto-reverted",
            )
        )
        return

    # Check for untracked files that would be lost on hard reset
    if mode == "hard" and untracked:
        violations.append(
            PolicyViolation(
                rule="rollback_hard_untracked",
                severity="warning",
                message=f"Hard reset would delete {len(untracked)} untracked file(s)",
            )
        )

    # Stash mode is generally safe for tracked files
    # but warn if there are uncommitted changes in protected files
    for rel in changed:
        if is_critical_protected_path(rel):
            violations.append(
                PolicyViolation(
                    rule="rollback_protected_change",
                    severity="warning",
                    message=f"Rollback may revert changes in protected file: {rel}",
                )
            )
