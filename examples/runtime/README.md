# Runtime examples

| File | What it is |
|---|---|
| [`tour.sh`](tour.sh) | A self-checking tour of every decision type — allow, ask, deny, rewrite, undo — using real hook payloads and the bundled policy. No agent needed. CI runs it. |
| [`tools.yaml`](tools.yaml) | An example MCP tool registry: three support-desk tools that together make the lethal trifecta (untrusted input, private data, a way out). |
| [`../intake/coding-agent.json`](../intake/coding-agent.json) | A design-time intake for a coding agent, for `hashimori envelope`. |

```bash
pip install -e .                      # from the repo root
bash examples/runtime/tour.sh
HASHIMORI_TOOLS=examples/runtime/tools.yaml \
  hashimori check --tool mcp__desk__crm_lookup_customer --input '{"customer_id": "C-1"}'
hashimori envelope --rules rulepacks/ --context examples/intake/coding-agent.json --out envelope.json
```

To put the gate in front of a real agent, see [`adapters/`](../../adapters/) and
[docs/runtime.md](../../docs/runtime.md).
