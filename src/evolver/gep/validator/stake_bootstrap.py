"""Stake bootstrap — guide new validators through the on-chain staking process.

Equivalent to Node's ``evolver/src/gep/validator/stakeBootstrap.js``.

When a new validator node first starts, it needs to stake tokens on
the EvoMap chain to gain voting power and eligibility. This module:

1. Generates a staking transaction request (unsigned).
2. Displays instructions for the user to complete the stake.
3. Polls the chain for stake confirmation.
4. Activates the validator identity once confirmed.

Design notes
------------
* Works entirely offline for transaction generation (no private keys).
* Polls the Hub ``/a2a/validator/stake-status`` endpoint.
* Respects ``enable_validator`` feature flag.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

# Config
DEFAULT_STAKE_AMOUNT = 100.0
DEFAULT_CURRENCY = "ATP"
POLL_INTERVAL = 30.0  # seconds
MAX_POLL_ATTEMPTS = 120  # 1 hour total

# State file
STAKE_STATE_PATH = Path("evolver") / ".config" / "stake_state.json"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class StakeRequest:
    node_id: str
    amount: float
    currency: str
    chain: str
    recipient_address: str
    memo: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "amount": self.amount,
            "currency": self.currency,
            "chain": self.chain,
            "recipient_address": self.recipient_address,
            "memo": self.memo,
        }


@dataclass
class StakeState:
    node_id: str
    status: str  # pending|submitted|confirmed|failed
    tx_hash: str = ""
    created_at: float = 0.0
    confirmed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "tx_hash": self.tx_hash,
            "created_at": self.created_at,
            "confirmed_at": self.confirmed_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StakeState:
        return cls(
            node_id=d.get("node_id", ""),
            status=d.get("status", "pending"),
            tx_hash=d.get("tx_hash", ""),
            created_at=d.get("created_at", 0.0),
            confirmed_at=d.get("confirmed_at"),
        )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _state_path() -> Path:
    return get_workspace_root() / STAKE_STATE_PATH


def load_stake_state() -> StakeState | None:
    p = _state_path()
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return StakeState.from_dict(data)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("[StakeBootstrap] Failed to load state: %s", exc)
        return None


def save_stake_state(state: StakeState) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Stake request generation
# ---------------------------------------------------------------------------


def generate_stake_request(
    *,
    node_id: str | None = None,
    amount: float = DEFAULT_STAKE_AMOUNT,
    currency: str = DEFAULT_CURRENCY,
    chain: str = "evomap",
    recipient_address: str = "evomap1validator",
) -> StakeRequest:
    """Generate an unsigned staking transaction request."""
    import os

    nid = node_id or os.environ.get("EVOLVER_AGENT_ID", "unknown-node")
    return StakeRequest(
        node_id=nid,
        amount=amount,
        currency=currency,
        chain=chain,
        recipient_address=recipient_address,
        memo=f"validator-stake-{nid}",
    )


def format_instructions(request: StakeRequest) -> str:
    """Return human-readable staking instructions."""
    lines = [
        "## Validator Stake Required",
        "",
        f"Your node ID: `{request.node_id}`",
        f"Required stake: **{request.amount} {request.currency}**",
        f"Chain: `{request.chain}`",
        f"Recipient: `{request.recipient_address}`",
        f"Memo: `{request.memo}`",
        "",
        "### Instructions",
        "",
        "1. Ensure your wallet has sufficient balance.",
        "2. Send the stake amount to the recipient address above.",
        "3. Include the memo in your transaction.",
        "4. Wait for confirmation (typically 1-2 minutes).",
        "",
        "Once confirmed, the validator daemon will start automatically.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Confirmation polling
# ---------------------------------------------------------------------------


def _query_stake_status(node_id: str) -> dict[str, Any] | None:
    """Query Hub for stake status."""
    try:
        import httpx

        from evolver.adapters.auth import load_auth
        from evolver.config import resolve_hub_url
        from evolver.gep.a2a_protocol import build_hub_headers

        headers = build_hub_headers()
        auth = load_auth()
        if auth:
            headers["Authorization"] = f"Bearer {auth['access_token']}"
        resp = httpx.get(
            f"{resolve_hub_url()}/v1/a2a/validator/stake-status",
            params={"node_id": node_id},
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code == 200:
            return cast(dict[str, Any], resp.json())
    except Exception as exc:
        logger.debug("[StakeBootstrap] Status query failed: %s", exc)
    return None


def wait_for_confirmation(
    node_id: str,
    *,
    poll_interval: float = POLL_INTERVAL,
    max_attempts: int = MAX_POLL_ATTEMPTS,
) -> StakeState:
    """Poll for stake confirmation.

    Returns the final :class:`StakeState`.
    """
    state = load_stake_state()
    if state is None:
        state = StakeState(node_id=node_id, status="pending", created_at=time.time())
        save_stake_state(state)

    if state.status == "confirmed":
        return state

    for attempt in range(max_attempts):
        result = _query_stake_status(node_id)
        if result:
            status = result.get("status", "").lower()
            tx_hash = result.get("tx_hash", "")
            if status == "confirmed":
                state.status = "confirmed"
                state.tx_hash = tx_hash
                state.confirmed_at = time.time()
                save_stake_state(state)
                logger.info("[StakeBootstrap] Stake confirmed (tx=%s)", tx_hash)
                return state
            if status == "failed":
                state.status = "failed"
                state.tx_hash = tx_hash
                save_stake_state(state)
                logger.warning("[StakeBootstrap] Stake failed (tx=%s)", tx_hash)
                return state

        time.sleep(poll_interval)

    logger.warning("[StakeBootstrap] Confirmation timeout after %d attempts", max_attempts)
    return state


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def bootstrap(
    *,
    node_id: str | None = None,
    interactive: bool = True,
) -> StakeState:
    """Run the full stake bootstrap flow.

    1. Load or create stake state.
    2. If pending, generate request and show instructions.
    3. Poll for confirmation.
    4. Return final state.
    """
    import os

    nid = node_id or os.environ.get("EVOLVER_AGENT_ID", "unknown-node")
    state = load_stake_state()

    if state is not None and state.status == "confirmed":
        logger.info("[StakeBootstrap] Validator already staked and confirmed")
        return state

    request = generate_stake_request(node_id=nid)

    if interactive:
        print(format_instructions(request))

    # Save pending state
    if state is None:
        state = StakeState(node_id=nid, status="pending", created_at=time.time())
        save_stake_state(state)

    # Poll
    return wait_for_confirmation(nid)


def is_staked() -> bool:
    """Return ``True`` if the local validator has a confirmed stake."""
    state = load_stake_state()
    return state is not None and state.status == "confirmed"
