"""Trading interface — watch and work with Bentlyk's evolving paper-trading colony.

Live forward equity curve, the champion's recent trades, the mined winning pattern,
and the best genome — so you can actually SEE how the colonies trade and what
conditions they win in. Read-only v1, served next to the dashboard/terminal.

    /api/trading
"""

from __future__ import annotations

import html
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bentlyk.serverless import build_agent  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            body = _page()
        except Exception as exc:  # pragma: no cover
            body = _HEAD + f'<div class="card"><pre>{html.escape(str(exc))}</pre></div>' + _FOOT
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())


def _page() -> str:
    agent = build_agent()
    s = agent.colony_stats() if hasattr(agent, "colony_stats") else {}
    started = s.get("steps", 0) > 0

    be, me = s.get("best_equity", 1.0), s.get("median_equity", 1.0)
    head = (f'<div class="kpis">'
            f'<div class="kpi"><b>{s.get("gen",0)}</b><span>поколение</span></div>'
            f'<div class="kpi"><b>{s.get("pop",0)}</b><span>кошельков</span></div>'
            f'<div class="kpi"><b>{s.get("steps",0)}</b><span>живых шагов</span></div>'
            f'<div class="kpi"><b class="{_cls(be)}">{(be-1)*100:+.1f}%</b><span>лучший (форвард)</span></div>'
            f'<div class="kpi"><b class="{_cls(me)}">{(me-1)*100:+.1f}%</b><span>медиана</span></div>'
            f'<div class="kpi"><b>{s.get("winrate",0):.2f}</b><span>винрейт</span></div></div>')

    curve = _card("Кривая капитала колонии (медиана, живой форвард)", _spark(s.get("history", []))
                  + '<div class="meta">пила = сброс капитала на каждом поколении эволюции (честная оценка заново). Линия 1.0 — безубыток.</div>')

    pat = s.get("pattern", {})
    if pat:
        d = pat.get("dir", 0)
        side = "ВВЕРХ (лонг)" if d >= 0 else "ВНИЗ (шорт)"
        conds = " · ".join(f"{k} {v:+.2f}" for k, v in pat.items() if k != "dir")
        pat_html = f'<div class="big">Выигрыши случались при: <b>{html.escape(conds)}</b><br>преобладающее направление: <b>{side}</b></div>'
    else:
        pat_html = '<p class="muted">копит выигрышные сделки для добычи паттерна…</p>'
    pattern = _card("Паттерн выигрышей — при каких условиях колония побеждала", pat_html
                    + '<div class="meta">новые геномы СМЕЩАЮТСЯ к этому паттерну (ищем те же условия снова). Реальный держится на будущем, случайный гаснет.</div>')

    feed = s.get("feed", [])
    rows = "".join(
        f'<div class="tr"><span class="dir {"up" if t["dir"]>0 else "dn"}">{"▲ вверх" if t["dir"]>0 else "▼ вниз"}</span>'
        f'<span class="pnl {_cls(1+t["pnl"]/100)}">{t["pnl"]:+.2f}%</span>'
        f'<span class="muted">пок.{t["g"]} · шаг {t["s"]}</span></div>'
        for t in reversed(feed))
    trades = _card("Сделки чемпиона (последние)", rows or '<p class="muted">пока нет сделок</p>')

    gen = s.get("best_genome", {})
    gen_html = "".join(
        f'<div class="sig"><span class="lbl">{html.escape(k)}</span>'
        f'<span class="track"><span class="fill" style="width:{int(min(100,abs(v)*50))}%;background:{"#2fb39b" if v>=0 else "#e0683c"}"></span></span>'
        f'<span class="val">{v:+.2f}</span></div>' for k, v in gen.items())
    genome = _card("Лучший геном (как чемпион взвешивает рынок)", gen_html or '<p class="muted">—</p>')

    warn = "" if started else _card("⏸ Колония ещё не запущена",
        '<p class="muted">воркер (тело) сейчас не работает — подними его в Render (Manual Deploy / Resume), '
        'и колония начнёт торговать вживую. Интерфейс наполнится сам.</p>')

    return _HEAD + warn + head + curve + pattern + trades + genome + _JS + _FOOT


