"""Operations module: lifecycle, health, cleanup, self-repair, skills monitoring.

Equivalent to evolver/src/ops/.
"""

from __future__ import annotations

from evolver.ops.cleanup import run_cleanup
from evolver.ops.health_check import run_health_check
from evolver.ops.innovation import (
    compute_innovation_roi,
    get_innovation_summary,
    record_innovation_attempt,
    record_innovation_outcome,
)
from evolver.ops.lifecycle import (
    check_health as check_lifecycle_health,
)
from evolver.ops.lifecycle import (
    restart,
    start,
    status,
    stop,
)
from evolver.ops.narrative import (
    append_narrative,
    append_reflection,
    generate_narrative,
    generate_reflection,
    record_narrative_and_reflection,
)
from evolver.ops.self_repair import repair
from evolver.ops.skills_monitor import auto_fix_skills, check_skills_health, run_skills_monitor
from evolver.ops.sqlite_store import (
    append_event,
    event_count,
    read_all_events,
    read_events,
    read_events_range,
    read_events_replay,
)
from evolver.ops.trigger import (
    check_file_trigger,
    consume_file_trigger,
    create_file_trigger,
    record_http_trigger,
    wait_for_trigger,
)

__all__ = [
    "append_event",
    "append_narrative",
    "append_reflection",
    "auto_fix_skills",
    "check_file_trigger",
    "check_lifecycle_health",
    "check_skills_health",
    "compute_innovation_roi",
    "consume_file_trigger",
    "create_file_trigger",
    "event_count",
    "generate_narrative",
    "generate_reflection",
    "get_innovation_summary",
    "read_all_events",
    "read_events",
    "read_events_range",
    "read_events_replay",
    "record_http_trigger",
    "record_innovation_attempt",
    "record_innovation_outcome",
    "record_narrative_and_reflection",
    "repair",
    "restart",
    "run_cleanup",
    "run_health_check",
    "run_skills_monitor",
    "start",
    "status",
    "stop",
    "wait_for_trigger",
]
