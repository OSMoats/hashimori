"""The session ledger: one record per agent session, shared by every sub-agent.

What it remembers is deliberately small and *monotonic*:

- ``max_sensitivity`` only goes up (raise-only taint). Reading a secret
  can't be undone by reading something boring afterwards.
- ``untrusted`` only goes from False to True. Once the session has read
  content an attacker could have written, it stays marked for the rest of
  the session.
- ``spent`` is the risk budget used so far. Only a human resets it: when a
  call we escalated ("ask") later completes, a person approved it.

Sub-agents share their parent's session id, so they inherit its taint and draw
from its budget. Delegation cannot mint new budget.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  max_sensitivity INTEGER NOT NULL DEFAULT 0,
  untrusted INTEGER NOT NULL DEFAULT 0,
  spent REAL NOT NULL DEFAULT 0,
  calls INTEGER NOT NULL DEFAULT 0,
  denies INTEGER NOT NULL DEFAULT 0,
  asks INTEGER NOT NULL DEFAULT 0,
  human_resets INTEGER NOT NULL DEFAULT 0,
  taint_sources TEXT NOT NULL DEFAULT '[]',
  created REAL, updated REAL
);
CREATE TABLE IF NOT EXISTS pending_asks (
  tool_use_id TEXT PRIMARY KEY, session_id TEXT, created REAL
);
"""


@dataclass
class SessionState:
    session_id: str
    max_sensitivity: int = 0
    untrusted: bool = False
    spent: float = 0.0
    calls: int = 0
    denies: int = 0
    asks: int = 0
    human_resets: int = 0
    taint_sources: list | None = None

    def to_context(self) -> dict:
        return {"max_sensitivity": self.max_sensitivity, "untrusted": self.untrusted,
                "spent": self.spent, "calls": self.calls, "denies": self.denies}


class Ledger:
    def __init__(self, path: str | Path, threaded: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # threaded=True for the resident server, which serialises access with a lock
        self.db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None,
                                  check_same_thread=not threaded)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def get(self, session_id: str) -> SessionState:
        row = self.db.execute(
            "SELECT max_sensitivity, untrusted, spent, calls, denies, asks, human_resets, taint_sources "
            "FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            return SessionState(session_id, taint_sources=[])
        return SessionState(session_id, row[0], bool(row[1]), row[2], row[3], row[4], row[5], row[6],
                            json.loads(row[7]))

    def commit(self, session_id: str, decision: str, price: float, raise_sensitivity: int,
               untrusted: bool, taint_sources: list[str], tool_use_id: str | None) -> SessionState:
        now = time.time()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cur = self.get(session_id)
            charged = price if decision in ("allow", "ask") else 0.0
            sources = (cur.taint_sources or []) + [s for s in taint_sources if s not in (cur.taint_sources or [])]
            self.db.execute(
                """INSERT INTO sessions (session_id, max_sensitivity, untrusted, spent, calls, denies, asks,
                     human_resets, taint_sources, created, updated)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     max_sensitivity=excluded.max_sensitivity, untrusted=excluded.untrusted,
                     spent=excluded.spent, calls=excluded.calls, denies=excluded.denies,
                     asks=excluded.asks, taint_sources=excluded.taint_sources, updated=excluded.updated""",
                (session_id,
                 max(cur.max_sensitivity, raise_sensitivity if decision != "deny" else 0),
                 int(cur.untrusted or (untrusted and decision != "deny")),
                 cur.spent + charged, cur.calls + 1, cur.denies + (decision == "deny"),
                 cur.asks + (decision == "ask"), cur.human_resets, json.dumps(sources[-20:]), now, now))
            if decision == "ask" and tool_use_id:
                self.db.execute("INSERT OR REPLACE INTO pending_asks VALUES (?,?,?)",
                                (tool_use_id, session_id, now))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return self.get(session_id)

    def observe_completion(self, session_id: str, tool_use_id: str | None,
                           raise_sensitivity: int = 0, source: str | None = None) -> bool:
        """PostToolUse. If this call was escalated and still ran, a human said yes:
        the meter resets. Output-based taint (secrets seen in results) also lands here."""
        self.db.execute("BEGIN IMMEDIATE")
        approved = False
        try:
            now = time.time()
            self.db.execute("INSERT OR IGNORE INTO sessions (session_id, created, updated) VALUES (?,?,?)",
                            (session_id, now, now))
            if tool_use_id and self.db.execute("DELETE FROM pending_asks WHERE tool_use_id=?",
                                               (tool_use_id,)).rowcount:
                approved = True
                self.db.execute("UPDATE sessions SET spent=0, human_resets=human_resets+1 WHERE session_id=?",
                                (session_id,))
            if raise_sensitivity:
                cur = self.get(session_id)
                srcs = (cur.taint_sources or []) + ([source] if source else [])
                self.db.execute("UPDATE sessions SET max_sensitivity=MAX(max_sensitivity, ?), taint_sources=? "
                                "WHERE session_id=?", (raise_sensitivity, json.dumps(srcs[-20:]), session_id))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return approved

    def reset(self, session_id: str | None = None) -> None:
        if session_id:
            self.db.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        else:
            self.db.execute("DELETE FROM sessions")
            self.db.execute("DELETE FROM pending_asks")

    def all(self) -> list[SessionState]:
        ids = [r[0] for r in self.db.execute("SELECT session_id FROM sessions ORDER BY updated DESC")]
        return [self.get(i) for i in ids]


def default_home(cwd: str | None = None) -> Path:
    return Path(os.environ.get("HASHIMORI_HOME") or Path(cwd or os.getcwd()) / ".hashimori")
