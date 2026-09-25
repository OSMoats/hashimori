"""Cursor adapter — the same gate behind Cursor's agent hooks.

    ~/.cursor/hooks.json or <project>/.cursor/hooks.json:
    {"version": 1, "hooks": {
       "beforeShellExecution": [{"command": "python3 -m hashimori.runtime.cursor", "failClosed": true}],
       "beforeMCPExecution":   [{"command": "python3 -m hashimori.runtime.cursor", "failClosed": true}],
       "beforeReadFile":       [{"command": "python3 -m hashimori.runtime.cursor", "failClosed": true}],
       "preToolUse":           [{"command": "python3 -m hashimori.runtime.cursor", "matcher": "Write|Delete|Task",
                                 "failClosed": true}]}}

Mapping follows Cursor's documented hook schema (cursor.com/docs/hooks, Sept 2026).
Cursor fails OPEN on hook crashes unless `failClosed: true` — set it. preToolUse
has no "ask", so an escalation there becomes a deny that tells the agent a human
must approve; beforeShellExecution / beforeMCPExecution support "ask" natively.
Not yet validated against a live Cursor install — unit-tested on documented payloads.
"""

from __future__ import annotations

import json
import os
import sys


def to_payload(evt: dict) -> tuple[dict, str]:
    """Cursor hook input → the gate's payload (Claude Code-shaped) + event name."""
    name = evt.get("hook_event_name", "")
    roots = evt.get("workspace_roots") or []
    cwd = evt.get("cwd") or (roots[0] if roots else os.getcwd())
    base = {"session_id": evt.get("conversation_id") or "cursor", "cwd": cwd,
            "tool_use_id": evt.get("tool_use_id") or evt.get("generation_id"),
            "transcript_path": evt.get("transcript_path")}
    if name == "beforeShellExecution":
        return {**base, "tool_name": "Bash", "tool_input": {"command": evt.get("command", "")}}, name
    if name == "beforeMCPExecution":
        ti = evt.get("tool_input")
        if isinstance(ti, str):
            try:
                ti = json.loads(ti)
            except ValueError:
                ti = {"raw": ti}
        server = evt.get("mcp_server_name") or "cursor"
        return {**base, "tool_name": f"mcp__{server}__{evt.get('tool_name', '')}", "tool_input": ti or {}}, name
    if name == "beforeReadFile":
        return {**base, "tool_name": "Read", "tool_input": {"file_path": evt.get("file_path", "")}}, name
    if name == "preToolUse":
        tool, ti = evt.get("tool_name", ""), dict(evt.get("tool_input") or {})
        if ti.get("working_directory"):
            base["cwd"] = ti["working_directory"]
        if tool == "Shell":
            return {**base, "tool_name": "Bash", "tool_input": {"command": ti.get("command", "")}}, name
        if tool == "Delete":
            path = ti.get("path") or ti.get("file_path") or ""
            return {**base, "tool_name": "Bash", "tool_input": {"command": f"rm -- {path}"}}, name
        if tool.startswith("MCP:"):
            return {**base, "tool_name": f"mcp__cursor__{tool[4:]}", "tool_input": ti}, name
        if tool in ("Read", "Write", "Task", "Grep"):
            if "path" in ti and "file_path" not in ti:
                ti["file_path"] = ti["path"]
            return {**base, "tool_name": "Agent" if tool == "Task" else tool, "tool_input": ti}, name
        return {**base, "tool_name": tool, "tool_input": ti}, name
    return {**base, "tool_name": evt.get("tool_name", ""), "tool_input": evt.get("tool_input") or {}}, name


def to_output(v, event: str) -> dict:
    """Gate verdict → Cursor hook output for that event."""
    decision = v.decision
    msg = f"hashimori: {v.agent_reason}"
    if event in ("beforeShellExecution", "beforeMCPExecution"):
        out = {"permission": decision}
        if decision != "allow":
            out.update({"user_message": f"hashimori: {v.reason}", "agent_message": msg})
        return out
    if event == "beforeReadFile":
        return {"permission": "deny" if decision == "deny" else "allow",
                **({"user_message": f"hashimori: {v.reason}"} if decision == "deny" else {})}
    # preToolUse: allow | deny (+ updated_input). No native "ask".
    if decision == "allow":
        out = {"permission": "allow"}
        if v.updated_input is not None:
            out["updated_input"] = v.updated_input
            out["agent_message"] = msg
        return out
    if decision == "ask":
        return {"permission": "deny", "user_message": f"hashimori (needs your approval): {v.reason}",
                "agent_message": "hashimori: this action needs a human's approval. Ask the user to run or approve it."}
    return {"permission": "deny", "user_message": f"hashimori: {v.reason}", "agent_message": msg}


def main() -> int:
    from hashimori.runtime.gate import Gate, audit_line
    from hashimori.runtime.ledger import default_home
    try:
        evt = json.loads(sys.stdin.read() or "{}")
        payload, event = to_payload(evt)
        v = Gate().decide(payload)
        home = default_home(payload.get("cwd"))
        home.mkdir(parents=True, exist_ok=True)
        with open(home / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({**audit_line(payload, v, "enforce"), "harness": "cursor", "event": event}) + "\n")
        sys.stdout.write(json.dumps(to_output(v, event)))
        return 0
    except Exception as exc:  # fail closed
        sys.stdout.write(json.dumps({"permission": "deny", "user_message": f"hashimori internal error: {exc}",
                                     "agent_message": "hashimori: blocked (internal error, failing closed)"}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
