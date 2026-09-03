"""Loading and validating Hashimori policy packs (YAML)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hashimori.conditions import validate_condition

SCHEMA_VERSION = 1
VALID_OUTCOMES = ("approved", "needs_review", "denied")


@dataclass
class Pack:
    name: str
    description: str
    source: str
    red_zones: list[dict] = field(default_factory=list)
    risk_factors: list[dict] = field(default_factory=list)
    tiers: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        canonical = yaml.safe_dump(self.raw, sort_keys=True).encode()
        return hashlib.sha256(canonical).hexdigest()


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def load_pack(path: str | Path) -> Pack:
    path = Path(path)
    data = _load_yaml(path)
    meta = data.get("pack", {}) or {}
    return Pack(
        name=meta.get("name", path.stem),
        description=meta.get("description", ""),
        source=str(path),
        red_zones=data.get("red_zones", []) or [],
        risk_factors=data.get("risk_factors", []) or [],
        tiers=data.get("tiers", []) or [],
        raw=data,
    )


def load_packs(paths: list[str | Path]) -> list[Pack]:
    """Load one or more packs. Directories are searched for *.yaml / *.yml."""
    packs: list[Pack] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*.y*ml")):
                packs.append(load_pack(f))
        else:
            packs.append(load_pack(p))
    if not packs:
        raise ValueError(f"No policy packs found in: {', '.join(str(p) for p in paths)}")
    return packs


def validate_pack(path: str | Path) -> list[str]:
    """Validate a pack file. Returns a list of error strings (empty = valid)."""
    errors: list[str] = []
    path = Path(path)
    try:
        data = _load_yaml(path)
    except (yaml.YAMLError, ValueError) as exc:
        return [f"{path}: not valid YAML: {exc}"]

    if data.get("version") != SCHEMA_VERSION:
        errors.append(f"{path}: 'version: {SCHEMA_VERSION}' is required")

    seen_ids: set[str] = set()

    def check_rule(rule: Any, kind: str, idx: int) -> None:
        where = f"{path}:{kind}[{idx}]"
        if not isinstance(rule, dict):
            errors.append(f"{where}: must be a mapping")
            return
        rid = rule.get("id")
        if not rid:
            errors.append(f"{where}: missing 'id'")
        elif rid in seen_ids:
            errors.append(f"{where}: duplicate id '{rid}'")
        else:
            seen_ids.add(rid)
        if not rule.get("name"):
            errors.append(f"{where}: missing 'name'")
        if "when" not in rule:
            errors.append(f"{where}: missing 'when' condition")
        else:
            validate_condition(rule["when"], where + ".when", errors)
        if kind == "red_zones" and not rule.get("message"):
            errors.append(f"{where}: red zones must carry a 'message' explaining the rejection")
        if kind == "risk_factors":
            w = rule.get("weight")
            if not isinstance(w, (int, float)) or w <= 0:
                errors.append(f"{where}: 'weight' must be a positive number")

    for i, rz in enumerate(data.get("red_zones", []) or []):
        check_rule(rz, "red_zones", i)
    for i, rf in enumerate(data.get("risk_factors", []) or []):
        check_rule(rf, "risk_factors", i)

    tiers = data.get("tiers", []) or []
    for i, tier in enumerate(tiers):
        where = f"{path}:tiers[{i}]"
        if not isinstance(tier, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        if not tier.get("name"):
            errors.append(f"{where}: missing 'name'")
        if tier.get("outcome") not in VALID_OUTCOMES:
            errors.append(f"{where}: 'outcome' must be one of {VALID_OUTCOMES}")
        if i < len(tiers) - 1 and not isinstance(tier.get("max_score"), (int, float)):
            errors.append(f"{where}: non-final tiers need a numeric 'max_score'")
    if tiers:
        scores = [t.get("max_score") for t in tiers[:-1] if isinstance(t, dict)]
        nums = [s for s in scores if isinstance(s, (int, float))]
        if nums != sorted(nums):
            errors.append(f"{path}: tiers must be ordered by ascending max_score")

    return errors
