"""Hashimori Runtime — enforcement for AI agent tool calls.

Same engine, same rule language as design-time review; different context.
Design time asks "should this agent exist?". Runtime asks, on every call,
"should THIS action happen, in THIS session, now?".

    effects.py  NORMALIZE  tool call → effect records (the agent "syscall" view)
    gate.py     DECIDE     rules → price → budget → allow / ask / deny / rewrite
    ledger.py   remember   raise-only taint + risk budget per session
    judge.py    signal     optional typed-decision model; escalate-only
    learn.py    LEARN      shadow-mode audit → proposed envelope
    hook.py     PLACE      Claude Code PreToolUse / PostToolUse adapter
"""
