"""Solve-prompt shape (S26.1c + 库即尺子 §5.4).

1:1 with ``evolver.bench.prompts``. The prompt is the engine's only interface
to the solving agent: it must embed the absolute workdir and forbid leaving
it (wikiskill Run-4), and the library block rides inside it — the host is
never pointed at a library directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evolver.bench.prompts import inference_prompt


def _task(grader_type: str = "exact") -> dict[str, Any]:
    grader: dict[str, Any]
    if grader_type == "code_stdout":
        grader = {"type": "code_stdout", "file": "sol.py", "script": "sol.py", "expected": "3"}
    else:
        grader = {"type": grader_type, "file": "out.txt", "expected": "x"}
    return {
        "id": "t",
        "split": "val",
        "title": "Sum the numbers",
        "prompt": "Read nums.txt and write the sum.",
        "sandbox": {"nums.txt": "1 2"},
        "grader": grader,
    }


class TestPromptShape:
    def test_embeds_the_resolved_workdir(self, tmp_path: Path) -> None:
        prompt = inference_prompt(_task(), tmp_path / "sb")
        assert f"WORKING DIRECTORY: {(tmp_path / 'sb').resolve()}" in prompt

    def test_forbids_leaving_the_workdir(self, tmp_path: Path) -> None:
        prompt = inference_prompt(_task(), tmp_path / "sb")
        assert "Work ONLY inside the working" in prompt

    def test_carries_title_and_prompt(self, tmp_path: Path) -> None:
        prompt = inference_prompt(_task(), tmp_path / "sb")
        assert "Sum the numbers" in prompt
        assert "Read nums.txt and write the sum." in prompt

    def test_readback_reminder_is_present(self, tmp_path: Path) -> None:
        prompt = inference_prompt(_task(), tmp_path / "sb")
        assert "verify-output-readback" in prompt


class TestDeliverablePhrasing:
    def test_exact_names_the_deliverable_file(self, tmp_path: Path) -> None:
        prompt = inference_prompt(_task("exact"), tmp_path / "sb")
        assert "Write the final answer to `out.txt`." in prompt
        assert "Grading is exact/structural" in prompt

    def test_code_stdout_names_the_script_and_the_runner(self, tmp_path: Path) -> None:
        prompt = inference_prompt(_task("code_stdout"), tmp_path / "sb")
        assert "Write your solution to `sol.py`" in prompt
        assert "the grader runs it with" in prompt


class TestLibraryBlock:
    def test_absent_block_leaves_no_section(self, tmp_path: Path) -> None:
        prompt = inference_prompt(_task(), tmp_path / "sb")
        assert "Library snapshot" not in prompt
        assert "## Task" in prompt and "## Deliverable" in prompt

    def test_block_sits_between_task_and_deliverable(self, tmp_path: Path) -> None:
        block = (
            "## Library snapshot (read-only design context)\n"
            "- snapshot id: `sha256:x`\n```json\n{}\n```"
        )
        prompt = inference_prompt(_task(), tmp_path / "sb", library_block=block)
        assert (
            prompt.index("## Task")
            < prompt.index("## Library snapshot")
            < prompt.index("## Deliverable")
        )

    def test_block_content_rides_inside_the_prompt(self, tmp_path: Path) -> None:
        block = "## Library snapshot\nSNAPSHOT-BODY-HERE"
        prompt = inference_prompt(_task(), tmp_path / "sb", library_block=block)
        assert "SNAPSHOT-BODY-HERE" in prompt

    def test_empty_block_is_treated_as_absent(self, tmp_path: Path) -> None:
        prompt = inference_prompt(_task(), tmp_path / "sb", library_block="")
        assert "Library snapshot" not in prompt
