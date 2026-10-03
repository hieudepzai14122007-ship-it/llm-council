"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Claude (runs through the Claude Code CLI on your subscription quota) ---

# Model aliases understood by `claude --model`
CHAIRMAN_MODEL = os.getenv("CHAIRMAN_MODEL", "opus")
FAST_MODEL = os.getenv("FAST_MODEL", "haiku")  # simple questions + conversation titles
SOLO_MODEL = os.getenv("SOLO_MODEL", "sonnet")  # medium questions: one strong model, no debate

# How many Claude calls may run at once (keeps a council run from bursting your quota)
CLAUDE_MAX_CONCURRENT = int(os.getenv("CLAUDE_MAX_CONCURRENT", "3"))

# --- Laya gatekeeper (local laya-serve) ---

LAYA_ENABLED = os.getenv("LAYA_ENABLED", "1") != "0"
LAYA_URL = os.getenv("LAYA_URL", "http://127.0.0.1:8000")
# Normal calls take ~0.1-0.3 s; the first one after Laya starts can take seconds while the GPU warms up.
LAYA_TIMEOUT = float(os.getenv("LAYA_TIMEOUT", "10.0"))

# Fast path only when Laya puts at least this much probability on complexity level 1 or 2.
# Raise it to send fewer questions to the fast path; anything below runs the full council.
LAYA_FAST_MIN_PROB = float(os.getenv("LAYA_FAST_MIN_PROB", "0.75"))
# Full council only when Laya puts at least this much probability on level 4 or 5.
# Everything in between gets one SOLO_MODEL answer. Lower it to convene the council more often.
LAYA_COUNCIL_MIN_PROB = float(os.getenv("LAYA_COUNCIL_MIN_PROB", "0.5"))
# Below this confidence the topic falls back to the "general" council.
LAYA_DOMAIN_MIN_CONFIDENCE = float(os.getenv("LAYA_DOMAIN_MIN_CONFIDENCE", "0.5"))

# --- Council members per topic ---
# Every member is a Claude model with a role. "id" is what the UI shows ("model/role").

def _member(model: str, role: str, prompt: str) -> dict:
    return {"id": f"{model}/{role}", "model": model, "system_prompt": prompt}


DOMAIN_COUNCILS = {
    "code": [
        _member("opus", "engineer", "You are a senior software engineer. Give a correct, complete, production-quality answer."),
        _member("sonnet", "security", "You are a security and edge-case reviewer. Answer the question, paying special attention to failure modes, security issues and edge cases."),
        _member("haiku", "pragmatist", "You are a pragmatic engineer who prefers the simplest solution that works. Answer concisely."),
    ],
    "math": [
        _member("opus", "prover", "You are a rigorous mathematician. Justify every step and check your result."),
        _member("sonnet", "solver", "You solve problems step by step, showing the working clearly."),
        _member("haiku", "checker", "You solve the problem, then verify the answer by an independent method."),
    ],
    "legal": [
        _member("opus", "analyst", "You are a careful legal analyst. Identify the relevant principles and note when the answer depends on jurisdiction. You are not giving legal advice."),
        _member("sonnet", "devils-advocate", "You argue the strongest opposing reading of the legal question, then give a balanced conclusion."),
        _member("haiku", "plain-language", "You explain legal questions in plain language for a non-lawyer."),
    ],
    "medical": [
        _member("opus", "clinician", "You answer like a careful clinician: evidence-based, noting uncertainty and when to see a doctor. You are not a substitute for medical care."),
        _member("sonnet", "researcher", "You answer from the research evidence, noting the strength of the evidence."),
        _member("haiku", "safety", "You focus on safety: red flags, contraindications and when urgent care is needed."),
    ],
    "creative": [
        _member("opus", "writer", "You are an accomplished writer with a distinctive voice."),
        _member("sonnet", "editor", "You are a sharp editor focused on structure, clarity and impact."),
        _member("haiku", "wildcard", "You take an unexpected, original angle on creative requests."),
    ],
    "general": [
        _member("opus", "expert", "You are a knowledgeable expert. Give an accurate, well-reasoned answer."),
        _member("sonnet", "skeptic", "You are a skeptic. Answer the question, challenging assumptions and noting what is uncertain."),
        _member("haiku", "concise", "You give the clearest, most concise correct answer."),
    ],
}

# Kept for anything that still expects a flat list of council models
COUNCIL_MODELS = [m["id"] for m in DOMAIN_COUNCILS["general"]]

# Data directory for conversation storage
DATA_DIR = "data/conversations"
LAYA_LOG_PATH = "data/laya_decisions.jsonl"
USAGE_LOG_PATH = "data/usage.jsonl"

# Follow-up questions: how much of the earlier conversation the models see
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "6"))  # last N question/answer pairs
HISTORY_ANSWER_CHARS = int(os.getenv("HISTORY_ANSWER_CHARS", "4000"))  # each earlier answer is cut to this
