"""LEARN, across agents: the fleet is the sensor.

One agent's denial is noise. The same destination, rule, or request fingerprint
showing up in denials across many independent sessions — and hosts — is a
campaign: someone planted the same injection where many agents will read it.

    hashimori fleet ~/agents/*/.hashimori/audit.jsonl

The most useful line in the output is often the one about ALLOWED traffic: a
destination that many sessions were blocked from reaching, but that some session
was allowed to reach (a clean session, a different envelope). That's where to look.

Prior art: cross-agent campaign attribution on tool-use style (arXiv 2607.18826)
and in-the-wild injection telemetry (Unit 42, Mar 2026). Correlating the
enforcement point's own deny/ask events by destination and request fingerprint
is the angle here.
"""

from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def _dest(obj: str) -> str:
    obj = (obj or "").lower().lstrip("*.").strip()
    if obj.startswith("chat:"):
        return obj
    parts = obj.split(".")
    if len(parts) > 2 and not obj.replace(".", "").isdigit():
        return ".".join(parts[-2:])  # registrable-ish: sub.evil.example → evil.example
    return obj


def _ts(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def load(paths: list[str]) -> list[dict]:
    files: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            files += [str(x) for x in Path(p).rglob("audit.jsonl")]   # includes hidden .hashimori/
        else:
            files += glob.glob(p)
    events = []
    for f in sorted(set(files)):
        host_guess = Path(f).parent.parent.name or Path(f).parent.name
        for line in Path(f).read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "decision" not in r:
                continue
            r.setdefault("host", host_guess)
            r["_file"] = f
            events.append(r)
    return events


def analyze(events: list[dict], min_sessions: int = 3, window_hours: float = 24.0,
            ignore: tuple[str, ...] = ("package-registry", "git-remote")) -> dict:
    blocked = defaultdict(list)     # indicator → events that were denied/asked
    allowed_dest = defaultdict(list)
    for e in events:
        dests = {_dest(x.get("object", "")) for x in e.get("effects", []) if x.get("verb") == "egress"}
        dests = {d for d in dests if d and d not in ignore and not d.startswith("<")}
        if e["decision"] in ("deny", "ask"):
            for d in dests:
                blocked[("destination", d)].append(e)
        if e["decision"] == "deny":
            for rz in e.get("red_zones", []):
                blocked[("rule", rz)].append(e)
            if e.get("input_fp"):
                blocked[("request", e["input_fp"])].append(e)
        elif e["decision"] == "allow":
            for d in dests:
                allowed_dest[d].append(e)

    alerts = []
    for (kind, value), evs in blocked.items():
        evs = sorted(evs, key=lambda x: x.get("ts") or "")
        # sliding window: the densest window of `window_hours`
        best = []
        times = [_ts(x.get("ts")) for x in evs]
        for i, t0 in enumerate(times):
            if t0 is None:
                continue
            win = [x for x, t in zip(evs, times) if t and t0 <= t <= t0 + timedelta(hours=window_hours)]
            if len({x.get("session_id") for x in win}) > len({x.get("session_id") for x in best}):
                best = win
        sessions = {x.get("session_id") for x in best}
        hosts = {x.get("host") for x in best}
        if len(sessions) < min_sessions or kind == "rule" and len(hosts) < 2:
            continue
        tainted = sum(1 for x in best if x.get("session_untrusted"))
        alert = {
            "indicator": kind, "value": value,
            # Injection-shaped: most of these sessions had read untrusted content before being blocked.
            "kind": "campaign" if tainted * 2 >= len(best) else "recurring",
            "untrusted_share": round(tainted / len(best), 2),
            "sessions": len(sessions), "hosts": len(hosts), "events": len(best),
            "first_seen": best[0].get("ts"), "last_seen": best[-1].get("ts"),
            "rules": sorted({r for x in best for r in x.get("red_zones", [])}),
            "incidents": [x.get("incident") for x in best if x.get("incident")][:8],
            "incidents_all": [x.get("incident") for x in best if x.get("incident")],
            "score": len(sessions) * (1 + len(hosts)),
        }
        if kind == "destination":
            ok = allowed_dest.get(value, [])
            alert["allowed_elsewhere"] = [{"session_id": x.get("session_id"), "host": x.get("host"),
                                           "ts": x.get("ts"), "tool": x.get("tool")} for x in ok][:10]
        alerts.append(alert)
    order = {"destination": 0, "request": 1, "rule": 2}
    alerts.sort(key=lambda a: (a["kind"] != "campaign", -a["score"], order[a["indicator"]]))
    # collapse alerts that describe the same events as a stronger one
    kept: list[dict] = []
    for a in alerts:
        inc = set(a["incidents"])
        if any(inc and inc <= set(k["incidents_all"]) for k in kept):
            continue
        kept.append(a)
    alerts = kept
    return {"events": len(events), "sessions": len({e.get("session_id") for e in events}),
            "hosts": len({e.get("host") for e in events}),
            "blocked_events": sum(1 for e in events if e["decision"] in ("deny", "ask")),
            "alerts": alerts, "params": {"min_sessions": min_sessions, "window_hours": window_hours}}


def render(report: dict, color: bool = True) -> str:
    R, B, D, RED, YEL = ("\033[0m", "\033[1m", "\033[2m", "\033[31m", "\033[33m") if color else ("",) * 5
    L = ["", f"  {B}🌉 hashimori fleet{R}  {report['events']:,} decisions · {report['sessions']} sessions · "
             f"{report['hosts']} hosts · {report['blocked_events']} blocked or escalated", ""]
    if not report["alerts"]:
        L.append(f"  {D}no campaign-shaped patterns (min {report['params']['min_sessions']} sessions){R}")
    for a in report["alerts"][:10]:
        label = {"destination": "same destination", "request": "same request", "rule": "same rule"}[a["indicator"]]
        if a["kind"] == "campaign":
            L.append(f"  {RED}● CAMPAIGN{R}  {B}{label}: {a['value']}{R}  "
                     f"{D}(injection-shaped: {int(a['untrusted_share'] * 100)}% of sessions had read untrusted input){R}")
        else:
            L.append(f"  {YEL}○ RECURRING{R}  {B}{label}: {a['value']}{R}  {D}(policy friction, not injection-shaped){R}")
        L.append(f"     {a['sessions']} sessions on {a['hosts']} hosts · {a['events']} events · "
                 f"{a['first_seen'][:19]} → {a['last_seen'][:19]}")
        if a["rules"]:
            L.append(f"     rules: {', '.join(a['rules'])}")
        if a.get("allowed_elsewhere"):
            s = a["allowed_elsewhere"][0]
            L.append(f"     {YEL}⚠ allowed elsewhere:{R} {len(a['allowed_elsewhere'])} call(s), e.g. session "
                     f"{s['session_id']} on {s['host']} ({s['tool']}) — investigate this one")
        L.append(f"     {D}incidents: {', '.join(a['incidents'][:5])}{R}")
        L.append("")
    return "\n".join(L)
