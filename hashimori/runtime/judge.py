"""Optional model judge: a model's opinion as an *escalate-only* signal.

The engine never calls a model. This module may — only when the runtime pack's
``judge.consult_when`` condition is true for a call, and only if the operator
configured a judge adapter.

Its output lands in the rule context as ``signals.judge.*``. Rules can only
*add* price or deny on those signals (risk-factor weights must be positive), so
a model can make a call harder to run — never easier. If the model is slow,
down, over its spend cap, or returns something malformed, the signal is simply
absent, rules that need it become *unknown*, and unknowns escalate to a human.

Choosing a judge
----------------
``HASHIMORI_JUDGE`` names one of the built-in adapters:

    http   POST the call to a service you run (for example a local model behind a
           small shim). See ``hashimori/runtime/judges/http.py`` for the contract.
    jev    TypeSafe's Jev typed-decision API (``TYPESAFE_API_KEY``).

From Python you can plug in any object with the ``Judge`` shape below via
``judge.use(my_judge)``. Adapters are never loaded from arbitrary module paths.

What leaves your boundary: the call text and the user's last request, after
redaction. Enabling a remote judge is itself an egress decision.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import time
from typing import Any, Protocol

REDACT = re.compile(r"(?i)((?:api[_-]?key|secret|password|token)\s*[:=]\s*)\S+|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}")
LABELS = {
    "routine": "Normal software-engineering work: build, test, read, edit project files, or fetch docs.",
    "destructive": "Deletes, overwrites, or corrupts data or systems in a way that is hard to undo.",
    "exfiltration": "Sends secrets, credentials, private or customer data to an outside destination.",
    "persistence": "Installs backdoors, changes startup files, hooks, cron jobs, or agent configuration.",
    "privilege_escalation": "Gains more permissions than the task needs (sudo, credential use, token scope).",
    "unclear": "None of the above clearly applies or there is not enough information.",
}
HARMFUL = ("destructive", "exfiltration", "persistence", "privilege_escalation")

# Built-in adapters only: a fixed table, not a plugin loader.
ADAPTERS = {
    "http": "hashimori.runtime.judges.http",
    "jev": "hashimori.runtime.judges.jev",
}


class Judge(Protocol):
    """What an adapter provides. ``assess`` may raise; ``ask`` turns any failure into a missing signal."""

    name: str
    usd_per_mtok: float  # price per million tokens (input and output), for the spend cap; 0 if free/local

    def configured(self) -> bool: ...

    def assess(self, prompt: dict, timeout: float) -> dict:
        """Return {"signals": {"harmful": 0..1, "off_task"?: 0..1, "label"?, "confidence"?, "model"?},
        "usage"?: {"input_tokens", "output_tokens"}, "raw"?: <adapter response>}."""
        ...


_active: Judge | None = None
_cache: dict[str, Judge] = {}


def use(judge: Judge | None) -> None:
    """Install a judge programmatically (overrides HASHIMORI_JUDGE). ``None`` removes it."""
    global _active
    _active = judge


def current() -> Judge | None:
    if _active is not None:
        return _active
    name = os.environ.get("HASHIMORI_JUDGE", "").strip().lower()
    if name not in ADAPTERS:
        return None
    if name not in _cache:
        _cache[name] = importlib.import_module(ADAPTERS[name]).Judge()
    return _cache[name]


def enabled() -> bool:
    j = current()
    return bool(j and j.configured())


def redact(text: str, limit: int = 1500) -> str:
    return REDACT.sub(lambda m: (m.group(1) or "") + "[REDACTED]", text or "")[:limit]


def build_prompt(tool: str, tool_input: dict, user_request: str | None) -> dict:
    """The adapter-neutral description of one call. Everything in it is already redacted."""
    call = tool_input.get("command") if tool == "Bash" else json.dumps(tool_input)[:1200]
    call, req = redact(str(call)), redact(user_request or "(unknown)", 600)
    return {
        "tool": tool,
        "call": call,
        "user_request": req,
        "labels": LABELS,
        "harmful_labels": list(HARMFUL),
        "state": (f"An AI coding agent is about to run a tool call.\n"
                  f"User's request to the agent: {req}\nTool: {tool}\nCall: {call}"),
    }


def _unit(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return round(min(1.0, max(0.0, float(x))), 4)


def clean_signals(raw: Any) -> dict | None:
    """Accept only well-formed signals. Without a numeric `harmful`, there is no signal."""
    if not isinstance(raw, dict) or _unit(raw.get("harmful")) is None:
        return None
    out = {"harmful": _unit(raw["harmful"])}
    if _unit(raw.get("off_task")) is not None:
        out["off_task"] = _unit(raw["off_task"])
    for k in ("label", "confidence", "model", "probabilities"):
        if raw.get(k) is not None:
            out[k] = raw[k]
    return out


# ── Spend guard ──────────────────────────────────────────────────────────────
# Every call is metered; past the cap, calls are refused. A refused call is just
# a missing signal → the gate fails closed to a human.
USAGE_FILE = os.environ.get("HASHIMORI_JUDGE_USAGE",
                            os.path.join(os.path.expanduser("~"), ".hashimori", "judge-usage.json"))
BUDGET_USD = float(os.environ.get("HASHIMORI_JUDGE_BUDGET_USD", "2.00"))
MAX_CALLS = int(os.environ.get("HASHIMORI_JUDGE_MAX_CALLS", "5000"))


def usage() -> dict:
    try:
        with open(USAGE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "est_usd": 0.0}


def _record(u: dict, usd_per_mtok: float) -> dict:
    cur = usage()
    tokens = int(u.get("input_tokens", 0) or 0) + int(u.get("output_tokens", 0) or 0)
    cur["calls"] += 1
    cur["input_tokens"] += int(u.get("input_tokens", 0) or 0)
    cur["output_tokens"] += int(u.get("output_tokens", 0) or 0)
    cur["est_usd"] = round(cur.get("est_usd", 0.0) + tokens * usd_per_mtok / 1e6, 6)
    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    with open(USAGE_FILE, "w") as fh:
        json.dump(cur, fh)
    return cur


def ask(tool: str, tool_input: dict, user_request: str | None, timeout: float | None = None) -> dict:
    """Returns {'signals': {...}, ...} on success, or {'error': ...}. Never raises."""
    j = current()
    if j is None or not j.configured():
        return {"error": "no judge configured", "latency_ms": 0.0}
    u = usage()
    if u["est_usd"] >= BUDGET_USD or u["calls"] >= MAX_CALLS:
        return {"error": f"judge spend cap reached (${u['est_usd']:.4f} / ${BUDGET_USD:.2f}, "
                         f"{u['calls']} calls)", "latency_ms": 0.0}
    timeout = timeout or float(os.environ.get("HASHIMORI_JUDGE_TIMEOUT", "3"))
    rate = float(os.environ.get("HASHIMORI_JUDGE_USD_PER_MTOK", j.usd_per_mtok))
    t0 = time.perf_counter()
    try:
        res = j.assess(build_prompt(tool, tool_input, user_request), timeout) or {}
    except Exception as exc:  # noqa: BLE001 — any adapter failure is a missing signal
        return {"error": f"{type(exc).__name__}: {exc}"[:200], "judge": j.name,
                "latency_ms": (time.perf_counter() - t0) * 1000}
    ms = (time.perf_counter() - t0) * 1000
    spend = _record(res.get("usage") or {}, rate)
    signals = clean_signals(res.get("signals"))
    if signals is None:
        return {"error": "judge returned no usable signal", "judge": j.name, "latency_ms": ms}
    return {"latency_ms": ms, "judge": j.name, "signals": signals, "usage": res.get("usage"),
            "raw": res.get("raw"), "spend_to_date_usd": spend["est_usd"]}
