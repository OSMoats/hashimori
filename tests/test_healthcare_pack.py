"""Healthcare rule pack tests. Run: pytest

The healthcare pack ships its own vocabulary (`clinical.*`) and its own
tiers, so it's loaded together with `red-zone` only — never `baseline`,
which also ships tiers the engine would flatten ahead of healthcare's. See
rulepacks/healthcare/README.md for why.
"""

import json
from pathlib import Path

from hashimori.engine import evaluate
from hashimori.loader import load_packs, validate_pack

ROOT = Path(__file__).parent.parent
PACKS = load_packs([ROOT / "rulepacks" / "red-zone", ROOT / "rulepacks" / "healthcare"])


def intake(name: str) -> dict:
    return json.loads((ROOT / "examples" / "intake" / f"{name}.json").read_text())


def test_healthcare_pack_validates_clean():
    assert validate_pack(ROOT / "rulepacks" / "healthcare" / "healthcare.yaml") == []


def test_ambient_scribe_with_attestation_needs_standard_review():
    d = evaluate(PACKS, intake("healthcare-ambient-scribe"))
    assert d.decision == "NEEDS_REVIEW"
    assert d.tier == "standard_review"
    assert d.unknown_paths == []
    assert d.red_zones_hit == []


def test_cleared_pediatric_imaging_ai_still_needs_committee():
    d = evaluate(PACKS, intake("healthcare-diagnostic-imaging-ai"))
    assert d.decision == "NEEDS_REVIEW"
    assert d.tier == "elevated_review"
    assert d.unknown_paths == []


def test_uncleared_triage_bot_hits_red_zones_the_generic_pack_would_miss():
    ctx = intake("healthcare-uncleared-triage-bot")
    assert ctx["use_case"]["decision_impact"] == "none"  # not self-reported as consequential
    d = evaluate(PACKS, ctx)
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"HC-RZ-001", "HC-RZ-005"}


def test_phi_without_baa_is_denied():
    d = evaluate(PACKS, intake("healthcare-phi-no-baa"))
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"HC-RZ-002"}


def test_vague_healthcare_submission_fails_closed():
    d = evaluate(PACKS, intake("healthcare-vague-submission"))
    assert d.decision == "NEEDS_REVIEW"
    assert "model.baa_signed" in d.unknown_paths
    assert "oversight.human_in_loop" in d.unknown_paths
