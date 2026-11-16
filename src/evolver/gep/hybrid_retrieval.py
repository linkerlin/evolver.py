"""Dual-view hybrid retrieval & adjacent inspiration slate (S-3).

Adapts Strategist's ``retrieval.py`` to ``evolver.py`` without heavy runtime
dependencies:
- Lexical view (weight ``HYBRID_ALPHA = 0.4``): IDF-weighted sparse cosine
  similarity over gene ``id``, ``summary``, ``when_to_use``, ``signals_match``,
  ``builds_on``, and ``slot_specs`` (preserving CJK + ASCII tokenization).
- Experience view (weight ``1 - HYBRID_ALPHA = 0.6``): cached normalized
  character 3-gram + token vector cosine over operator measurement stats
  (``helped`` / ``hurt``), ``learning_history``, ``anti_patterns``, and
  ``strategy``, persisted atomically per text SHA-256 hash using cross-platform
  PID tmp + ``Path.replace`` (zero Unix-only ``fcntl``).
- ``retrieve_operators_and_inspiration`` returns both ``relevant`` (top-k) and
  deduplicated cross-family ``inspiration`` (ranks 4..12) slates.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Any, Final

from evolver.gep.selector import _score_gene, tokenize

HYBRID_ALPHA: Final[float] = 0.4
_DEFAULT_CACHE_FILENAME: Final[str] = "retrieval_vec_cache.json"
_ADJACENT_RANK_START: Final[int] = 3
_ADJACENT_RANK_END: Final[int] = 12


def _char_ngrams(text: str, n: int = 3) -> list[str]:
    clean = " ".join(text.lower().split())
    if not clean:
        return []
    if len(clean) < n:
        return [clean]
    return [clean[i : i + n] for i in range(len(clean) - n + 1)]


def _normalized_sparse_vector(text: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    for tok in tokenize(text):
        key = f"w:{tok}"
        counts[key] = counts.get(key, 0.0) + 1.5
    for ng in _char_ngrams(text, 3):
        key = f"g:{ng}"
        counts[key] = counts.get(key, 0.0) + 0.5
    if not counts:
        return {}
    mag = math.sqrt(sum(v * v for v in counts.values()))
    if mag <= 0.0:
        return {}
    return {k: round(v / mag, 6) for k, v in counts.items()}


def _sparse_cosine(v1: Mapping[str, float], v2: Mapping[str, float]) -> float:
    if not v1 or not v2:
        return 0.0
    if len(v1) > len(v2):
        v1, v2 = v2, v1
    dot = sum(val * v2[k] for k, val in v1.items() if k in v2)
    return float(max(0.0, min(1.0, dot)))


def _lexical_text(gene: Mapping[str, Any]) -> str:
    gid = str(gene.get("id") or "")
    slots = " ".join(
        str(s.get("id") or "") for s in (gene.get("slot_specs") or []) if isinstance(s, Mapping)
    )
    parts = [
        gid.replace("_", " "),
        str(gene.get("category") or ""),
        str(gene.get("summary") or ""),
        str(gene.get("when_to_use") or ""),
        " ".join(str(s) for s in (gene.get("signals_match") or [])),
        " ".join(str(b) for b in (gene.get("builds_on") or gene.get("dependencies") or [])),
        slots,
    ]
    return " ".join(p for p in parts if p)


def _experience_text(gene: Mapping[str, Any], stats: Mapping[str, Any] | None) -> str:
    parts: list[str] = [
        str(gene.get("summary") or ""),
        str(gene.get("when_to_use") or ""),
        " ".join(str(s) for s in (gene.get("strategy") or [])),
    ]
    if isinstance(stats, Mapping):
        parts.append(
            f"dispatches {stats.get('dispatches', 0)} "
            f"helped {stats.get('helped', 0)} hurt {stats.get('hurt', 0)}"
        )
    for lh in (gene.get("learning_history") or [])[-5:]:
        if isinstance(lh, Mapping):
            parts.append(str(lh.get("outcome") or ""))
            parts.append(" ".join(str(s) for s in (lh.get("signals") or [])))
    for ap in (gene.get("anti_patterns") or [])[-5:]:
        if isinstance(ap, Mapping):
            parts.append(str(ap.get("reasonClass") or ""))
            parts.append(" ".join(str(s) for s in (ap.get("signals") or [])))
        elif isinstance(ap, str):
            parts.append(ap)
    return " ".join(p for p in parts if p)


def compute_idf_weights(documents: Mapping[str, str]) -> dict[str, float]:
    """Compute smooth IDF weights ``log((N + 1) / (df + 1)) + 1.0`` across *documents*."""
    n_docs = len(documents)
    if n_docs == 0:
        return {}
    df: Counter[str] = Counter()
    for text in documents.values():
        for tok in set(tokenize(text)):
            df[tok] += 1
    return {tok: math.log((n_docs + 1.0) / (count + 1.0)) + 1.0 for tok, count in df.items()}


def idf_lexical_cosine(
    query: str,
    doc_text: str,
    idf: Mapping[str, float],
) -> float:
    """Compute TF-IDF weighted cosine similarity between *query* and *doc_text*."""
    q_tokens = tokenize(query)
    d_tokens = tokenize(doc_text)
    if not q_tokens or not d_tokens:
        return 0.0
    q_tf = Counter(q_tokens)
    d_tf = Counter(d_tokens)
    q_len = float(len(q_tokens))
    d_len = float(len(d_tokens))
    q_vec = {t: (c / q_len) * float(idf.get(t, 1.0)) for t, c in q_tf.items()}
    d_vec = {t: (c / d_len) * float(idf.get(t, 1.0)) for t, c in d_tf.items()}
    common = set(q_vec) & set(d_vec)
    if not common:
        return 0.0
    dot = sum(q_vec[t] * d_vec[t] for t in common)
    mag_q = math.sqrt(sum(v * v for v in q_vec.values()))
    mag_d = math.sqrt(sum(v * v for v in d_vec.values()))
    if mag_q <= 0.0 or mag_d <= 0.0:
        return 0.0
    return float(max(0.0, min(1.0, dot / (mag_q * mag_d))))


def _default_cache_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / _DEFAULT_CACHE_FILENAME


def _load_or_update_vec_cache(
    exp_corpus: Mapping[str, str],
    *,
    cache_path: Path | None = None,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> dict[str, Any]:
    path = cache_path or _default_cache_path()
    cached: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cached = raw
        except (OSError, json.JSONDecodeError):
            cached = {}

    out: dict[str, Any] = {}
    missing: list[tuple[str, str, str]] = []
    for gid, text in exp_corpus.items():
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        entry = cached.get(gid)
        if isinstance(entry, dict) and entry.get("hash") == digest and entry.get("vec") is not None:
            out[gid] = entry["vec"]
        else:
            missing.append((gid, digest, text))

    if missing:
        if embed_fn is not None:
            dense_vecs = embed_fn([item[2] for item in missing])
            for (gid, digest, _), vec in zip(missing, dense_vecs, strict=False):
                out[gid] = vec
                cached[gid] = {"hash": digest, "vec": vec}
        else:
            for gid, digest, text in missing:
                sparse_vec = _normalized_sparse_vector(text)
                out[gid] = sparse_vec
                cached[gid] = {"hash": digest, "vec": sparse_vec}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    return out


def _dense_cosine(v1: Sequence[float], v2: Sequence[float]) -> float:
    dot = sum(float(a) * float(b) for a, b in zip(v1, v2, strict=False))
    m1 = math.sqrt(sum(float(a) * float(a) for a in v1))
    m2 = math.sqrt(sum(float(b) * float(b) for b in v2))
    if m1 <= 0.0 or m2 <= 0.0:
        return 0.0
    return float(max(0.0, min(1.0, dot / (m1 * m2))))


def _primary_family(gene: Mapping[str, Any]) -> str:
    app = gene.get("applicability")
    if isinstance(app, Mapping):
        fams = app.get("signal_families") or []
        if fams:
            return str(fams[0]).split("|", 1)[0].strip().lower()
    sigs = gene.get("signals_match") or []
    if sigs:
        return str(sigs[0]).split("|", 1)[0].strip().lower()
    return str(gene.get("category") or "general").lower()


def retrieve_operators_and_inspiration(
    genes: Sequence[Mapping[str, Any]],
    signals: Sequence[str],
    *,
    operator_stats_map: Mapping[str, Mapping[str, Any]] | None = None,
    k_relevant: int = 3,
    k_inspiration: int = 2,
    excluded_ids: AbstractSet[str] = frozenset(),
    cache_path: Path | None = None,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    alpha: float = HYBRID_ALPHA,
) -> dict[str, Any]:
    """Rank operators via dual-view hybrid score and sample deduplicated inspiration."""
    stats_map = operator_stats_map or {}
    active: list[Mapping[str, Any]] = [
        g
        for g in genes
        if isinstance(g, Mapping) and g.get("id") and str(g.get("id")) not in excluded_ids
    ]
    if not active:
        return {"relevant": [], "inspiration": [], "idf_vocab_size": 0}

    query = " ".join(str(s) for s in signals if str(s).strip())
    lex_corpus = {str(g["id"]): _lexical_text(g) for g in active}
    exp_corpus = {str(g["id"]): _experience_text(g, stats_map.get(str(g["id"]))) for g in active}
    idf = compute_idf_weights(lex_corpus)
    exp_vecs = _load_or_update_vec_cache(
        exp_corpus,
        cache_path=cache_path,
        embed_fn=embed_fn,
    )
    q_exp_vec: Any = (
        embed_fn([query])[0] if embed_fn is not None else _normalized_sparse_vector(query)
    )

    scored: list[dict[str, Any]] = []
    for g in active:
        gid = str(g["id"])
        s_lex = idf_lexical_cosine(query, lex_corpus[gid], idf) if query else 0.0
        g_vec = exp_vecs.get(gid)
        if isinstance(g_vec, list) and isinstance(q_exp_vec, list):
            s_exp = _dense_cosine(q_exp_vec, g_vec)
        elif isinstance(g_vec, Mapping) and isinstance(q_exp_vec, Mapping):
            s_exp = _sparse_cosine(q_exp_vec, g_vec)
        else:
            s_exp = 0.0
        legacy_signal = _score_gene(dict(g), [str(s) for s in signals])
        hybrid = alpha * s_lex + (1.0 - alpha) * s_exp + 0.05 * min(4.0, legacy_signal)
        scored.append(
            {
                "gene": g,
                "id": gid,
                "score": round(hybrid, 6),
                "lexical_score": round(s_lex, 6),
                "experience_score": round(s_exp, 6),
                "family": _primary_family(g),
                "category": str(g.get("category") or ""),
            }
        )

    scored.sort(key=lambda item: (-float(item["score"]), item["id"]))
    relevant = scored[: max(1, int(k_relevant))]
    taken_ids = {item["id"] for item in relevant}
    taken_families = {item["family"] for item in relevant}

    # Adjacent inspiration zone (ranks 4..12): deduplicated against relevant,
    # preferring different signal families or executable operator genes.
    adjacent_pool = [
        item
        for item in scored[_ADJACENT_RANK_START:_ADJACENT_RANK_END]
        if item["id"] not in taken_ids
    ]
    if not adjacent_pool:
        adjacent_pool = [item for item in scored if item["id"] not in taken_ids]

    def _insp_priority(item: Mapping[str, Any]) -> tuple[int, int, float, str]:
        g = item["gene"]
        diff_family = 1 if item["family"] not in taken_families else 0
        has_lens = 1 if g.get("lens") is not None else 0
        return (-diff_family, -has_lens, -float(item["score"]), str(item["id"]))

    adjacent_pool.sort(key=_insp_priority)
    inspiration = adjacent_pool[: max(0, int(k_inspiration))]

    return {
        "relevant": relevant,
        "inspiration": inspiration,
        "idf_vocab_size": len(idf),
    }


__all__ = [
    "HYBRID_ALPHA",
    "compute_idf_weights",
    "idf_lexical_cosine",
    "retrieve_operators_and_inspiration",
]
