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
- No network calls, no model calls, no telemetry. Evaluation is a pure
  function of (packs, context).
- YAML is parsed exclusively with `yaml.safe_load`; documents are hashed
  with SHA-256 for the audit record.
- One runtime dependency (PyYAML). Dependencies are monitored by
  Dependabot.

**Out of scope:** denial of service via enormous self-supplied inputs to
your own CLI; issues requiring a malicious rule pack; social-preview /
repository metadata; the demo and presentation materials.

If something violates the guarantees above — an intake context that can
influence anything beyond a decision value, a way to make unknowns
auto-approve, nondeterminism between identical runs — that's exactly what
we want to hear about.
