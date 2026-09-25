#!/usr/bin/env python3
"""Slide-ready charts (1920×1080 SVG) from demo/eval/results/.

    python3 demo/eval/make_charts.py      → demo/eval/results/chart-*.svg

Needs summary.json (current run). If summary_blind_*.json is present, the
before→after chart compares the run made with code written before the data
was seen against the current one. Colours follow the deck brief; the four
decision colours were checked with a CVD/contrast validator (ochre is below 3:1
on paper, so every mark is directly labelled).
"""
import glob
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape as esc

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
W, H = 1920, 1080
BG, INK, MUTED, HAIR, TEAL, GRAY = "#F6F4EF", "#1E2329", "#5B6470", "#D8D2C6", "#1F6F6B", "#AEB4BA"
DEC = {"allow": "#3A8A4C", "rewrite": "#2A6DB0", "ask_price": "#C99A1E", "ask_unknown": "#C99A1E", "deny": "#9E3223"}
LABEL = {"allow": "Allowed", "rewrite": "Rewritten to reversible", "ask_price": "Asked a human · over price",
         "ask_unknown": "Asked a human · couldn't tell what it does", "deny": "Denied"}
FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
SCOPE = {**{i: "action" for i in (1, 2, 4, 6, 8, 9, 10, 14, 18, 21)},
         **{i: "read_only" for i in (3, 5, 7, 11, 13)},
         **{i: "quality" for i in (12, 15, 16, 17, 19, 20, 22, 23, 24, 25)}}


def num(s):
    return int("".join(c for c in s if c.isdigit()) or 0)


def svg(title, subtitle, body, source):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">'
            f'<rect width="{W}" height="{H}" fill="{BG}"/>'
            f'<text x="96" y="120" font-size="52" font-weight="700" fill="{INK}">{esc(title)}</text>'
            f'<text x="96" y="170" font-size="26" fill="{MUTED}">{esc(subtitle)}</text>'
            f'{body}<text x="96" y="{H - 44}" font-size="17" fill="{MUTED}">{esc(source)}</text></svg>')


def hbar(y, label, value, maxv, color, x0=780, width=880, h=46, valtext=None, lab_color=INK):
    w = max(3, width * (value / maxv if maxv else 0))
    return (f'<text x="{x0 - 24}" y="{y + h * 0.68}" font-size="24" fill="{lab_color}" text-anchor="end">{esc(label)}</text>'
            f'<rect x="{x0}" y="{y}" width="{w:.1f}" height="{h}" rx="4" fill="{color}"/>'
            f'<text x="{x0 + w + 14:.1f}" y="{y + h * 0.68}" font-size="24" font-weight="650" fill="{INK}">{esc(valtext or str(value))}</text>')


def chart_nl2bash(s):
    nb = s["nl2bash"]
    order = ["allow", "rewrite", "ask_price", "ask_unknown", "deny"]
    body, y = [], 250
    mx = max(nb["outcomes"].get(k, 0) for k in order) or 1
    for k in order:
        c = nb["outcomes"].get(k, 0)
        body.append(hbar(y, LABEL[k], c, mx, DEC[k], valtext=f"{c:,}  ·  {nb['outcomes_pct'].get(k, 0) or 0}%"))
        y += 84
    tiles = [(f"{nb['auto_decided_pct']}%", "decided without a human"),
             (f"{nb['latency_ms']['p50']:.2f} ms", "median decision time"),
             (f"{nb['latency_ms']['p99']:.2f} ms", "99th percentile")]
    for i, (big, small) in enumerate(tiles):
        x = 96 + i * 420
        body.append(f'<rect x="{x}" y="730" width="380" height="170" rx="16" fill="#FFFFFF" stroke="{HAIR}"/>'
                    f'<text x="{x + 28}" y="820" font-size="60" font-weight="700" fill="{TEAL}">{esc(big)}</text>'
                    f'<text x="{x + 28}" y="868" font-size="22" fill="{MUTED}">{esc(small)}</text>')
    body.append(f'<text x="1380" y="780" font-size="22" fill="{MUTED}">No harm labels in this corpus:</text>'
                f'<text x="1380" y="812" font-size="22" fill="{MUTED}">a denial is a decision to read,</text>'
                f'<text x="1380" y="844" font-size="22" fill="{MUTED}">not automatically a false positive.</text>')
    return svg(f"{nb['n']:,} real shell commands", "Everyday one-liners, each checked on its own with the default policy",
               "".join(body), f"Data: NL2Bash corpus (Lin et al., LREC 2018; HF jiacheng-ye/nl2bash is a split of it) · "
                              f"measured on {s['platform']}, Python {s['python']}")


