# Healthcare / clinical AI rule pack

Encodes healthcare-specific "never" patterns and graduated risk that the
generic shipped packs can't check, because they only look at how a team
self-reported the use case (`use_case.decision_impact: medical`). This pack
checks the underlying facts instead — FDA SaMD clearance, a signed BAA
before PHI reaches a vendor, 42 CFR Part 2 consent, a clinician between
AI-drafted notes and the chart — so an under-reported use case doesn't slip
through.

## Compose with `red-zone`, not `baseline`

```bash
hashimori evaluate --rules rulepacks/red-zone rulepacks/healthcare --context intake.json
hashimori test examples/tests/healthcare-decisions.yaml --rules rulepacks/red-zone rulepacks/healthcare
```

This pack ships its own `tiers`. The engine concatenates `tiers` across
every pack in a loaded set and stops at the first tier whose `max_score`
isn't exceeded — it does not merge or namespace them per pack. Load
`baseline` and `healthcare` in the same run and `baseline`'s catch-all tier
(no `max_score`, sorted first) matches every score before this pack's
ladder is ever reached — and because both packs happen to name their
catch-all tier `elevated_review`, the failure is silent, not obvious: the
decision still reports `tier: elevated_review`, but with *baseline's*
reviewers, not healthcare's. Verified example — the pediatric imaging case
in `examples/intake/healthcare-diagnostic-imaging-ai.json` scores 9 either
way, but:

```
loaded with red-zone (correct):   reviewers = [security, privacy, legal, clinical_safety_committee, ai_governance_board]
loaded with baseline (incorrect): reviewers = [security, privacy, legal, ai_governance_board]
```

`clinical_safety_committee` silently disappears — same tier name, wrong
committee. If you want one merged healthcare-plus-baseline scoring model,
write it as a single pack with one tier ladder instead of loading both.

`hashimori validate rulepacks/` still lints this file individually and is
unaffected — validation never composes packs.

## Vocabulary this pack adds

Reuses `use_case.*`, `data.*`, `model.*`, `oversight.*` from the shipped
conventions (see `examples/intake/` and `docs/schema.md`), plus:

| Path | Type | Meaning |
|---|---|---|
| `clinical.decision_support_type` | `none \| administrative \| diagnostic \| treatment_recommendation \| triage` | What the AI does clinically, if anything |
| `clinical.samd_classification_required` | bool | Your regulatory/quality function has determined this needs FDA clearance as a medical device |
| `clinical.fda_cleared` | bool | That clearance/authorization has been obtained |
| `clinical.validation_study_completed` | bool | A clinical validation study was run before deployment |
| `clinical.ai_generated_documentation` | bool | The system drafts notes, orders, or summaries destined for the record |
| `clinical.clinician_attestation_before_record` | bool | A clinician reviews and attests before that draft is filed |
| `clinical.fallback_to_standard_triage` | bool | Staff can fall back to the non-AI triage protocol at any time |
| `data.categories` (new values) | list | `phi`, `genetic_data`, `substance_use_disorder_records` |
| `data.part2_consent_obtained` | bool | Specific 42 CFR Part 2 consent for this disclosure (separate from general HIPAA consent) |
| `model.baa_signed` | bool | A Business Associate Agreement covers this vendor for this use |

`phi` is a deliberately distinct value from the generic pack's
`sensitive_personal_data` tag — this pack's rules check for it explicitly,
so tag PHI as `phi` (and also `sensitive_personal_data` if you want the
generic `red-zone` pack's own sensitivity check to consider it too; the two
are independent tags on the same list).

Every field above is a convention checked by this pack's rules, not an
engine-enforced schema. Missing fields are `unknown`, not `false` — an
incomplete healthcare intake will never auto-approve, and the missing paths
are named in the decision's `unknown_paths`.

See `examples/intake/healthcare-*.json` for five worked cases (a compliant
scribe, an FDA-cleared pediatric imaging AI, an uncleared triage bot denied
even though it wasn't self-reported as consequential, PHI shipped without a
BAA, and a vague submission that fails closed) and
`examples/tests/healthcare-decisions.yaml` for the test suite.
