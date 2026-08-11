"""Publish-path validation command gate (v1.94.0 parity).

Behavioral port of Node ``test/proxyPublishValidation.test.js`` (issues
#607/#608/#609): the publish path can only ever emit validation commands the
validator sandbox will actually run.
"""

import re

import pytest

from evolver.gep.validator.sandbox_executor import assert_node_command_safe, parse_command
from evolver.proxy.asset_publish import (
    PublishValidationError,
    build_bundle_from_loose_asset,
)

LONG_CONTENT = (
    "Detect the failing lifecycle probe and restart the supervised worker. "
    "Confirm the restart cleared the stale socket before adopting the change."
)


def sandbox_would_run(cmd: object) -> bool:
    try:
        executable, args = parse_command(cmd)  # type: ignore[arg-type]
        assert_node_command_safe(executable, args)
        return True
    except (ValueError, TypeError):
        return False


def build(raw: dict) -> tuple[dict, dict]:
    return build_bundle_from_loose_asset(raw)


class TestMcpPublishValidation:
    def test_defaults_to_sandbox_runnable_validation(self) -> None:
        gene, _capsule = build({"content": LONG_CONTENT})
        assert isinstance(gene["validation"], list) and gene["validation"]
        for cmd in gene["validation"]:
            assert sandbox_would_run(cmd), f"default validation not sandbox-runnable: {cmd!r}"

    def test_capsule_carries_validation_too(self) -> None:
        gene, capsule = build({"content": LONG_CONTENT})
        assert capsule["validation"] == gene["validation"]

    def test_never_emits_inline_node_e_default(self) -> None:
        gene, _ = build({"content": LONG_CONTENT})
        for cmd in gene["validation"]:
            assert not re.search(r"(^|\s)(-e|--eval|-p|--print)(\s|=|$)", str(cmd))

    def test_preserves_caller_supplied_runnable_validation(self) -> None:
        gene, _ = build({"content": LONG_CONTENT, "validation": ["node scripts/check.js --quiet"]})
        assert gene["validation"] == ["node scripts/check.js --quiet"]

    @pytest.mark.parametrize(
        "bad",
        [
            'node -e "process.exit(0)"',
            'node --eval "1"',
            "node -r ./preload.js check.js",
            "node --inspect check.js",
            'node "--inspect" check.js',
            'node "--require=./preload.js" check.js',
            'node "-r" "./preload.js" check.js',
            "node --watch check.js",
            'node "--watch" check.js',
            "npm test",
            "node --test",
            "node check.js && echo pwn",
        ],
    )
    def test_rejects_unrunnable_commands_with_400(self, bad: str) -> None:
        with pytest.raises(PublishValidationError) as exc_info:
            build({"content": LONG_CONTENT, "validation": [bad]})
        assert exc_info.value.status_code == 400, f"must be a clean 400 for {bad!r}"
        assert "validator sandbox cannot run" in str(exc_info.value)

    def test_rejects_mixed_batch_when_any_unrunnable(self) -> None:
        with pytest.raises(PublishValidationError) as exc_info:
            build({"content": LONG_CONTENT, "validation": ["node --version", 'node -e "1"']})
        assert exc_info.value.status_code == 400
        assert "node -e" in str(exc_info.value)

    @pytest.mark.parametrize("validation", [[], ["", "   "]])
    def test_falls_back_to_default_when_empty_or_blank(self, validation: list[str]) -> None:
        gene, _ = build({"content": LONG_CONTENT, "validation": validation})
        assert gene["validation"]
        assert all(sandbox_would_run(cmd) for cmd in gene["validation"])