def cls(by_scn, c, test_only=False):
    vals = [v for k, v in by_scn.items() if SCOPE.get(num(k)) == c and (not test_only or num(k) > 10)]
    return round(sum(vals) / len(vals), 1) if vals else None


def chart_before_after(s, blind):
    nb_b = blind["nl2bash"]
    # NL2Bash held-out half, blind value computed from its outcomes if split missing
    after_unknown = s["nl2bash"]["split"]["test"]["outcomes_pct"]["ask_unknown"]
    before_unknown = blind.get("_test_unknown", nb_b["outcomes_pct"].get("ask_unknown"))
    pb = blind["programs"]["v0.2.1 (script inspection)"]
    pa = s["programs"]["v0.2.1 (script inspection)"]
    rows = [
        ("Everyday commands: needs a human because the gate couldn't tell", before_unknown, after_unknown, "lower is better", "held-out half"),
        ("Risky bash actions stopped", cls(pb["bash"]["inline"]["redcode_by_scenario"], "action", True),
         cls(pa["bash"]["inline"]["redcode_by_scenario"], "action", True), "higher is better", "held-out 14, 18, 21"),
        ("Risky Python actions stopped (write, then run)", cls(pb["python"]["file"]["redcode_by_scenario"], "action", True),
         cls(pa["python"]["file"]["redcode_by_scenario"], "action", True), "higher is better", "held-out 14, 18, 21"),
        ("Bash read-only scripts \"stopped\"", cls(pb["bash"]["inline"]["redcode_by_scenario"], "read_only"),
         cls(pa["bash"]["inline"]["redcode_by_scenario"], "read_only"), "was confusion, not detection", "all"),
        ("Benign Python programs stopped (MBPP)", pb["python"]["file"]["mbpp_false_positive_pct"],
         pa["python"]["file"]["mbpp_false_positive_pct"], "lower is better", "974 programs"),
    ]
    x0, x1 = 820, 1760
    body = [f'<line x1="{x0}" x2="{x0}" y1="230" y2="880" stroke="{HAIR}"/>',
            f'<line x1="{x1}" x2="{x1}" y1="230" y2="880" stroke="{HAIR}"/>',
            f'<text x="{x0}" y="906" font-size="18" fill="{MUTED}" text-anchor="middle">0%</text>',
            f'<text x="{x1}" y="906" font-size="18" fill="{MUTED}" text-anchor="middle">100%</text>']
    y = 280
    for label, b, a, note, split in rows:
        bx = x0 + (x1 - x0) * (b or 0) / 100
        ax = x0 + (x1 - x0) * (a or 0) / 100
        body.append(f'<text x="{x0 - 30}" y="{y + 6}" font-size="23" fill="{INK}" text-anchor="end">{esc(label)}</text>'
                    f'<text x="{x0 - 30}" y="{y + 36}" font-size="17" fill="{MUTED}" text-anchor="end">{esc(split)} · {esc(note)}</text>'
                    f'<line x1="{min(ax, bx)}" x2="{max(ax, bx)}" y1="{y}" y2="{y}" stroke="{GRAY}" stroke-width="4"/>'
                    f'<circle cx="{bx}" cy="{y}" r="11" fill="{GRAY}" stroke="{BG}" stroke-width="2"/>'
                    f'<circle cx="{ax}" cy="{y}" r="13" fill="{TEAL}" stroke="{BG}" stroke-width="2"/>'
                    f'<text x="{bx}" y="{y - 22}" font-size="18" fill="{MUTED}" text-anchor="middle">{b:g}%</text>'
                    f'<text x="{ax}" y="{y + 42}" font-size="21" font-weight="700" fill="{TEAL}" text-anchor="middle">{a:g}%</text>')
        y += 128
    body.append(f'<circle cx="96" cy="946" r="9" fill="{GRAY}"/><text x="114" y="952" font-size="20" fill="{MUTED}">code written before seeing the data</text>'
                f'<circle cx="520" cy="946" r="10" fill="{TEAL}"/><text x="538" y="952" font-size="20" fill="{MUTED}">after one night of error analysis on the dev split only</text>')
    return svg("Blind run → error analysis → re-measure", "Fixes were made on dev data only; the numbers that matter are the held-out ones",
               "".join(body), "Data: RedCode-Exec (Guo et al., NeurIPS 2024; CC BY 4.0) · MBPP (Austin et al., 2021) · NL2Bash (Lin et al., 2018). "
                              "An intermediate build flagged 1 of 974 MBPP programs (str.replace read as a file rename); that case informed the fix.")


