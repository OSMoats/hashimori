"""DECIDE — the runtime gate.

    tool call ─▶ lift to effects ─▶ rewrite? ─▶ rules per effect ─▶ price
             ─▶ (judge, only if consult_when and enabled — escalate-only)
             ─▶ red zone? deny · unknown? ask · over budget? ask · else allow
             ─▶ ledger (taint, spend) ─▶ audit line

The engine call (`evaluate_rules`) is the same pure function that reviews AI
use cases at design time. Everything stateful lives here, outside it.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from hashimori.conditions import evaluate_condition
from hashimori.engine import evaluate_rules
from hashimori.loader import Pack, load_pack
from hashimori.runtime.effects import Effect, lift_call, lift_shell
from hashimori.runtime.ledger import Ledger, SessionState, default_home

PACK_DIR = Path(__file__).parent / "packs"
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # libyaml when available: ~10x faster parse


class _LazyJudge:
    """Import the HTTP client only if a judge is actually used (saves ~16 ms per hook process)."""

    def __getattr__(self, name):
        from hashimori.runtime import judge
        return getattr(judge, name)


judge_mod = _LazyJudge()


@dataclass
class Verdict:
    decision: str                      # allow | ask | deny
    reason: str                        # full reason (audit / SOC / human)
    agent_reason: str = ""             # what the agent is told (see HASHIMORI_AGENT_MESSAGES)
    incident: str = ""                 # short id linking the agent's message to the audit record
    price: float = 0.0
    spent_before: float = 0.0
    budget: dict = field(default_factory=dict)
    red_zones: list = field(default_factory=list)
    factors: list = field(default_factory=list)
    unknown: list = field(default_factory=list)
    effects: list = field(default_factory=list)
    rewrite: dict | None = None
    updated_input: dict | None = None
    judge: dict | None = None
    timings_us: dict = field(default_factory=dict)
    session: dict = field(default_factory=dict)


class RuntimeConfig:
    """Runtime packs + tool registry + envelope, loaded once per process."""

    def __init__(self, rules_dir: str | Path | None = None, envelope_path: str | Path | None = None):
        rules_dir = Path(rules_dir or os.environ.get("HASHIMORI_RULES") or PACK_DIR)
        self.packs: list[Pack] = []
        self.registry: dict = {"tools": {}}
        raw_merged: dict = {}
        files = sorted(rules_dir.rglob("*.y*ml")) if rules_dir.is_dir() else [rules_dir]
        for f in files:
            data = yaml.load(f.read_text(), Loader=_Loader) or {}
            if "tools" in data and "version" not in data:
                self.registry["tools"].update(data["tools"] or {})
                continue
            self.packs.append(load_pack(f))
            for key in ("rewrites", "budget", "judge", "envelope"):
                if key in data:
                    if isinstance(data[key], list):
                        raw_merged.setdefault(key, []).extend(data[key])
                    else:
                        raw_merged.setdefault(key, {}).update(data[key])
        self.rewrites = raw_merged.get("rewrites", [])
        self.budget = {"per_call": 7, "session": 20, **raw_merged.get("budget", {})}
        self.judge_when = (raw_merged.get("judge") or {}).get("consult_when")
        self.envelope = {"allowed_egress": [], "use_case_denied": False, **raw_merged.get("envelope", {})}
        env_path = envelope_path or os.environ.get("HASHIMORI_ENVELOPE")
        if env_path and Path(env_path).exists():
            generated = json.loads(Path(env_path).read_text())
            self.envelope.update({k: v for k, v in generated.items() if k != "budget"})
            self.budget.update(generated.get("budget", {}))


def _allowlisted(obj: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(obj.lower(), p.lower()) for p in patterns)


_SAFE_TARGET = re.compile(r"^[\w./*?@%+=,:-]+$")


def rewrite_rm(command: str) -> str | None:
    """Rewrite-before-refuse, only for shell we fully understand: a chain of
    simple commands joined by && or ; where at least one is a plain `rm`.
    Each rm becomes `mkdir -p <trash> && mv -- <targets> <trash>/`.
    Anything with pipes, substitution, redirects, or odd quoting is left alone."""
    if any(ch in command for ch in "|`$<>(){}\n\\!") or "||" in command:
        return None
    parts = re.split(r"(\s*(?:&&|;)\s*)", command.strip())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = f".hashimori-trash/{stamp}"
    out, rewrote = [], False
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(part)
            continue
        try:
            argv = shlex.split(part)
        except ValueError:
            return None
        if not argv:
            out.append(part)
            continue
        if argv[0] != "rm":
            out.append(part)
            continue
        targets = [a for a in argv[1:] if not a.startswith("-")]
        if not targets or not all(_SAFE_TARGET.match(t) for t in targets):
            return None
        if any(t in ("/", "~", ".", "..") or t.startswith(("/", "~", "..")) for t in targets):
            return None  # outside-workspace deletes are priced / denied, never quietly moved
        # keep each target's relative directory so `hashimori restore` can put it back
        groups: dict[str, list[str]] = {}
        for t in targets:
            groups.setdefault(os.path.dirname(t.rstrip("/")) or ".", []).append(t)
        moves = []
        for d, ts in groups.items():
            where = dest if d == "." else f"{dest}/{d}"
            moves.append(f"mkdir -p {where} && mv -- {' '.join(ts)} {where}/")
        out.append(" && ".join(moves))
        rewrote = True
    return "".join(out) if rewrote else None


def last_user_request(transcript_path: str | None) -> str | None:
    """The user's latest instruction, for intent checks. Best effort, bounded."""
    if not transcript_path or not os.path.exists(transcript_path):
        return None
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 400_000))
            lines = fh.read().decode("utf-8", "ignore").splitlines()
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") != "user":
                continue
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                if any(t.strip() for t in texts):
                    return " ".join(texts).strip()
    except OSError:
        return None
    return None


