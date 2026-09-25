"""Financial-services rule pack tests. Run: pytest

Scoped to rulepacks/red-zone + rulepacks/finance only — see the note at the
top of test_engine.py and rulepacks/finance/README.md "Composition" for why
this pack is never loaded alongside rulepacks/baseline.
"""

import json
from pathlib import Path

from hashimori.engine import evaluate
from hashimori.loader import load_packs, validate_pack

ROOT = Path(__file__).parent.parent
PACKS = load_packs([ROOT / "rulepacks" / "red-zone", ROOT / "rulepacks" / "finance"])


def intake(name: str) -> dict:
    return json.loads((ROOT / "examples" / "intake" / f"{name}.json").read_text())


def test_finance_pack_validates_clean():
    assert validate_pack(ROOT / "rulepacks" / "finance" / "finance.yaml") == []


def test_underwriting_prescreen_routes_to_standard_review():
    d = evaluate(PACKS, intake("finance-credit-underwriting-standard"))
    assert d.decision == "NEEDS_REVIEW"
    assert d.tier == "standard_review"
    assert d.reviewers == ["security", "compliance"]
    assert d.sla_days == 5


def test_trading_with_controls_still_needs_elevated_review():
    d = evaluate(PACKS, intake("finance-algo-trading-with-controls"))
    assert d.decision == "NEEDS_REVIEW"
    assert d.tier == "elevated_review"
    assert "model_risk_committee" in d.reviewers
    assert d.red_zones_hit == []  # controls in place — not short-circuited


def test_credit_denial_with_no_explainability_is_red_zone():
    d = evaluate(PACKS, intake("finance-credit-denial-no-explainability"))
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"FIN-RZ-001"}
    assert d.risk_factors_hit == []  # short-circuited before scoring


def test_aml_auto_dismiss_is_red_zone():
    d = evaluate(PACKS, intake("finance-aml-auto-dismiss"))
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"FIN-RZ-002"}


def test_trading_without_kill_switch_is_red_zone():
    d = evaluate(PACKS, intake("finance-trading-no-kill-switch"))
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"FIN-RZ-003"}


def test_robo_advice_without_disclosure_is_red_zone():
    d = evaluate(PACKS, intake("finance-robo-advice-no-disclosure"))
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"FIN-RZ-004"}


def test_cardholder_data_without_agreement_is_red_zone():
    d = evaluate(PACKS, intake("finance-cardholder-data-no-agreement"))
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"FIN-RZ-005"}


def test_credit_model_without_validation_is_red_zone():
    d = evaluate(PACKS, intake("finance-credit-no-model-validation"))
    assert d.decision == "DENIED"
    assert {h["id"] for h in d.red_zones_hit} == {"FIN-RZ-006"}


def test_vague_finance_submission_fails_closed():
    d = evaluate(PACKS, intake("finance-vague-submission"))
    assert d.decision == "NEEDS_REVIEW"
    assert d.unknown_paths
