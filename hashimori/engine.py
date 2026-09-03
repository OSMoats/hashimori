"""The Hashimori evaluation engine.

Deterministic, auditable, boring on purpose:

1. **Red zones first.** Every red zone in every pack is checked. Any match
   short-circuits the request to DENIED — no scoring, no meetings, no committee.
2. **Fail closed.** If a red-zone check couldn't be decided because the intake
   was missing data, the request cannot be auto-approved. It becomes
   NEEDS_REVIEW with the missing paths named.
3. **Graduated tiers.** Otherwise, risk factors are summed into a score and the
   score selects a tier: auto-approve with obligations, or route to the right
   reviewers with an SLA.

There is no model call anywhere in this file. That is the point.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from hashimori.conditions import evaluate_condition
from hashimori.loader import Pack

ENGINE = "hashimori"


@dataclass
class Decision:
    decision: str  # DENIED | APPROVED | NEEDS_REVIEW
    tier: str | None
    score: float
    red_zones_hit: list[dict]
    risk_factors_hit: list[dict]
    obligations: list[str]
    reviewers: list[str]
    sla_days: int | None
    unknown_paths: list[str]
    reasons: list[str]
    audit: dict
    auto_approval_blocked: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


def _hit(rule: dict, pack: Pack, extra: dict | None = None) -> dict:
    out = {
        "id": rule.get("id"),
        "name": rule.get("name"),
        "pack": pack.name,
        "refs": rule.get("refs", []),
    }
    if rule.get("message"):
        out["message"] = rule["message"]
    if rule.get("remedy"):
        out["remedy"] = rule["remedy"]
    if extra:
        out.update(extra)
    return out


def evaluate(packs: list[Pack], context: dict, now: datetime | None = None) -> Decision:
    """Evaluate an intake context against one or more policy packs."""
    now = now or datetime.now(timezone.utc)
    red_hits: list[dict] = []
    unknowns: list[str] = []

    # ---- Phase 1: red zones (short-circuit) --------------------------------
    for pack in packs:
        for rz in pack.red_zones:
            result = evaluate_condition(rz["when"], context)
            unknowns.extend(result.unknown_paths)
            if result.value:
                red_hits.append(_hit(rz, pack))

    audit = _audit(packs, context, now)

    if red_hits:
        return Decision(
            decision="DENIED",
            tier=None,
            score=0.0,
            red_zones_hit=red_hits,
            risk_factors_hit=[],
            obligations=[],
            reviewers=[],
            sla_days=None,
            unknown_paths=sorted(set(unknowns)),
            reasons=[f"Red zone {h['id']}: {h['name']}" for h in red_hits],
            audit=audit,
        )

    # ---- Phase 2: risk scoring --------------------------------------------
    factor_hits: list[dict] = []
    score = 0.0
    for pack in packs:
        for rf in pack.risk_factors:
            result = evaluate_condition(rf["when"], context)
            unknowns.extend(result.unknown_paths)
            if result.value:
                weight = float(rf.get("weight", 1))
                score += weight
                factor_hits.append(_hit(rf, pack, {"weight": weight}))

    unknown_sorted = sorted(set(unknowns))

    # ---- Phase 3: tier selection ------------------------------------------
    tiers = [t for pack in packs for t in pack.tiers]
    if not tiers:
        raise ValueError("No tiers defined in any pack — add a 'tiers:' section.")

    tier = tiers[-1]  # catch-all default
    for t in tiers:
        max_score = t.get("max_score")
        if max_score is None or score <= float(max_score):
            tier = t
            break

    outcome = {"approved": "APPROVED", "denied": "DENIED", "needs_review": "NEEDS_REVIEW"}[
        tier["outcome"]
    ]
    reasons = [
        f"Score {score:g} falls in tier '{tier['name']}'",
        *[f"Risk factor {h['id']} (+{h['weight']:g}): {h['name']}" for h in factor_hits],
    ]

    # ---- Fail closed: unknowns block auto-approval -------------------------
    blocked = False
    if outcome == "APPROVED" and unknown_sorted:
        outcome = "NEEDS_REVIEW"
        blocked = True
        reasons.insert(
            0,
            "Auto-approval blocked: intake is missing data the policy needs "
            f"({', '.join(unknown_sorted)}). Hashimori fails closed.",
        )

    return Decision(
        decision=outcome,
        tier=tier["name"],
        score=score,
        red_zones_hit=[],
        risk_factors_hit=factor_hits,
        obligations=list(tier.get("obligations", [])),
        reviewers=list(tier.get("reviewers", [])),
        sla_days=tier.get("sla_days"),
        unknown_paths=unknown_sorted,
        reasons=reasons,
        audit=audit,
        auto_approval_blocked=blocked,
    )


def _audit(packs: list[Pack], context: dict, now: datetime) -> dict:
    from hashimori import __version__

    context_hash = hashlib.sha256(
        json.dumps(context, sort_keys=True, default=str).encode()
    ).hexdigest()
    return {
        "engine": f"{ENGINE} {__version__}",
        "evaluated_at": now.isoformat(),
        "packs": [{"name": p.name, "source": p.source, "sha256": p.sha256} for p in packs],
        "context_sha256": context_hash,
        "deterministic": True,
    }
