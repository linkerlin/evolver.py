"""Canonicalization + SHA-256 content addressing.

Equivalent to evolver/src/gep/contentHash.js.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = "1.8.0"


def canonicalize(obj: Any) -> str:
    """Stable JSON canonicalization for hashing."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_asset_id(asset: dict) -> str:
    # Exclude asset_id from the hash payload to avoid self-reference mismatch.
    payload = {k: v for k, v in asset.items() if k != "asset_id"}
    canonical = canonicalize(payload)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def verify_asset_id(asset: dict, asset_id: str) -> bool:
    return compute_asset_id(asset) == asset_id
