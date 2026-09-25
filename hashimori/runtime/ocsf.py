"""Export decisions and fleet alerts as OCSF-shaped Detection Findings.

Shape follows OCSF's Detection Finding class (category_uid 2 "Findings",
class_uid 2004, type_uid 200401 = Create) as used by SIEM vendors. It is
OCSF-*shaped*: not validated against a specific schema release — check your
SIEM's OCSF version and adjust `metadata.version`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from hashimori import __version__

SEVERITY = {"ask": (3, "Medium"), "deny": (4, "High"), "campaign": (5, "Critical")}


def _ms(ts: str | None) -> int:
    try:
        return int(datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return int(datetime.now(timezone.utc).timestamp() * 1000)


def _base(uid: str, title: str, sev: tuple[int, str], ts: str | None, types: list[str]) -> dict:
    return {
        "category_uid": 2, "category_name": "Findings",
        "class_uid": 2004, "class_name": "Detection Finding",
        "activity_id": 1, "activity_name": "Create", "type_uid": 200401,
        "severity_id": sev[0], "severity": sev[1],
        "status_id": 1, "status": "New",
        "time": _ms(ts),
        "metadata": {"version": "1.5.0", "product": {"name": "Hashimori Runtime", "vendor_name": "Hashimori (OSS)",
                                                     "version": __version__}},
        "finding_info": {"uid": uid, "title": title, "types": types},
    }


def decision_to_ocsf(e: dict) -> dict | None:
    if e.get("decision") not in ("deny", "ask"):
        return None
    title = (e.get("reason") or "").split(". ")[0][:200]
    f = _base(e.get("incident") or e.get("tool_use_id") or "unknown", title, SEVERITY[e["decision"]], e.get("ts"),
              ["AI agent tool call", e["decision"]] + list(e.get("red_zones", [])))
    f["actor"] = {"session": {"uid": e.get("session_id")}, "app_name": e.get("agent")}
    f["device"] = {"hostname": e.get("host")}
    f["unmapped"] = {"tool": e.get("tool"), "input_fp": e.get("input_fp"), "price": e.get("price"),
                     "effects": e.get("effects"), "rules": e.get("red_zones", []) + e.get("factors", [])}
    return f


def alert_to_ocsf(a: dict) -> dict:
    title = f"Possible agent campaign: {a['sessions']} sessions on {a['hosts']} hosts blocked on the same {a['indicator']} ({a['value']})"
    f = _base(f"fleet-{a['indicator']}-{a['value']}"[:120], title, SEVERITY["campaign"], a.get("last_seen"),
              ["AI agent campaign", a["indicator"]])
    f["finding_info"]["first_seen_time"] = _ms(a.get("first_seen"))
    f["finding_info"]["last_seen_time"] = _ms(a.get("last_seen"))
    f["finding_info"]["related_events"] = [{"uid": i} for i in a.get("incidents", [])]
    f["count"] = a["events"]
    f["unmapped"] = {k: a.get(k) for k in ("rules", "allowed_elsewhere", "score")}
    return f


def to_jsonl(events: list[dict], alerts: list[dict]) -> str:
    rows = [x for x in (decision_to_ocsf(e) for e in events) if x] + [alert_to_ocsf(a) for a in alerts]
    return "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else "")
