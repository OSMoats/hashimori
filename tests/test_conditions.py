"""Condition-tree edge cases not covered by test_engine.py's happy paths.

Covers the operators and error paths a coverage run showed were previously
untouched by any test: `not_contains`, `gt`/`lt`/`lte`, `matches` on a
non-string, the `none` group, and every raise/append path in
evaluate_condition and validate_condition.
"""

import pytest

from hashimori.conditions import evaluate_condition, validate_condition


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def test_not_contains_operator():
    assert evaluate_condition({"path": "tags", "not_contains": "z"}, {"tags": ["a", "b"]}).value is True
    assert evaluate_condition({"path": "tags", "not_contains": "a"}, {"tags": ["a", "b"]}).value is False
    assert evaluate_condition({"path": "s", "not_contains": "z"}, {"s": "hello"}).value is True
    assert evaluate_condition({"path": "s", "not_contains": "hel"}, {"s": "hello"}).value is False


def test_gt_lt_lte_operators():
    ctx = {"n": 5}
    assert evaluate_condition({"path": "n", "gt": 3}, ctx).value is True
    assert evaluate_condition({"path": "n", "gt": 5}, ctx).value is False
    assert evaluate_condition({"path": "n", "lt": 10}, ctx).value is True
    assert evaluate_condition({"path": "n", "lte": 5}, ctx).value is True


def test_numeric_operators_are_false_not_crash_on_non_numeric_actual():
    # actual is a non-numeric string; the rule pack author's expected value
    # is a number -- this should be False (the rule doesn't fire), never an
    # unhandled exception, since intake data is untrusted and can contain
    # anything.
    ctx = {"n": "not-a-number"}
    for op in ("gt", "gte", "lt", "lte"):
        assert evaluate_condition({"path": "n", op: 5}, ctx).value is False


def test_matches_operator_false_on_non_string_actual():
    assert evaluate_condition({"path": "n", "matches": "5"}, {"n": 5}).value is False


def test_none_group():
    # 'none' with every child false is True
    cond = {"none": [{"path": "x", "is": True}, {"path": "y", "is": True}]}
    assert evaluate_condition(cond, {"x": False, "y": False}).value is True
    # 'none' with one true child is decided False, even with an unknown sibling
    cond = {"none": [{"path": "x", "is": True}, {"path": "missing", "is": True}]}
    res = evaluate_condition(cond, {"x": True})
    assert res.value is False
    assert res.unknown_paths == []
    # 'none' with an unknown child and no true child is unknown
    cond = {"none": [{"path": "x", "is": True}, {"path": "missing", "is": True}]}
    res = evaluate_condition(cond, {"x": False})
    assert res.value is None
    assert res.unknown_paths == ["missing"]


# ---------------------------------------------------------------------------
# evaluate_condition: malformed condition trees
# ---------------------------------------------------------------------------

def test_evaluate_condition_rejects_non_mapping():
    with pytest.raises(ValueError, match="must be a mapping"):
        evaluate_condition("not-a-condition", {})  # type: ignore[arg-type]


def test_evaluate_condition_rejects_leaf_missing_path():
    with pytest.raises(ValueError, match="missing 'path'"):
        evaluate_condition({"is": True}, {})


def test_evaluate_condition_rejects_unrecognized_operator():
    with pytest.raises(ValueError, match="no recognized operator"):
        evaluate_condition({"path": "x", "startswith": "y"}, {"x": "yz"})


# ---------------------------------------------------------------------------
# validate_condition: every static-check path
# ---------------------------------------------------------------------------

def test_validate_condition_flags_non_mapping():
    errors: list[str] = []
    validate_condition("not-a-condition", "loc", errors)
    assert any("must be a mapping" in e for e in errors)


def test_validate_condition_flags_empty_group():
    errors: list[str] = []
    validate_condition({"all": []}, "loc", errors)
    assert any("non-empty list" in e for e in errors)


def test_validate_condition_flags_leaf_missing_path():
    errors: list[str] = []
    validate_condition({"is": True}, "loc", errors)
    assert any("missing 'path'" in e for e in errors)


def test_validate_condition_flags_unrecognized_operator():
    errors: list[str] = []
    validate_condition({"path": "x", "startswith": "y"}, "loc", errors)
    assert any("no recognized operator" in e for e in errors)
