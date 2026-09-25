# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's
**[private vulnerability reporting](https://github.com/OSMoats/hashimori/security/advisories/new)**
(Security tab → "Report a vulnerability"). Please do not open public issues
for security reports. You'll get an acknowledgment within a few days, and
credit in the advisory if you'd like it.

Only the latest 0.x release line is supported with fixes.

## Threat model — read this before filing

Hashimori is deliberately small, and its security posture rests on a clear
trust boundary:

**Rule packs are trusted code.** A policy pack decides who gets to deploy
AI systems — it is *policy as code*, and it must be reviewed, versioned,
and protected exactly like code (code review, protected branches, CI).
Loading a rule pack from an untrusted source is equivalent to running
untrusted CI configuration, and is out of scope as an attack vector.
Consequences of this boundary:

- Regular expressions in `matches:` conditions are authored by the rule
  pack owner. Authors should avoid patterns vulnerable to catastrophic
  backtracking (ReDoS) when the matched intake field is attacker-shaped;
  the `rule-redteam` skill's checklist includes this.
- Weights, tiers, messages, and refs render into terminals and reports as
  trusted content.

**Intake context is untrusted data.** The engine treats submitted JSON as
pure data: it is compared against rule conditions, hashed for the audit
trail, and never interpolated into code, shell, regex patterns, file
paths, or queries. Unknown or missing fields fail closed (`NEEDS_REVIEW`),
never open.

**The engine itself:**

- No dynamic code execution — no `eval`, `exec`, pickle, or plugin loading.
- The engine makes no network calls, no model calls, no telemetry.
  Evaluation is a pure function of (packs, context).
- YAML is parsed only with PyYAML's safe loaders (`SafeLoader` /
  `CSafeLoader`); documents are hashed with SHA-256 for the audit record.

**Runtime (0.3+).** `hashimori.runtime` wraps the pure engine with state and
I/O: a local SQLite ledger (session taint + risk budget), an append-only
JSONL audit log, the Claude Code hook adapter, and an optional resident
server bound to 127.0.0.1. Its guarantees:

- **Fail closed.** Any internal error in the hook returns `ask` (or `deny`
  with `HASHIMORI_ON_ERROR=deny`). Claude Code itself treats crashed hooks as
  non-blocking, so the shipped settings add a shell `|| echo <deny>` fallback.
- **Monotonic.** Session taint only rises; model signals only add price.
- **The judge is opt-in** (`HASHIMORI_JUDGE=jev`). When enabled, the tool call
  text and the user's latest request — redacted for obvious secrets — are sent
  to the judge's API. Treat enabling it as an egress decision. A hard spend
  cap (`HASHIMORI_JUDGE_BUDGET_USD`, default $2) stops calls; a stopped judge
  fails closed.
- **Scope.** Runtime rules see what the agent *asks* to run. Local scripts (and
  their local imports) are read before they run, but installed packages,
  obfuscated or data-dependent code, and files changed between check and run
  are not (see `test_known_gap_installed_packages_are_not_inspected`). Use an
  OS sandbox and scoped credentials alongside it.
- **Fleet/report/export** read audit logs you point them at and write local
  files only. Audit logs contain command text: treat them as sensitive.
- One runtime dependency (PyYAML). Dependencies are monitored by
  Dependabot.

**Out of scope:** denial of service via enormous self-supplied inputs to
your own CLI; issues requiring a malicious rule pack; social-preview /
repository metadata; the demo and presentation materials.

If something violates the guarantees above — an intake context that can
influence anything beyond a decision value, a way to make unknowns
auto-approve, nondeterminism between identical runs — that's exactly what
we want to hear about.
