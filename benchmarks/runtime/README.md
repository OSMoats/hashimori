# Runtime benchmark

Measures what the runtime gate does to real commands and real risky code, on
public datasets, so you can check the claims in the README — and re-measure
after you change the policy or an adapter.

```bash
python3 benchmarks/runtime/fetch_datasets.py   # once: git + github.com; pinned commits → data/
python3 benchmarks/runtime/run_eval.py         # ~30 s → results/report.md, summary.json, CSVs
python3 benchmarks/runtime/run_eval.py --limit 200               # quick smoke run
HASHIMORI_JUDGE=http HASHIMORI_JUDGE_URL=… python3 benchmarks/runtime/run_eval.py --judge-sample 5
```

The datasets are not redistributed here; `fetch_datasets.py` pulls them from
their upstream repositories at the commits recorded in `data/MANIFEST.json`.

| Dataset | Rows | Used for | License |
|---|---:|---|---|
| [NL2Bash](https://github.com/TellinaTool/nl2bash) (Lin et al., LREC 2018) | 10,624 unique commands | friction: how often everyday shell work runs, asks or is denied; latency | GPL-3.0 |
| [RedCode-Exec](https://github.com/AI-secure/RedCode) (Guo et al., NeurIPS 2024 D&B) | 810 Python · 600 Bash | how often a risky program is stopped before it runs | CC BY 4.0 |
| [MBPP](https://github.com/google-research/google-research/tree/master/mbpp) (Austin et al., 2021) | 974 | false positives on benign Python, same flow | CC BY 4.0 |

## What is measured

- **NL2Bash** has no harm labels. A *deny* is a decision to read, not
  automatically a false positive; the report samples every outcome so you can.
  "No human needed" counts allow, rewrite and deny; "resolved by policy" also
  counts calls the policy priced as risky and sent to a human on purpose.
- **RedCode-Exec** programs run two ways: inline (`python3 -c`, or the Bash
  itself) and written to a file and then run. *Stopped* means the gate asked or
  denied before the code ran. Scenarios are grouped by the paper's own taxonomy
  (Table 4) into **action** (write, delete, exfiltrate, persist, kill, eval),
  **read-only** (reading or listing sensitive files) and **code-quality** (the
  paper's "buggy code" and bias scenarios). A tool-call gate is designed to stop
  actions; read-only access is recorded but allowed, and code quality is out of
  scope.
- **Held-out split.** RedCode scenarios 1–10 and half of NL2Bash (by a hash of
  the command) are the dev split used for error analysis; report the other half
  as the headline.
- **Ablation.** Each program is also run with script inspection turned off
  (`HASHIMORI_NO_CODE_INSPECT=1`), to show what reading a script before it runs
  adds.
- **Model judge (optional).** `--judge-sample N` sends N RedCode programs per
  scenario, and as many MBPP programs, to whichever judge adapter is configured.
  Calls are metered against the judge spend cap.

## Results at the time of the 0.3.0 release

Measured on Linux (x86_64, Python 3.11); decision
latency will differ on your machine.

| | Result |
|---|---|
| NL2Bash, no human needed | 77.2% (5.8% priced as risky → ask; 17.1% couldn't be parsed → ask; 1.2% denied) |
| NL2Bash held-out half, "couldn't tell → ask" | 16.5% (36.8% before error analysis on the dev half) |
| RedCode Python, written then run, **action** stopped | 90.0% (held-out 66.7%) |
| RedCode Bash, **action** stopped | 98.9% (held-out 96.7%) |
| MBPP false positives, written then run | 0 of 974 |
| Python written then run, script inspection **off** | 0% of actions stopped |
| Inline `python3 -c` | 100% of risky *and* 100% of benign asked — no discrimination |

Known misses are part of the result. On the held-out split, process kills
through `psutil` objects were stopped 0 of 30 times.
