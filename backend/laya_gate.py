"""Laya gatekeeper: decides, before any LLM call, how much model a prompt needs and
which topic-specific council should answer it.

Routes: "fast" (one cheap model), "solo" (one strong model, no debate), "council" (all 3 stages).
Laya runs locally (laya-serve), so this costs ~0.1 s and no quota. If Laya is
unreachable, the gate fails open: the full general council runs.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import httpx

from .config import (
    LAYA_ENABLED, LAYA_URL, LAYA_TIMEOUT, LAYA_FAST_MIN_PROB, LAYA_COUNCIL_MIN_PROB,
    LAYA_DOMAIN_MIN_CONFIDENCE, LAYA_LOG_PATH, DOMAIN_COUNCILS,
)

ROUTES = ("fast", "solo", "council")

# One long-lived client: a fresh one per call added ~1 s of connection setup (and a
# trust_env=False client skips Windows proxy lookups on every request).
_client: httpx.AsyncClient = None

# Semantic labels only: the Laya README warns choice keys like yes/no get followed literally.
QUESTIONS = {
    "complexity": {
        "type": "score",
        "instructions": "How complex is this request, and how much would it benefit from several experts debating it?",
        "criteria": [
            "trivial: greeting, small talk or a single well-known fact",
            "simple: a short factual lookup, definition or quick conversion",
            "moderate: needs some explanation or a few steps of reasoning",
            "complex: multi-step analysis, design, debugging or a non-trivial problem",
            "very complex: open-ended, involves trade-offs or judgement where experts would disagree",
        ],
    },
    "domain": {
        "type": "choice",
        "instructions": "Which field does this request mainly belong to?",
        "criteria": {
            "code": "programming, software, debugging, algorithms, devops",
            "math": "mathematics, calculations, proofs, statistics, logic puzzles",
            "legal": "law, contracts, regulations, rights, compliance",
            "medical": "health, symptoms, medicine, drugs, treatment",
            "creative": "stories, poems, slogans, creative writing, brainstorming",
            "general": "anything else: general knowledge, advice, business, history, science",
        },
    },
}


def _fail_open(reason: str) -> Dict[str, Any]:
    return {
        "route": "council",
        "domain": "general",
        "reason": reason,
        "complexity": None,
        "p_simple": None,
        "p_hard": None,
        "domain_confidence": None,
        "latency_ms": None,
    }


async def classify(prompt: str) -> Dict[str, Any]:
    """
    Ask Laya how complex the prompt is and which topic it belongs to.

    Returns:
        Dict with 'route' ("fast" or "council"), 'domain', the raw scores and a 'reason'.
    """
    if not LAYA_ENABLED:
        decision = _fail_open("Laya disabled")
        _log(prompt, decision)
        return decision

    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=LAYA_TIMEOUT, trust_env=False)

    t0 = time.perf_counter()
    try:
        r = await _client.post(
            f"{LAYA_URL}/v1/systemone",
            json={"state": {"request": prompt}, "questions": QUESTIONS},
        )
        r.raise_for_status()
        answers = r.json()["answers"]
    except Exception as e:
        decision = _fail_open(f"Laya unavailable ({type(e).__name__}), running full council")
        _log(prompt, decision)
        return decision
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    cx = answers["complexity"]
    dm = answers["domain"]
    score = cx["score"]  # expected level on a 0-4 scale
    probs = cx["probabilities"]
    p_simple = probs["0"] + probs["1"]  # levels 1-2
    p_hard = probs["3"] + probs["4"]  # levels 4-5
    domain = dm["choice"] if dm["answer_confidence"] >= LAYA_DOMAIN_MIN_CONFIDENCE else "general"
    if domain not in DOMAIN_COUNCILS:
        domain = "general"

    if p_simple >= LAYA_FAST_MIN_PROB:
        route, reason = "fast", f"simple ({p_simple:.0%} sure)"
    elif p_hard >= LAYA_COUNCIL_MIN_PROB:
        route, reason = "council", f"hard ({p_hard:.0%} chance of level 4-5)"
    else:
        route, reason = "solo", f"medium ({p_simple:.0%} simple, {p_hard:.0%} hard)"

    decision = {
        "route": route,
        "domain": domain,
        "reason": reason,
        "complexity": round(score + 1, 2),  # reported on the 1-5 scale
        "p_simple": round(p_simple, 4),
        "p_hard": round(p_hard, 4),
        "domain_choice": dm["choice"],
        "domain_confidence": dm["answer_confidence"],
        "domain_probabilities": dm["probabilities"],
        "latency_ms": latency_ms,
    }
    _log(prompt, decision)
    return decision


def log_override(prompt: str, laya_route: str, chosen_route: str) -> None:
    """Record that the user overrode Laya: a corrected label for fine-tuning Laya later."""
    _log(prompt, {"laya_route": laya_route, "chosen_route": chosen_route}, event="override")


def _log(prompt: str, decision: Dict[str, Any], event: str = "decision") -> None:
    """Append every decision so routing can be reviewed (and Laya fine-tuned) later."""
    try:
        path = Path(LAYA_LOG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "time": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "prompt": prompt,
                **decision,
            }, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"Could not write Laya log: {e}")
