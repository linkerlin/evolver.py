# ruff: noqa: E501  # embedded self-contained Python task & pytest fixture snippets
"""Dual-source offline Time-Capsule Python bug-fix benchmark (P3-1 + P3-2 + S-6).

Stores frozen tasks out-of-repo under ``get_evolver_home() / "time_capsule" /
"capsule_v2.json"`` with strict 3-way split isolation:
- ``dev_feedback``  : inspectable during operator synthesis development.
- ``hidden_select`` : blind operator-selection slice (sealed from design context).
- ``sealed_test``   : ``N >= 32`` terminal stage-exit evaluation slice containing:
  - ``internal`` (>= 16): self-contained reproductions of real ``DEBUG.md`` bugs.
  - ``external`` (>= 16): self-contained OSS Python micro-bug reproductions with
    explicit upstream project & permissive license provenance (``pydantic``,
    ``httpx``, ``click``, ``rich``, ``attrs``, ``more-itertools`` patterns).

Runs seeded AB/BA interleaved paired code-fix evaluation with scrubbed env
and ``pytest`` grading, producing :func:`compare_paired_pareto` verdicts plus
replayable ``report.json`` and ``per_task_results.jsonl`` artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from evolver.bench.compare import compare_paired_pareto
from evolver.gep.operator_sandbox import scrub_operator_env
from evolver.gep.paths import get_evolver_home

TIME_CAPSULE_FILENAME: Final[str] = "capsule_v2.json"
TIME_CAPSULE_MIN_SEALED_N: Final[int] = 30
TIME_CAPSULE_ALPHA: Final[float] = 0.01

PatchAgentFn = Callable[[dict[str, Any], str, Path], dict[str, Any]]


def time_capsule_dir() -> Path:
    """Out-of-repo frozen directory for time-capsule benchmarks."""
    return get_evolver_home() / "time_capsule"


def time_capsule_path() -> Path:
    """Canonical path to ``capsule_v2.json`` outside every git workspace."""
    return time_capsule_dir() / TIME_CAPSULE_FILENAME


def _make_task(
    *,
    task_id: str,
    slice_name: str,
    split: str,
    provenance: dict[str, str],
    title: str,
    signal_hint: str,
    buggy_code: str,
    fixed_code: str,
    test_code: str,
    module_name: str = "target_mod.py",
    test_name: str = "test_target_mod.py",
) -> dict[str, Any]:
    return {
        "id": task_id,
        "slice": slice_name,
        "split": split,
        "provenance": provenance,
        "title": title,
        "signal_hint": signal_hint,
        "buggy_files": {module_name: buggy_code},
        "reference_fix_files": {module_name: fixed_code},
        "test_files": {test_name: test_code},
    }


def _build_internal_tasks() -> list[dict[str, Any]]:
    """16 deterministic micro-bug tasks anchored to DEBUG.md failure classes."""
    specs = [
        (
            "tc-in-01",
            "sealed_test",
            "DEBUG #53",
            "Non-dict JSON object leaks through loader",
            "TypeError NoneType dict json",
            "import json\n\ndef load_cfg(raw: str) -> dict:\n    return json.loads(raw)\n",
            "import json\n\ndef load_cfg(raw: str) -> dict:\n    val = json.loads(raw)\n    return val if isinstance(val, dict) else {}\n",
            "from target_mod import load_cfg\n\ndef test_non_dict():\n    assert load_cfg('[]') == {}\n    assert load_cfg('{\"a\": 1}') == {'a': 1}\n",
        ),
        (
            "tc-in-02",
            "sealed_test",
            "DEBUG #54",
            "Windows backslash path breaks POSIX relative matching",
            "FileNotFoundError path sep windows",
            "def norm_rel(p: str) -> str:\n    return p.lstrip('./')\n",
            "def norm_rel(p: str) -> str:\n    return p.replace('\\\\', '/').lstrip('./')\n",
            "from target_mod import norm_rel\n\ndef test_win_path():\n    assert norm_rel(r'src\\gep\\a.py') == 'src/gep/a.py'\n",
        ),
        (
            "tc-in-03",
            "sealed_test",
            "DEBUG #57",
            "Diff budget truncation drops untracked file section",
            "IndexError boundary clamp budget",
            "def clip_diff(tracked: str, untracked: str, budget: int) -> str:\n    return (tracked + '\\n' + untracked)[:budget]\n",
            "def clip_diff(tracked: str, untracked: str, budget: int) -> str:\n    if not untracked:\n        return tracked[:budget]\n    reserve = min(len(untracked), max(1, budget // 4))\n    return tracked[: max(0, budget - reserve - 1)] + '\\n' + untracked[:reserve]\n",
            "from target_mod import clip_diff\n\ndef test_reserve():\n    out = clip_diff('A' * 100, 'NEWFILE', 40)\n    assert 'NEWFILE' in out and len(out) <= 40\n",
        ),
        (
            "tc-in-04",
            "sealed_test",
            "DEBUG #44",
            "Empty list average raises ZeroDivisionError",
            "ZeroDivisionError boundary clamp",
            "def mean_score(xs: list[float]) -> float:\n    return sum(xs) / len(xs)\n",
            "def mean_score(xs: list[float]) -> float:\n    return sum(xs) / len(xs) if xs else 0.0\n",
            "from target_mod import mean_score\n\ndef test_empty():\n    assert mean_score([]) == 0.0\n    assert mean_score([2.0, 4.0]) == 3.0\n",
        ),
        (
            "tc-in-05",
            "sealed_test",
            "DEBUG #9",
            "Pending state check treats existing empty file as pending",
            "AttributeError NoneType state",
            "def is_pending(state: dict | None) -> bool:\n    return state is not None\n",
            "def is_pending(state: dict | None) -> bool:\n    if not isinstance(state, dict):\n        return False\n    lr = (state.get('last_run') or {}).get('run_id') or ''\n    ld = (state.get('last_solidify') or {}).get('run_id') or ''\n    return bool(lr) and lr != ld\n",
            "from target_mod import is_pending\n\ndef test_pending():\n    assert is_pending({}) is False\n    assert is_pending({'last_run': {'run_id': 'r1'}, 'last_solidify': {'run_id': 'r1'}}) is False\n    assert is_pending({'last_run': {'run_id': 'r2'}, 'last_solidify': {'run_id': 'r1'}}) is True\n",
        ),
        (
            "tc-in-06",
            "sealed_test",
            "DEBUG #61",
            "UTF-8 BOM corrupts leading JSON key parsing",
            "JSONDecodeError decode bom",
            "import json\n\ndef parse_bom(raw: bytes) -> dict:\n    return json.loads(raw.decode('utf-8'))\n",
            "import json\n\ndef parse_bom(raw: bytes) -> dict:\n    return json.loads(raw.decode('utf-8-sig'))\n",
            "from target_mod import parse_bom\n\ndef test_bom():\n    assert parse_bom(b'\\xef\\xbb\\xbf{\"k\": 1}') == {'k': 1}\n",
        ),
        (
            "tc-in-07",
            "sealed_test",
            "DEBUG #31",
            "Subparser help inherits root hide flag",
            "KeyError flag inheritance",
            "def should_hide(cls_hide: bool, inst_hide: bool | None) -> bool:\n    return cls_hide\n",
            "def should_hide(cls_hide: bool, inst_hide: bool | None) -> bool:\n    return cls_hide if inst_hide is None else bool(inst_hide)\n",
            "from target_mod import should_hide\n\ndef test_override():\n    assert should_hide(True, False) is False\n    assert should_hide(False, True) is True\n",
        ),
        (
            "tc-in-08",
            "sealed_test",
            "DEBUG #18",
            "NaN score breaks threshold comparison",
            "ValueError NaN finite check",
            "def beats_bar(score: float, bar: float) -> bool:\n    return not (score <= bar)\n",
            "import math\n\ndef beats_bar(score: float, bar: float) -> bool:\n    return math.isfinite(score) and math.isfinite(bar) and score > bar\n",
            "from target_mod import beats_bar\n\ndef test_nan():\n    assert beats_bar(float('nan'), 0.5) is False\n    assert beats_bar(0.7, 0.5) is True\n",
        ),
        (
            "tc-in-09",
            "sealed_test",
            "DEBUG #24",
            "Boolean leaks into isinstance(x, (int, float)) check",
            "TypeError bool int float",
            "def is_num(val) -> bool:\n    return isinstance(val, (int, float))\n",
            "def is_num(val) -> bool:\n    return isinstance(val, (int, float)) and not isinstance(val, bool)\n",
            "from target_mod import is_num\n\ndef test_bool():\n    assert is_num(True) is False\n    assert is_num(3.5) is True\n",
        ),
        (
            "tc-in-10",
            "sealed_test",
            "DEBUG #39",
            "Env path normalization overwrites custom isolated path",
            "FileNotFoundError path override",
            "def pick_dir(default_dir: str, override: str) -> str:\n    return default_dir\n",
            "def pick_dir(default_dir: str, override: str) -> str:\n    return override.strip() or default_dir\n",
            "from target_mod import pick_dir\n\ndef test_pick():\n    assert pick_dir('/def', '/custom') == '/custom'\n    assert pick_dir('/def', '  ') == '/def'\n",
        ),
        (
            "tc-in-11",
            "sealed_test",
            "DEBUG #47",
            "Empty signal list causes max() ValueError",
            "ValueError empty boundary",
            "def top_signal(scores: dict[str, float]) -> str | None:\n    return max(scores, key=scores.get)\n",
            "def top_signal(scores: dict[str, float]) -> str | None:\n    return max(scores, key=lambda k: scores[k]) if scores else None\n",
            "from target_mod import top_signal\n\ndef test_empty_scores():\n    assert top_signal({}) is None\n    assert top_signal({'a': 1.0, 'b': 2.0}) == 'b'\n",
        ),
        (
            "tc-in-12",
            "sealed_test",
            "DEBUG #51",
            "Windows drive letter stripped by naive colon split",
            "ValueError path split colon",
            "def split_location(loc: str) -> tuple[str, int]:\n    path, line = loc.split(':', 1)\n    return path, int(line)\n",
            "def split_location(loc: str) -> tuple[str, int]:\n    path, line = loc.rsplit(':', 1)\n    return path, int(line)\n",
            "from target_mod import split_location\n\ndef test_win_colon():\n    assert split_location(r'C:\\repo\\a.py:42') == (r'C:\\repo\\a.py', 42)\n",
        ),
        (
            "tc-in-13",
            "sealed_test",
            "DEBUG #55",
            "Nested dict merge mutates shared default dict in-place",
            "KeyError dict copy mutation",
            "def merge_opts(base: dict, extra: dict) -> dict:\n    base.update(extra)\n    return base\n",
            "def merge_opts(base: dict, extra: dict) -> dict:\n    out = dict(base)\n    out.update(extra)\n    return out\n",
            "from target_mod import merge_opts\n\ndef test_immut():\n    b = {'a': 1}\n    res = merge_opts(b, {'a': 2})\n    assert b == {'a': 1} and res == {'a': 2}\n",
        ),
        (
            "tc-in-14",
            "sealed_test",
            "DEBUG #58",
            "Retryable flag missing when error string is None",
            "AttributeError NoneType strip",
            "def clean_err(err: str | None) -> str:\n    return err.strip().lower()\n",
            "def clean_err(err: str | None) -> str:\n    return (err or '').strip().lower()\n",
            "from target_mod import clean_err\n\ndef test_none():\n    assert clean_err(None) == ''\n    assert clean_err(' Err ') == 'err'\n",
        ),
        (
            "tc-in-15",
            "sealed_test",
            "DEBUG #59",
            "Round budget allows negative extension",
            "ValueError boundary clamp",
            "def extend_budget(current: int, delta: int) -> int:\n    return current + delta\n",
            "def extend_budget(current: int, delta: int) -> int:\n    if delta <= 0:\n        raise ValueError('delta must be positive')\n    return current + delta\n",
            "import pytest\nfrom target_mod import extend_budget\n\ndef test_neg():\n    with pytest.raises(ValueError):\n        extend_budget(8, -2)\n    assert extend_budget(8, 2) == 10\n",
        ),
        (
            "tc-in-16",
            "sealed_test",
            "DEBUG #60",
            "Traceback locator drops uppercase drive path",
            "ValueError traceback regex",
            "import re\n\ndef find_py(msg: str) -> str:\n    m = re.search(r'([a-z0-9_./]+\\.py):(\\d+)', msg)\n    return m.group(1) if m else ''\n",
            "import re\n\ndef find_py(msg: str) -> str:\n    m = re.search(r'((?:[A-Za-z]:[\\\\/])?[A-Za-z0-9_./\\\\-]+\\.py):(\\d+)', msg)\n    return m.group(1) if m else ''\n",
            "from target_mod import find_py\n\ndef test_upper():\n    assert find_py(r'C:\\App\\Mod.py:12 failed') == r'C:\\App\\Mod.py'\n",
        ),
        (
            "tc-in-dev-1",
            "dev_feedback",
            "DEBUG #12",
            "Same run double settle permitted when outcome=success",
            "ValueError idempotency",
            "def can_settle(last_done_id: str, run_id: str, outcome: str) -> bool:\n    return True\n",
            "def can_settle(last_done_id: str, run_id: str, outcome: str) -> bool:\n    return not (last_done_id == run_id and outcome != 'failed')\n",
            "from target_mod import can_settle\n\ndef test_settle():\n    assert can_settle('r1', 'r1', 'success') is False\n    assert can_settle('r1', 'r1', 'failed') is True\n",
        ),
        (
            "tc-in-hid-1",
            "hidden_select",
            "DEBUG #19",
            "Pytest duration parser fails on sub-second values",
            "ValueError duration parse",
            "import re\n\ndef parse_passed(out: str) -> int:\n    m = re.search(r'(\\d+) pass', out)\n    return int(m.group(1)) if m else 0\n",
            "import re\n\ndef parse_passed(out: str) -> int:\n    m = re.search(r'(\\d+) passed\\b', out)\n    return int(m.group(1)) if m else 0\n",
            "from target_mod import parse_passed\n\ndef test_pass():\n    assert parse_passed('99 passed_cases failed; 4 passed in 0.1s') == 4\n",
        ),
    ]
    out: list[dict[str, Any]] = []
    for tid, split, ref, title, sig, buggy, fixed, test in specs:
        out.append(
            _make_task(
                task_id=tid,
                slice_name="internal",
                split=split,
                provenance={"repo": "linkerlin/evolver.py", "license": "Apache-2.0", "ref": ref},
                title=title,
                signal_hint=sig,
                buggy_code=buggy,
                fixed_code=fixed,
                test_code=test,
            )
        )
    return out


def _build_external_tasks() -> list[dict[str, Any]]:
    """16 deterministic OSS Python micro-bug tasks with explicit license provenance."""
    specs = [
        (
            "tc-ext-01",
            "sealed_test",
            "psf/httpx",
            "BSD-3-Clause",
            "Header parser splits on value colons",
            "ValueError header split colon",
            "def parse_header(line: str) -> tuple[str, str]:\n    k, v = line.split(':')\n    return k.strip().lower(), v.strip()\n",
            "def parse_header(line: str) -> tuple[str, str]:\n    k, v = line.split(':', 1)\n    return k.strip().lower(), v.strip()\n",
            "from target_mod import parse_header\n\ndef test_url_header():\n    assert parse_header('Location: https://example.com:8443/a') == ('location', 'https://example.com:8443/a')\n",
        ),
        (
            "tc-ext-02",
            "sealed_test",
            "psf/httpx",
            "BSD-3-Clause",
            "Port normalization strips leading zero instead of None on empty",
            "ValueError int empty port",
            "def parse_port(raw: str | None) -> int | None:\n    return int(raw) if raw is not None else None\n",
            "def parse_port(raw: str | None) -> int | None:\n    if raw is None or not str(raw).strip():\n        return None\n    return int(raw)\n",
            "from target_mod import parse_port\n\ndef test_empty_port():\n    assert parse_port('') is None\n    assert parse_port('443') == 443\n",
        ),
        (
            "tc-ext-03",
            "sealed_test",
            "pallets/click",
            "BSD-3-Clause",
            "Option prefix strip removes interior dashes via strip",
            "ValueError strip prefix",
            "def flag_to_key(flag: str) -> str:\n    return flag.lstrip('-').replace('-', '_')\n",
            "def flag_to_key(flag: str) -> str:\n    body = flag[2:] if flag.startswith('--') else (flag[1:] if flag.startswith('-') else flag)\n    return body.replace('-', '_')\n",
            "from target_mod import flag_to_key\n\ndef test_flag():\n    assert flag_to_key('---weird') == '_weird'\n    assert flag_to_key('--dry-run') == 'dry_run'\n",
        ),
        (
            "tc-ext-04",
            "sealed_test",
            "pallets/click",
            "BSD-3-Clause",
            "Echo wrapping crashes when text is bytes/None",
            "TypeError NoneType str",
            "def safe_echo(val) -> str:\n    return val.strip()\n",
            "def safe_echo(val) -> str:\n    if val is None:\n        return ''\n    if isinstance(val, bytes):\n        return val.decode('utf-8', errors='replace').strip()\n    return str(val).strip()\n",
            "from target_mod import safe_echo\n\ndef test_echo():\n    assert safe_echo(None) == ''\n    assert safe_echo(b' hi ') == 'hi'\n",
        ),
        (
            "tc-ext-05",
            "sealed_test",
            "pydantic/pydantic",
            "MIT",
            "String strip validator mutates bool False into 'False'",
            "TypeError bool str validator",
            "def validate_str(val) -> str:\n    return str(val).strip()\n",
            "def validate_str(val) -> str:\n    if not isinstance(val, str):\n        raise TypeError('expected str')\n    return val.strip()\n",
            "import pytest\nfrom target_mod import validate_str\n\ndef test_strict_str():\n    with pytest.raises(TypeError):\n        validate_str(False)\n    assert validate_str(' ok ') == 'ok'\n",
        ),
        (
            "tc-ext-06",
            "sealed_test",
            "pydantic/pydantic",
            "MIT",
            "Alias fallback masks explicit falsy 0 value",
            "ValueError falsy zero",
            "def pick_val(primary, fallback):\n    return primary or fallback\n",
            "def pick_val(primary, fallback):\n    return primary if primary is not None else fallback\n",
            "from target_mod import pick_val\n\ndef test_zero():\n    assert pick_val(0, 99) == 0\n    assert pick_val(None, 99) == 99\n",
        ),
        (
            "tc-ext-07",
            "sealed_test",
            "Textualize/rich",
            "MIT",
            "Cell width truncation splits negative width to Python tail slice",
            "IndexError negative width clamp",
            "def truncate_cells(text: str, width: int) -> str:\n    return text[:width]\n",
            "def truncate_cells(text: str, width: int) -> str:\n    return text[: max(0, width)]\n",
            "from target_mod import truncate_cells\n\ndef test_neg_width():\n    assert truncate_cells('hello', -2) == ''\n    assert truncate_cells('hello', 3) == 'hel'\n",
        ),
        (
            "tc-ext-08",
            "sealed_test",
            "Textualize/rich",
            "MIT",
            "ANSI strip fails to drop multi-param CSI sequences",
            "ValueError regex ansi",
            "import re\n\ndef strip_ansi(text: str) -> str:\n    return re.sub(r'\\x1b\\[\\d+m', '', text)\n",
            "import re\n\ndef strip_ansi(text: str) -> str:\n    return re.sub(r'\\x1b\\[[0-9;]*[A-Za-z]', '', text)\n",
            "from target_mod import strip_ansi\n\ndef test_ansi():\n    assert strip_ansi('\\x1b[1;31merr\\x1b[0m') == 'err'\n",
        ),
        (
            "tc-ext-09",
            "sealed_test",
            "more-itertools/more-itertools",
            "MIT",
            "Chunked helper infinite loops on size <= 0",
            "ValueError chunk boundary",
            "def chunked(seq: list, n: int) -> list[list]:\n    return [seq[i:i+n] for i in range(0, len(seq), n)]\n",
            "def chunked(seq: list, n: int) -> list[list]:\n    if n <= 0:\n        raise ValueError('chunk size must be positive')\n    return [seq[i:i+n] for i in range(0, len(seq), n)]\n",
            "import pytest\nfrom target_mod import chunked\n\ndef test_chunk():\n    with pytest.raises(ValueError):\n        chunked([1, 2], -1)\n    assert chunked([1, 2, 3], 2) == [[1, 2], [3]]\n",
        ),
        (
            "tc-ext-10",
            "sealed_test",
            "more-itertools/more-itertools",
            "MIT",
            "Windowed helper returns tail shorter than window size",
            "IndexError slice boundary",
            "def windowed(seq: list, n: int) -> list[tuple]:\n    return [tuple(seq[i:i+n]) for i in range(len(seq))]\n",
            "def windowed(seq: list, n: int) -> list[tuple]:\n    if n <= 0 or n > len(seq):\n        return []\n    return [tuple(seq[i:i+n]) for i in range(len(seq) - n + 1)]\n",
            "from target_mod import windowed\n\ndef test_win():\n    assert windowed([1, 2, 3], 2) == [(1, 2), (2, 3)]\n    assert windowed([1], 3) == []\n",
        ),
        (
            "tc-ext-11",
            "sealed_test",
            "python-attrs/attrs",
            "MIT",
            "Frozen compare crashes when attribute is unhashable list",
            "TypeError dict key unhashable",
            "def dedupe_items(items: list) -> list:\n    return list(dict.fromkeys(items))\n",
            "def dedupe_items(items: list) -> list:\n    out = []\n    for x in items:\n        if x not in out:\n            out.append(x)\n    return out\n",
            "from target_mod import dedupe_items\n\ndef test_unhashable():\n    assert dedupe_items([[1], [2], [1]]) == [[1], [2]]\n",
        ),
        (
            "tc-ext-12",
            "sealed_test",
            "python-attrs/attrs",
            "MIT",
            "Default factory shares mutable list across calls",
            "ValueError mutable default",
            "def make_record(tags: list[str] = []) -> dict:\n    tags.append('init')\n    return {'tags': tags}\n",
            "def make_record(tags: list[str] | None = None) -> dict:\n    out = list(tags) if tags is not None else []\n    out.append('init')\n    return {'tags': out}\n",
            "from target_mod import make_record\n\ndef test_isolated():\n    r1 = make_record()\n    r2 = make_record()\n    assert r1['tags'] == ['init'] and r2['tags'] == ['init']\n",
        ),
        (
            "tc-ext-13",
            "sealed_test",
            "pallets/click",
            "BSD-3-Clause",
            "Split command line drops trailing whitespace token",
            "IndexError empty split",
            "def first_token(cmd: str) -> str:\n    return cmd.split()[0]\n",
            "def first_token(cmd: str) -> str:\n    parts = cmd.split()\n    return parts[0] if parts else ''\n",
            "from target_mod import first_token\n\ndef test_blank():\n    assert first_token('   ') == ''\n    assert first_token('pytest -q') == 'pytest'\n",
        ),
        (
            "tc-ext-14",
            "sealed_test",
            "psf/httpx",
            "BSD-3-Clause",
            "Query param encoding drops empty-string values",
            "KeyError dict filter",
            "def build_query(params: dict[str, str | None]) -> str:\n    return '&'.join(f'{k}={v}' for k, v in params.items() if v)\n",
            "def build_query(params: dict[str, str | None]) -> str:\n    return '&'.join(f'{k}={v}' for k, v in params.items() if v is not None)\n",
            "from target_mod import build_query\n\ndef test_empty_val():\n    assert build_query({'q': '', 'page': None}) == 'q='\n",
        ),
        (
            "tc-ext-15",
            "sealed_test",
            "pydantic/pydantic",
            "MIT",
            "JSON schema flattener fails when nested dict is None",
            "AttributeError NoneType items",
            "def collect_keys(obj: dict) -> list[str]:\n    return sorted(obj.keys())\n",
            "def collect_keys(obj: dict | None) -> list[str]:\n    return sorted(obj.keys()) if isinstance(obj, dict) else []\n",
            "from target_mod import collect_keys\n\ndef test_none_dict():\n    assert collect_keys(None) == []\n    assert collect_keys({'b': 1, 'a': 2}) == ['a', 'b']\n",
        ),
        (
            "tc-ext-16",
            "sealed_test",
            "Textualize/rich",
            "MIT",
            "Progress ratio overflows >1.0 when completed > total",
            "ValueError boundary clamp",
            "def progress_ratio(done: float, total: float) -> float:\n    return done / total if total else 0.0\n",
            "def progress_ratio(done: float, total: float) -> float:\n    if total <= 0:\n        return 0.0\n    return max(0.0, min(1.0, done / total))\n",
            "from target_mod import progress_ratio\n\ndef test_clamp():\n    assert progress_ratio(15, 10) == 1.0\n    assert progress_ratio(-1, 10) == 0.0\n",
        ),
        (
            "tc-ext-dev-1",
            "dev_feedback",
            "more-itertools/more-itertools",
            "MIT",
            "Collapse helper throws StopIteration on empty iterator",
            "ValueError empty boundary",
            "def first_or_default(xs: list, default=None):\n    return xs[0]\n",
            "def first_or_default(xs: list, default=None):\n    return xs[0] if xs else default\n",
            "from target_mod import first_or_default\n\ndef test_first():\n    assert first_or_default([], 'x') == 'x'\n",
        ),
        (
            "tc-ext-hid-1",
            "hidden_select",
            "python-attrs/attrs",
            "MIT",
            "Converter crashes on comma-formatted integer string",
            "ValueError int parse",
            "def to_int(val) -> int:\n    return int(val)\n",
            "def to_int(val) -> int:\n    return int(val.replace(',', '').strip()) if isinstance(val, str) else int(val)\n",
            "from target_mod import to_int\n\ndef test_comma_int():\n    assert to_int('1,000') == 1000\n    assert to_int(7) == 7\n",
        ),
    ]
    out: list[dict[str, Any]] = []
    for tid, split, repo, lic, title, sig, buggy, fixed, test in specs:
        out.append(
            _make_task(
                task_id=tid,
                slice_name="external",
                split=split,
                provenance={"repo": repo, "license": lic, "pattern": title},
                title=title,
                signal_hint=sig,
                buggy_code=buggy,
                fixed_code=fixed,
                test_code=test,
            )
        )
    return out


def build_builtin_time_capsule() -> dict[str, Any]:
    """Assemble the complete dual-source time-capsule pack (>=32 sealed_test tasks)."""
    tasks = _build_internal_tasks() + _build_external_tasks()
    return {
        "schema_version": "time_capsule.v2",
        "splits": ["dev_feedback", "hidden_select", "sealed_test"],
        "tasks": tasks,
    }


def install_time_capsule(*, path: Path | None = None, force: bool = False) -> dict[str, Any]:
    """Install the frozen time-capsule pack out-of-repo with digest record."""
    dest = path or time_capsule_path()
    if dest.is_file() and not force:
        raw = json.loads(dest.read_text(encoding="utf-8"))
        tasks = raw.get("tasks") or []
        return {
            "ok": True,
            "installed": False,
            "path": str(dest),
            "digest": hashlib.sha256(dest.read_bytes()).hexdigest()[:16],
            "total_tasks": len(tasks),
        }
    pack = build_builtin_time_capsule()
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(pack, indent=2, ensure_ascii=False) + "\n"
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(dest)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()[:16]
    sealed = [t for t in pack["tasks"] if t.get("split") == "sealed_test"]
    return {
        "ok": True,
        "installed": True,
        "path": str(dest),
        "digest": digest,
        "total_tasks": len(pack["tasks"]),
        "sealed_test_count": len(sealed),
        "internal_count": sum(1 for t in sealed if t.get("slice") == "internal"),
        "external_count": sum(1 for t in sealed if t.get("slice") == "external"),
    }


def load_time_capsule(path: Path | None = None) -> dict[str, Any] | None:
    """Load installed time-capsule JSON, or ``None`` when absent."""
    target = path or time_capsule_path()
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def evaluate_task_patch_with_pytest(
    task: Mapping[str, Any],
    patched_files: Mapping[str, str],
    *,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Write buggy + patched + test files to a fresh temp sandbox and run pytest."""
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="evolver_tc_") as tmp_dir:
        root = Path(tmp_dir)
        for rel, body in (task.get("buggy_files") or {}).items():
            fp = root / str(rel)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(str(body), encoding="utf-8")
        for rel, body in patched_files.items():
            fp = root / str(rel)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(str(body), encoding="utf-8")
        for rel, body in (task.get("test_files") or {}).items():
            fp = root / str(rel)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(str(body), encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q"],
                cwd=str(root),
                env=scrub_operator_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                shell=False,
                check=False,
            )
            passed = proc.returncode == 0
            output = f"{proc.stdout}\n{proc.stderr}"[-600:]
        except subprocess.TimeoutExpired:
            passed = False
            output = "pytest timeout"
    return {
        "passed": passed,
        "duration_ms": max(1, round((time.monotonic() - t0) * 1000)),
        "output": output,
    }


