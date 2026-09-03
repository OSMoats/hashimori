<div align="center">

# 🌉 Hashimori

**橋守 · the bridge keeper**

*A tiny, deterministic rules engine for AI use case governance.*
*Policy in YAML. Intake in JSON. Decision in milliseconds — with an audit trail.*

[![CI](https://github.com/OSMoats/hashimori/actions/workflows/ci.yml/badge.svg)](https://github.com/OSMoats/hashimori/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)
![No LLM in the decision path](https://img.shields.io/badge/LLM%20in%20decision%20path-never-red.svg)

</div>

---

Your AI policy is a PDF. Your teams ship AI features every week. The bridge
between those two facts is, today, a spreadsheet and a recurring meeting —
and it is either a rubber stamp or a bottleneck, depending on the week.

Security teams are good at digging moats. **Hashimori is the bridge keeper**:
the small, boring, auditable piece of code that decides what crosses, what
doesn't, and what needs a human — so your reviewers spend their judgment on
the five cases that deserve it instead of the fifty that don't.

## Sixty seconds

```bash
pip install git+https://github.com/OSMoats/hashimori
git clone https://github.com/OSMoats/hashimori && cd hashimori

hashimori evaluate --rules rulepacks/ --context examples/intake/loan-agent.json
```

```text
  🌉 hashimori v0.1.0   →   DENIED

  ⛔ RED ZONE — evaluation short-circuited. No review queue. No committee.
     REDZONE-001  Consequential decisions with no human in the loop  [red-zone]
       Fully automated decisions that materially affect a person's access to
       credit, work, housing, care, or justice are categorically prohibited.
       ↳ path to yes: Put a qualified human between the model output and the
         decision taking effect, then resubmit.

  audit: context 4e84afea7ff2… · 2 pack(s) hashed · 2026-09-03T03:13:30Z
```

That rejection took 40 milliseconds, cited the exact rule, told the team how
to fix it, and left a reproducible audit record. Nobody scheduled a meeting.

## How it works

**1. Red zones short-circuit.** Every enterprise AI policy has a "never"
list. Hashimori checks it *first*, and a match is an instant, final DENIED —
with the rule's message and its `remedy` (the path to yes). Your highest-risk
patterns get your fastest answers.

**2. Everything else is graduated.** Risk factors add weights to a score;
the score picks a tier: fast-track auto-approval with obligations, standard
security review with an SLA, or elevated review with the full committee.
Most submissions are boring — the engine clears them so humans review the
rest.

**3. Unknowns fail closed.** Conditions evaluate three-valued: true, false,
or *unknown* when the intake didn't answer the question. A use case with
unknowns can never be auto-approved — it routes to review with the missing
answers named. The vague submission doesn't slip through; it gets a to-do
list.

**4. Every decision is reproducible.** Decisions carry SHA-256 hashes of the
rule packs and the intake context, the engine version, and the reason chain.
Same inputs, same decision — provable in an audit, two years later.

```yaml
# This is a complete, working red zone.
red_zones:
  - id: REDZONE-001
    name: Consequential decisions with no human in the loop
    when:
      all:
        - path: use_case.decision_impact
          in: [credit, employment, housing, medical, legal]
        - path: oversight.human_in_loop
          is: false
    message: Fully automated consequential decisions are prohibited.
    remedy: Add pre-decision human review, then resubmit.
    refs: [NIST-AI-RMF:MANAGE-2.2, EU-AI-Act:Art.14]
```

Full schema: [docs/schema.md](docs/schema.md).

## No LLM in the decision path. Ever.

This is the design decision everything else hangs on. Models are brilliant at
reading policies and terrible at being audited — so Hashimori uses AI only
**at the edges**, through [four drop-in agent skills](skills/):

- **[`policy-to-rules`](skills/policy-to-rules/)** — feed it your AI policy
  (PDF, Word, text, markdown); it emits a validated rule pack *with tests*,
  and an honest list of what it couldn't encode.
- **[`intake-copilot`](skills/intake-copilot/)** — turns a team's messy PRD
  or Slack thread into clean intake JSON, and refuses to launder risk.
- **[`decision-memo`](skills/decision-memo/)** — turns a decision JSON into a
  kind, clear memo for the team and a complete record for GRC.
- **[`rule-redteam`](skills/rule-redteam/)** — attacks your rule pack and
  hands you the holes as failing test cases.

The skills draft; the engine decides; humans own the policy. That's the
whole trick.

## Your policy, tested like code

Rule packs ship with decision tests, and CI fails when a policy change flips
a decision you didn't mean to flip:

```bash
hashimori test examples/tests/decisions.yaml --rules rulepacks/
```

```text
  ✓ internal docs answerbot fast-tracks
  ✓ autonomous loan agent is denied without a meeting
  ✓ vague submission fails closed, never approves
  ✓ employee emotion recognition has no path to yes
  7/7 policy tests passed
```

## Governance as a pull request

The best intake form is a file in the team's own repo. With the
[GitHub Actions integration](integrations/github-action/), teams submit AI
use cases as PRs: red zones fail the check with the remedy in the log,
"needs review" auto-assigns your reviewers via CODEOWNERS, and the merge
*is* the auditable record.

## Start with your own policy

```bash
hashimori init governance/        # rules + intake template + tests, ready to edit
```

or point the `policy-to-rules` skill at the PDF you already have. The shipped
[rulepacks](rulepacks/) encode the "never" list and graduated-review shape
most enterprise AI policies share — edit the vocabulary and weights to match
yours. (They're engineering starting points, not legal advice.)

## What Hashimori is not

- **Not a GRC platform.** It's the ~600-line decision core that platforms
  are missing. Bring your own intake UI, ticketing, and dashboards — or use
  the PR flow and have none.
- **Not a model evaluator.** It governs *use cases* (what you deploy, to
  whom, with what oversight), not model weights.
- **Not vendor-anything.** MIT-licensed, one dependency (PyYAML), runs
  anywhere Python runs, exports plain JSON. Fork it and make it yours —
  that's the point.

## Design principles

1. **Deterministic core, intelligent edges.** Auditability is a feature you
   can't retrofit.
2. **Small enough to read.** One security engineer can review the entire
   engine before trusting it. That is a governance property, not a nicety.
3. **The remedy is part of the rejection.** Governance that only says "no"
   trains teams to route around it. Every red zone ships a path to yes.
4. **Fail closed, loudly.** Missing answers create review work, never silent
   approvals.

## Contributing

Rule packs for your industry, integration recipes, and new edge skills are
the most valuable contributions — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Built by Aakash Yadav and contributors, in a personal
capacity. First presented at AI TechWorld 2026.
