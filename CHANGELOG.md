# Changelog

## 0.3.0 — Runtime enforcement for AI agent tool calls

### Added

- **`hashimori.runtime`**: decide on every tool call an agent makes — allow, ask,
  deny, or rewrite — with the same engine and rule language used for design-time
  review. Default policy in `hashimori/runtime/packs/agent-runtime.yaml`.
  - Effect lifting for shell, file tools, web fetch/search, sub-agents and MCP
    tools. MCP tools are mapped by an operator-owned registry (`--tools` /
    `HASHIMORI_TOOLS`); server self-declared annotations are not trusted.
  - Shell adapter: variables and loops, `find -exec/-delete`, `xargs`/`parallel`,
    wrappers, process substitution, system-change commands, downloads. Unresolved
    targets on writes and deletes are unknown, never guessed; unknowns ask.
  - Script inspection: local scripts run by python/bash/sh, and their local
    imports, are lifted into effects before they run. Installed packages are not
    inspected (pinned as a known-gap test).
  - Red zones, per-call pricing, a session risk budget, raise-only taint shared
    with sub-agents, and rewrite-before-refuse (workspace deletes → a recoverable
    quarantine the agent can't empty; `hashimori restore`).
- **Adapters:** Claude Code `PreToolUse`/`PostToolUse` (fails closed; tells the
  agent when a call was rewritten), Cursor hooks, and `hashimori serve` for
  low-latency hooks. Ready-made configs in `adapters/`.
- **Design time → runtime:** `hashimori envelope` compiles a review decision into
  runtime limits; `hashimori learn` proposes an envelope from shadow-mode logs.
- **Operations:** `hashimori fleet` (cross-session and cross-host campaign
  detection, "allowed elsewhere"), `hashimori report` (self-contained HTML),
  OCSF Detection Finding export, minimal agent messages with incident ids,
  `check`, `ledger`, `bench`.
- **Optional model judge**, escalate-only, behind a small adapter interface:
  `http` (any model behind a service you run) and `jev` (TypeSafe), or your own
  object via `judge.use()`. Malformed answers are discarded; hard spend cap.
- **Benchmark** on NL2Bash, RedCode-Exec (Python and Bash) and MBPP, with
  held-out splits and pinned dataset sources (`benchmarks/runtime/`).
- **Docs and examples:** `docs/runtime.md`, `examples/runtime/tour.sh` (a
  self-checking tour, also run in CI), `examples/runtime/tools.yaml`,
  `examples/intake/coding-agent.json`.

### Changed

- **Engine:** `evaluate_rules()` and `select_tier()` are exposed; pack hashes are
  cached at load (a full evaluation was spending ~99% of its time re-hashing
  packs); the libyaml safe loader is used when available. `evaluate()` behaves
  the same.

## 0.2.0 — first PyPI release (Sept 2026)

- Published to PyPI via Trusted Publishing (OIDC); zero-install quickstart with `uvx` / `pipx`.
- Healthcare/clinical and financial-services rule packs, with example intakes and decision tests.
- Fix: silent rule bypass in `in` / `not_in` when the expected value isn't a list.
- CLI hardened against malformed input; version read from package metadata.
- CODEOWNERS, StepSecurity Harden Runner in CI, Dependabot action bumps.
