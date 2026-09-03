# Hashimori Skills

Drop-in [Agent Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) for Claude Code, Cowork, and any agent runtime that reads `SKILL.md` folders. Each one is small, composable, and independent — use one, use all four, or fork them.

**The architecture rule they all obey: the LLM works at the edges, never in the decision path.**

AI is excellent at reading a 40-page policy PDF and terrible at being audited. So the skills use AI to *write and test the rules* — and the rules themselves are evaluated by the deterministic engine, which gives the same answer every time, hashes its inputs, and can be replayed in front of an auditor.

| Skill | In | Out |
|---|---|---|
| [`policy-to-rules`](policy-to-rules/) | Your AI policy (PDF, Word, text, markdown) | A validated, **tested** Hashimori rule pack |
| [`intake-copilot`](intake-copilot/) | A team's messy description of what they want to ship | Clean intake JSON the engine can evaluate |
| [`decision-memo`](decision-memo/) | A decision JSON from the engine | A human-readable memo for the requester + the GRC record |
| [`rule-redteam`](rule-redteam/) | Your rule pack | The holes in it, as failing test cases |

## Install

Copy the folder(s) you want into your project's `.claude/skills/` directory (or `~/.claude/skills/` for personal use):

```bash
cp -r skills/policy-to-rules /your/project/.claude/skills/
```

Then ask your agent: *"Convert our AI policy at policy.pdf into a Hashimori rule pack."*