class Gate:
    def __init__(self, config: RuntimeConfig | None = None, home: str | Path | None = None):
        self.config = config or RuntimeConfig()
        self.home = Path(home) if home else None
        self._ledger: Ledger | None = None

    def ledger(self, cwd: str) -> Ledger:
        if self._ledger is None:
            self._ledger = Ledger((self.home or default_home(cwd)) / "ledger.db")
        return self._ledger

    # ------------------------------------------------------------------ core
    def decide(self, payload: dict, commit: bool = True, use_judge: bool | None = None) -> Verdict:
        t0 = time.perf_counter()
        tool = payload.get("tool_name", "")
        tool_input = dict(payload.get("tool_input") or {})
        cwd = payload.get("cwd") or os.getcwd()
        session_id = payload.get("session_id") or "no-session"
        agent = payload.get("agent_type") or "main"
        cfg = self.config
        timings: dict[str, float] = {}

        effects = lift_call(tool, tool_input, cwd, cfg.registry)
        timings["lift"] = (time.perf_counter() - t0) * 1e6

        ledger = self.ledger(cwd)
        prior = ledger.get(session_id)

        rewrite = None
        updated_input = None
        rm_rewrite = rewrite_rm(str(tool_input.get("command", ""))) if tool == "Bash" else None

        def build(effs: list[Effect], simple_rm: bool) -> tuple[dict, dict]:
            reads = [e for e in effs if e.verb == "read"]
            raise_sens = max([e.sensitivity for e in reads] + [0])
            untrusted = any("untrusted_source" in e.tags for e in effs)
            call = {
                "tool": tool, "agent": agent, "simple_rm": simple_rm,
                "reads_secret": any(e.verb == "read" and ("secret_store" in e.tags or e.sensitivity >= 3)
                                    for e in effs),
                "has_egress": any(e.verb == "egress" for e in effs),
                "has_delete": any(e.verb == "delete" for e in effs),
                "ambiguous": any(not e.resolved for e in effs),
                "judged": False,
                "n_effects": len(effs),
            }
            session = prior.to_context()
            session["max_sensitivity"] = max(session["max_sensitivity"], raise_sens)
            session["untrusted"] = bool(session["untrusted"] or untrusted)
            return call, session

        call, session = build(effects, rm_rewrite is not None)

        # ---- rewrite before refuse ------------------------------------------
        # Only for calls that would otherwise be priced or asked: a red zone is never rewritten away.
        if rm_rewrite and any(evaluate_rules(cfg.packs, self._ctx(e, call, session), short_circuit=True).red_zones_hit
                              for e in effects):
            rm_rewrite = None
        for rw in cfg.rewrites:
            hit = any(evaluate_condition(rw["when"], self._ctx(e, call, session)).is_true for e in effects)
            if hit and rw.get("action") == "quarantine" and rm_rewrite:
                new_cmd = rm_rewrite
                updated_input = {**tool_input, "command": new_cmd}
                rewrite = {"id": rw["id"], "name": rw["name"], "from": tool_input["command"], "to": new_cmd}
                effects = lift_shell(new_cmd, cwd)
                call, session = build(effects, False)
                break

        # ---- optional judge (escalate-only) ----------------------------------
        judge_result = None
        want_judge = judge_mod.enabled() if use_judge is None else use_judge
        if want_judge and cfg.judge_when:
            probe = {"call": call, "session": session, "envelope": cfg.envelope}
            if evaluate_condition(cfg.judge_when, probe).is_true:
                tj = time.perf_counter()
                judge_result = judge_mod.ask(tool, updated_input or tool_input,
                                             last_user_request(payload.get("transcript_path")))
                timings["judge"] = (time.perf_counter() - tj) * 1e6
                call["judged"] = True

        signals = {"judge": judge_result["signals"]} if judge_result and "signals" in judge_result else {}

        # ---- rules, per effect ----------------------------------------------
        tr = time.perf_counter()
        red, factors, unknown, price = [], [], [], 0.0
        for e in effects:
            rr = evaluate_rules(cfg.packs, self._ctx(e, call, session, signals), short_circuit=False)
            for h in rr.red_zones_hit:
                if h["id"] not in {x["id"] for x in red}:
                    red.append({**h, "object": e.object})
            for h in rr.risk_factors_hit:
                factors.append({"id": h["id"], "name": h["name"], "weight": h["weight"], "object": e.object})
            price += rr.score
            unknown += rr.unknown_paths
        unknown = sorted(set(unknown))
        timings["rules"] = (time.perf_counter() - tr) * 1e6

        budget = cfg.budget
        if red:
            h = red[0]
            decision = "deny"
            reason = f"⛔ {h['id']} {h['name']}. {(h.get('message') or '').strip()} ↳ {(h.get('remedy') or '').strip()}"
        elif unknown:
            decision = "ask"
            what = ", ".join(sorted({t for e in effects if not e.resolved for t in e.tags})) or "missing facts"
            reason = (f"✋ Could not establish what this call does ({what}); unknowns fail closed to a human."
                      + (f" Judge: {signals['judge'].get('label')} (harmful {signals['judge'].get('harmful')})"
                         if signals.get("judge") else "")
                      + (" Judge unavailable — failing closed." if judge_result and "error" in judge_result else ""))
        elif price > budget["per_call"]:
            decision = "ask"
            reason = f"✋ Price {price:g} exceeds per-call limit {budget['per_call']:g}: " + \
                "; ".join(f"{f['id']} +{f['weight']:g} {f['name']}" for f in factors)
        elif price > 0 and prior.spent + price > budget["session"]:   # free calls never hit the budget
            decision = "ask"
            reason = (f"✋ Session risk budget exhausted: {prior.spent:g} spent + {price:g} "
                      f"> {budget['session']:g}. A human approval resets the meter.")
        else:
            decision = "allow"
            reason = f"✓ Price {price:g} · budget {prior.spent + price:g}/{budget['session']:g}"
            if rewrite:
                reason = f"↺ {rewrite['id']} {rewrite['name']} · " + reason

        # ---- ledger ----------------------------------------------------------
        tl = time.perf_counter()
        raise_sens = max([e.sensitivity for e in effects if e.verb == "read"] + [0])
        untrusted = any("untrusted_source" in e.tags for e in effects)
        sources = [f"{tool}:{e.object}" for e in effects
                   if (e.verb == "read" and e.sensitivity >= 2) or "untrusted_source" in e.tags]
        after = prior
        if commit:
            after = ledger.commit(session_id, decision, price, raise_sens, untrusted, sources,
                                  payload.get("tool_use_id"))
        timings["ledger"] = (time.perf_counter() - tl) * 1e6
        timings["total"] = (time.perf_counter() - t0) * 1e6

        incident = "H-" + hashlib.sha256(f"{session_id}|{payload.get('tool_use_id')}|{time.time_ns()}|{reason}"
                                         .encode()).hexdigest()[:8]
        agent_reason = reason
        if decision == "deny" and os.environ.get("HASHIMORI_AGENT_MESSAGES", "full") == "minimal":
            # Denials leak information and coach workarounds (cf. arXiv 2604.04035). Tell the agent
            # as little as possible; the full reason is in the audit log under the same incident id.
            agent_reason = f"Blocked by policy (incident {incident}). No workaround is available to the agent."
        elif rewrite:
            agent_reason = reason + (f" Your command was rewritten to `{rewrite['to']}`; nothing was deleted. "
                                     "A human can restore with `hashimori restore`.")
        return Verdict(
            decision=decision, reason=reason, agent_reason=agent_reason, incident=incident,
            price=price, spent_before=prior.spent, budget=dict(budget),
            red_zones=[{k: h.get(k) for k in ("id", "name", "object", "refs")} for h in red],
            factors=factors, unknown=unknown, effects=[e.to_context() for e in effects],
            rewrite=rewrite, updated_input=updated_input if decision != "deny" else None,
            judge={k: v for k, v in (judge_result or {}).items() if k != "raw"} or None,
            timings_us={k: round(v, 1) for k, v in timings.items()},
            session={"agent": agent, **after.to_context()},
        )

    def _ctx(self, e: Effect, call: dict, session: dict, signals: dict | None = None) -> dict:
        eff = e.to_context()
        eff["allowlisted"] = e.verb == "egress" and _allowlisted(e.object, self.config.envelope["allowed_egress"])
        ctx = {"effect": eff, "call": call, "session": session, "envelope": self.config.envelope}
        if signals:
            ctx["signals"] = signals
        return ctx

    def observe(self, payload: dict) -> dict:
        """PostToolUse: human-approved asks reset the budget; secrets in output raise taint."""
        from hashimori.runtime.effects import SECRET_CONTENT
        cwd = payload.get("cwd") or os.getcwd()
        resp = payload.get("tool_response")
        text = resp if isinstance(resp, str) else json.dumps(resp or "")[:200_000]
        secret = bool(SECRET_CONTENT.search(text))
        approved = self.ledger(cwd).observe_completion(
            payload.get("session_id") or "no-session", payload.get("tool_use_id"),
            raise_sensitivity=3 if secret else 0,
            source=f"{payload.get('tool_name')}:output-contained-secret" if secret else None)
        return {"human_approved": approved, "secret_in_output": secret}


