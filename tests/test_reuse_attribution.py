"""P4-a Slice A/B — reuse attribution + optional Hub outcome report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from evolver.config import outcome_report_mode, reuse_attribution_mode
from evolver.gep import asset_call_log as acl
from evolver.gep import memory_graph as mg
from evolver.gep.reuse_attribution import (
    REUSE_ATTR_SCHEMA,
    build_outcome_report_payload,
    build_reuse_attribution,
)

ACT_AT = "2026-06-03T10:00:00.000Z"
RUN_AT_FRESH = "2026-06-03T10:00:05.000Z"
RUN_AT_STALE = "2026-06-03T09:59:00.000Z"


@pytest.fixture
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.delenv("EVOLVER_REUSE_ATTRIBUTION", raising=False)
    monkeypatch.delenv("EVOLVER_OUTCOME_REPORT", raising=False)
    monkeypatch.delenv("A2A_NODE_SECRET", raising=False)
    monkeypatch.delenv("EVOMAP_NODE_SECRET", raising=False)
    return tmp_path


def _write_run_state(tmp: Path, last_run: dict[str, Any]) -> None:
    lr = {"created_at": RUN_AT_FRESH, **last_run}
    (tmp / "evolution_solidify_state.json").write_text(
        json.dumps({"last_run": lr}), encoding="utf-8"
    )


def _write_last_action(tmp: Path) -> None:
    state_path = tmp / "memory_graph_state.json"
    state_path.write_text(
        json.dumps(
            {
                "last_action": {
                    "action_id": "act_test",
                    "signal_key": "k",
                    "signals": ["log_error"],
                    "had_error": True,
                    "outcome_recorded": False,
                    "created_at": ACT_AT,
                    "ts": ACT_AT,
                }
            }
        ),
        encoding="utf-8",
    )


class TestConfigFlags:
    def test_reuse_defaults_off_only_shadow_accepted(
        self, isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert reuse_attribution_mode() == "off"
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "SHADOW")
        assert reuse_attribution_mode() == "shadow"
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "enforce")
        assert reuse_attribution_mode() == "off"
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "garbage")
        assert reuse_attribution_mode() == "off"

    def test_outcome_report_on_aliases(
        self, isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert outcome_report_mode() == "off"
        monkeypatch.setenv("EVOLVER_OUTCOME_REPORT", "on")
        assert outcome_report_mode() == "on"
        monkeypatch.setenv("EVOLVER_OUTCOME_REPORT", "true")
        assert outcome_report_mode() == "on"
        monkeypatch.setenv("EVOLVER_OUTCOME_REPORT", "nope")
        assert outcome_report_mode() == "off"


class TestBuildReuseAttribution:
    def test_off_mode_no_block(self, isolated_paths: Path) -> None:
        block = build_reuse_attribution(
            {
                "source_type": "reused",
                "reused_asset_id": "sha256:abc",
                "created_at": RUN_AT_FRESH,
            },
            {"created_at": ACT_AT},
            mode="off",
        )
        assert block is None

    def test_shadow_reused_no_client_source_node_id(self, isolated_paths: Path) -> None:
        block = build_reuse_attribution(
            {
                "source_type": "reused",
                "reused_asset_id": "sha256:abc",
                "reused_chain_id": "chain1",
                "reused_source_node": "node_pub_DO_NOT_TRUST",
                "created_at": RUN_AT_FRESH,
            },
            {"created_at": ACT_AT},
            mode="shadow",
        )
        assert block is not None
        assert block["reused_asset_id"] == "sha256:abc"
        assert block["reused_chain_id"] == "chain1"
        assert block["source_type"] == "reused"
        assert block["schema"] == REUSE_ATTR_SCHEMA
        assert "source_node_id" not in block
        assert "node_pub_DO_NOT_TRUST" not in json.dumps(block)

    def test_shadow_generated_no_block(self, isolated_paths: Path) -> None:
        assert (
            build_reuse_attribution(
                {"source_type": "generated", "created_at": RUN_AT_FRESH},
                {"created_at": ACT_AT},
                mode="shadow",
            )
            is None
        )

    def test_shadow_reference_attaches(self, isolated_paths: Path) -> None:
        block = build_reuse_attribution(
            {
                "source_type": "reference",
                "reused_asset_id": "sha256:ref1",
                "reused_chain_id": None,
                "created_at": RUN_AT_FRESH,
            },
            {"created_at": ACT_AT},
            mode="shadow",
        )
        assert block is not None
        assert block["source_type"] == "reference"
        assert block["reused_chain_id"] is None

    def test_stale_last_run_no_block(self, isolated_paths: Path) -> None:
        block = build_reuse_attribution(
            {
                "source_type": "reused",
                "reused_asset_id": "sha256:STALE",
                "created_at": RUN_AT_STALE,
            },
            {"created_at": ACT_AT},
            mode="shadow",
        )
        assert block is None

    def test_missing_created_at_no_block(self, isolated_paths: Path) -> None:
        block = build_reuse_attribution(
            {"source_type": "reused", "reused_asset_id": "sha256:nocreat"},
            {"created_at": ACT_AT},
            mode="shadow",
        )
        assert block is None


class TestRecordOutcomeFromState:
    def test_off_mode_no_attribution_even_on_reuse(
        self, isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tmp = isolated_paths
        _write_run_state(
            tmp,
            {
                "source_type": "reused",
                "reused_asset_id": "sha256:abc",
                "reused_chain_id": "chain1",
                "reused_source_node": "node_pub",
            },
        )
        _write_last_action(tmp)
        monkeypatch.delenv("EVOLVER_REUSE_ATTRIBUTION", raising=False)
        ev = mg.record_outcome_from_state(signals=[], observations=None)
        assert ev is not None
        assert "reuse_attribution" not in ev

    def test_shadow_reused_attaches_block(
        self, isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tmp = isolated_paths
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "shadow")
        _write_run_state(
            tmp,
            {
                "source_type": "reused",
                "reused_asset_id": "sha256:abc",
                "reused_chain_id": "chain1",
                "reused_source_node": "node_pub_DO_NOT_TRUST",
            },
        )
        _write_last_action(tmp)
        ev = mg.record_outcome_from_state(signals=[], observations=None)
        assert ev is not None
        attr = ev.get("reuse_attribution")
        assert isinstance(attr, dict)
        assert attr["reused_asset_id"] == "sha256:abc"
        assert attr["schema"] == REUSE_ATTR_SCHEMA
        assert "source_node_id" not in attr
        assert "node_pub_DO_NOT_TRUST" not in json.dumps(ev)

    def test_shadow_stale_no_block(
        self, isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tmp = isolated_paths
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "shadow")
        (tmp / "evolution_solidify_state.json").write_text(
            json.dumps(
                {
                    "last_run": {
                        "source_type": "reused",
                        "reused_asset_id": "sha256:STALE",
                        "created_at": RUN_AT_STALE,
                    }
                }
            ),
            encoding="utf-8",
        )
        _write_last_action(tmp)
        ev = mg.record_outcome_from_state(signals=[], observations=None)
        assert ev is not None
        assert "reuse_attribution" not in ev
        assert "STALE" not in json.dumps(ev)

    def test_shadow_no_run_state_no_crash(
        self, isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "shadow")
        _write_last_action(isolated_paths)
        ev = mg.record_outcome_from_state(signals=[], observations=None)
        assert ev is not None
        assert "reuse_attribution" not in ev


class TestLocalRollup:
    def test_reuse_attribution_summary(self, isolated_paths: Path) -> None:
        acl.log_asset_call(
            {
                "run_id": "r1",
                "action": "asset_reuse",
                "asset_id": "A",
                "source_node_id": "nodeA",
                "chain_id": "c1",
            }
        )
        acl.log_asset_call({"run_id": "r2", "action": "asset_reuse", "asset_id": "A"})
        acl.log_asset_call(
            {
                "run_id": "r3",
                "action": "asset_reference",
                "asset_id": "B",
                "source_node_id": "nodeB",
            }
        )
        acl.log_asset_call({"run_id": "r4", "action": "hub_search_hit", "asset_id": "C"})
        summary = acl.reuse_attribution_summary()
        assert summary["total_reuse"] == 2
        assert summary["total_reference"] == 1
        a = next(x for x in summary["by_asset"] if x["asset_id"] == "A")
        assert a["reuse"] == 2 and a["reference"] == 0 and a["source_node_id"] == "nodeA"
        assert summary["by_asset"][0]["asset_id"] == "A"

    def test_tokens_saved_rollup(self, isolated_paths: Path) -> None:
        acl.log_asset_call(
            {
                "run_id": "r1",
                "action": "asset_reuse",
                "asset_id": "A",
                "tokens_saved": 1000,
            }
        )
        acl.log_asset_call(
            {
                "run_id": "r2",
                "action": "asset_reuse",
                "asset_id": "A",
                "tokens_saved": 500,
            }
        )
        acl.log_asset_call(
            {
                "run_id": "r3",
                "action": "asset_reference",
                "asset_id": "B",
                "tokens_saved": 200,
            }
        )
        acl.log_asset_call(
            {
                "run_id": "r4",
                "action": "asset_publish",
                "asset_id": "A",
                "tokens_spent": 9999,
            }
        )
        summary = acl.reuse_attribution_summary()
        assert summary["total_tokens_saved"] == 1700
        assert next(x for x in summary["by_asset"] if x["asset_id"] == "A")["tokens_saved"] == 1500

    def test_asset_cost_index(self, isolated_paths: Path) -> None:
        acl.log_asset_call(
            {
                "run_id": "r1",
                "action": "asset_publish",
                "asset_id": "A",
                "tokens_spent": 1000,
            }
        )
        acl.log_asset_call(
            {
                "run_id": "r2",
                "action": "asset_publish",
                "asset_id": "A",
                "tokens_spent": 1200,
            }
        )
        acl.log_asset_call({"run_id": "r3", "action": "asset_publish", "asset_id": "B"})
        idx = acl.asset_cost_index()
        assert idx["A"] == 1200
        assert "B" not in idx


class TestOutcomeReport:
    def test_payload_builder_only_direct_reuse(self, isolated_paths: Path) -> None:
        attr = {
            "schema": REUSE_ATTR_SCHEMA,
            "source_type": "reused",
            "reused_asset_id": "sha256:abc",
            "reused_chain_id": None,
        }
        # mode off → None
        payload = build_outcome_report_payload(
            last_run={"source_type": "reused"},
            last_action={"signals": ["log_error"]},
            signals=[],
            status="success",
            sender_id="node_abc",
            attribution=attr,
        )
        assert payload is None  # outcome_report default off

    def test_payload_on_direct_reuse(
        self, isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_OUTCOME_REPORT", "on")
        attr = {
            "schema": REUSE_ATTR_SCHEMA,
            "source_type": "reused",
            "reused_asset_id": "sha256:abc",
        }
        payload = build_outcome_report_payload(
            last_run={"source_type": "reused"},
            last_action={"signals": ["log_error"]},
            signals=[],
            status="success",
            sender_id="node_deadbeefcafe",
            attribution=attr,
        )
        assert payload is not None
        assert payload["used_asset_ids"] == ["sha256:abc"]
        assert payload["status"] == "success"
        assert payload["sender_id"] == "node_deadbeefcafe"
        assert payload["signals"]
        assert "event" not in payload

    def test_reference_no_payload(
        self, isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_OUTCOME_REPORT", "on")
        attr = {
            "schema": REUSE_ATTR_SCHEMA,
            "source_type": "reference",
            "reused_asset_id": "sha256:ref1",
        }
        assert (
            build_outcome_report_payload(
                last_run={"source_type": "reference"},
                last_action={},
                signals=[],
                status="success",
                sender_id="node_deadbeefcafe",
                attribution=attr,
            )
            is None
        )

    @respx.mock
    def test_record_outcome_posts_when_on(
        self, isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "shadow")
        monkeypatch.setenv("EVOLVER_OUTCOME_REPORT", "on")
        monkeypatch.setenv("A2A_HUB_URL", "http://localhost:19997")
        monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
        monkeypatch.setenv("A2A_NODE_SECRET", "test_secret")
        monkeypatch.setattr(
            "evolver.gep.node_identity.get_or_create_node_id",
            lambda: "node_deadbeefcafe",
        )
        route = respx.post("http://localhost:19997/a2a/memory/record").mock(
            return_value=httpx.Response(200, json={"recorded": True})
        )
        _write_run_state(
            isolated_paths,
            {"source_type": "reused", "reused_asset_id": "sha256:abc"},
        )
        _write_last_action(isolated_paths)
        mg.record_outcome_from_state(signals=[], observations=None)
        assert route.called
        body = json.loads(route.calls.last.request.content.decode())
        assert body["used_asset_ids"] == ["sha256:abc"]
        assert body["sender_id"] == "node_deadbeefcafe"
        assert route.calls.last.request.headers["Authorization"] == "Bearer test_secret"

    @respx.mock
    def test_no_post_when_outcome_report_off(
        self, isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "shadow")
        monkeypatch.setenv("A2A_HUB_URL", "http://localhost:19997")
        monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
        route = respx.post("http://localhost:19997/a2a/memory/record").mock(
            return_value=httpx.Response(200, json={"recorded": True})
        )
        _write_run_state(
            isolated_paths,
            {"source_type": "reused", "reused_asset_id": "sha256:abc"},
        )
        _write_last_action(isolated_paths)
        mg.record_outcome_from_state(signals=[], observations=None)
        assert not route.called
