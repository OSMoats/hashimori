"""Engine tests. Run: pytest"""

import json
from pathlib import Path

import pytest

from hashimori.conditions import evaluate_condition
from hashimori.engine import evaluate
from hashimori.loader import load_packs, validate_pack

ROOT = Path(__file__).parent.parent
PACKS = load_packs([ROOT / "rulepacks"])


def intake(name: str) -> dict:
    return json.loads((ROOT / "examples" / "intake" / f"{name}.json").read_text())


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

def test_leaf_operators():
    ctx = {"a": {"b": "Hello"}, "n": 5, "tags": ["x", "Y"]}
    assert evaluate_condition({"path": "a.b", "is": "hello"}, ctx).is_true
    assert evaluate_condition({"path": "n", "gte": 5}, ctx).is_true
    assert evaluate_condition({"path": "tags", "contains": "y"}, ctx).is_true
    assert evaluate_condition({"path": "a.b", "matches": "(?i)^hel"}, ctx).is_true
    assert evaluate_condition({"path": "a.b", "in": ["hi", "hello"]}, ctx).is_true
    assert not evaluate_condition({"path": "n", "lt": 5}, ctx).is_true


def test_missing_path_is_unknown_not_false():
    res = evaluate_condition({"path": "nope.nothing", "is": True}, {})
    assert res.is_unknown
    assert res.unknown_paths == ["nope.nothing"]


def test_decided_groups_prune_unknowns():
    # 'all' with a definitively-false child is False even if a sibling is unknown
    cond = {"all": [{"path": "x", "is": True}, {"path": "missing", "is": True}]}
    res = evaluate_condition(cond, {"x": False})
    assert res.value is False
    assert res.unknown_paths == []
    # 'any' with a true child is True even if a sibling is unknown
    cond = {"any": [{"path": "x", "is": True}, {"path": "missing", "is": True}]}
    assert evaluate_condition(cond, {"x": True}).value is True


def test_exists_operator():
    assert evaluate_condition({"path": "a", "exists": True}, {"a": 1}).is_true
    assert evaluate_condition({"path": "b", "exists": False}, {"a": 1}).is_true


def test_in_and_not_in_reject_a_bare_string_instead_of_a_list():
    # A pack author writing `in: credit` instead of `in: [credit]` used to be
    # silently interpreted as "credit" in list("credit") -- checked one
    # character at a time, which a real value almost never matches. That
    # turned a rule meant to fire into one that silently never does, with no
    # error anywhere: `hashimori validate` catches this typo, but
    # `hashimori evaluate` -- what actually runs in production -- did not,
    # so a red zone written to deny a real case would come back APPROVED.
    # `in`/`not_in` now fail loudly instead of silently misevaluating.
    with pytest.raises(ValueError, match="expects a list"):
        evaluate_condition({"path": "x", "in": "credit"}, {"x": "credit"})
    with pytest.raises(ValueError, match="expects a list"):
        evaluate_condition({"path": "x", "not_in": "ab"}, {"x": "z"})

    # correctly bracketed still behaves exactly as before
    assert evaluate_condition({"path": "x", "in": ["credit"]}, {"x": "credit"}).value is True
    assert evaluate_condition({"path": "x", "not_in": ["a", "b"]}, {"x": "z"}).value is True


# ---------------------------------------------------------------------------
# Engine on the shipped examples
# ---------------------------------------------------------------------------

def test_docs_answerbot_fast_tracks():
    d = evaluate(PACKS, intake("docs-answerbot"))
    assert d.decision == "APPROVED"
    assert d.tier == "fast_track"
    assert d.unknown_paths == []
    assert "register_in_ai_inventory" in d.obligations


def test_support_chatbot_needs_standard_review():
    d = evaluate(PACKS, intake("support-chatbot"))
    assert d.decision == "NEEDS_REVIEW"
    assert d.tier == "standard_review"
    assert d.score == 5
    assert d.reviewers == ["security"]
    assert d.sla_days == 5


def test_loan_agent_hits_red_zones():
    d = evaluate(PACKS, intake("loan-agent"))
    assert d.decision == "DENIED"
    hit_ids = {h["id"] for h in d.red_zones_hit}
    assert hit_ids == {"REDZONE-001", "REDZONE-005"}
    assert d.tier is None
    assert d.risk_factors_hit == []  # short-circuited before scoring


def test_vague_submission_fails_closed():
    d = evaluate(PACKS, intake("vague-submission"))
    assert d.decision == "NEEDS_REVIEW"
    assert d.unknown_paths  # the gaps are named
    assert "oversight.human_in_loop" in d.unknown_paths


def test_red_zone_short_circuit_skips_scoring():
    ctx = intake("loan-agent")
    d = evaluate(PACKS, ctx)
    assert d.score == 0.0


def test_audit_trail_is_reproducible():
    ctx = intake("docs-answerbot")
    d1, d2 = evaluate(PACKS, ctx), evaluate(PACKS, ctx)
    assert d1.audit["context_sha256"] == d2.audit["context_sha256"]
    assert d1.audit["packs"] == d2.audit["packs"]
    assert all(len(p["sha256"]) == 64 for p in d1.audit["packs"])


def test_decision_serializes_to_json():
    d = evaluate(PACKS, intake("docs-answerbot"))
    round_tripped = json.loads(d.to_json())
    assert round_tripped["decision"] == "APPROVED"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_shipped_packs_validate_clean():
    for pack_file in (ROOT / "rulepacks").rglob("*.yaml"):
        assert validate_pack(pack_file) == [], f"{pack_file} failed validation"


def test_validator_catches_broken_pack(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: 1\n"
        "red_zones:\n"
        "  - id: REDZONE-X\n"
        "    when: {path: a, matches: '['}\n"
        "tiers:\n"
        "  - name: t\n"
        "    outcome: nonsense\n"
    )
    errors = validate_pack(bad)
    assert any("missing 'name'" in e for e in errors)
    assert any("invalid regex" in e for e in errors)
    assert any("'outcome' must be one of" in e for e in errors)
    assert any("'message'" in e for e in errors)


def test_no_tiers_raises():
    from hashimori.loader import Pack

    with pytest.raises(ValueError, match="tiers"):
        evaluate([Pack(name="empty", description="", source="x")], {})
