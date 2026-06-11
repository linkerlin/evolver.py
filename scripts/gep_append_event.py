#!/usr/bin/env python3
"""Append a manual event record to GEP events.jsonl.

Usage:
    python scripts/gep_append_event.py --type note --message "manual checkpoint"
    python scripts/gep_append_event.py --json '{"type":"custom","detail":{}}'
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Append an event to GEP events.jsonl")
    parser.add_argument("--type", default="manual", help="Event type field")
    parser.add_argument("--message", default="", help="Short message / note")
    parser.add_argument("--json", dest="json_blob", default=None, help="Full JSON object")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.asset_store import append_event_jsonl

    if args.json_blob:
        try:
            record = json.loads(args.json_blob)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}", file=sys.stderr)
            return 1
        if not isinstance(record, dict):
            print("JSON root must be an object", file=sys.stderr)
            return 1
    else:
        record = {
            "type": args.type,
            "message": args.message,
            "source": "gep_append_event.py",
        }

    record.setdefault("timestamp", time.time())
    append_event_jsonl(record)
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
