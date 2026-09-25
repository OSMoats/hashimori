#!/usr/bin/env python3
"""Slide-ready charts (1920×1080 SVG) from demo/eval/results/summary.json.

    python3 demo/eval/make_charts.py   → demo/eval/results/chart-*.svg
Colours match the deck brief; the four decision colours were checked with a
CVD/contrast validator (ochre is below 3:1 on paper, so every bar is directly
labelled).
"""
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape as esc

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
W, H = 1920, 1080
BG, INK, MUTED, HAIR, TEAL, GRAY = "#F6F4EF", "#1E2329", "#5B6470", "#D8D2C6", "#1F6F6B", "#B9BEC4"
DEC = {"allow": "#3A8A4C", "rewrite": "#2A6DB0", "ask_price": "#C99A1E", "ask_unknown": "#C99A1E", "deny": "#9E3223"}
LABEL = {"allow": "Allowed", "rewrite": "Rewritten to reversible", "ask_price": "Asked a human · over price",
         "ask_unknown": "Asked a human · couldn't tell what it does", "deny": "Denied"}
FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"


def svg(title, subtitle, body, source):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">'
            f'<rect width="{W}" height="{H}" fill="{BG}"/>'
            f'<text x="96" y="120" font-size="52" font-weight="700" fill="{INK}">{esc(title)}</text>'
            f'<text x="96" y="170" font-size="26" fill="{MUTED}">{esc(subtitle)}</text>'
            f'{body}'
            f'<text x="96" y="{H-48}" font-size="17" fill="{MUTED}">{esc(source)}</text></svg>')


def hbar(y, label, value, maxv, color, x0=760, width=900, h=46, valtext=None, lab_color=INK):
    w = max(3, width * (value / maxv if maxv else 0))
    return (f'<text x="{x0-24}" y="{y+h*0.68}" font-size="24" fill="{lab_color}" text-anchor="end">{esc(label)}</text>'
            f'<rect x="{x0}" y="{y}" width="{w:.1f}" height="{h}" rx="4" fill="{color}"/>'
            f'<text x="{x0+w+14:.1f}" y="{y+h*0.68}" font-size="24" font-weight="650" fill="{INK}">{esc(valtext or str(value))}</text>')


def chart_nl2bash(s):
    nb = s["nl2bash"]
    order = ["allow", "rewrite", "ask_price", "ask_unknown", "deny"]
    n = nb["n"]
    body, y = [], 260
    mx = max(nb["outcomes"].get(k, 0) for k in order) or 1
    for k in order:
        c = nb["outcomes"].get(k, 0)
        body.append(hbar(y, LABEL[k], c, mx, DEC[k], valtext=f"{c:,}  ·  {nb['outcomes_pct'].get(k, 0) or 0}%"))
        y += 84
    # stat tiles
    tiles = [(f"{nb['auto_decided_pct']}%", "decided without a human"),
             (f"{nb['latency_ms']['p50']} ms", "median decision time"),
             (f"{nb['latency_ms']['p99']} ms", "99th percentile")]
    for i, (big, small) in enumerate(tiles):
        x = 96 + i * 420
        body.append(f'<rect x="{x}" y="740" width="380" height="170" rx="16" fill="#FFFFFF" stroke="{HAIR}"/>'
                    f'<text x="{x+28}" y="830" font-size="60" font-weight="700" fill="{TEAL}">{esc(big)}</text>'
                    f'<text x="{x+28}" y="878" font-size="22" fill="{MUTED}">{esc(small)}</text>')
    body.append(f'<text x="1380" y="790" font-size="22" fill="{MUTED}">No harm labels in this dataset:</text>'
                f'<text x="1380" y="822" font-size="22" fill="{MUTED}">a denial is a decision to read,</text>'
                f'<text x="1380" y="854" font-size="22" fill="{MUTED}">not automatically a false positive.</text>')
    return svg(f"{n:,} real shell commands", "Everyday one-liners, each evaluated on its own with the default policy",
               "".join(body), f"Data: NL2Bash (Lin et al., LREC 2018), Hugging Face jiacheng-ye/nl2bash · measured on {s['platform']}, Python {s['python']}")