def input_fingerprint(tool: str, tool_input: dict) -> str:
    """Stable fingerprint of what the agent asked for, robust to small variations
    (numbers, hex, whitespace) — lets the fleet sensor cluster the same attack."""
    raw = tool_input.get("command") if tool == "Bash" else json.dumps(tool_input, sort_keys=True)
    norm = re.sub(r"\s+", " ", str(raw or "")).strip().lower()
    norm = re.sub(r"[0-9a-f]{8,}", "<hex>", norm)
    norm = re.sub(r"\d+", "0", norm)
    return hashlib.sha256(f"{tool}|{norm}".encode()).hexdigest()[:12]


def audit_line(payload: dict, v: Verdict, mode: str) -> dict:
    return {
        "host": os.environ.get("HASHIMORI_HOST") or os.uname().nodename if hasattr(os, "uname") else None,
        "input_fp": input_fingerprint(payload.get("tool_name", ""), payload.get("tool_input") or {}),
        "ts": datetime.now(timezone.utc).isoformat(), "mode": mode,
        "session_id": payload.get("session_id"), "agent": payload.get("agent_type") or "main",
        "tool": payload.get("tool_name"), "tool_use_id": payload.get("tool_use_id"),
        "decision": v.decision, "reason": v.reason, "incident": v.incident,
        "agent_reason": v.agent_reason if v.agent_reason != v.reason else None,
        "price": v.price, "spent_before": v.spent_before,
        "red_zones": [h["id"] for h in v.red_zones], "factors": [f["id"] for f in v.factors],
        "unknown": v.unknown, "rewrite": v.rewrite, "judge": v.judge,
        "effects": [{k: e.get(k) for k in ("verb", "object", "surface", "sensitivity", "reversible",
                                           "blast", "tags")} for e in v.effects],
        "session_untrusted": bool(v.session.get("untrusted")),
        "session_sensitivity": v.session.get("max_sensitivity"),
        "timings_us": v.timings_us,
    }