def _cls(eq):
    return "g" if eq > 1.0 else ("r" if eq < 1.0 else "")


def _card(title, body):
    return f'<div class="card"><h2>{html.escape(title)}</h2>{body}</div>'


def _spark(hist):
    if len(hist) < 2:
        return '<p class="muted">кривая появится с первыми шагами</p>'
    w, h = 800, 180
    lo, hi = min(hist), max(hist)
    rng = (hi - lo) or 1e-6
    n = len(hist)
    pts = " ".join(f"{i/(n-1)*w:.1f},{h-(v-lo)/rng*h:.1f}" for i, v in enumerate(hist))
    base = h - (1.0 - lo) / rng * h if lo <= 1.0 <= hi else None
    bl = f'<line x1="0" y1="{base:.1f}" x2="{w}" y2="{base:.1f}" stroke="var(--mut)" stroke-dasharray="4" opacity=".5"/>' if base is not None else ""
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" style="width:100%;height:180px;display:block">'
            f'{bl}<polyline points="{pts}" fill="none" stroke="var(--acc)" stroke-width="2"/></svg>')


_HEAD = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="30">
<title>Bentlyk — трейдинг</title><style>
 :root{--bg:#0e1116;--card:#161b22;--b:#232b36;--txt:#cdd3da;--mut:#7d8794;--acc:#2fb39b;--g:#2fb39b;--r:#e0683c}
 body.light{--bg:#f7f8fa;--card:#fff;--b:#e2e6ea;--txt:#1d2430;--mut:#6b7480;--acc:#1f8f80}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,sans-serif}
 .wrap{max-width:980px;margin:0 auto;padding:1rem 1rem 4rem}h1{font-size:1.4rem;margin:.3rem 0}
 .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:.5rem;margin:.6rem 0}
 .kpi{background:var(--card);border:1px solid var(--b);border-radius:12px;padding:.7rem;text-align:center}
 .kpi b{font-size:1.25rem;display:block}.kpi span{font-size:.72rem;color:var(--mut)}
 .g{color:var(--g)}.r{color:var(--r)}
 .card{background:var(--card);border:1px solid var(--b);border-radius:14px;padding:1rem;margin:.7rem 0}
 .card h2{font-size:.74rem;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);margin:0 0 .7rem}
 .big{font-size:1.05rem;line-height:1.5}.meta{color:var(--mut);font-size:.83rem;margin-top:.4rem}.muted{color:var(--mut)}
 .tr{display:flex;gap:1rem;align-items:center;padding:.35rem 0;border-bottom:1px solid var(--b);font-size:.86rem}
 .dir{width:5.5rem}.dir.up{color:var(--g)}.dir.dn{color:var(--r)}.pnl{width:5rem;text-align:right;font-variant-numeric:tabular-nums}
 .sig{display:flex;align-items:center;gap:.6rem;margin:.3rem 0;font-size:.84rem}.sig .lbl{width:5rem;color:var(--mut)}
 .sig .track{flex:1;height:8px;background:var(--b);border-radius:6px;overflow:hidden}.sig .fill{display:block;height:100%}
 .sig .val{width:3rem;text-align:right;color:var(--mut)}
 .theme{background:transparent;color:var(--mut);border:1px solid var(--b);border-radius:8px;padding:.3rem .6rem;cursor:pointer}
 a{color:var(--acc);text-decoration:none}
</style></head><body><div class="wrap">
 <h1>&#128200; Трейдинг — колонии <a href="/api/dashboard" style="font-size:.8rem">← дашборд</a> <a href="/api/terminal" style="font-size:.8rem">терминал →</a>
 <button class="theme" style="float:right" onclick="tt()">◐</button></h1>
"""

_JS = """<script>function tt(){var l=document.body.classList.toggle('light');try{localStorage.setItem('bk_theme',l?'light':'dark')}catch(e){}}
try{if(localStorage.getItem('bk_theme')==='light')document.body.classList.add('light')}catch(e){}</script>"""

_FOOT = f'<div class="muted" style="text-align:center;margin-top:1.4rem;font-size:.74rem">обновлено {time.strftime("%H:%M:%S")} · живой форвард, без бэктестов</div></div></body></html>'