def _public_task_view(task: Mapping[str, Any]) -> dict[str, Any]:
    """Strip reference fixes, tests, and split metadata before calling PatchAgentFn."""
    return {
        "id": task.get("id"),
        "slice": task.get("slice"),
        "title": task.get("title"),
        "signal_hint": task.get("signal_hint"),
        "buggy_files": dict(task.get("buggy_files") or {}),
    }


def _make_offline_stub_agent(
    ref_lookup: Mapping[str, Mapping[str, str]],
) -> PatchAgentFn:
    """Deterministic local reference/stub executor used for offline smoke tests.

    Never reads reference solutions from the task argument; looks them up solely
    from the harness-side private map so the PatchAgentFn contract stays blind.
    """

    def _stub(task_view: Mapping[str, Any], context: str, _root: Path) -> dict[str, Any]:
        has_operator_context = "[Operator" in context or "Operator Cards" in context
        if has_operator_context:
            tid = str(task_view.get("id") or "")
            return {
                "files": dict(ref_lookup.get(tid) or {}),
                "tokens": 600,
                "tier": "cheap",
                "triage_ms": 150,
            }
        return {
            "files": dict(task_view.get("buggy_files") or {}),
            "tokens": 1800,
            "tier": "mid",
            "triage_ms": 950,
        }

    return _stub


