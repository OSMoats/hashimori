# Changelog

## 0.3.0 — Runtime enforcement (BSides Orlando 2026)

### Added during BSides prep

- Script inspection: local scripts run by python/bash/sh (and their local imports) are
  lifted into effects before they run. Site-packages are not inspected (pinned gap).
- Shell adapter: variables and loops, find -exec/-delete, xargs/parallel, wrappers,
  process substitution, system-change commands, downloads; unresolved targets on
  writes/deletes are unknown (never guessed).
- Fleet sensor (`hashimori fleet`), Gatehouse HTML report (`hashimori report`),
  OCSF-shaped export, `hashimori restore`, minimal agent messages with incident ids,
  rewrites reported to the agent via PostToolUse, Cursor adapter.
- Evaluation harness on NL2Bash, RedCode-Exec (Python + Bash) and MBPP with a blind
  baseline and held-out splits (`demo/eval`).

### Runtime enforcement

- **New: `hashimori.runtime`** — enforce AI agent tool calls with the same engine
  and rule language used for design-time review.
  - Effect lifting for shell, file tools, web fetch, sub-agents, and MCP tools
    (operator-owned registry; server self-declared annotations are not trusted).
  - Red zones, per-call pricing, session risk budget, raise-only taint shared with
    sub-agents, rewrite-before-refuse (workspace deletes → quarantine move).
  - Claude Code PreToolUse/PostToolUse adapter that fails closed; resident
    `hashimori serve` for low-latency hooks.
  - `hashimori envelope`: design-time decision → runtime limits.
  - `hashimori learn`: shadow-mode audit → proposed envelope.
  - Optional escalate-only semantic judge (TypeSafe Jev adapter) with a hard spend cap.
  - `hashimori check`, `ledger`, `bench` commands. Demo kit in `demo/`.
- **Engine:** `evaluate_rules()` and `select_tier()` exposed; pack hashes cached at
  load (full evaluation was spending ~99% of its time re-hashing packs); libyaml
  safe loader used when available.

## 0.2.0 — first PyPI release (Sept 2026)

- Published to PyPI via Trusted Publishing (OIDC); zero-install quickstart with `uvx` / `pipx`.
- Healthcare/clinical and financial-services rule packs, with example intakes and decision tests.
- Fix: silent rule bypass in `in` / `not_in` when the expected value isn't a list.
- CLI hardened against malformed input; version read from package metadata.
- CODEOWNERS, StepSecurity Harden Runner in CI, Dependabot action bumps.
