"""Loader edge cases not covered by test_engine.py's happy paths.

Covers the error paths a coverage run showed were previously untouched:
a non-mapping YAML top level, an empty pack search, duplicate rule ids,
non-mapping rule/tier entries, and out-of-order tier max_scores.
"""

import pytest

from hashimori.loader import Pack, load_pack, load_packs, validate_pack


def write(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def test_load_yaml_rejects_non_mapping_top_level(tmp_path):
    path = write(tmp_path, "list-at-top.yaml", "- 1\n- 2\n")
    with pytest.raises(ValueError, match="top level must be a mapping"):
        load_pack(path)


def test_load_packs_raises_when_nothing_found(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="No policy packs found"):
        load_packs([empty_dir])


def test_load_pack_defaults_name_to_filename_stem_when_metadata_omitted(tmp_path):
    path = write(tmp_path, "no-metadata.yaml", "version: 1\ntiers: [{name: t, outcome: approved}]\n")
    pack = load_pack(path)
    assert pack.name == "no-metadata"
    assert pack.description == ""


def test_pack_sha256_is_stable_and_hex():
    pack = Pack(name="p", description="", source="x", raw={"a": 1})
    assert len(pack.sha256) == 64
    assert pack.sha256 == pack.sha256  # deterministic across repeated calls


# ---------------------------------------------------------------------------
# validate_pack
# ---------------------------------------------------------------------------

def test_validate_pack_flags_duplicate_ids(tmp_path):
    path = write(
        tmp_path,
        "dup.yaml",
        "version: 1\n"
        "red_zones:\n"
        "  - {id: RZ-1, name: a, when: {path: x, is: true}, message: m}\n"
        "  - {id: RZ-1, name: b, when: {path: y, is: true}, message: m}\n"
        "tiers: [{name: t, outcome: approved}]\n",
    )
    errors = validate_pack(path)
    assert any("duplicate id 'RZ-1'" in e for e in errors)


def test_validate_pack_flags_non_mapping_rule_entry(tmp_path):
    path = write(
        tmp_path,
        "bad-rule.yaml",
        "version: 1\n"
        "risk_factors:\n"
        "  - \"just a string, not a mapping\"\n"
        "tiers: [{name: t, outcome: approved}]\n",
    )
    errors = validate_pack(path)
    assert any("must be a mapping" in e for e in errors)


def test_validate_pack_flags_non_mapping_tier_entry(tmp_path):
    path = write(tmp_path, "bad-tier.yaml", "version: 1\ntiers:\n  - \"not a mapping\"\n")
    errors = validate_pack(path)
    assert any("tiers[0]" in e and "must be a mapping" in e for e in errors)


def test_validate_pack_flags_out_of_order_tiers(tmp_path):
    path = write(
        tmp_path,
        "out-of-order.yaml",
        "version: 1\n"
        "tiers:\n"
        "  - {name: a, max_score: 10, outcome: approved}\n"
        "  - {name: b, max_score: 2, outcome: needs_review}\n"
        "  - {name: c, outcome: needs_review}\n",
    )
    errors = validate_pack(path)
    assert any("ascending max_score" in e for e in errors)


def test_validate_pack_flags_missing_weight_on_risk_factor(tmp_path):
    path = write(
        tmp_path,
        "no-weight.yaml",
        "version: 1\n"
        "risk_factors:\n"
        "  - {id: R-1, name: a, when: {path: x, is: true}}\n"
        "tiers: [{name: t, outcome: approved}]\n",
    )
    errors = validate_pack(path)
    assert any("'weight' must be a positive number" in e for e in errors)
