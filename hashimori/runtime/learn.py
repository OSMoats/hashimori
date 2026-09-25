"""LEARN — shadow mode → a proposed least-privilege envelope ("audit2allow for agents").

Run the hook with HASHIMORI_MODE=shadow for a while. Every call is lifted to
effects and logged, nothing is blocked. `hashimori learn` then proposes the
envelope that *would have* allowed what you observed: egress destinations,
write roots, and tools in use — and flags what it refuses to learn.

The known risk: if an attacker was active during observation, their behaviour
becomes your baseline. So learn() never proposes anything a red zone fired on,
and it reports those separately for a human.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path


def learn(audit_path: str | Path, min_count: int = 1) -> dict:
    egress, writes, tools, refused = Counter(), Counter(), Counter(), []
    n = 0
    for line in Path(audit_path).read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("event") == "post" or "effects" not in rec:
            continue
        n += 1
        tools[rec.get("tool")] += 1
        if rec.get("red_zones"):
            refused.append({"tool": rec.get("tool"), "red_zones": rec["red_zones"],
                            "objects": [e.get("object") for e in rec["effects"]]})
            continue
        for e in rec["effects"]:
            if e.get("verb") == "egress":
                egress[e.get("object")] += 1
            elif e.get("verb") in ("write", "delete") and e.get("object", "").startswith("/"):
                writes[os.path.dirname(e["object"])] += 1
    return {
        "observed_calls": n,
        "proposed_envelope": {
            "allowed_egress": sorted(k for k, c in egress.items() if c >= min_count and "*" not in k),
            "write_roots": sorted(k for k, c in writes.items() if c >= min_count),
        },
        "tools_seen": dict(tools.most_common()),
        "refused_to_learn": refused,
        "warning": ("Learned from observed behaviour. Anything an attacker did during the observation "
                    "window is in here unless a red zone caught it — review before adopting."),
    }
