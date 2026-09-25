# Runtime enforcement: configuration

`hashimori.runtime` decides on every tool call an AI agent makes, before it
runs: **allow**, **ask** a human, **deny**, or **rewrite** it into something
reversible. This page covers setup and configuration. For how the gate
reasons, read the runtime section of the [README](../README.md) and the policy
itself: [`hashimori/runtime/packs/agent-runtime.yaml`](../hashimori/runtime/packs/agent-runtime.yaml).

## Install and try it

```bash
pip install hashimori            # or, from a clone: pip install -e .
hashimori check -c 'rm -rf build'
bash examples/runtime/tour.sh    # every decision type, self-checking, no agent needed
```

## Wire it into an agent

| Harness | Config | Notes |
|---|---|---|
| Claude Code | [`adapters/claude-code/settings.json`](../adapters/claude-code/settings.json) → merge into `.claude/settings.json` | `PreToolUse` decides; `PostToolUse` records outcomes, taints the session on secrets in output, and tells the agent when a call was rewritten. |
| Claude Code, low latency | [`settings.fast.json`](../adapters/claude-code/settings.fast.json) + `hashimori serve` | A resident decision point on 127.0.0.1:8787 avoids starting Python per call. |
| Cursor | [`adapters/cursor/hooks.json`](../adapters/cursor/hooks.json) → `.cursor/hooks.json` | `beforeShellExecution`, `beforeMCPExecution`, `beforeReadFile`, `preToolUse`; `failClosed: true`. Cursor has no "ask" in `preToolUse`, so an ask becomes a deny there. |

**Fail closed.** Claude Code treats a crashed or timed-out hook as
non-blocking — the call proceeds. The adapter catches its own errors and returns
`ask` (or `deny`), and the shipped settings add `|| echo <deny>` for the case
where the hook can't start at all.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `HASHIMORI_MODE` | `enforce` | `shadow` logs every decision but never blocks. |
| `HASHIMORI_ALLOW` | `defer` | On allow: `defer` to the harness's own permission flow, or `grant` (skip its prompts). |
| `HASHIMORI_ON_ERROR` | `ask` | What an internal error becomes: `ask` or `deny`. |
| `HASHIMORI_AGENT_MESSAGES` | `full` | `minimal` tells the agent only `Blocked by policy (incident H-…)`; the reason stays in the audit log. |
| `HASHIMORI_HOME` | `<project>/.hashimori` | Session ledger (SQLite) and `audit.jsonl`. |
| `HASHIMORI_RULES` | bundled packs | Directory of runtime packs to use instead. |
| `HASHIMORI_TOOLS` | — | Your MCP / function-calling tool registry (see below). Several files: separate with `:` (`;` on Windows). |
| `HASHIMORI_ENVELOPE` | — | `envelope.json` from `hashimori envelope`. |
| `HASHIMORI_HOST` | hostname | Host label written to the audit log (for `hashimori fleet`). |
| `HASHIMORI_NO_CODE_INSPECT` | — | `1` turns off reading scripts before they run (for ablation only). |
| `HASHIMORI_JUDGE` | — | `http` or `jev` to enable a model judge (see below). |

## Your MCP tools

MCP servers can describe their own tools as read-only or destructive, but the
MCP spec says clients must treat those annotations as untrusted. Hashimori uses
a registry **you** own instead. A tool that isn't in it is an *unknown*, and
unknowns ask a human. The bundled registry is empty.

```yaml
# my-tools.yaml — the MCP tool name, without the mcp__<server>__ prefix
tools:
  crm_lookup_customer:
    verb: read                         # read | write | delete | exec | egress | delegate
    object: "crm:customer/{customer_id}"   # {arg} is filled from the call's arguments
    sensitivity: 2                     # 0 public · 1 internal · 2 confidential · 3 restricted
    reversible: true
    tags: [pii]
  chat_post_message:
    verb: egress
    object: "chat:#{channel}"
    external: true
    reversible: false
    tags: [upload]
```

