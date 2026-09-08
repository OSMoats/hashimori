# Pack schema reference

A Hashimori policy pack is one YAML file. Version 1 has four top-level keys:

```yaml
version: 1          # required, literal 1
pack:               # metadata
  name: my-policy
  description: One honest sentence.
red_zones: [...]    # optional — checked first, any match short-circuits to DENIED
risk_factors: [...] # optional — matches add weights to a score
tiers: [...]        # required somewhere across your packs — score → outcome
```

Packs compose: point the engine at a directory and every `*.yaml` in it loads.
Red zones from all packs are checked before any scoring. This is how you keep
a company-wide `red-zone.yaml` alongside per-department baselines.

**Loading more than one pack with `tiers:`, on the other hand, is not
"merged" scoring.** `tiers` from every loaded pack are concatenated into one
list, and the engine stops at the first tier whose `max_score` isn't
exceeded — it does not namespace or reconcile ladders per pack. If pack A's
catch-all tier (no `max_score`) sorts ahead of pack B's ladder, B's tiers
are simply never reached — and if the two catch-all tiers happen to share a
`name`, the failure is silent: the decision reports the right-looking tier
name with the wrong pack's reviewers and obligations underneath it. Load at
most one tiered pack per run (pairing it with red-zone-only packs is fine,
since those never define `tiers`); see `rulepacks/healthcare/README.md` for
a verified example of the failure mode and how to compose around it.

## Red zones

```yaml
red_zones:
  - id: REDZONE-001                 # unique across all loaded packs
    name: Short human name
    when: <condition>          # see Conditions
    message: >                 # required — shown to the requester on denial
      What is prohibited, in your policy's words.
    remedy: >                  # strongly recommended — the path to yes
      What to change before resubmitting (or say plainly there is no path).
    refs: [NIST-AI-RMF:MANAGE-2.2, InternalPolicy:2.1]   # optional mapping tags
```

A red zone match means **DENIED, immediately**: scoring is skipped, no
reviewers are assigned. The decision carries every matched red zone, its
message, and its remedy — an automatic rejection should be the clearest
message a team gets all week, not the vaguest.

## Risk factors

```yaml
risk_factors:
  - id: RISK-001
    name: Handles personal data
    when: <condition>
    weight: 3                  # positive number; matched weights are summed
    refs: [...]
```

## Tiers

Ordered list; the score selects the first tier whose `max_score` is not
exceeded. The last tier omits `max_score` and catches everything else.

```yaml
tiers:
  - name: fast_track
    max_score: 2
    outcome: approved          # approved | needs_review | denied
    obligations: [enable_logging, register_in_ai_inventory, annual_review]
  - name: standard_review
    max_score: 6
    outcome: needs_review
    reviewers: [security]
    sla_days: 5
  - name: elevated_review
    outcome: needs_review
    reviewers: [security, privacy, legal, ai_governance_board]
    sla_days: 15
```

## Conditions

A condition is a leaf or a group. Groups nest arbitrarily.

```yaml
# Groups
all:  [<condition>, ...]   # every child true
any:  [<condition>, ...]   # at least one child true
none: [<condition>, ...]   # no child true

# Leaves — one path, one operator
- {path: oversight.human_in_loop, is: false}
- {path: model.provider, is_not: self_hosted}
- {path: use_case.decision_impact, in: [credit, employment]}
- {path: data.categories, not_in: [public]}
- {path: data.categories, contains: personal_data}      # list membership or substring
- {path: data.categories, not_contains: personal_data}
- {path: use_case.affected_people, gte: 10000}          # also gt, lt, lte
- {path: use_case.description, matches: "(?i)autonom"}  # regex
- {path: security.pen_test_date, exists: true}
```

`path` is a dotted path into the intake JSON. String comparisons are
case-insensitive.

### Three-valued evaluation (read this one section)

Every condition evaluates to **true**, **false**, or **unknown**:

- A leaf whose `path` is missing from the intake is **unknown** (except
  `exists`, which is always decidable).
- `all` with a false child is **false** — decided, regardless of unknowns.
  Otherwise, any unknown child makes it unknown.
- `any` with a true child is **true** — decided. Otherwise, any unknown child
  makes it unknown.

Rules only fire on **true**. But unknowns are not forgotten: every path that
made a rule undecidable is collected into the decision's `unknown_paths`, and
**a use case with unknowns can never be auto-approved** — it becomes
`NEEDS_REVIEW` with the missing answers named. Hashimori fails closed.

## Intake context

The intake is plain JSON. Field names are conventions, not schema — the
engine evaluates whatever paths your rules reference. The shipped packs use
these namespaces (see `examples/intake/` for full examples):

`use_case.*` `data.*` `model.*` `oversight.*` `agent.*` `observability.*`

Keep your vocabulary documented next to your packs; the `rule-redteam` skill
checks for vocabulary gaps.

## Test suites

```yaml
tests:
  - name: automated hiring decision is denied
    context: {...}                      # inline intake, or:
    context_file: ../intake/case.json   # relative to the suite file
    expect:
      decision: DENIED                  # DENIED | APPROVED | NEEDS_REVIEW
      tier: elevated_review             # optional
      red_zones: [REDZONE-001]               # optional — ids that must have fired
```

Run with `hashimori test suite.yaml --rules packs/`. Treat the suite like any
other test suite: it runs in CI, and a policy change that flips a decision
should fail loudly until the tests are updated deliberately.

## Decision output

`hashimori evaluate --json` emits:

```json
{
  "decision": "DENIED | APPROVED | NEEDS_REVIEW",
  "tier": "standard_review",
  "score": 5.0,
  "red_zones_hit": [{"id": "...", "name": "...", "message": "...", "remedy": "...", "refs": [...], "pack": "..."}],
  "risk_factors_hit": [{"id": "...", "weight": 3.0, ...}],
  "obligations": ["..."],
  "reviewers": ["..."],
  "sla_days": 5,
  "unknown_paths": ["..."],
  "reasons": ["..."],
  "auto_approval_blocked": false,
  "audit": {
    "engine": "hashimori 0.1.0",
    "evaluated_at": "...",
    "packs": [{"name": "...", "source": "...", "sha256": "..."}],
    "context_sha256": "...",
    "deterministic": true
  }
}
```

The audit block is the point: same packs + same context = same decision,
provably, years later.
