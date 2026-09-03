"""Hashimori CLI.

    hashimori evaluate --rules rulepacks/ --context examples/intake/chatbot.json
    hashimori validate rulepacks/
    hashimori test tests/decisions.yaml --rules rulepacks/
    hashimori init my-governance/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from hashimori import __version__
from hashimori.engine import Decision, evaluate
from hashimori.loader import load_packs, validate_pack

# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"

BADGE = {
    "DENIED": f"{BOLD}{RED}",
    "APPROVED": f"{BOLD}{GREEN}",
    "NEEDS_REVIEW": f"{BOLD}{YELLOW}",
}


def _color_enabled(args: argparse.Namespace) -> bool:
    if getattr(args, "no_color", False):
        return False
    return sys.stdout.isatty() or getattr(args, "force_color", False)


def render_pretty(decision: Decision, color: bool = True) -> str:
    def c(code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if color else text

    lines: list[str] = []
    badge = c(BADGE[decision.decision], f" {decision.decision.replace('_', ' ')} ")
    lines.append("")
    lines.append(f"  {c(BOLD, '🌉 hashimori')} {c(DIM, 'v' + __version__)}   →  {badge}")
    lines.append("")

    if decision.red_zones_hit:
        lines.append(c(RED, "  ⛔ RED ZONE — evaluation short-circuited. No review queue. No committee."))
        for h in decision.red_zones_hit:
            lines.append(f"     {c(BOLD, h['id'])}  {h['name']}  {c(DIM, '[' + h['pack'] + ']')}")
            if h.get("message"):
                lines.append(c(DIM, f"       {h['message'].strip()}"))
            if h.get("remedy"):
                lines.append(f"       {c(CYAN, '↳ path to yes:')} {h['remedy'].strip()}")
    else:
        tier_label = str(decision.tier)
        if decision.auto_approval_blocked:
            tier_label += " (auto-approval blocked)"
        lines.append(f"  score {c(BOLD, f'{decision.score:g}')}  →  tier {c(BOLD, tier_label)}")
        for h in decision.risk_factors_hit:
            weight = "+{:g}".format(h["weight"])
            lines.append(f"     {c(YELLOW, weight)}  {h['id']}  {h['name']}")
        if not decision.risk_factors_hit:
            lines.append(c(DIM, "     no risk factors triggered"))
        if decision.reviewers:
            sla = f" (SLA {decision.sla_days}d)" if decision.sla_days else ""
            lines.append(f"  reviewers: {', '.join(decision.reviewers)}{sla}")
        if decision.obligations and decision.decision == "APPROVED":
            lines.append(f"  obligations: {', '.join(decision.obligations)}")

    if decision.unknown_paths:
        lines.append(c(YELLOW, f"  ⚠ missing intake data: {', '.join(decision.unknown_paths)}"))
        lines.append(c(DIM, "    hashimori fails closed — unknowns never auto-approve."))

    a = decision.audit
    lines.append(c(DIM, f"  audit: context {a['context_sha256'][:12]}… · "
                        f"{len(a['packs'])} pack(s) hashed · {a['evaluated_at']}"))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_evaluate(args: argparse.Namespace) -> int:
    packs = load_packs(args.rules)
    raw = sys.stdin.read() if args.context == "-" else Path(args.context).read_text()
    context = json.loads(raw)
    decision = evaluate(packs, context)

    if args.json:
        print(decision.to_json())
    else:
        print(render_pretty(decision, color=_color_enabled(args)))

    if args.exit_code:
        return {"APPROVED": 0, "NEEDS_REVIEW": 78, "DENIED": 2}[decision.decision]
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    paths: list[Path] = []
    for p in args.packs:
        p = Path(p)
        paths.extend(sorted(p.rglob("*.y*ml")) if p.is_dir() else [p])
    failed = False
    for path in paths:
        errors = validate_pack(path)
        if errors:
            failed = True
            print(f"✗ {path}")
            for err in errors:
                print(f"    {err}")
        else:
            print(f"✓ {path}")
    return 1 if failed else 0


def cmd_test(args: argparse.Namespace) -> int:
    packs = load_packs(args.rules)
    suite = yaml.safe_load(Path(args.suite).read_text())
    cases = suite.get("tests", [])
    if not cases:
        print(f"No tests found in {args.suite}")
        return 1

    passed = 0
    failures: list[str] = []
    for case in cases:
        name = case.get("name", "<unnamed>")
        if "context_file" in case:
            context = json.loads((Path(args.suite).parent / case["context_file"]).read_text())
        else:
            context = case.get("context", {})
        decision = evaluate(packs, context)
        expect = case.get("expect", {})
        ok = True
        if "decision" in expect and decision.decision != expect["decision"]:
            ok = False
            failures.append(
                f"{name}: expected decision {expect['decision']}, got {decision.decision}"
            )
        if "tier" in expect and decision.tier != expect["tier"]:
            ok = False
            failures.append(f"{name}: expected tier {expect['tier']}, got {decision.tier}")
        if "red_zones" in expect:
            hit_ids = {h["id"] for h in decision.red_zones_hit}
            missing = set(expect["red_zones"]) - hit_ids
            if missing:
                ok = False
                failures.append(f"{name}: expected red zones not hit: {sorted(missing)}")
        if ok:
            passed += 1
            print(f"  ✓ {name}")
        else:
            print(f"  ✗ {name}")

    print(f"\n{passed}/{len(cases)} policy tests passed")
    for f in failures:
        print(f"  ! {f}")
    return 0 if passed == len(cases) else 1


STARTER_PACK = """\
version: 1
pack:
  name: starter
  description: Starter policy — edit me. Generated by `hashimori init`.

