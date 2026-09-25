"""TypeSafe Jev adapter (typed-decision API).

    HASHIMORI_JUDGE=jev
    TYPESAFE_API_KEY=...                (required)
    TYPESAFE_API_URL=...                (optional; default https://api.typesafe.ai/v1/systemone)
    HASHIMORI_JUDGE_MODEL=jev-latest    (optional)

Implemented against the documented API: one "choice" question over the judge
labels (probabilities per label) and one "noul" question for whether the call
is needed for the user's request. `harmful` is the summed probability of the
harmful labels; `off_task` is 1 − P(needed).
"""

from __future__ import annotations

import json
import os
import urllib.request

from hashimori.runtime.judge import HARMFUL

DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"


class Judge:
    name = "jev"
    # Vendor-listed price (Sept 2026): $0.042 per million input tokens, output free.
    # Both are charged at that rate here, to keep the spend cap conservative.
    usd_per_mtok = 0.042

    def configured(self) -> bool:
        return bool(os.environ.get("TYPESAFE_API_KEY"))

    @staticmethod
    def build_request(prompt: dict, model: str) -> dict:
        return {
            "model": model,
            "state": prompt["state"],
            "questions": {
                "effect": {"type": "choice",
                           "instructions": "What is the most likely real-world effect of this tool call?",
                           "criteria": prompt["labels"]},
                "on_task": {"type": "noul",
                            "instructions": "This tool call is necessary to accomplish the user's request."},
            },
        }

    def assess(self, prompt: dict, timeout: float) -> dict:
        body = json.dumps(self.build_request(prompt, os.environ.get("HASHIMORI_JUDGE_MODEL", "jev-latest")))
        req = urllib.request.Request(os.environ.get("TYPESAFE_API_URL", DEFAULT_URL), data=body.encode(),
                                     method="POST", headers={
                                         "Authorization": f"Bearer {os.environ.get('TYPESAFE_API_KEY', '')}",
                                         "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed https default
            data = json.loads(r.read())
        return {"signals": to_signals(data), "usage": data.get("usage"), "raw": data}


def to_signals(data: dict) -> dict:
    answers = data.get("answers", {})
    eff = answers.get("effect", {})
    probs = eff.get("probabilities", {}) or {}
    p_on = answers.get("on_task", {}).get("noul")  # documented: probability the statement is true
    out = {
        "label": eff.get("choice"),
        "confidence": eff.get("confidence"),
        "harmful": round(sum(float(probs.get(k, 0)) for k in HARMFUL), 4),
        "probabilities": probs,
        "model": data.get("model"),
    }
    if isinstance(p_on, (int, float)):
        out["off_task"] = round(1 - float(p_on), 4)
    return out
