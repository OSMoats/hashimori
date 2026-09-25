"""The bridge: a design-time decision compiles into a runtime envelope.

At intake, a team *attests* things about its agent — "irreversible actions go
through an approval gate", "we only talk to these hosts". A design-time review
reads those claims. Nothing checks them afterwards. The envelope turns the
reviewed intake into the runtime limits that enforce them:

- the review tier sets the session risk budget (less-reviewed → less autonomy)
- a DENIED use case gets an envelope that denies every call
- agent.approval_gate: true → every irreversible effect asks a human
- agent.allowed_egress → the destinations the agent may reach
"""

from __future__ import annotations

import hashlib
import json

from hashimori.engine import evaluate
from hashimori.loader import Pack

DEFAULT_BUDGETS = {
    "fast_track": {"session": 30, "per_call": 8},
    "standard_review": {"session": 20, "per_call": 7},
    "elevated_review": {"session": 8, "per_call": 4},
}


def compile_envelope(packs: list[Pack], intake: dict, budgets: dict | None = None,
                     default_egress: list[str] | None = None) -> dict:
    budgets = {**DEFAULT_BUDGETS, **(budgets or {})}
    d = evaluate(packs, intake)
    agent = intake.get("agent", {}) or {}
    budget = dict(budgets.get(d.tier or "", {"session": 0, "per_call": 0}))
    notes = [f"design-time decision {d.decision} (tier {d.tier}) → session budget {budget.get('session')}"]
    if agent.get("approval_gate") is True:
        budget["per_call"] = min(budget.get("per_call", 7), 2)
        notes.append("attested approval_gate → every irreversible effect (price ≥ 3) asks a human")
    egress = sorted(set((default_egress or []) + list(agent.get("allowed_egress", []) or [])))
    return {
        "use_case": (intake.get("use_case") or {}).get("name"),
        "design_time_decision": d.decision,
        "tier": d.tier,
        "use_case_denied": d.decision == "DENIED",
        "budget": budget,
        "allowed_egress": egress,
        "attestations": {k: agent.get(k) for k in ("autonomous_actions", "irreversible_effects",
                                                    "approval_gate", "rollback_plan")},
        "notes": notes,
        "provenance": {"context_sha256": d.audit["context_sha256"],
                       "packs": [p["sha256"][:12] for p in d.audit["packs"]]},
    }
