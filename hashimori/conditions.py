"""Condition evaluation for Hashimori rules.

A condition is either a *leaf* (one check against one path in the intake
context) or a *group* (``all`` / ``any`` / ``none`` of nested conditions).

Leaves look like::

    {path: oversight.human_in_loop, is: false}
    {path: data.categories, contains: personal_data}
    {path: model.provider, in: [openai, anthropic, self_hosted]}
    {path: use_case.affected_users, gte: 10000}
    {path: use_case.description, matches: "(?i)autonomous"}
    {path: security.pen_test_date, exists: true}

Missing data is tracked, never ignored: if a condition needs a path that the
intake context does not contain, the condition is False AND the path is
recorded as *unknown*. The engine uses that to fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

GROUP_KEYS = ("all", "any", "none")
LEAF_OPS = (
    "is",
    "is_not",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "matches",
    "exists",
)

_MISSING = object()


@dataclass
class EvalResult:
    """Outcome of evaluating one condition tree.

    Three-valued: ``value`` is True (triggered), False (not triggered), or
    None (*undecidable* — the intake context is missing data this condition
    needs, and the missing paths are in ``unknown_paths``). Unknowns are only
    reported when they actually block a decision: an ``all`` group with one
    definitively-false child is False, full stop.
    """

    value: bool | None
    unknown_paths: list[str] = field(default_factory=list)

    @property
    def is_true(self) -> bool:
        return self.value is True

    @property
    def is_unknown(self) -> bool:
        return self.value is None


def resolve_path(context: dict, path: str) -> Any:
    """Resolve a dotted path (``a.b.c``) in a nested dict. Returns _MISSING sentinel if absent."""
    node: Any = context
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return _MISSING
    return node


def _norm(value: Any) -> Any:
    """Normalize for comparison: case-fold strings so YAML authors don't fight casing."""
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def _compare(op: str, actual: Any, expected: Any) -> bool:
    if op == "is":
        return _norm(actual) == _norm(expected)
    if op == "is_not":
        return _norm(actual) != _norm(expected)
    if op == "in":
        return _norm(actual) in [_norm(v) for v in expected]
    if op == "not_in":
        return _norm(actual) not in [_norm(v) for v in expected]
    if op == "contains":
        if isinstance(actual, (list, tuple, set)):
            return _norm(expected) in [_norm(v) for v in actual]
        if isinstance(actual, str):
            return str(_norm(expected)) in _norm(actual)
        return False
    if op == "not_contains":
        return not _compare("contains", actual, expected)
    if op in ("gt", "gte", "lt", "lte"):
        try:
            a, e = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return {"gt": a > e, "gte": a >= e, "lt": a < e, "lte": a <= e}[op]
    if op == "matches":
        if not isinstance(actual, str):
            return False
        return re.search(str(expected), actual) is not None
    raise ValueError(f"Unknown operator: {op}")


def evaluate_condition(cond: dict, context: dict) -> EvalResult:
    """Evaluate a condition tree against an intake context."""
    if not isinstance(cond, dict):
        raise ValueError(f"Condition must be a mapping, got: {cond!r}")

    group_key = next((k for k in GROUP_KEYS if k in cond), None)
    if group_key is not None:
        children = [evaluate_condition(c, context) for c in cond[group_key]]
        unknowns = sorted({p for c in children if c.is_unknown for p in c.unknown_paths})
        values = [c.value for c in children]
        if group_key == "all":
            if any(v is False for v in values):
                return EvalResult(False)  # decided — unknowns can't change it
            if any(v is None for v in values):
                return EvalResult(None, unknowns)
            return EvalResult(True)
        if group_key == "any":
            if any(v is True for v in values):
                return EvalResult(True)  # decided
            if any(v is None for v in values):
                return EvalResult(None, unknowns)
            return EvalResult(False)
        # none
        if any(v is True for v in values):
            return EvalResult(False)
        if any(v is None for v in values):
            return EvalResult(None, unknowns)
        return EvalResult(True)

    if "path" not in cond:
        raise ValueError(f"Leaf condition missing 'path': {cond!r}")
    path = cond["path"]
    op = next((k for k in LEAF_OPS if k in cond), None)
    if op is None:
        raise ValueError(f"Condition on '{path}' has no recognized operator {LEAF_OPS}")

    actual = resolve_path(context, path)

    if op == "exists":
        present = actual is not _MISSING
        want = bool(cond["exists"])
        return EvalResult(present is want)

    if actual is _MISSING:
        return EvalResult(None, [path])  # undecidable, and the gap is named

    return EvalResult(_compare(op, actual, cond[op]))


def validate_condition(cond: Any, where: str, errors: list[str]) -> None:
    """Static validation of a condition tree (for `hashimori validate`)."""
    if not isinstance(cond, dict):
        errors.append(f"{where}: condition must be a mapping")
        return
    group_key = next((k for k in GROUP_KEYS if k in cond), None)
    if group_key is not None:
        if not isinstance(cond[group_key], list) or not cond[group_key]:
            errors.append(f"{where}: '{group_key}' must be a non-empty list")
            return
        for i, child in enumerate(cond[group_key]):
            validate_condition(child, f"{where}.{group_key}[{i}]", errors)
        return
    if "path" not in cond:
        errors.append(f"{where}: leaf condition missing 'path'")
        return
    op = next((k for k in LEAF_OPS if k in cond), None)
    if op is None:
        errors.append(f"{where}: no recognized operator (one of {', '.join(LEAF_OPS)})")
        return
    if op == "matches":
        try:
            re.compile(str(cond[op]))
        except re.error as exc:
            errors.append(f"{where}: invalid regex: {exc}")
    if op in ("in", "not_in") and not isinstance(cond[op], list):
        errors.append(f"{where}: '{op}' expects a list")