def chart_programs(s):
    pr = s["programs"]
    rows = [("Tool review only (static allowlist)", 0.0, 0.0, False)]
    for cname, modes in pr.items():
        short = "No script inspection" if "no inspection" in cname else "Script inspection"
        rows.append((f"{short} · write file, then run", modes["file"]["redcode_stopped_pct_test_11_21"],
                     modes["file"]["mbpp_false_positive_pct"], "inspection" in cname and "no" not in cname))
    inline = pr[list(pr)[-1]]["inline"]
    rows.append(("Either · inline python -c", inline["redcode_stopped_pct_test_11_21"], inline["mbpp_false_positive_pct"], False))
    body = [f'<text x="760" y="250" font-size="24" font-weight="650" fill="{INK}">Risky programs stopped (RedCode, held-out scenarios 11–21)</text>',
            f'<text x="760" y="610" font-size="24" font-weight="650" fill="{INK}">Benign programs stopped (MBPP) — false positives</text>']
    y = 280
    for label, stop, fp, hero in rows:
        body.append(hbar(y, label, stop, 100, TEAL if hero else GRAY, width=820, h=42, valtext=f"{stop}%"))
        y += 70
    y = 640
    for label, stop, fp, hero in rows:
        body.append(hbar(y, label, fp, 100, TEAL if hero else GRAY, width=820, h=42, valtext=f"{fp}%"))
        y += 70
    return svg("Same programs, three kinds of guard", "Stopped = denied or sent to a human. Higher is better on top, lower is better below.",
               "".join(body), "Data: RedCode-Exec Python (Guo et al., NeurIPS 2024; HF mirror monsoon-nlp/redcode-hf) · MBPP (Austin et al., 2021; google-research-datasets/mbpp)")


def chart_scenarios(s):
    best = s["programs"][[k for k in s["programs"] if "no inspection" not in k][0]]["file"]["redcode_by_scenario"]
    labels = s.get("scenario_labels", {})
    items = list(best.items())
    body, y = [], 220
    h = min(34, int(760 / max(1, len(items))) - 6)
    for scn, rate in items:
        num = int("".join(ch for ch in scn if ch.isdigit()) or 0)
        test = num > 10
        lab = f"{num:>2} · {labels.get(scn, '')[:62]}"
        body.append(hbar(y, lab, rate or 0, 100, TEAL if test else GRAY, x0=1080, width=640, h=h,
                         valtext=f"{rate}%", lab_color=INK if test else MUTED))
        y += h + 6
    body.append(f'<rect x="1080" y="{y+14}" width="18" height="18" rx="3" fill="{TEAL}"/><text x="1106" y="{y+30}" font-size="20" fill="{MUTED}">held-out test scenarios (11–21)</text>'
                f'<rect x="1440" y="{y+14}" width="18" height="18" rx="3" fill="{GRAY}"/><text x="1466" y="{y+30}" font-size="20" fill="{MUTED}">dev scenarios (1–10)</text>')
    return svg("Where script inspection helps — and where it can't", "Write-then-run, per RedCode scenario (labels are the dataset's own summaries)",
               "".join(body), "Some scenarios are code-quality risks with no side effect a tool-call gate can see. Data: RedCode-Exec Python via monsoon-nlp/redcode-hf")


def main():
    s = json.loads((RES / "summary.json").read_text())
    out = []
    if "nl2bash" in s:
        (RES / "chart-nl2bash.svg").write_text(chart_nl2bash(s)); out.append("chart-nl2bash.svg")
    if "programs" in s:
        (RES / "chart-programs.svg").write_text(chart_programs(s)); out.append("chart-programs.svg")
        (RES / "chart-scenarios.svg").write_text(chart_scenarios(s)); out.append("chart-scenarios.svg")
    print("wrote", ", ".join(out))


if __name__ == "__main__":
    sys.exit(main())
