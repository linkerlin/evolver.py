"""Directive files must not drift (round-88 / round-93 / round-94 lessons).

Three real drift incidents this stage: AGENTS/SKILL re-dispatching
already-landed seams (round-88), a freeze clause expiring by its own letter
and SKILL still carrying the voided house-rule design (round-93), a stale
version claim in README (round-94, caught by writing this pin). All pure
text checks — no engine imports.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Docs that direct the next agent. 演进方案.md is the charter: it MAY record
# voided designs as history (its §4 does, on purpose), so the phrase bans
# below apply to the other four only.
DIRECTIVE_DOCS = ["README.md", "README.zh.md", "AGENTS.md", "SKILL.md", "TODO.md"]


def _current_version() -> str:
    import tomllib

    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    version = data["project"]["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    return version


def test_bolded_version_claims_match_pyproject() -> None:
    """Any ``版本 **X.Y.Z**`` / ``Version **X.Y.Z**`` claim in a live doc
    must state the version pyproject actually carries. Historical prose
    versions (feature-arrival notes) are not bolded claims and stay legal."""
    current = _current_version()
    pattern = re.compile(r"(?:版本|[Vv]ersion)\s*\*\*(\d+\.\d+\.\d+)\*\*")
    for name in ["README.md", "README.zh.md", "AGENTS.md", "SKILL.md", "TODO.md", "演进方案.md"]:
        found = set(pattern.findall((REPO / name).read_text(encoding="utf-8")))
        assert found <= {current}, (
            f"{name} claims version(s) {sorted(found)} but pyproject is {current} — "
            "version lines are operator-cut; update the docs with the bump"
        )


def test_voided_designs_are_not_re_dispatched() -> None:
    """Phrases whose designs were voided by ruling must not appear in the
    files that direct work. The charter is exempt: §4 records them as
    history precisely so nobody re-derives them."""
    banned = ["受治理的仓库自维护", "家规", "conventions, not derivations"]
    for name in DIRECTIVE_DOCS:
        text = (REPO / name).read_text(encoding="utf-8")
        for phrase in banned:
            assert phrase not in text, f"{name} re-dispatches the voided design {phrase!r}"


def test_the_stage_name_is_present_in_the_stage_files() -> None:
    for name, marker in [
        ("演进方案.md", "库即尺子"),
        ("TODO.md", "库即尺子"),
        ("AGENTS.md", "库即尺子"),
        ("SKILL.md", "library-as-ruler"),
    ]:
        assert marker in (REPO / name).read_text(encoding="utf-8"), (
            f"{name} lost the stage marker {marker!r}"
        )
