# AI agent governance rule pack

Identity and governance controls for AI agents, independent of industry:
is this agent registered as a distinct identity with an accountable owner,
is its access scoped and reviewed the way any other privileged identity's
access would be, and can its actions be traced back to the human or process
that authorized them. Where the finance and healthcare packs govern *what an
agent in that industry is allowed to decide*, this pack governs *whether the
agent is a governed identity in the first place*.

Framework refs (`NIST-AI-RMF`, `ISO-42001`) are informational mappings, not
compliance claims — see the disclaimer in the repo's
[CONTRIBUTING.md](../../CONTRIBUTING.md). Calibrate the thresholds and the
`agent.*` vocabulary below to your own identity and access review process;
the shape is the point.

The rules here are original to this pack. They were informed by the
publicly published Blueprint Alliance reference architecture for agentic AI
governance (an open, vendor-neutral framework covering agent discovery and
identity, access and entitlements, runtime authorization, and containment),
but the conditions, weights, wording, and thresholds below are this pack's
own, not a reproduction of that or any other source document.

## Vocabulary

This pack reads the `agent.*` and `observability.*` namespaces in the intake
context, alongside the shared `use_case.*`, `data.*`, `model.*`, and
`oversight.*` namespaces documented in [docs/schema.md](../../docs/schema.md).

| Path | Type | Meaning |
|---|---|---|
| `agent.identity_registered` | bool | The agent has a verified identity record (a directory entry), not shared or borrowed credentials. |
| `agent.owner_assigned` | bool | A specific accountable human owner is on record for this agent. |
| `agent.owner_active` | bool | That owner is still active in the role that made them the right owner. |
| `agent.access_time_bound` | bool | The agent's access grant expires automatically rather than standing indefinitely. |
| `agent.last_access_review_days` | number | Days since the agent's entitlements were last reviewed by their owner or a system owner. |
| `agent.can_originate_and_approve` | bool | This agent can both generate and approve the same consequential action with no second identity in the loop. |
| `agent.delegation_traceable` | bool | Every hop of a spawned sub-agent chain carries a link back to the human or process that authorized it. |
| `agent.delegation_depth` | number | How many hops of spawned sub-agents sit between this agent and the original human delegator. |

`observability.runtime_monitoring` (bool, shared namespace) records whether
the agent's runtime behavior, not just its access grant, is being watched
for drift from its authorized purpose.

## Composition

```bash
hashimori evaluate --rules rulepacks/red-zone rulepacks/ai-agent-governance rulepacks/baseline --context your-intake.json
hashimori test examples/tests/ai-agent-governance-decisions.yaml --rules rulepacks/red-zone rulepacks/ai-agent-governance rulepacks/baseline
```

This pack defines no `tiers`, so it never triggers the tier-shadowing
failure mode documented in [docs/schema.md](../../docs/schema.md#red-zones):
load it alongside `red-zone` and exactly one tiered pack, whichever fits the
use case (`baseline` for general-purpose agents, or an industry pack such as
`finance` or `healthcare`). Its red zones are checked with everyone else's,
and its risk factors add to whichever tiered pack you loaded.

## Tests

[`examples/tests/ai-agent-governance-decisions.yaml`](../../examples/tests/ai-agent-governance-decisions.yaml)
exercises all three red zones, the risk-factor scoring path, and the
fail-closed path on a vague submission. `tests/test_ai_agent_governance_pack.py`
runs the same suite through pytest.

## Author

Built by [Tushar Badlani](https://tusharbadlani.studio/), in a personal
capacity.
