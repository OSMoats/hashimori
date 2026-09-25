# Changelog

## 0.2.0 — Runtime enforcement (BSides Orlando 2026)

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