```bash
HASHIMORI_TOOLS=my-tools.yaml hashimori hook pre      # or: hashimori check --tools my-tools.yaml …
```

[`examples/runtime/tools.yaml`](../examples/runtime/tools.yaml) is a complete
example: three support-desk tools that together form the lethal trifecta.

## From design-time review to runtime limits

```bash
hashimori envelope --rules rulepacks/ --context examples/intake/coding-agent.json --out envelope.json
HASHIMORI_ENVELOPE=envelope.json hashimori check -c 'curl https://api.example.com'
```

The review tier sets the risk budget, a DENIED use case denies every call, the
intake's `allowed_egress` extends the allowlist, and an attested
`approval_gate` makes every irreversible effect ask a human.

## Shadow mode → least privilege

Run with `HASHIMORI_MODE=shadow` for a while, then:

```bash
hashimori learn --audit .hashimori/audit.jsonl      # proposes an envelope from what agents actually did
```

It never learns from calls a red zone caught.

## Operating it

```bash
hashimori fleet ./logs/                       # campaigns across sessions and hosts; "allowed elsewhere"
hashimori fleet ./logs/ --ocsf findings.jsonl # OCSF Detection Findings (class 2004) for your SIEM
hashimori report ./logs/ --out report.html    # one self-contained HTML page
hashimori restore --list | --latest           # undo rewritten deletes from .hashimori-trash/
hashimori ledger show | reset                 # inspect or clear session state
hashimori bench                               # decision latency on this machine
```

Audit logs contain command text. Treat them as sensitive.

## Model judge (optional)

A model can be consulted when the pack's `judge.consult_when` matches (by
default: ambiguous calls, egress, deletes). Its output becomes
`signals.judge.harmful` and `signals.judge.off_task`, which rules can only use
to **add** price or deny. A missing, slow, malformed or over-budget answer is
no signal, and rules that needed it fail closed.

| Adapter | Enable | Settings |
|---|---|---|
| `http` | `HASHIMORI_JUDGE=http` | `HASHIMORI_JUDGE_URL` (http/https, required), `HASHIMORI_JUDGE_TOKEN` (optional bearer) |
| `jev` | `HASHIMORI_JUDGE=jev` | `TYPESAFE_API_KEY`, optional `TYPESAFE_API_URL`, `HASHIMORI_JUDGE_MODEL` |

**The `http` contract** — put any model behind a small service:

```text
POST <HASHIMORI_JUDGE_URL>
{"tool": "Bash", "call": "<redacted call>", "user_request": "<redacted>",
 "labels": {"routine": "...", "destructive": "...", ...}, "harmful_labels": [...], "state": "<one-paragraph summary>"}

200 OK
{"harmful": 0.0-1.0, "off_task": 0.0-1.0, "label": "...", "confidence": 0.7, "model": "...",
 "usage": {"input_tokens": 0, "output_tokens": 0}}          # only "harmful" is required
```

**From Python**, install any object with `name`, `usd_per_mtok`, `configured()`
and `assess(prompt, timeout)`:

```python
from hashimori.runtime import judge
judge.use(MyJudge())
```

**Spend cap.** Every call is metered in `~/.hashimori/judge-usage.json`
(`HASHIMORI_JUDGE_USAGE`). Calls stop at `HASHIMORI_JUDGE_BUDGET_USD` (default
2.00) or `HASHIMORI_JUDGE_MAX_CALLS` (default 5000). The price per million
tokens comes from the adapter, or from `HASHIMORI_JUDGE_USD_PER_MTOK`.
`HASHIMORI_JUDGE_TIMEOUT` defaults to 3 seconds.

**What leaves your boundary:** the call text and the user's last request, after
redaction of obvious secrets. Prefer a local model for sensitive environments.

## Benchmarks

[`benchmarks/runtime/`](../benchmarks/runtime/) measures friction and catch
rates on public datasets. See its README.
