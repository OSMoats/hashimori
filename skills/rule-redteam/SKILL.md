---
name: rule-redteam
description: Adversarially probe a Hashimori rule pack for gaps, contradictions, and bypasses, and turn every finding into a failing test case. Use before a rule pack ships, after policy changes, or on a schedule.
---

# Rule Red Team

You are attacking a governance rule pack the way a motivated product team (or a lazy intake form) would — not to embarrass the authors, but to hand them failing tests they can fix.

## Attack the pack from five angles

1. **The honest bypass.** Construct realistic intakes that *should* obviously be denied or elevated under the policy's intent but slip through as APPROVED. Vary one field at a time from the shipped deny examples — if flipping a single boolean flips DENIED to fast-track APPROVED, the pack is brittle and needs a risk factor covering the middle ground.
2. **The vocabulary gap.** Rules match exact values (`decision_impact: credit`). What happens when a team writes `lending`? `loan_underwriting`? List every enum-like field the pack depends on, and check whether the intake conventions document those vocabularies. Undocumented vocabulary = silent approval path.
3. **The missing-data probe.** Strip fields from realistic intakes and verify the engine goes to NEEDS_REVIEW (fail closed), never APPROVED. Pay attention to red zones whose conditions can be made undecidable — those must surface in `unknown_paths`.
4. **The contradiction sweep.** Find pairs of rules that can't both be satisfied, tiers whose boundaries overlap or leave holes, and remedies that route into another red zone.
5. **The weight audit.** Sum the weights of plausible combinations. Can a use case with personal data + autonomy + external audience still land under the fast-track threshold? Should it?

## Turn findings into tests, not prose

Every finding becomes a case in a `tests:` YAML suite with a comment naming the finding:

```yaml
  # FINDING: 'lending' bypasses REDZONE-001's decision_impact vocabulary
  - name: lending vocabulary bypass should not fast-track
    context:
      use_case: {decision_impact: lending}
      oversight: {human_in_loop: false}
    expect: {decision: NEEDS_REVIEW}
```

Run `hashimori test` to confirm each case fails against the current pack, then deliver: the failing suite, a severity-ordered summary (approval-path holes first), and a suggested fix per finding. Do not fix the pack yourself unless asked — the authors own the policy.
