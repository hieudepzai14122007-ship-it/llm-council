"""Per-answer usage records and a running summary of what Laya's routing saved.

Costs are the Claude CLI's API-list-price estimates. On a subscription you are not billed
these amounts, but they are a fair measure of how much quota each answer used.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import USAGE_LOG_PATH


def total(*groups) -> Dict[str, Any]:
    """Add up the 'usage' of every stage result passed in (lists of results or single results)."""
    out = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for group in groups:
        items = group if isinstance(group, list) else [group]
        for item in items:
            u = (item or {}).get("usage") or {}
            for key in out:
                out[key] += u.get(key, 0) or 0
    out["cost_usd"] = round(out["cost_usd"], 4)
    return out


def record(route: str, usage: Dict[str, Any], seconds: float, override: bool) -> None:
    """Append one answer's usage to the log."""
    path = Path(USAGE_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "time": datetime.now(timezone.utc).isoformat(),
            "route": route,
            "override": override,
            "seconds": round(seconds, 1),
            **usage,
        }) + "\n")


def _load() -> List[Dict[str, Any]]:
    path = Path(USAGE_LOG_PATH)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def summary() -> Dict[str, Any]:
    """Totals per route, plus the estimated savings versus sending everything to the council."""
    rows = _load()
    by_route = {r: {"answers": 0, "calls": 0, "cost_usd": 0.0, "seconds": 0.0}
                for r in ("fast", "solo", "council")}
    for row in rows:
        b = by_route.setdefault(row["route"], {"answers": 0, "calls": 0, "cost_usd": 0.0, "seconds": 0.0})
        b["answers"] += 1
        b["calls"] += row.get("calls", 0)
        b["cost_usd"] += row.get("cost_usd", 0.0)
        b["seconds"] += row.get("seconds", 0.0)

    council = by_route["council"]
    avg_council: Optional[Dict[str, float]] = None
    if council["answers"]:
        n = council["answers"]
        avg_council = {"cost_usd": council["cost_usd"] / n, "calls": council["calls"] / n,
                       "seconds": council["seconds"] / n}

    saved = None
    if avg_council:
        others = [r for r in rows if r["route"] != "council"]
        saved = {
            "cost_usd": round(sum(avg_council["cost_usd"] - r.get("cost_usd", 0) for r in others), 4),
            "calls": round(sum(avg_council["calls"] - r.get("calls", 0) for r in others)),
            "seconds": round(sum(avg_council["seconds"] - r.get("seconds", 0) for r in others)),
        }

    for b in by_route.values():
        b["cost_usd"] = round(b["cost_usd"], 4)
        b["seconds"] = round(b["seconds"], 1)

    return {
        "answers": len(rows),
        "cost_usd": round(sum(r.get("cost_usd", 0) for r in rows), 4),
        "calls": sum(r.get("calls", 0) for r in rows),
        "by_route": by_route,
        "avg_council": avg_council,
        "saved": saved,  # None until at least one council answer exists to compare against
    }
