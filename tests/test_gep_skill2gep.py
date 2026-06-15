"""Tests for evolver.gep.skill2gep — parse_skill_md + infer_category.

Equivalent to test/skill2gepParser.test.js.
"""

# ruff: noqa: E501, RUF001

from __future__ import annotations

from evolver.gep.skill2gep import infer_category, parse_skill_md

SKILL_MD = "\n".join([
    "---",
    "name: sample-evolver",
    "description: Use when upgrading an AI system with VOI, OODA, evals, human gates, versioning, and rollback.",
    "---",
    "",
    "# Sample Evolver",
    "",
    "## Quick Workflow",
    "1. Define the current task and the system layer being changed.",
    "2. Pass a VOI gate before gathering more information.",
    "3. Make the operating model explicit:",
    "   - compression: shortest model that explains most cases?",
    "   - causality: which mediator variables connect input to outcome?",
    "   - control points: which mediator can you intervene on?",
    "4. Maintain a compact OODA state:",
    "   - Observe: goal, context, evidence.",
    "   - Orient: current frame, uncertainty map.",
    "5. Keep every change as `candidate` until evidence, evals, approval, and rollback are present.",
    "",
    "## Human Gate Defaults",
    "Ask for human confirmation before:",
    "- writing long-term memory",
    "- changing production strategy or user-visible systems",
    "- promoting a `candidate` to current rule",
    "",
    "## Output Contract",
    "End by stating:",
    "- what changed",
    "- which evals ran",
    "- how to rollback",
])


class TestParseSkillMdGovernance:
    def setup_method(self) -> None:
        self.parsed = parse_skill_md(SKILL_MD)

    def test_keeps_candidate_gating(self) -> None:
        blob = " ".join(self.parsed.strategy).lower()
        assert "candidate" in blob

    def test_keeps_human_gate_items(self) -> None:
        blob = " ".join(self.parsed.strategy).lower()
        assert "human confirmation" in blob or "long-term memory" in blob or "production strategy" in blob

    def test_keeps_output_contract_items(self) -> None:
        blob = " ".join(self.parsed.strategy).lower()
        assert "what changed" in blob or "how to rollback" in blob

    def test_emits_sub_bullets_as_own_steps(self) -> None:
        assert any("compression:" in s.strip().lower() for s in self.parsed.strategy)
        assert any("control points:" in s.strip().lower() for s in self.parsed.strategy)

    def test_strategy_rich_but_capped(self) -> None:
        assert len(self.parsed.strategy) > 10
        assert len(self.parsed.strategy) <= 28

    def test_uniform_indented_list_stays_separate(self) -> None:
        md = "\n".join([
            "---", "name: t", "description: optimize the build", "---", "# T", "",
            "## Workflow",
            "  1. first step do the thing",
            "  2. second step validate it",
            "  3. third step record outcome",
        ])
        p = parse_skill_md(md)
        assert len(p.strategy) == 3

    def test_governance_items_separate_steps(self) -> None:
        md = "\n".join([
            "---", "name: t", "description: optimize a system", "---", "# T", "",
            "## Quick Workflow",
            "1. define the layer being changed",
            "2. validate and record",
            "## Human Gate Defaults",
            "Ask before:",
            "  - writing long-term memory",
            "  - changing production strategy",
        ])
        p = parse_skill_md(md)
        assert any("writing long-term memory" in s for s in p.strategy)
        assert any("changing production strategy" in s for s in p.strategy)
        assert not any("validate and record" in s and "writing long-term" in s for s in p.strategy)


class TestInferCategory:
    def test_upgrade_with_rollback_is_optimize(self) -> None:
        assert infer_category([], "Use when upgrading an AI system with versioning and rollback and guard rails") == "optimize"

    def test_fix_bugs_is_repair(self) -> None:
        assert infer_category([], "review and fix critical production bugs and crashes") == "repair"

    def test_tunnel_is_innovate(self) -> None:
        assert infer_category([], "implement a tunnel for secure remote access") == "innovate"

    def test_add_is_innovate(self) -> None:
        assert infer_category([], "add a new monitoring dashboard") == "innovate"
        assert infer_category([], "add retry logic to the client") == "innovate"

    def test_additional_not_innovate(self) -> None:
        assert infer_category([], "optimize additional logging throughput") == "optimize"
        assert infer_category([], "reduce padding in the buffer layout") == "optimize"

    def test_inflected_repair_forms(self) -> None:
        assert infer_category([], "handle errors and crashes after a fix was reverted") == "repair"

    def test_underscore_signals_repair(self) -> None:
        assert infer_category(["log_error", "test_failure"], "") == "repair"

    def test_short_preconditions_kept(self) -> None:
        md = "\n".join([
            "---", "name: t", "description: optimize the build", "---",
            "# T", "", "## Prerequisites", "- Git", "- npm", "- a configured CI token", "",
            "## Workflow", "1. do the thing carefully", "2. validate it",
        ])
        p = parse_skill_md(md)
        assert "Git" in p.preconditions
        assert "npm" in p.preconditions
        assert len(p.preconditions) == 3


class TestCjkSections:
    CJK_MD = "\n".join([
        "---",
        "name: cjk-curator",
        "description: Use when curating game design sources, research, screening, review, and ingestion into a durable local knowledge base.",
        "---",
        "",
        "# 资料策展",
        "",
        "## 触发条件",
        "- 来源研究、首轮建档、候选审核、标准入库时使用",
        "",
        "## 快速工作流",
        "1. Observe：确认任务模式，从研究、建档、审核中选一个主模式。",
        "2. VOI 门：只收集会改变决策的信息，先做去重和短读。",
        "3. Decide：状态推进必须有证据，未深读不得进入 accepted。",
        "",
        "## 输出门",
        "- 检查 catalog、registry、update-history 是否同步完成",
        "- 未知字段保留 unknown，不能悄悄猜满",
        "",
        "## 不要做",
        "- 不要见文就收、短读即入库",
        "- 不要忽略去重、证据门和置信度",
        "",
        "## 前置条件",
        "- Git",
        "- 已配置的本地知识库目录",
    ])

    def setup_method(self) -> None:
        self.parsed = parse_skill_md(self.CJK_MD)

    def test_extracts_strategy_from_cjk_workflow(self) -> None:
        assert len(self.parsed.strategy) >= 5
        assert any("确认任务模式" in s for s in self.parsed.strategy)
        assert any("catalog、registry" in s for s in self.parsed.strategy)

    def test_extracts_avoid_from_cjk_heading(self) -> None:
        assert len(self.parsed.avoid) >= 2
        assert any("见文就收" in s for s in self.parsed.avoid)

    def test_signals_from_english_description(self) -> None:
        assert any(
            any(kw in s for kw in ("curat", "knowledge", "base", "source"))
            for s in self.parsed.signals_match
        )

    def test_cjk_only_body_no_signals(self) -> None:
        cjk_only = "\n".join([
            "---", "name: t", "description: 用于资料策展", "---",
            "# T", "", "## 触发条件", "- 来源研究、首轮建档、候选审核",
        ])
        assert len(parse_skill_md(cjk_only).signals_match) == 0

    def test_keeps_short_preconditions_cjk(self) -> None:
        assert "Git" in self.parsed.preconditions