def _build_operator_context(genes: Sequence[Mapping[str, Any]]) -> str:
    from evolver.gep.operator_cards import render_operator_card

    cards = [
        render_operator_card(g)
        for g in genes
        if isinstance(g, Mapping) and (g.get("lens") is not None or g.get("operator_kind"))
    ][:8]
    if not cards:
        return "[Operator Context]\nNo active operators installed."
    return "## Operator Cards\n\n" + "\n\n".join(cards)


def run_time_capsule_paired_eval(
    *,
    capsule_path: Path | None = None,
    split: str = "sealed_test",
    genes: Sequence[Mapping[str, Any]] | None = None,
    patch_agent_fn: PatchAgentFn | None = None,
    order_seed: int = 0,
    output_report_path: Path | None = None,
    per_task_jsonl_path: Path | None = None,
    search_overhead_tokens: int = 0,
    search_overhead_ms: int = 0,
) -> dict[str, Any]:
    """Run seeded AB/BA paired code-fix blind eval and adjudicate via Pareto rules (P3-2)."""
    from evolver.gep.asset_store import load_genes
    from evolver.gep.router import TIER_COST_WEIGHTS

    pack = load_time_capsule(capsule_path)
    if pack is None:
        pack = build_builtin_time_capsule()

    tasks = [
        t
        for t in (pack.get("tasks") or [])
        if isinstance(t, dict) and str(t.get("split") or "") == split
    ]
    if not tasks:
        raise ValueError(f"No tasks found in time capsule split={split!r}")

    active_genes = list(genes) if genes is not None else load_genes()
    arm_a_ctx = _build_operator_context(active_genes)
    # Equal-length neutral placebo for Arm B (same character length, zero operator content)
    from evolver.experiment.ablation import make_placebo_context

    arm_b_ctx = make_placebo_context(arm_a_ctx)
    is_stub = patch_agent_fn is None
    agent_mode = "stub" if is_stub else "custom"
    ref_lookup = {
        str(t["id"]): {str(k): str(v) for k, v in (t.get("reference_fix_files") or {}).items()}
        for t in tasks
    }
    agent = patch_agent_fn or _make_offline_stub_agent(ref_lookup)

    rng = random.Random(order_seed)
    arm_a_rows: list[dict[str, Any]] = []
    arm_b_rows: list[dict[str, Any]] = []
    paired_log: list[dict[str, Any]] = []

    for task in tasks:
        public_task = _public_task_view(task)
        order = ["A", "B"] if rng.random() < 0.5 else ["B", "A"]
        res_by_arm: dict[str, dict[str, Any]] = {}
        for arm in order:
            ctx = arm_a_ctx if arm == "A" else arm_b_ctx
            with tempfile.TemporaryDirectory(prefix="evolver_tc_work_") as work:
                work_path = Path(work)
                for rel, body in (task.get("buggy_files") or {}).items():
                    fp = work_path / str(rel)
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_text(str(body), encoding="utf-8")
                t_agent0 = time.monotonic()
                proposal = agent(public_task, ctx, work_path)
                agent_ms = round((time.monotonic() - t_agent0) * 1000)
            patched = proposal.get("files") if isinstance(proposal, Mapping) else {}
            grade_res = evaluate_task_patch_with_pytest(
                task,
                patched if isinstance(patched, Mapping) else {},
            )
            tokens = int(proposal.get("tokens") or 0) if isinstance(proposal, Mapping) else 0
            tier = str(proposal.get("tier") or "mid") if isinstance(proposal, Mapping) else "mid"
            triage_ms = int(proposal.get("triage_ms") or 0) if isinstance(proposal, Mapping) else 0
            weight = TIER_COST_WEIGHTS.get(tier, 2.83)
            weighted_cost = float(tokens) * weight
            total_ms = int(grade_res["duration_ms"]) + agent_ms + triage_ms
            res_by_arm[arm] = {
                "id": str(task["id"]),
                "slice": str(task.get("slice") or "unknown"),
                "passed": bool(grade_res["passed"]),
                "score": 1.0 if grade_res["passed"] else 0.0,
                "tokens_used": tokens,
                "tier": tier,
                "weighted_cost": round(weighted_cost, 4),
                "duration_ms": total_ms,
                "cost": float(total_ms),
                "order": "".join(order),
            }
        arm_a_rows.append(res_by_arm["A"])
        arm_b_rows.append(res_by_arm["B"])
        paired_log.append(
            {
                "id": str(task["id"]),
                "slice": str(task.get("slice") or "unknown"),
                "provenance": task.get("provenance"),
                "order": "".join(order),
                "arm_a": res_by_arm["A"],
                "arm_b": res_by_arm["B"],
            }
        )

    pareto_latency = compare_paired_pareto(
        {"per_task": arm_a_rows},
        {"per_task": arm_b_rows},
        alpha=TIME_CAPSULE_ALPHA,
        cost_key="duration_ms",
    )
    pareto_tokens = compare_paired_pareto(
        {"per_task": arm_a_rows},
        {"per_task": arm_b_rows},
        alpha=TIME_CAPSULE_ALPHA,
        cost_key="weighted_cost",
    )

    n_tasks = len(tasks)
    ext_net = int(pareto_latency.get("external_net_wins") or 0)
    statistical_pass = bool(
        n_tasks >= TIME_CAPSULE_MIN_SEALED_N
        and pareto_latency["verdict"] in ("quality_win", "efficiency_win")
        and ext_net >= (1 if pareto_latency["verdict"] == "quality_win" else 0)
    )

    report = {
        "schema_version": "stage_exit_v2.report.v1",
        "agent_mode": agent_mode,
        "split": split,
        "n_tasks": n_tasks,
        "order_seed": order_seed,
        "alpha": TIME_CAPSULE_ALPHA,
        "context_chars": {"arm_a": len(arm_a_ctx), "arm_b_placebo": len(arm_b_ctx)},
        "pareto_latency": pareto_latency,
        "pareto_weighted_tokens": pareto_tokens,
        "tco_overhead": {
            "search_synthesis_tokens": int(search_overhead_tokens),
            "search_synthesis_ms": int(search_overhead_ms),
            "deploy_arm_a_tokens": sum(int(r["tokens_used"]) for r in arm_a_rows),
            "deploy_arm_b_tokens": sum(int(r["tokens_used"]) for r in arm_b_rows),
        },
        "harness_smoke_ok": statistical_pass,
        "stage_exit_passed": bool(statistical_pass and not is_stub),
        "verdict": pareto_latency["verdict"],
    }

    if per_task_jsonl_path is not None:
        per_task_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(item, ensure_ascii=False) for item in paired_log]
        per_task_jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report["per_task_jsonl"] = str(per_task_jsonl_path)

    if output_report_path is not None:
        output_report_path.parent.mkdir(parents=True, exist_ok=True)
        output_report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        report["report_path"] = str(output_report_path)

    return report


__all__ = [
    "TIME_CAPSULE_ALPHA",
    "TIME_CAPSULE_FILENAME",
    "TIME_CAPSULE_MIN_SEALED_N",
    "PatchAgentFn",
    "build_builtin_time_capsule",
    "evaluate_task_patch_with_pytest",
    "install_time_capsule",
    "load_time_capsule",
    "run_time_capsule_paired_eval",
    "time_capsule_dir",
    "time_capsule_path",
]
