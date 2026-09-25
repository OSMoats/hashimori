#!/usr/bin/env python3
"""Fetch the public datasets used by the runtime benchmark, at pinned commits.

    python3 benchmarks/runtime/fetch_datasets.py              # → benchmarks/runtime/data/
    python3 benchmarks/runtime/fetch_datasets.py --from DIR   # reuse existing clones in DIR

Needs `git` and network access to github.com. Standard library only. The data is
not redistributed in this repository; each dataset keeps its own license:

  NL2Bash      github.com/TellinaTool/nl2bash (Lin et al., LREC 2018) — GPL-3.0
               data/bash/all.{nl,cm}: 12,607 pairs → 10,624 unique commands
  RedCode-Exec github.com/AI-secure/RedCode (Guo et al., NeurIPS 2024 D&B) — CC BY 4.0
               dataset/RedCode-Exec: risky Python (27 scenarios) and Bash (20 scenarios)
  MBPP         github.com/google-research/google-research mbpp/ (Austin et al., 2021) — CC BY 4.0
               974 benign Python programs (used as the false-positive control)

Hugging Face hosts copies of some of these (jiacheng-ye/nl2bash is a 9,305-pair
split; monsoon-nlp/redcode-hf holds a Python subset). The benchmark uses the
upstream sources so every scenario, in both languages, is present.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data"

# Pinned upstream commits: the benchmark numbers in the README were produced from these.
SOURCES = {
    "nl2bash": ("https://github.com/TellinaTool/nl2bash.git",
                "d6b9f5bdff45621d190134e31ab63b7bf7002190", ["data/bash"]),
    "RedCode": ("https://github.com/AI-secure/RedCode.git",
                "c84b6db88fd8bd258e29f12e692ccfd4287a454d", ["dataset/RedCode-Exec"]),
    "google-research": ("https://github.com/google-research/google-research.git",
                        "d36068b845da4c2b24927fee2cea1e6ef98dadda", ["mbpp"]),
}


def _git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def checkout(name: str, root: Path) -> Path:
    """Shallow, sparse checkout of one pinned commit (google-research is huge)."""
    url, sha, paths = SOURCES[name]
    repo = root / name
    if (repo / ".git").exists():
        return repo
    repo.mkdir(parents=True)
    _git("init", "-q", cwd=repo)
    _git("remote", "add", "origin", url, cwd=repo)
    _git("sparse-checkout", "set", "--no-cone", *paths, cwd=repo)
    _git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", sha, cwd=repo)
    _git("checkout", "-q", "FETCH_HEAD", cwd=repo)
    return repo


def _num(p: Path) -> int:
    return int(re.search(r"index(\d+)_", p.name).group(1))


def build(src: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    counts = {}

    # NL2Bash: keep the first occurrence of each command.
    nl2 = src / "nl2bash" / "data" / "bash"
    nls = (nl2 / "all.nl").read_text().splitlines()
    cms = (nl2 / "all.cm").read_text().splitlines()
    seen, rows = set(), []
    for nl, cm in zip(nls, cms):
        if cm.strip() and cm not in seen:
            seen.add(cm)
            rows.append({"nl": nl, "bash": cm})
    counts["nl2bash"] = _write(out / "nl2bash.jsonl", rows)

    # RedCode-Exec: one file per scenario; tag each row with its scenario id.
    rc = src / "RedCode" / "dataset" / "RedCode-Exec"
    for lang, folder in (("python", "py2text_dataset_json"), ("bash", "bash2text_dataset_json")):
        rows = []
        for f in sorted((rc / folder).glob("index*_30_codes_full*.json"), key=_num):
            scenario = [{"_split": f"{lang}{_num(f)}", **r} for r in json.loads(f.read_text())]
            rows += sorted(scenario, key=lambda r: str(r.get("Index")))  # stable, documented order
        counts[f"redcode_exec_{lang}"] = _write(out / f"redcode_exec_{lang}.jsonl", rows)

    # MBPP: as published.
    mbpp = (src / "google-research" / "mbpp" / "mbpp.jsonl").read_text().splitlines()
    counts["mbpp"] = _write(out / "mbpp.jsonl", [json.loads(l) for l in mbpp if l.strip()])

    manifest = {name: {"repo": url, "commit": sha, "paths": paths} for name, (url, sha, paths) in SOURCES.items()}
    manifest["rows"] = counts
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return counts


def _write(path: Path, rows: list[dict]) -> int:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="src", help="directory that already holds the three clones")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    if args.src:
        src = Path(args.src)
    else:
        src = Path(tempfile.mkdtemp(prefix="hashimori-bench-"))
        for name in SOURCES:
            print(f"  fetching {name} @ {SOURCES[name][1][:7]} …", flush=True)
            try:
                checkout(name, src)
            except subprocess.CalledProcessError as exc:
                print(f"git failed for {name}: {exc.stderr.decode(errors='replace').strip()}", file=sys.stderr)
                return 1
    counts = build(src, Path(args.out))
    for k, v in counts.items():
        print(f"  {k:22} {v:>6,} rows")
    print(f"✓ {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
