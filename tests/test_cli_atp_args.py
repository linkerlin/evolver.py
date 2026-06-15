"""CLI argparse coverage for ATP commands."""

from __future__ import annotations

import pytest

from evolver.cli import _build_parser


@pytest.fixture
def parser():
    return _build_parser()


def test_buy_parser_accepts_skill_id(parser):
    args = parser.parse_args(["buy", "skill_demo"])
    assert args.command == "buy"
    assert args.skill_id == "skill_demo"
    assert args.quantity == 1


def test_orders_parser_accepts_filters(parser):
    args = parser.parse_args(["orders", "--status", "open", "--limit", "5"])
    assert args.status == "open"
    assert args.limit == 5


def test_verify_parser_accepts_order_id(parser):
    args = parser.parse_args(["verify", "ord_123"])
    assert args.order_id == "ord_123"
    assert args.reject is False


def test_atp_subcommands(parser):
    args = parser.parse_args(["atp", "deposit", "10.5"])
    assert args.atp_action == "deposit"
    assert args.amount == 10.5

    args2 = parser.parse_args(["atp", "enable"])
    assert args2.atp_action == "enable"


def test_atp_complete_parser(parser):
    args = parser.parse_args(["atp-complete", "task_1"])
    assert args.task_id == "task_1"
