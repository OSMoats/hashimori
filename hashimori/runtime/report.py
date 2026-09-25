"""`hashimori report`: a self-contained HTML "gatehouse" view of audit logs.

One file, no server, no network: open it in a browser. Shows the decision mix,
campaign alerts from the fleet sensor, a per-host timeline of every decision,
the rules that fired most, and the latest incidents (with their incident ids,
which is what an agent sees when HASHIMORI_AGENT_MESSAGES=minimal).
"""

from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime

DEC_COLOR = {"allow": "var(--allow)", "ask": "var(--ask)", "deny": "var(--deny)", "rewrite": "var(--rewrite)"}


def _t(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _outcome(e):
    return "rewrite" if e.get("decision") == "allow" and e.get("rewrite") else e.get("decision")


def build_html(events: list[dict], fleet: dict, title: str = "Gatehouse") -> str:
    esc = html.escape
    n = len(events)
    mix = Counter(_outcome(e) for e in events)
    hosts = sorted({e.get("host") or "?" for e in events})
    sessions = {e.get("session_id") for e in events}
    rules = Counter(r for e in events for r in e.get("red_zones", []))
    times = [t for t in (_t(e.get("ts")) for e in events) if t]
    t0, t1 = (min(times), max(times)) if times else (None, None)
    span = max(1.0, (t1 - t0).total_seconds()) if times else 1.0

    # decision mix bar
    bar, x = [], 0.0
    for k in ("allow", "rewrite", "ask", "deny"):
        w = 100.0 * mix.get(k, 0) / max(1, n)
        if w:
            bar.append(f'<div class="seg" style="width:{w:.2f}%;background:{DEC_COLOR[k]}" '
                       f'title="{k}: {mix.get(k, 0)} ({w:.1f}%)"></div>')
    legend = "".join(f'<span class="lg"><i style="background:{DEC_COLOR[k]}"></i>{k} <b>{mix.get(k, 0):,}</b></span>'
                     for k in ("allow", "rewrite", "ask", "deny"))

    # timeline: one row per host
    W, rowh, pad = 1000, 34, 130
    alert_incidents = {i for a in fleet.get("alerts", []) if a.get("kind") == "campaign" for i in a.get("incidents_all", [])}
    svg = [f'<svg viewBox="0 0 {W + pad + 20} {rowh * len(hosts) + 40}" class="tl" role="img" '
           f'aria-label="Decisions over time per host">']
    for i, h in enumerate(hosts):
        y = 20 + i * rowh
        svg.append(f'<text x="{pad - 12}" y="{y + 5}" text-anchor="end" class="axis">{esc(h)}</text>'
                   f'<line x1="{pad}" x2="{pad + W}" y1="{y}" y2="{y}" class="grid"/>')
        for e in events:
            if (e.get("host") or "?") != h:
                continue
            t = _t(e.get("ts"))
            if not t:
                continue
            cx = pad + W * (t - t0).total_seconds() / span
            o = _outcome(e)
            r = 6 if o in ("deny", "ask") else 3.5
            ring = ' class="hot"' if e.get("incident") in alert_incidents else ""
            tip = f"{e.get('ts', '')[11:19]} · {e.get('session_id')} · {e.get('tool')} · {o}" + \
                  (f" · {', '.join(e.get('red_zones', []))}" if e.get("red_zones") else "")
            svg.append(f'<circle cx="{cx:.1f}" cy="{y}" r="{r}" fill="{DEC_COLOR.get(o, "gray")}"{ring}>'
                       f'<title>{esc(tip)}</title></circle>')
    if times:
        svg.append(f'<text x="{pad}" y="{rowh * len(hosts) + 34}" class="axis">{t0.strftime("%H:%M")}</text>'
                   f'<text x="{pad + W}" y="{rowh * len(hosts) + 34}" class="axis" text-anchor="end">{t1.strftime("%H:%M")} UTC</text>')
    svg.append("</svg>")

    # alerts
    cards = []
    for a in fleet.get("alerts", [])[:6]:
        label = {"destination": "Same destination", "request": "Same request", "rule": "Same rule"}[a["indicator"]]
        kind = "Campaign · injection-shaped" if a["kind"] == "campaign" else "Recurring · policy friction"
        allowed = ""
        if a.get("allowed_elsewhere"):
            s = a["allowed_elsewhere"][0]
            allowed = (f'<p class="warn">Allowed elsewhere: {len(a["allowed_elsewhere"])} call(s) — e.g. '
                       f'<code>{esc(str(s["session_id"]))}</code> on <code>{esc(str(s["host"]))}</code>. Investigate this one.</p>')
        cards.append(f'''<article class="card {a['kind']}"><div class="kind">{kind}</div>
<h3>{label}: <code>{esc(str(a['value']))}</code></h3>
<p>{a['sessions']} sessions · {a['hosts']} hosts · {a['events']} events · {esc(str(a['first_seen'])[11:16])}–{esc(str(a['last_seen'])[11:16])}</p>
<p class="muted">{esc(', '.join(a['rules']) or '—')} · incidents {esc(', '.join(a['incidents'][:4]))}</p>{allowed}</article>''')

    rules_rows = "".join(f"<tr><td><code>{esc(r)}</code></td><td class='num'>{c:,}</td></tr>" for r, c in rules.most_common(10))
    recent = [e for e in sorted(events, key=lambda e: e.get("ts") or "", reverse=True) if e.get("decision") in ("deny", "ask")][:14]
    inc_rows = "".join(
        f"<tr><td><code>{esc(e.get('incident') or '')}</code></td><td>{esc((e.get('ts') or '')[11:19])}</td>"
        f"<td>{esc(str(e.get('host')))}</td><td>{esc(str(e.get('session_id')))}</td>"
        f"<td><span class='chip' style='background:{DEC_COLOR[_outcome(e)]}'>{esc(_outcome(e))}</span></td>"
        f"<td>{esc((e.get('reason') or '')[:120])}</td></tr>" for e in recent)

    data = json.dumps({"n": n, "mix": dict(mix), "alerts": len(fleet.get("alerts", []))})
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<style>
:root{{--bg:#F6F4EF;--panel:#fff;--ink:#1E2329;--muted:#5B6470;--hair:#D8D2C6;--teal:#1F6F6B;
--allow:#3A8A4C;--rewrite:#2A6DB0;--ask:#C99A1E;--deny:#9E3223}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16191D;--panel:#1F2328;--ink:#E8E6E1;--muted:#9AA3AD;--hair:#343A41;
--teal:#5FB3AB;--allow:#5DAE6E;--rewrite:#5B97D6;--ask:#D8AE3F;--deny:#D0614F}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,"Helvetica Neue",Arial,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:32px 16px 64px}}h1{{font-size:30px;margin:0 0 4px}}h2{{font-size:18px;margin:32px 0 12px}}
.sub,.muted{{color:var(--muted)}}.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:20px 0}}
.kpi{{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:14px 16px}}.kpi b{{display:block;font-size:28px;color:var(--teal)}}
.bar{{display:flex;height:22px;border-radius:6px;overflow:hidden;gap:2px;background:var(--bg)}}.seg{{height:100%}}
.lg{{margin-right:18px;color:var(--muted)}}.lg i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}}.lg b{{color:var(--ink)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}
.card{{background:var(--panel);border:1px solid var(--hair);border-left:4px solid var(--ask);border-radius:12px;padding:14px 16px}}
.card.campaign{{border-left-color:var(--deny)}}.card h3{{margin:4px 0;font-size:16px}}.card p{{margin:4px 0}}
.kind{{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}}.warn{{color:var(--ask)}}
.panel{{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:12px;overflow-x:auto}}
.tl{{width:100%;min-width:640px;height:auto}}.tl .axis{{fill:var(--muted);font-size:12px}}.tl .grid{{stroke:var(--hair)}}
.tl circle{{stroke:var(--panel);stroke-width:1.5}}.tl circle.hot{{stroke:var(--deny);stroke-width:3}}
table{{width:100%;border-collapse:collapse}}td,th{{padding:6px 8px;border-bottom:1px solid var(--hair);text-align:left;vertical-align:top}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}code{{font:13px "JetBrains Mono",Menlo,monospace}}
.chip{{color:#fff;border-radius:10px;padding:1px 8px;font-size:12px}}.two{{display:grid;grid-template-columns:1fr 2fr;gap:16px}}
@media (max-width:760px){{.two{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>🌉 {esc(title)}</h1><div class="sub">Hashimori Runtime · {n:,} decisions from {len(sessions)} sessions on {len(hosts)} hosts</div>
<div class="kpis"><div class="kpi"><b>{n:,}</b>tool calls decided</div>
<div class="kpi"><b>{100 * (mix.get('allow', 0) + mix.get('rewrite', 0)) / max(1, n):.0f}%</b>ran without a human</div>
<div class="kpi"><b>{mix.get('deny', 0):,}</b>denied</div><div class="kpi"><b>{mix.get('ask', 0):,}</b>asked a human</div>
<div class="kpi"><b>{sum(1 for a in fleet.get('alerts', []) if a.get('kind') == 'campaign')}</b>campaign alerts</div></div>
<div class="bar" role="img" aria-label="Decision mix">{''.join(bar)}</div><p>{legend}</p>
<h2>Fleet alerts</h2><div class="cards">{''.join(cards) or '<p class="muted">No campaign-shaped patterns.</p>'}</div>
<h2>Every decision, per host</h2><div class="panel">{''.join(svg)}</div>
<p class="muted">Hover a dot for details. Ringed dots belong to a campaign alert.</p>
<div class="two"><section><h2>Rules that fired</h2><div class="panel"><table>{rules_rows or '<tr><td class="muted">none</td></tr>'}</table></div></section>
<section><h2>Latest incidents</h2><div class="panel"><table><tr><th>Incident</th><th>Time</th><th>Host</th><th>Session</th><th></th><th>Reason</th></tr>{inc_rows}</table></div></section></div>
<script type="application/json" id="summary">{data}</script>
</main></body></html>"""
