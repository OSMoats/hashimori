# Contributing

Thanks for helping keep the bridge. Be kind, assume good faith, and remember
that people run this in front of auditors — boring and correct beats clever.

## Ground rules

- **The engine stays deterministic.** PRs that put a model call, network
  call, or wall-clock dependence in the decision path will be declined, with
  affection. LLMs live in `skills/`, at the edges.
- **The core stays small.** New operators and schema features need a real
  policy that can't be expressed without them. Integrations and rule packs
  are where growth belongs.
- **Rules ship with tests.** A rule pack PR without `hashimori test` cases
  doesn't merge. Policy is code here; code has tests.

## Good first contributions

- A rule pack for your industry (finance, health, public sector) under
  `rulepacks/` — generic, with framework refs and a test suite.
- An integration recipe under `integrations/` (GitLab CI, Jira intake,
  ServiceNow, OPA export).
- A skill under `skills/` that follows the pattern: LLM at the edge,
  deterministic engine in the middle.
- Vocabulary docs: better documented intake conventions for a domain.

## Dev setup

```bash
pip install -e ".[dev]"
pytest
hashimori validate rulepacks/
hashimori test examples/tests/decisions.yaml --rules rulepacks/
```

## Disclaimer for rule packs

Shipped rule packs are engineering starting points, not legal advice, and the
framework refs (`NIST-AI-RMF`, `EU-AI-Act`, `ISO-42001`) are informational
mappings, not compliance claims. Calibrate with your own counsel and risk
team.
