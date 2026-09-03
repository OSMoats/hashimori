"""CLI tests. Run: pytest

Exercises hashimori/cli.py directly via main(argv) -- capsys captures
stdout/stderr, tmp_path provides scratch files. Before this file, cli.py
(the actual user-facing entrypoint) had 0% test coverage: nothing verified
argument parsing, --json output shape, --exit-code values, `hashimori
init`'s scaffold, or how malformed input is handled.
"""

import json
from pathlib import Path

import pytest

from hashimori.cli import main

ROOT = Path(__file__).parent.parent
RULES = [str(ROOT / "rulepacks" / "baseline"), str(ROOT / "rulepacks" / "red-zone")]


def intake_path(name: str) -> str:
    return str(ROOT / "examples" / "intake" / f"{name}.json")


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

def test_evaluate_pretty_output_fast_track(capsys):
    rc = main(["evaluate", "--rules", *RULES, "--context", intake_path("docs-answerbot"), "--no-color"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "APPROVED" in out
    assert "fast_track" in out


def test_evaluate_json_output_shape(capsys):
    rc = main(["evaluate", "--rules", *RULES, "--context", intake_path("loan-agent"), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)  # must be valid, parseable JSON
    assert rc == 0
    assert payload["decision"] == "DENIED"
    assert {"score", "red_zones_hit", "unknown_paths", "audit"} <= payload.keys()


@pytest.mark.parametrize(
    "intake_name,expected_code",
    [("docs-answerbot", 0), ("support-chatbot", 78), ("loan-agent", 2)],
)
def test_evaluate_exit_code_contract(capsys, intake_name, expected_code):
    rc = main(["evaluate", "--rules", *RULES, "--context", intake_path(intake_name),
               "--exit-code", "--no-color"])
    capsys.readouterr()
    assert rc == expected_code


def test_evaluate_reads_context_from_stdin(capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(Path(intake_path("docs-answerbot")).read_text()))
    rc = main(["evaluate", "--rules", *RULES, "--context", "-", "--no-color"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "APPROVED" in out


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def test_validate_clean_packs_exits_zero(capsys):
    rc = main(["validate", str(ROOT / "rulepacks")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "✓" in out


def test_validate_broken_pack_exits_one_and_names_the_error(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 2\nred_zones: []\ntiers: [{name: t, outcome: approved}]\n")
    rc = main(["validate", str(bad)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "version: 1" in out


# ---------------------------------------------------------------------------
# test (policy decision suites)
# ---------------------------------------------------------------------------

def test_policy_decision_suite_passes(capsys):
    rc = main(["test", str(ROOT / "examples" / "tests" / "decisions.yaml"), "--rules", *RULES])
    out = capsys.readouterr().out
    assert rc == 0
    assert "policy tests passed" in out


def test_policy_decision_suite_reports_failures(tmp_path, capsys):
    suite = tmp_path / "suite.yaml"
    suite.write_text(
        "tests:\n"
        "  - name: this expectation is deliberately wrong\n"
        "    context: {use_case: {audience: internal, decision_impact: none}, "
        "oversight: {human_in_loop: true}, data: {categories: [public]}}\n"
        "    expect: {decision: DENIED}\n"
    )
    rc = main(["test", str(suite), "--rules", *RULES])
    out = capsys.readouterr().out
    assert rc == 1
    assert "✗" in out


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def test_init_scaffolds_a_working_governance_workspace(tmp_path, capsys):
    workspace = tmp_path / "governance"
    rc = main(["init", str(workspace)])
    capsys.readouterr()
    assert rc == 0
    assert (workspace / "rules" / "starter.yaml").exists()
    assert (workspace / "intake" / "template.json").exists()
    assert (workspace / "tests" / "decisions.yaml").exists()

    # eat our own dog food: the scaffold itself must validate and pass its own tests
    rc = main(["validate", str(workspace / "rules")])
    capsys.readouterr()
    assert rc == 0

    rc = main(["test", str(workspace / "tests" / "decisions.yaml"), "--rules", str(workspace / "rules")])
    capsys.readouterr()
    assert rc == 0


# ---------------------------------------------------------------------------
# Malformed input: crashes vs. clean errors
# ---------------------------------------------------------------------------

def test_malformed_yaml_pack_fails_cleanly_not_a_traceback(tmp_path, capsys):
    bad = tmp_path / "broken.yaml"
    bad.write_text("version: 1\nred_zones: [\n")  # unterminated YAML flow sequence
    ctx = tmp_path / "ctx.json"
    ctx.write_text("{}")
    rc = main(["evaluate", "--rules", str(bad), "--context", str(ctx)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "Traceback" not in err
    assert "hashimori: error:" in err


def test_malformed_pack_shape_fails_cleanly_not_a_traceback(tmp_path, capsys):
    bad = tmp_path / "wrong-shape.yaml"
    bad.write_text('version: 1\nred_zones: "oops"\ntiers:\n  - {name: t, outcome: approved}\n')
    ctx = tmp_path / "ctx.json"
    ctx.write_text("{}")
    rc = main(["evaluate", "--rules", str(bad), "--context", str(ctx)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "Traceback" not in err
    assert "hashimori: error:" in err


def test_missing_context_file_fails_cleanly_not_a_traceback(capsys):
    rc = main(["evaluate", "--rules", *RULES, "--context", "/no/such/file.json"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "Traceback" not in err
    assert "hashimori: error:" in err
