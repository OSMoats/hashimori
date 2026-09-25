"""Claude Code hook adapter (the Intent plane's enforcement point).

    PreToolUse  → python3 -m hashimori.runtime.hook pre
    PostToolUse → python3 -m hashimori.runtime.hook post

Claude Code treats a hook that crashes, times out, or exits non-zero (other
than 2) as a *non-blocking* error — the tool call proceeds. In other words the
harness fails OPEN. So this adapter catches everything and fails CLOSED on its
own; the settings snippet also wraps it in `|| echo <deny json>` for the case
where Python itself can't start.

Environment:
    HASHIMORI_MODE      enforce (default) | shadow  — shadow logs, never blocks
    HASHIMORI_ALLOW     defer (default) | grant     — on allow, defer to Claude
                        Code's normal permission flow, or grant (skip prompts)
    HASHIMORI_ON_ERROR  ask (default) | deny
    HASHIMORI_AGENT_MESSAGES  full (default) | minimal — minimal tells the agent only
                        "blocked (incident H-xxxx)"; the full reason stays in the audit log
    HASHIMORI_RULES     runtime pack dir (default: packs bundled with hashimori)
    HASHIMORI_HOME      ledger + audit dir (default: <project>/.hashimori)
    HASHIMORI_ENVELOPE  envelope.json from `hashimori envelope`
    HASHIMORI_JUDGE=jev + TYPESAFE_API_KEY  enable the optional semantic judge
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _emit(decision: str | None, reason: str = "", updated_input: dict | None = None,
          system_message: str | None = None) -> None:
    if decision is None:
        return  # no opinion: Claude Code's normal permission flow applies
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                  "permissionDecisionReason": f"hashimori: {reason}"}}
    if updated_input is not None and decision in ("allow", "ask"):
        out["hookSpecificOutput"]["updatedInput"] = updated_input
    if system_message:
        out["systemMessage"] = system_message   # rewrites are told to the agent, not hidden from it
    sys.stdout.write(json.dumps(out))


def pre(payload: dict) -> None:
    from hashimori.runtime.gate import Gate, audit_line
    from hashimori.runtime.ledger import default_home

    mode = os.environ.get("HASHIMORI_MODE", "enforce")
    gate = Gate()
    v = gate.decide(payload)
    home = default_home(payload.get("cwd"))
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "audit.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(audit_line(payload, v, mode)) + "\n")

    if mode == "shadow":
        return
    if v.decision == "allow":
        if v.updated_input is not None:
            grant = os.environ.get("HASHIMORI_ALLOW", "defer") == "grant"
            _emit("allow" if grant else "ask", v.agent_reason, v.updated_input,
                  system_message=f"hashimori: {v.agent_reason}")
        elif os.environ.get("HASHIMORI_ALLOW", "defer") == "grant":
            _emit("allow", v.agent_reason)
        return
    _emit(v.decision, v.agent_reason, v.updated_input)


def post(payload: dict) -> None:
    from hashimori.runtime.gate import Gate
    from hashimori.runtime.ledger import default_home
    result = Gate().observe(payload)
    home = default_home(payload.get("cwd"))
    if result["human_approved"] or result["secret_in_output"]:
        with open(home / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "post", "tool": payload.get("tool_name"),
                                 "session_id": payload.get("session_id"),
                                 "tool_use_id": payload.get("tool_use_id"), **result}) + "\n")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    event = argv[0] if argv else "pre"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if event == "post":
            post(payload)
        else:
            pre(payload)
        return 0
    except Exception as exc:  # fail closed — never let an error become an allow
        if event == "post":
            return 0  # PostToolUse can't block anyway
        on_error = os.environ.get("HASHIMORI_ON_ERROR", "ask")
        _emit("deny" if on_error == "deny" else "ask",
              f"internal error, failing closed ({type(exc).__name__}: {str(exc)[:160]})")
        return 0


if __name__ == "__main__":
    sys.exit(main())
