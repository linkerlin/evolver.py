"""Mechanical private-literal leakage audit for Skill-derived Genes.

Equivalent to ``evolver/src/gep/skill2gepAudit.js``.  Public literals already
present in ``SKILL.md`` remain usable; hard literals seen only in hidden run
output are reported or generalized.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator
from typing import Any

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_QUOTED_RE = re.compile(r"""['"]([^'"]{2,64})['"]""")
_CODE_SPAN_RE = re.compile(r"(?<!`)`([^`\n]{2,80})`(?!`)")
_FLAG_RE = re.compile(r"--[a-z][a-z0-9_-]*[a-z0-9]", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_BARE_STRUCTURED_RE = re.compile(
    r"(?<![A-Za-z0-9_./\\-])[A-Za-z0-9][A-Za-z0-9_./\\-]{1,80}"
    r"(?![A-Za-z0-9_./\\-])"
)
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "your",
        "you",
        "are",
        "not",
        "use",
        "using",
        "must",
        "should",
        "will",
        "can",
        "may",
        "any",
        "all",
        "each",
        "one",
        "two",
        "given",
        "input",
        "output",
        "value",
        "values",
        "result",
        "results",
        "return",
        "returns",
        "function",
        "functions",
        "code",
        "task",
        "tasks",
        "test",
        "tests",
        "assert",
        "import",
        "def",
        "class",
        "self",
        "true",
        "false",
        "none",
        "print",
        "data",
        "list",
        "dict",
        "string",
        "str",
        "int",
        "float",
        "bool",
        "file",
        "files",
        "path",
        "line",
        "lines",
        "answer",
        "analysis",
        "solution",
        "program",
        "python",
        "run",
        "running",
        "expected",
        "actual",
        "case",
        "cases",
        "example",
        "examples",
        "following",
        "above",
        "below",
        "number",
        "numbers",
        "set",
        "get",
        "name",
        "names",
        "format",
        "required",
        "exactly",
        "scenario",
        "problem",
        "compute",
        "calculate",
    }
)


def is_trivial_number(token: str) -> bool:
    if "." in token:
        return False
    try:
        value = int(token)
    except ValueError:
        return False
    return abs(value) < 10


def is_structured_literal(token: str) -> bool:
    value = str(token or "").strip()
    if not value:
        return False
    if _NUM_RE.fullmatch(value):
        return not is_trivial_number(value)
    return bool(
        value.startswith("--")
        or re.search(r"\d", value)
        or any(char in value for char in ("_", ".", "/", "\\"))
        or re.fullmatch(r"[A-Z][A-Z0-9_-]{2,}", value)
    )


def _alnum_count(value: str) -> int:
    return len(re.findall(r"[a-z0-9]", value, re.IGNORECASE))


def content_tokens(text: Any) -> dict[str, set[str]]:
    value = str(text or "")
    words = {
        match.group(0).lower()
        for match in _WORD_RE.finditer(value)
        if match.group(0).lower() not in _STOPWORDS
    }
    hard = {
        match.group(0)
        for match in _NUM_RE.finditer(value)
        if not is_trivial_number(match.group(0))
    }
    for pattern in (_QUOTED_RE, _CODE_SPAN_RE):
        for match in pattern.finditer(value):
            token = match.group(1).strip().lower()
            if (
                _alnum_count(token) >= 3
                and token not in _STOPWORDS
                and is_structured_literal(token)
            ):
                hard.add(token)
    hard.update(match.group(0).lower() for match in _FLAG_RE.finditer(value))
    return {"words": words, "hard": hard}


def public_hard_tokens(text: Any) -> set[str]:
    value = str(text or "")
    hard = set(content_tokens(value)["hard"])
    for match in _BARE_STRUCTURED_RE.finditer(value):
        token = match.group(0).strip("`'\".,:;()[]{}<>").lower()
        if (
            _alnum_count(token) >= 2
            and token not in _STOPWORDS
            and is_structured_literal(token)
        ):
            hard.add(token)
    return hard


def _hidden_blob(execution: dict[str, Any] | None) -> str:
    source = execution or {}
    parts = [
        str(source[key])
        for key in ("final_solution", "content_summary")
        if source.get(key)
    ]
    for trace in source.get("trace") or []:
        if isinstance(trace, dict):
            parts.extend(
                str(trace[key])
                for key in ("stdout_tail", "stderr_tail")
                if trace.get(key)
            )
    for rollout in source.get("rollouts") or []:
        if isinstance(rollout, dict) and rollout.get("feedback_tail"):
            parts.append(str(rollout["feedback_tail"]))
    parts.extend(str(value) for value in source.get("mutation_log") or [])
    return "\n".join(parts)


def build_private_vocab(skill_md: str, execution: dict[str, Any] | None) -> set[str]:
    public = public_hard_tokens(skill_md)
    hidden = content_tokens(_hidden_blob(execution))["hard"]
    return hidden - public


def iter_payload_strings(payload: dict[str, Any]) -> Iterator[tuple[str, str]]:
    for field in ("summary", "category"):
        if isinstance(payload.get(field), str):
            yield field, payload[field]
    for field in ("signals_match", "strategy", "preconditions", "avoid", "validation"):
        values = payload.get(field)
        if isinstance(values, list):
            for index, value in enumerate(values):
                if isinstance(value, str):
                    yield f"{field}[{index}]", value
    source = payload.get("_source")
    errors = source.get("overcame_errors") if isinstance(source, dict) else None
    if isinstance(errors, list):
        for index, value in enumerate(errors):
            if isinstance(value, str):
                yield f"_source.overcame_errors[{index}]", value


def _token_pattern(token: str) -> re.Pattern[str]:
    escaped = re.escape(token)
    if re.search(r"[a-z]", token, re.IGNORECASE):
        return re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", re.IGNORECASE)
    return re.compile(rf"(?<![A-Za-z0-9_.]){escaped}(?![A-Za-z0-9_.])")


def find_leakage(
    payload: dict[str, Any],
    private_vocab: set[str] | None,
) -> list[dict[str, str]]:
    leaks: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for location, value in iter_payload_strings(payload):
        for token in private_vocab or set():
            key = (token, location)
            if _alnum_count(token) >= 2 and _token_pattern(token).search(value) and key not in seen:
                seen.add(key)
                leaks.append({"token": token, "location": location})
    return leaks


def _literal_replacement(token: str) -> str:
    if _NUM_RE.fullmatch(token):
        return "the task-specific numeric value"
    if any(char in token for char in ("/", "\\", ".")):
        return "the task-specified file or path"
    if "_" in token:
        return "the task-specific field"
    return "the task-specific term"


def redact_private_literals(
    payload: dict[str, Any],
    private_vocab: set[str] | None,
) -> dict[str, Any]:
    output = copy.deepcopy(payload)
    tokens = sorted(private_vocab or set(), key=len, reverse=True)

    def redact(value: str) -> str:
        result = value
        for token in tokens:
            result = _token_pattern(token).sub(_literal_replacement(token), result)
        return result

    for field in ("summary", "category"):
        if isinstance(output.get(field), str):
            output[field] = redact(output[field])
    for field in ("signals_match", "strategy", "preconditions", "avoid"):
        values = output.get(field)
        if isinstance(values, list):
            output[field] = [redact(value) if isinstance(value, str) else value for value in values]
    validations = output.get("validation")
    if isinstance(validations, list):
        output["validation"] = [
            command
            for command in validations
            if isinstance(command, str)
            and not any(_token_pattern(token).search(command) for token in tokens)
        ]
    source = output.get("_source")
    if isinstance(source, dict) and isinstance(source.get("overcame_errors"), list):
        source["overcame_errors"] = [
            redact(value) if isinstance(value, str) else value
            for value in source["overcame_errors"]
        ]
    summary = output.get("summary")
    if isinstance(summary, str) and len(summary) > 300:
        output["summary"] = summary[:297].rstrip() + "..."
    return output


__all__ = [
    "build_private_vocab",
    "content_tokens",
    "find_leakage",
    "is_structured_literal",
    "is_trivial_number",
    "iter_payload_strings",
    "public_hard_tokens",
    "redact_private_literals",
]
