"""Hub search — semantic + signal search for Hub services and skills.

Combines:
1. **Keyword search** over service metadata.
2. **Signal boosting** — services with recent uptime, fast response, high
   success rate rank higher.
3. **Semantic similarity** via simple TF-IDF cosine on descriptions.

Equivalent to Node's ``evolver/src/gep/hubSearch.js``.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ServiceHit:
    service_id: str
    title: str
    score: float  # combined score (0–1)
    signals: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Simple TF-IDF helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))


def _tfidf_similarity(query: str, description: str, corpus: list[str]) -> float:
    """Return a rough cosine similarity between *query* and *description*."""
    q_tokens = _tokenize(query)
    d_tokens = _tokenize(description)
    if not q_tokens or not d_tokens:
        return 0.0

    all_docs = [_tokenize(d) for d in corpus]
    idf: dict[str, float] = {}
    for token in q_tokens:
        df = 1 + sum(1 for doc in all_docs if token in doc)
        idf[token] = math.log(len(corpus) / df)

    q_vec = {t: idf.get(t, 1.0) for t in q_tokens}
    d_vec = {t: idf.get(t, 1.0) for t in d_tokens}

    def _dot(a: dict[str, float], b: dict[str, float]) -> float:
        return sum(a.get(k, 0.0) * b.get(k, 0.0) for k in set(a) & set(b))

    def _norm(v: dict[str, float]) -> float:
        return math.sqrt(sum(x * x for x in v.values()))

    nq, nd = _norm(q_vec), _norm(d_vec)
    if nq == 0 or nd == 0:
        return 0.0
    return _dot(q_vec, d_vec) / (nq * nd)


# ---------------------------------------------------------------------------
# Signal scoring
# ---------------------------------------------------------------------------


def _signal_score(service: dict[str, Any]) -> float:
    """Compute a 0–1 signal score from service metadata."""
    # Uptime rate
    uptime = float(service.get("uptime_rate", 1.0))
    # Avg response time (ms) — lower is better, clamp at 5 s
    avg_ms = float(service.get("avg_response_ms", 500))
    response_score = max(0.0, 1.0 - avg_ms / 5000)
    # Success rate
    success_rate = float(service.get("success_rate", 1.0))
    # Reviews / rating
    rating = float(service.get("rating", 0.0))
    reviews = float(service.get("reviews_count", 0))
    review_boost = min(1.0, reviews / 10) * (rating / 5.0 if rating else 0.5)

    weights = {"uptime": 0.3, "response": 0.25, "success": 0.25, "reviews": 0.2}
    return (
        weights["uptime"] * uptime
        + weights["response"] * response_score
        + weights["success"] * success_rate
        + weights["reviews"] * review_boost
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_services(
    services: list[dict[str, Any]],
    query: str,
    *,
    top_k: int = 10,
    min_signal: float = 0.0,
) -> list[ServiceHit]:
    """Rank *services* against *query* using keyword + semantic + signal."""
    corpus = [str(s.get("description", "")) for s in services]
    hits: list[ServiceHit] = []

    for svc in services:
        title = str(svc.get("title", ""))
        desc = str(svc.get("description", ""))
        service_id = str(svc.get("service_id", ""))

        # Keyword overlap
        q_tokens = _tokenize(query)
        title_tokens = _tokenize(title)
        desc_tokens = _tokenize(desc)
        keyword_score = 0.6 * len(q_tokens & title_tokens) / max(len(q_tokens), 1) + 0.4 * len(
            q_tokens & desc_tokens
        ) / max(len(q_tokens), 1)

        # Semantic
        semantic_score = _tfidf_similarity(query, desc, corpus)

        # Signal
        sig = _signal_score(svc)
        if sig < min_signal:
            continue

        # Combined score (arbitrary weights tuned for balance)
        combined = 0.35 * min(1.0, keyword_score) + 0.35 * max(0.0, semantic_score) + 0.30 * sig
        hits.append(
            ServiceHit(
                service_id=service_id,
                title=title,
                score=combined,
                signals={"keyword": keyword_score, "semantic": semantic_score, "signal": sig},
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    logger.info("[HubSearch] query='%s' returned %d hits (top_k=%d)", query, len(hits), top_k)
    return hits[:top_k]
