"""Security contract tests for the node validation-command gate (v1.94.0).

Behavioral port of Node ``test/sandboxExecutor.security.test.js`` (GHSA-jxh8-
jh77-xh6g follow-up + issues #607/#608/#609). The gates here must agree
exactly with :func:`evolver.gep.policy_check.is_validation_command_allowed`.
"""

import pytest

from evolver.gep.policy_check import is_validation_command_allowed
from evolver.gep.validator.sandbox_executor import (
    ALLOWED_EXECUTABLES,
    BLOCKED_NODE_FLAGS,
    SCRIPTLESS_NODE_FLAGS,
    assert_node_command_safe,
    parse_command,
)


class TestParseCommand:
    def test_splits_simple_command(self) -> None:
        executable, args = parse_command("node index.js")
        assert executable == "node"
        assert args == ["index.js"]

    def test_quoted_args_with_spaces(self) -> None:
        executable, args = parse_command('node "my script.js" --flag value')
        assert executable == "node"
        assert args == ["my script.js", "--flag", "value"]

    @pytest.mark.parametrize(
        "bad",
        [
            "node idx.js; rm -rf /",
            "node idx.js && echo pwn",
            "node idx.js | tee pwn.log",
            "node idx.js `cat /etc/passwd`",
            "node idx.js $(cat /etc/passwd)",
            "node idx.js > /tmp/x",
            "node idx.js < /tmp/x",
            "node idx.js & background",
        ],
    )
    def test_rejects_shell_metacharacters(self, bad: str) -> None:
        with pytest.raises(ValueError, match="metacharacter"):
            parse_command(bad)

    def test_rejects_empty_and_non_string(self) -> None:
        with pytest.raises(ValueError):
            parse_command("")
        with pytest.raises(ValueError):
            parse_command(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            parse_command(123)  # type: ignore[arg-type]


class TestAllowlist:
    def test_only_node_allowed(self) -> None:
        assert sorted(ALLOWED_EXECUTABLES) == ["node"]

    def test_npm_npx_rejected(self) -> None:
        for binary in ("npm", "npx"):
            assert binary not in ALLOWED_EXECUTABLES, "lifecycle-script RCE class (GHSA)"

    def test_shell_and_arbitrary_binaries_rejected(self) -> None:
        for binary in ("bash", "sh", "zsh", "cmd", "python", "curl", "wget", "rm"):
            assert binary not in ALLOWED_EXECUTABLES


class TestBlockedFlags:
    def test_eval_require_class_flags_blocked(self) -> None:
        for flag in ("-e", "--eval", "-p", "--print", "-r", "--require", "--loader", "--import"):
            assert flag in BLOCKED_NODE_FLAGS

    def test_assert_rejects_inline_eval_flags(self) -> None:
        cases = [
            ["-e", "console.log(1)"],
            ["--eval=1+1"],
            ["-p", "1+1"],
            ["--require", "./preload.js", "script.js"],
        ]
        for args in cases:
            with pytest.raises(ValueError, match="node flag not allowed"):
                assert_node_command_safe("node", args)

    def test_rejects_node_with_no_positional_script(self) -> None:
        for args in ([], ["--no-warnings"]):
            with pytest.raises(ValueError, match="script file argument"):
                assert_node_command_safe("node", args)

    def test_noop_for_non_node_executables(self) -> None:
        assert_node_command_safe("npm", ["test"])
        assert_node_command_safe("npx", ["-y", "eslint", "."])

    def test_accepts_well_formed_invocations(self) -> None:
        for args in (
            ["index.js"],
            ["--no-warnings", "index.js"],
            ["scripts/validate-suite.js", "--quiet"],
        ):
            assert_node_command_safe("node", args)


class TestV194Hardening:
    """Issues #607/#608/#609: info-only commands must be runnable in the empty
    sandbox workdir; the eval/preload/inspector/watch class stays blocked."""

    @pytest.mark.parametrize("args", [["--version"], ["-v"], ["--help"], ["-h"]])
    def test_info_only_flags_allowed_without_script(self, args: list[str]) -> None:
        assert_node_command_safe("node", args)

    @pytest.mark.parametrize(
        "args",
        [
            ["-e", "1"],
            ["--eval", "1"],
            ["-p", "1"],
            ["--print", "1"],
            ["-r", "./p.js", "s.js"],
            ["--require=./p.js", "s.js"],
            ["--import", "./p.js", "s.js"],
            ["--loader", "./l.js", "s.js"],
            ["--env-file", ".env", "s.js"],
            ["--inspect", "s.js"],
            ["--inspect-brk", "s.js"],
            ["--watch", "s.js"],
            ["--watch-path", "./x", "s.js"],
            ["--conditions", "prod", "s.js"],
            ["-C", "prod", "s.js"],
        ],
    )
    def test_blocks_eval_preload_inspector_watch_flags(self, args: list[str]) -> None:
        with pytest.raises(ValueError, match="node flag not allowed"):
            assert_node_command_safe("node", args)

    def test_still_requires_script_for_non_info_flags(self) -> None:
        for args in ([], ["--no-warnings"]):
            with pytest.raises(ValueError, match="script file argument"):
                assert_node_command_safe("node", args)

    def test_gates_agree(self) -> None:
        """The publish-side gate and validator-side gate must never drift."""
        cases = [
            "node --version",
            "node -v",
            "node --help",
            "node validate.js",
            "node scripts/check.js --quiet",
            'node -e "1"',
            "node --eval x",
            "node -p x",
            "node -r ./p.js s.js",
            "node --require=./p.js s.js",
            "node --import ./p.js s.js",
            "node --loader ./l.js s.js",
            "node --env-file .env s.js",
            "node --inspect s.js",
            "node --inspect-brk s.js",
            "node --inspect-port=9229 s.js",
            'node "--inspect" check.js',
            'node "--require=./p.js" check.js',
            'node "-r" "./p.js" check.js',
            'node "--watch" check.js',
            "node --watch s.js",
            "node --watch-path ./x s.js",
            "node --conditions prod s.js",
            "node -C prod s.js",
            "node --no-warnings",
            "node --test",
        ]
        for cmd in cases:
            try:
                executable, args = parse_command(cmd)
                assert_node_command_safe(executable, args)
                sandbox_ok = True
            except ValueError:
                sandbox_ok = False
            assert sandbox_ok is is_validation_command_allowed(cmd), (
                f"gate disagreement for {cmd!r}: sandbox={sandbox_ok}"
            )

    def test_flag_sets_identical_and_disjoint(self) -> None:
        overlap = SCRIPTLESS_NODE_FLAGS & BLOCKED_NODE_FLAGS
        assert not overlap, f"flag in both sets: {sorted(overlap)}"