def chart_classes(s):
    pa = s["programs"]["v0.2.1 (script inspection)"]
    rows = []
    for lang, mode, name in (("python", "file", "Python · write, then run"), ("bash", "inline", "Bash · run as a command")):
        bc = pa[lang][mode]["by_class"]
        rows.append((name, bc["action"]["stopped_pct"], bc["read_only"]["stopped_pct"], bc["read_only"]["visible_pct"],
                     bc["quality"]["stopped_pct"]))
    body = []
    heads = [("Actions stopped", 1, TEAL), ("Read-only stopped", 2, GRAY), ("Read-only visible in audit", 3, TEAL),
             ("Code-quality 'stopped'", 4, GRAY)]
    y = 250
    for name, *vals in rows:
        body.append(f'<text x="96" y="{y}" font-size="30" font-weight="650" fill="{INK}">{esc(name)}</text>')
        y += 30
        for (h, i, col) in heads:
            body.append(hbar(y, h, vals[i - 1] or 0, 100, col, x0=560, width=900, h=40, valtext=f"{vals[i - 1]}%"))
            y += 56
        y += 50
    body.append(f'<text x="96" y="{y + 10}" font-size="21" fill="{MUTED}">Actions = the paper\'s file, network, OS and eval-injection scenarios. '
                f'Read-only = read or list only: allowed by design, recorded. Code-quality = scenarios the paper marks "buggy code":</text>'
                f'<text x="96" y="{y + 40}" font-size="21" fill="{MUTED}">out of scope for a tool-call gate. Bash scores high there only because the gate asks about shell syntax it can\'t parse — friction, not detection.</text>')
    return svg("What a tool-call gate can and can't see", "RedCode-Exec risky programs by the paper's own risk classes",
               "".join(body), "Data: RedCode-Exec (Guo et al., NeurIPS 2024 D&B; github.com/AI-secure/RedCode, CC BY 4.0) · classes from the paper's Table 4")


def main():
    s = json.loads((RES / "summary.json").read_text())
    out = []
    (RES / "chart-nl2bash.svg").write_text(chart_nl2bash(s)); out.append("chart-nl2bash.svg")
    (RES / "chart-classes.svg").write_text(chart_classes(s)); out.append("chart-classes.svg")
    blinds = sorted(glob.glob(str(RES / "summary_blind_*.json")))
    if blinds:
        blind = json.loads(Path(blinds[-1]).read_text())
        csvp = RES / "nl2bash_decisions_blind.csv"
        if csvp.exists():
            import csv
            import zlib
            rows = [r for r in csv.DictReader(open(csvp)) if zlib.crc32(r["bash"].encode()) % 2 == 1]
            blind["_test_unknown"] = round(100 * sum(r["outcome"] == "ask_unknown" for r in rows) / len(rows), 1)
        (RES / "chart-before-after.svg").write_text(chart_before_after(s, blind)); out.append("chart-before-after.svg")
    print("wrote", ", ".join(out))


if __name__ == "__main__":
    sys.exit(main())
