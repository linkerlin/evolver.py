"""WebUI observer subsystem — transforms local state into WebUI-ready data."""

from .asset_call_log import call_log_summary, calls_by_run, cost_index, recent_calls, reuse_summary
from .assets import serialize_assets
from .commentary_obs import latest_all_commentaries, latest_commentary
from .github import get_open_prs, get_pr_status, get_repo_info
from .health import health_check, health_summary
from .insights import pipeline_insights
from .interactions import format_interactions
from .jsonl import stream_jsonl
from .lifecycle_obs import lifecycle_status, lifecycle_summary
from .narrative_obs import narrative_history, narrative_summary, reflection_entries
from .paths import sanitize_path
from .personality import personality_data
from .pipeline_events import pipeline_timeline
from .redact import redact_text
from .runs import runs_history
from .safety import safety_events
from .skills import skills_health, skills_monitor_run, skills_status
from .status import system_status

__all__ = [
    "call_log_summary",
    "calls_by_run",
    "cost_index",
    "format_interactions",
    "get_open_prs",
    "get_pr_status",
    "get_repo_info",
    "health_check",
    "health_summary",
    "latest_all_commentaries",
    "latest_commentary",
    "lifecycle_status",
    "lifecycle_summary",
    "narrative_history",
    "narrative_summary",
    "personality_data",
    "pipeline_insights",
    "pipeline_timeline",
    "recent_calls",
    "redact_text",
    "reflection_entries",
    "reuse_summary",
    "runs_history",
    "safety_events",
    "sanitize_path",
    "serialize_assets",
    "skills_health",
    "skills_monitor_run",
    "skills_status",
    "stream_jsonl",
    "system_status",
]
