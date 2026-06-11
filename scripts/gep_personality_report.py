#!/usr/bin/env python3
"""Generate a simple HTML report for GEP personality state.

Usage:
    python scripts/gep_personality_report.py -o personality.html
"""

from __future__ import annotations

import argparse
import html
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="GEP personality HTML report")
    parser.add_argument("-o", "--output", default="personality_report.html")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from evolver.gep.personality import (
        is_conservative_personality,
        is_high_risk_personality,
        load_personality,
        personality_to_strategy_bias,
    )

    personality = load_personality()
    bias = personality_to_strategy_bias(personality)
    risk = "high" if is_high_risk_personality(personality) else (
        "conservative" if is_conservative_personality(personality) else "balanced"
    )

    rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v:.3f}</td></tr>"
        for k, v in sorted(personality.items())
    )
    bias_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v:+.3f}</td></tr>"
        for k, v in sorted(bias.items())
    )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>GEP Personality Report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0d1117; color: #e6edf3; }}
    table {{ border-collapse: collapse; margin: 1rem 0; }}
    td, th {{ border: 1px solid #30363d; padding: 0.4rem 0.8rem; }}
    th {{ background: #161b22; }}
  </style>
</head>
<body>
  <h1>GEP Personality</h1>
  <p>Generated: {html.escape(datetime.now().isoformat())}</p>
  <p>Risk profile: <strong>{html.escape(risk)}</strong></p>
  <h2>Traits</h2>
  <table><tr><th>Key</th><th>Value</th></tr>{rows}</table>
  <h2>Strategy bias</h2>
  <table><tr><th>Category</th><th>Bias</th></tr>{bias_rows}</table>
</body>
</html>
"""

    out = Path(args.output)
    out.write_text(doc, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