red_zones:
  - id: REDZONE-001
    name: Consequential decisions with no human in the loop
    when:
      all:
        - path: use_case.decision_impact
          in: [credit, employment, housing, medical, legal, law_enforcement]
        - path: oversight.human_in_loop
          is: false
    message: Fully automated consequential decisions are prohibited by policy.
    remedy: Add human review before decisions take effect, then resubmit.

risk_factors:
  - id: RISK-001
    name: Handles personal data
    when: {path: data.categories, contains: personal_data}
    weight: 3
  - id: RISK-002
    name: Customer-facing
    when: {path: use_case.audience, is: external}
    weight: 2

tiers:
  - name: fast_track
    max_score: 2
    outcome: approved
    obligations: [enable_logging, annual_review]
  - name: standard_review
    max_score: 5
    outcome: needs_review
    reviewers: [security]
    sla_days: 5
  - name: elevated_review
    outcome: needs_review
    reviewers: [security, legal, ai_governance_board]
    sla_days: 15
"""

STARTER_INTAKE = {
    "use_case": {
        "name": "My AI feature",
        "description": "What it does, in one honest paragraph.",
        "audience": "internal",
        "decision_impact": "none",
    },
    "data": {"categories": ["public"]},
    "oversight": {"human_in_loop": True},
}

STARTER_TESTS = """\
tests:
  - name: harmless internal tool fast-tracks
    context:
      use_case: {audience: internal, decision_impact: none}
      data: {categories: [public]}
      oversight: {human_in_loop: true}
    expect: {decision: APPROVED, tier: fast_track}

  - name: automated hiring decision hits the red zone
    context:
      use_case: {decision_impact: employment}
      oversight: {human_in_loop: false}
    expect: {decision: DENIED, red_zones: [REDZONE-001]}
"""


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.dir)
    (root / "rules").mkdir(parents=True, exist_ok=True)
    (root / "intake").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "rules" / "starter.yaml").write_text(STARTER_PACK)
    (root / "intake" / "template.json").write_text(json.dumps(STARTER_INTAKE, indent=2) + "\n")
    (root / "tests" / "decisions.yaml").write_text(STARTER_TESTS)
    print(f"Initialized governance workspace in {root}/")
    print("  rules/starter.yaml    — your policy, as code. Edit it.")
    print("  intake/template.json  — what teams submit.")
    print("  tests/decisions.yaml  — your policy, tested like code.")
    print(f"\nTry:  hashimori evaluate --rules {root}/rules --context {root}/intake/template.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hashimori",
        description="A tiny, deterministic rules engine for AI use case governance.",
    )
    parser.add_argument("--version", action="version", version=f"hashimori {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_eval = sub.add_parser("evaluate", help="Evaluate an intake context against policy packs")
    p_eval.add_argument("--rules", nargs="+", required=True, help="Pack files or directories")
    p_eval.add_argument("--context", required=True, help="Intake JSON file, or - for stdin")
    p_eval.add_argument("--json", action="store_true", help="Emit the full decision as JSON")
    p_eval.add_argument("--exit-code", action="store_true",
                        help="Exit 0=approved, 78=needs review, 2=denied (for CI)")
    p_eval.add_argument("--no-color", action="store_true")
    p_eval.add_argument("--force-color", action="store_true", help=argparse.SUPPRESS)
    p_eval.set_defaults(func=cmd_evaluate)

    p_val = sub.add_parser("validate", help="Lint policy packs")
    p_val.add_argument("packs", nargs="+")
    p_val.set_defaults(func=cmd_validate)

    p_test = sub.add_parser("test", help="Run policy decision tests")
    p_test.add_argument("suite", help="YAML test suite file")
    p_test.add_argument("--rules", nargs="+", required=True)
    p_test.set_defaults(func=cmd_test)

    p_init = sub.add_parser("init", help="Scaffold a governance workspace")
    p_init.add_argument("dir", nargs="?", default="governance")
    p_init.set_defaults(func=cmd_init)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
