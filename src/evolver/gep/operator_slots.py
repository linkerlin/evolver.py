"""AST structural deduplication & parameterizable slot overrides (S-1).

Ported and hardened for operator genes from Strategist's ``prompt_slots.py``
and ``search.py::structural_hash``:
- ``structural_hash(source)`` strips module-level ``META`` / ``OPERATOR_META``,
  docstrings, and literal strings (preserving f-string placeholder topology) so
  operators differing only in task-specific literals map to one canonical
  skeleton hash.
- ``list_operator_slots(source)`` numbers parameterizable string/f-string
  literals as ``s1, s2, ...`` in deterministic source order.
- ``apply_slot_overrides`` / ``render_with_overrides`` instantiate slot
  overrides in memory without mutating the canonical vault operator.
- ``deduplicate_or_bind_operator`` collapses duplicate skeletons into the
  canonical gene's ``slot_bindings`` instead of spawning clone genes.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

MIN_SLOT_CHARS: Final[int] = 4
_META_NAMES: Final[frozenset[str]] = frozenset({"META", "OPERATOR_META"})


def _literal_text(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    return ""


def _placeholders(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.JoinedStr):
        return []
    return [ast.unparse(v.value) for v in node.values if isinstance(v, ast.FormattedValue)]


def _is_docstring_stmt(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _is_meta_assign(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id in _META_NAMES for target in stmt.targets
    )


def structural_hash(source: str) -> str | None:
    """Return SHA-256 hex over code AST with metadata, docstrings, and literals elided."""
    if not isinstance(source, str) or not source.strip():
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    tree.body = [stmt for stmt in tree.body if not _is_meta_assign(stmt)]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and _is_docstring_stmt(node.body[0]):
                node.body = node.body[1:] or [ast.Pass()]

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            node.values = [v for v in node.values if isinstance(v, ast.FormattedValue)]

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""

    dumped = ast.dump(tree, annotate_fields=False, include_attributes=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _slot_nodes(tree: ast.Module, *, min_chars: int = MIN_SLOT_CHARS) -> list[ast.AST]:
    """Return parameterizable string / f-string AST nodes in deterministic source order."""
    parent: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node

    def ancestors(node: ast.AST) -> list[ast.AST]:
        chain: list[ast.AST] = []
        cur = node
        while id(cur) in parent:
            cur = parent[id(cur)]
            chain.append(cur)
        return chain

    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and _is_docstring_stmt(node.body[0]):
                expr_stmt = node.body[0]
                if isinstance(expr_stmt, ast.Expr):
                    docstrings.add(id(expr_stmt.value))

    def assigned_names(stmt: ast.AST) -> list[str]:
        if isinstance(stmt, ast.Assign):
            return [t.id for t in stmt.targets if isinstance(t, ast.Name)]
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            return [stmt.target.id]
        return []

    slots: list[ast.AST] = []
    for node in ast.walk(tree):
        is_string = isinstance(node, ast.JoinedStr) or (
            isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        if not is_string or id(node) in docstrings:
            continue
        up = parent.get(id(node))
        if isinstance(up, (ast.JoinedStr, ast.FormattedValue)):
            continue
        if isinstance(up, ast.Dict) and any(key is node for key in up.keys):
            continue
        if (
            isinstance(up, ast.Call)
            and isinstance(up.func, ast.Attribute)
            and isinstance(up.func.value, ast.Name)
            and up.func.value.id == "re"
        ):
            continue
        chain = ancestors(node)
        if any(any(m in assigned_names(a) for m in _META_NAMES) for a in chain):
            continue
        in_function = any(isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef)) for a in chain)
        module_constant = any(
            parent.get(id(a)) is tree and any(name.isupper() for name in assigned_names(a))
            for a in chain
        )
        if not (in_function or module_constant):
            continue
        if len(_literal_text(node).strip()) < min_chars:
            continue
        slots.append(node)

    slots.sort(key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0)))
    return slots


def _template_of(node: ast.AST) -> str:
    if isinstance(node, ast.JoinedStr):
        unparsed = ast.unparse(node)
        if unparsed.startswith(("f'", 'f"')):
            return str(ast.literal_eval(unparsed[1:]))
        return unparsed
    assert isinstance(node, ast.Constant)
    return str(node.value)


def _parse_template(text: str) -> ast.JoinedStr:
    node = ast.parse("f" + repr(text), mode="eval").body
    if not isinstance(node, ast.JoinedStr):
        node = ast.JoinedStr(values=[node])
    return node


def list_operator_slots(source: str, *, min_chars: int = MIN_SLOT_CHARS) -> list[dict[str, Any]]:
    """Return ``[{id, default, fstring, placeholders, line}]`` for *source*."""
    if not isinstance(source, str) or not source.strip():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[dict[str, Any]] = []
    for idx, node in enumerate(_slot_nodes(tree, min_chars=min_chars), 1):
        out.append(
            {
                "id": f"s{idx}",
                "default": _template_of(node),
                "fstring": isinstance(node, ast.JoinedStr),
                "placeholders": sorted(set(_placeholders(node))),
                "line": int(getattr(node, "lineno", 0)),
            }
        )
    return out


def validate_slot_overrides(
    source: str,
    overrides: Any,
    *,
    min_chars: int = MIN_SLOT_CHARS,
) -> list[str]:
    """Return validation problems for *overrides* against *source* (empty when valid)."""
    if not overrides:
        return []
    if not isinstance(overrides, Mapping):
        return ["`slots` must be a mapping from slot id (`s1`, `s2`, ...) to replacement text"]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"operator source does not parse: {exc}"]

    nodes = {f"s{i}": n for i, n in enumerate(_slot_nodes(tree, min_chars=min_chars), 1)}
    problems: list[str] = []
    for key, text in overrides.items():
        node = nodes.get(str(key))
        if node is None:
            avail = ", ".join(nodes) or "no slots"
            problems.append(f"unknown slot `{key}` (available: {avail})")
            continue
        if not isinstance(text, str) or not text.strip():
            problems.append(f"slot `{key}`: replacement must be a non-empty string")
            continue
        if isinstance(node, ast.JoinedStr):
            try:
                new_node = _parse_template(text)
            except SyntaxError:
                problems.append(f"slot `{key}`: invalid f-string template")
                continue
            want = sorted(set(_placeholders(node)))
            got = sorted(set(_placeholders(new_node)))
            if want != got:
                want_fmt = ", ".join("{" + p + "}" for p in want) or "none"
                got_fmt = ", ".join("{" + p + "}" for p in got) or "none"
                problems.append(
                    f"slot `{key}`: must preserve placeholders ({want_fmt}), got ({got_fmt})"
                )
    return problems


class _SlotReplacer(ast.NodeTransformer):
    def __init__(self, mapping: dict[int, ast.AST]) -> None:
        self.mapping = mapping

    def visit(self, node: ast.AST) -> ast.AST:
        replacement = self.mapping.get(id(node))
        if replacement is not None:
            return ast.copy_location(replacement, node)
        return cast(ast.AST, super().visit(node))


def apply_slot_overrides(
    source: str,
    overrides: Mapping[str, str] | None,
    *,
    min_chars: int = MIN_SLOT_CHARS,
) -> ast.Module:
    """Return an AST with requested slots overridden in memory."""
    tree = ast.parse(source)
    if not overrides:
        return tree
    mapping: dict[int, ast.AST] = {}
    for idx, node in enumerate(_slot_nodes(tree, min_chars=min_chars), 1):
        text = overrides.get(f"s{idx}")
        if text is None:
            continue
        mapping[id(node)] = (
            _parse_template(text) if isinstance(node, ast.JoinedStr) else ast.Constant(value=text)
        )
    transformed = _SlotReplacer(mapping).visit(tree)
    assert isinstance(transformed, ast.Module)
    ast.fix_missing_locations(transformed)
    return transformed


def render_with_overrides(
    source: str,
    overrides: Mapping[str, str] | None,
    *,
    min_chars: int = MIN_SLOT_CHARS,
) -> str:
    """Return unparsed Python source with slot overrides applied (raises ValueError)."""
    problems = validate_slot_overrides(source, overrides, min_chars=min_chars)
    if problems:
        raise ValueError("; ".join(problems))
    if not overrides:
        return source
    return ast.unparse(apply_slot_overrides(source, overrides, min_chars=min_chars))


def overrides_fingerprint(overrides: Mapping[str, str] | None) -> str:
    """Return stable SHA-256 fingerprint of a slot-override mapping."""
    if not overrides:
        return ""
    blob = json.dumps(sorted((str(k), str(v)) for k, v in overrides.items()), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def extract_operator_code(gene: Mapping[str, Any]) -> str:
    """Extract executable Python source from *gene* (``lens`` + ``codemod``)."""
    parts: list[str] = []
    for field in ("lens", "codemod"):
        val = gene.get(field)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
        elif isinstance(val, Mapping):
            code = val.get("code")
            if isinstance(code, str) and code.strip():
                parts.append(code.strip())
    return "\n\n".join(parts)


def compute_slot_delta(
    canonical_code: str,
    candidate_code: str,
    *,
    min_chars: int = MIN_SLOT_CHARS,
) -> dict[str, str]:
    """Extract slot overrides transforming *canonical_code* literals into *candidate_code*."""
    base_slots = list_operator_slots(canonical_code, min_chars=min_chars)
    cand_slots = list_operator_slots(candidate_code, min_chars=min_chars)
    delta: dict[str, str] = {}
    for b, c in zip(base_slots, cand_slots, strict=False):
        if b["default"] != c["default"] and b["placeholders"] == c["placeholders"]:
            delta[str(b["id"])] = str(c["default"])
    return delta


def deduplicate_or_bind_operator(
    candidate: Mapping[str, Any],
    existing_genes: Sequence[Mapping[str, Any]],
    *,
    run_id: str = "",
    signals: Sequence[str] = (),
) -> dict[str, Any]:
    """Deduplicate *candidate* against *existing_genes* via AST structural hash.

    When an existing gene carries the same ``structural_hash`` (ignoring literals
    and docstrings), returns a merged copy of the canonical gene with the new
    ``slot_bindings`` entry attached rather than emitting a clone gene.
    """
    cand = dict(candidate)
    code = extract_operator_code(cand)
    if not code:
        return {
            "duplicate": False,
            "gene": cand,
            "structural_hash": None,
            "canonical_id": None,
        }

    h = structural_hash(code)
    if not h:
        return {
            "duplicate": False,
            "gene": cand,
            "structural_hash": None,
            "canonical_id": None,
        }

    cand["structural_hash"] = h
    if not cand.get("slot_specs"):
        cand["slot_specs"] = list_operator_slots(code)

    cand_id = str(cand.get("id") or "")
    eff_run_id = run_id or str(cand.get("distilled_run_id") or "")
    for existing in existing_genes:
        if not isinstance(existing, Mapping):
            continue
        ex_id = str(existing.get("id") or "")
        if not ex_id:
            continue
        ex_hash = existing.get("structural_hash")
        ex_code = extract_operator_code(existing)
        if not ex_hash and ex_code:
            ex_hash = structural_hash(ex_code)
        if ex_hash != h:
            continue
        slot_delta = compute_slot_delta(ex_code, code) if ex_code else {}
        if (
            ex_id == cand_id
            and not slot_delta
            and (not eff_run_id or eff_run_id == str(existing.get("distilled_run_id") or ""))
        ):
            continue
        merged = dict(existing)
        if not merged.get("structural_hash"):
            merged["structural_hash"] = h
        if not merged.get("slot_specs") and ex_code:
            merged["slot_specs"] = list_operator_slots(ex_code)
        bindings = list(merged.get("slot_bindings") or [])
        fp = overrides_fingerprint(slot_delta)
        binding_entry = {
            "run_id": eff_run_id,
            "source_candidate_id": cand_id,
            "slots": slot_delta,
            "fingerprint": fp,
            "signals": [str(s) for s in signals[:6] if str(s).strip()],
        }
        already = any(
            isinstance(b, Mapping)
            and b.get("fingerprint") == fp
            and (fp != "" or b.get("run_id") == eff_run_id)
            for b in bindings
        )
        if not already:
            bindings.append(binding_entry)
        merged["slot_bindings"] = bindings[-20:]
        return {
            "duplicate": True,
            "canonical_id": ex_id,
            "merged_gene": merged,
            "slot_binding": binding_entry,
            "structural_hash": h,
        }

    return {
        "duplicate": False,
        "gene": cand,
        "structural_hash": h,
        "canonical_id": None,
    }


__all__ = [
    "MIN_SLOT_CHARS",
    "apply_slot_overrides",
    "compute_slot_delta",
    "deduplicate_or_bind_operator",
    "extract_operator_code",
    "list_operator_slots",
    "overrides_fingerprint",
    "render_with_overrides",
    "structural_hash",
    "validate_slot_overrides",
]
