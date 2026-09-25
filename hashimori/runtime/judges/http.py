"""Generic HTTP judge: ask a service you run.

Use it to put any model behind the judge — a local model, your own gateway, or
a hosted API — with a small shim that speaks this contract.

    HASHIMORI_JUDGE=http
    HASHIMORI_JUDGE_URL=http://127.0.0.1:9000/judge     (required; http or https)
    HASHIMORI_JUDGE_TOKEN=...                           (optional; sent as a Bearer token)
    HASHIMORI_JUDGE_USD_PER_MTOK=0                      (optional; for the spend cap)

Request (POST, JSON): the adapter-neutral prompt, already redacted —
    {"tool": "Bash", "call": "...", "user_request": "...",
     "labels": {"routine": "...", "destructive": "...", ...},
     "harmful_labels": ["destructive", "exfiltration", ...], "state": "..."}

Response (JSON):
    {"harmful": 0.0-1.0,            required — probability the call is harmful
     "off_task": 0.0-1.0,           optional — probability it isn't needed for the request
     "label": "exfiltration",       optional
     "confidence": 0.7,             optional
     "model": "my-model-1",         optional
     "usage": {"input_tokens": 0, "output_tokens": 0}}   optional

Anything else — a timeout, a non-2xx status, a missing `harmful` — is treated as
no signal, and the gate fails closed.
"""

from __future__ import annotations

import json
import os
import urllib.request
from urllib.parse import urlparse


class Judge:
    name = "http"

    def __init__(self) -> None:
        self.usd_per_mtok = 0.0

    @staticmethod
    def _url() -> str:
        return os.environ.get("HASHIMORI_JUDGE_URL", "").strip()

    def configured(self) -> bool:
        return urlparse(self._url()).scheme in ("http", "https")

    def assess(self, prompt: dict, timeout: float) -> dict:
        url = self._url()
        if urlparse(url).scheme not in ("http", "https"):
            raise ValueError("HASHIMORI_JUDGE_URL must be an http(s) URL")
        headers = {"Content-Type": "application/json"}
        if os.environ.get("HASHIMORI_JUDGE_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['HASHIMORI_JUDGE_TOKEN']}"
        req = urllib.request.Request(url, data=json.dumps(prompt).encode(), method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — scheme checked above
            data = json.loads(r.read())
        return {"signals": data, "usage": data.get("usage"), "raw": data}
