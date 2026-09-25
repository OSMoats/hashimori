#!/usr/bin/env python3
"""Download the three public Hugging Face datasets used by the evaluation.

Standard library only — uses the Hugging Face dataset viewer API
(https://datasets-server.huggingface.co), 100 rows per request.

    python3 demo/eval/fetch_hf.py            # → demo/eval/data/*.jsonl

Datasets (not redistributed in this repo — each keeps its own license):
  jiacheng-ye/nl2bash        NL2Bash (Lin et al., LREC 2018): real-world bash one-liners
  google-research-datasets/mbpp   MBPP (Austin et al., 2021): benign Python programs
  monsoon-nlp/redcode-hf     community mirror of RedCode-Exec (Guo et al., NeurIPS 2024
                             D&B track): risky Python snippets. The official AI-Secure HF
                             repo is empty; the original is github.com/AI-secure/RedCode.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://datasets-server.huggingface.co"
OUT = Path(__file__).resolve().parent / "data"
DATASETS = {
    "nl2bash": "jiacheng-ye/nl2bash",
    "mbpp": "google-research-datasets/mbpp",
    "redcode_exec_python": "monsoon-nlp/redcode-hf",
}


def get(path, **params):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hashimori-eval"}),
                                        timeout=60) as r:
                return json.loads(r.read())
        except Exception as exc:  # retry politely on rate limits / hiccups
            if attempt == 4:
                raise
            print(f"   retry {attempt + 1} ({exc})", file=sys.stderr)
            time.sleep(2 * (attempt + 1))


def fetch(name, repo):
    splits = get("splits", dataset=repo)["splits"]
    if name == "mbpp":
        splits = [s for s in splits if s["config"] == "full"] or splits
    out = OUT / f"{name}.jsonl"
    n = 0
    with out.open("w") as fh:
        for s in splits:
            offset = 0
            while True:
                page = get("rows", dataset=repo, config=s["config"], split=s["split"], offset=offset, length=100)
                rows = page.get("rows", [])
                for r in rows:
                    fh.write(json.dumps({"_config": s["config"], "_split": s["split"], **r["row"]}) + "\n")
                n += len(rows)
                offset += len(rows)
                if not rows or offset >= page.get("num_rows_total", 0):
                    break
            print(f"   {repo} [{s['config']}/{s['split']}] done ({offset} rows)")
    print(f"✓ {name}: {n} rows → {out}")
    return n


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, repo in DATASETS.items():
        meta[name] = {"repo": repo, "rows": fetch(name, repo),
                      "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (OUT / "MANIFEST.json").write_text(json.dumps(meta, indent=2))
    print("\nDone. Now run:  python3 demo/eval/run_eval.py")


if __name__ == "__main__":
    main()
