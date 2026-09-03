---
name: policy-to-rules
description: Convert a written AI policy document (PDF, Word, text, or markdown) into a validated, tested Hashimori rule pack. Use when someone provides an AI policy, AI acceptable-use standard, or governance document and wants it enforced as code.
---

# Policy → Rules

You are converting a human-written AI policy into a Hashimori policy pack: executable YAML that a deterministic engine evaluates. Your output is *code that stands in for the policy*, so precision beats coverage — a rule that misfires erodes trust in the whole system.

## Step 1 — Read the policy completely

Read the document the user provides (use pdf/docx tooling if needed to extract text). Build three lists as you read:

1. **Absolute prohibitions** — sentences like "must never", "under no circumstances", "is prohibited". These become `red_zones`.
2. **Risk statements** — "requires additional review", "elevated risk", "must be assessed". These become `risk_factors` with weights.
3. **Approval structure** — who approves what, at which risk level, in how many days. This becomes `tiers`.

Quote each candidate back to its source (section number or heading) — every rule you emit must carry a `refs` entry pointing at the policy section it encodes, plus any external framework refs the policy itself cites (NIST AI RMF, EU AI Act, ISO 42001).

## Step 2 — Decide what does NOT become a rule

A policy sentence becomes a rule only when a machine could check it against intake data. "Teams should consider fairness" is not checkable; "systems making employment decisions require human review" is. Put everything unencodable in a `# NOT ENCODED` comment block at the bottom of the pack with one line of why — the security team needs to see what still requires human judgment. Do not invent intake fields that no team could plausibly answer.

## Step 3 — Write the pack

Follow the schema in `docs/schema.md` of the Hashimori repo. Conventions:

- Context paths use the standard namespaces: `use_case.*`, `data.*`, `model.*`, `oversight.*`, `agent.*`, `observability.*`. Reuse existing field names from `examples/intake/` before inventing new ones.
- Red zone `message` states the prohibition in the policy's own words (short). `remedy` states the path to yes — or says plainly there isn't one.
- Weights: 1 = notable, 2 = meaningful, 3 = serious, 4-5 = severe. Sum-based tiers, so calibrate against each other, not in isolation.
- Prefer few strong rules over many weak ones. A first pack with 5 red zones and 8 risk factors is healthy; 40 rules is a smell.

## Step 4 — Validate, test, iterate

1. Run `hashimori validate <pack>.yaml` — fix every error.
2. Write a test suite (`tests:` YAML, see `docs/schema.md`) with at least: one clear denial per red zone, one fast-track approval, one boundary case per tier edge, and one incomplete-intake case that must fail closed (`NEEDS_REVIEW`).
3. Run `hashimori test <suite>.yaml --rules <pack>.yaml` until everything passes.

## Step 5 — Hand off honestly

Present the user: the pack, the test results, the NOT ENCODED list, and 2-3 questions where the policy was ambiguous and you made a judgment call. Never present the pack as complete coverage of the policy — it encodes the checkable parts, and you must say so.
