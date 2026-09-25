"""A resident decision point — because process-per-call is the real latency cost.

Measured: the decision itself is ~1 ms; starting Python for every hook call is
~100+ ms. Keep the engine resident and make the per-call hook a tiny curl that
FAILS CLOSED if the server is down:

    hashimori serve --port 8787 &
    # .claude/settings.json → PreToolUse command:
    curl -sf --max-time 2 -H 'content-type: application/json' --data-binary @- \\
      http://127.0.0.1:8787/pre || echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse",
      "permissionDecision":"deny","permissionDecisionReason":"hashimori unreachable: failing closed"}}'

Binds to 127.0.0.1 only. Stdlib only.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from hashimori.runtime.gate import Gate, RuntimeConfig, audit_line


def make_handler(gate: Gate, home: Path, mode: str, grant: bool):
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # decisions go to the audit log, not stderr
            pass

        def _send(self, obj: dict | None) -> None:
            body = json.dumps(obj).encode() if obj else b""
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send({"ok": True, "service": "hashimori", "mode": mode})

        def do_POST(self):
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                with lock:
                    if self.path.startswith("/post"):
                        res = gate.observe(payload)
                        if res.get("note_for_agent"):
                            return self._send({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                                      "additionalContext": res["note_for_agent"]}})
                        return self._send(None)
                    v = gate.decide(payload)
                    with open(home / "audit.jsonl", "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(audit_line(payload, v, mode + "+serve")) + "\n")
                if mode == "shadow" or (v.decision == "allow" and v.updated_input is None and not grant):
                    return self._send(None)
                decision = v.decision
                if v.decision == "allow" and v.updated_input is not None and not grant:
                    decision = "ask"
                out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                              "permissionDecisionReason": "hashimori: " + v.agent_reason}}
                if v.updated_input is not None and decision in ("allow", "ask"):
                    out["hookSpecificOutput"]["updatedInput"] = v.updated_input
                    out["systemMessage"] = "hashimori: " + v.agent_reason
                self._send(out)
            except Exception as exc:  # fail closed
                self._send({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                   "permissionDecisionReason": f"hashimori internal error: {exc}"}})

    return H


def serve(port: int = 8787, home: str | None = None, rules: str | None = None,
          envelope: str | None = None, tools: list | None = None) -> None:
    home_p = Path(home or os.environ.get("HASHIMORI_HOME") or Path.cwd() / ".hashimori")
    home_p.mkdir(parents=True, exist_ok=True)
    gate = Gate(RuntimeConfig(rules, envelope, tools), home=home_p)
    from hashimori.runtime.ledger import Ledger
    gate._ledger = Ledger(home_p / "ledger.db", threaded=True)
    mode = os.environ.get("HASHIMORI_MODE", "enforce")
    grant = os.environ.get("HASHIMORI_ALLOW", "defer") == "grant"
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(gate, home_p, mode, grant))
    print(f"🌉 hashimori serving on http://127.0.0.1:{port}  (mode={mode}, home={home_p})", flush=True)
    httpd.serve_forever()
