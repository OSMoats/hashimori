"""AI agent governance rule pack tests. Run: pytest

Loaded with red-zone + baseline, same as rulepacks/finance/README.md
recommends: this pack defines no tiers of its own, so it never hits the
tier-shadowing failure mode that keeps finance/healthcare off baseline.
"""

import json
from pathlib import Path

from hashimori.engine import evaluate
from hashimori.loader import load_packs, validate_pack

ROOT = Path(__file__).parent.parent
PACKS = load_packs([
    ROOT / "rulepacks" / "red-zone",
    ROOT / "rulepacks" / "ai-agent-governance",
    ROOT / "rulepacks" / "baseline",
])


def intake(name: str) -> dict:
    return json.loads((ROOT / "examples" / "intake" / f"{name}.json").read_text())


def test_ai_agent_governance_pack_validates_clean():
    assert validate_pack(ROOT / "rulepacks" / "ai-agent-governance" / "ai-agent-governance.yaml") == []


def test_unregistered_agent_is_red_zone():
    d = evaluate(PACKS, intake("agent-gov-unregistered-identity"))
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"AG-RZ-001"}


def test_no_separation_of_duties_is_red_zone():
    d = evaluate(PACKS, intake("agent-gov-no-separation-of-duties"))
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"AG-RZ-002"}


def test_untraceable_delegation_is_red_zone():
    d = evaluate(PACKS, intake("agent-gov-untraceable-delegation"))
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"AG-RZ-003"}


def test_standing_access_and_stale_review_routes_to_elevated_review():
    d = evaluate(PACKS, intake("agent-gov-standing-access-stale-review"))
    assert d.decision == "NEEDS_REVIEW"
    assert d.tier == "elevated_review"
    assert d.red_zones_hit == []  # graduated, not a hard prohibition
    hit_ids = {h["id"] for h in d.risk_factors_hit}
    assert {"AG-RISK-001", "AG-RISK-002", "AG-RISK-003", "AG-RISK-004", "AG-RISK-005"} <= hit_ids


def test_fully_governed_agent_fast_tracks():
    d = evaluate(PACKS, intake("agent-gov-fully-governed"))
    assert d.decision == "APPROVED"
    assert d.tier == "fast_track"
    assert d.red_zones_hit == []
    assert not d.unknown_paths


def test_vague_agent_submission_fails_closed():
    d = evaluate(PACKS, intake("agent-gov-vague-submission"))
    assert d.decision == "NEEDS_REVIEW"
    assert d.unknown_paths
