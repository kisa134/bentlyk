"""A simple, clear Polymarket trading terminal — read-only v1, served next to the
dashboard. Browse events by category and the short-term crypto Up/Down board with
live countdowns. A referral/registration button (your builder/affiliate link) sits
at the entrance. Trading (agent + users' own wallets) is a later, gated phase.

    /api/terminal
"""

from __future__ import annotations

import html
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bentlyk import polymarket as pm  # noqa: E402

_REF = os.environ.get("POLYMARKET_REF", "https://polymarket.com")


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            body = _page()
        except Exception as exc:  # pragma: no cover
            body = _HEAD + f'<div class="card"><pre>terminal error: {html.escape(str(exc))}</pre></div>' + _FOOT
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())


def _page() -> str:
    board = pm.crypto_updown()
    sports = pm.events(tag="sports", limit=18)
    allev = pm.events(limit=24)
    offline = not (board or sports or allev)

    cta = (f'<a class="cta" href="{html.escape(_REF)}" target="_blank" rel="noopener">'
           '★ Зарегистрироваться на Polymarket</a>')

    crypto = _crypto_board(board) if board else _muted(
        "крипто-борд недоступен (Polymarket не отвечает или гео-блок хоста)")
    sports_html = _events(sports) if sports else _muted("нет событий")
    all_html = _events(allev) if allev else _muted("нет событий")

    tabs = [("crypto", f"Крипто ({len(board)})", crypto),
            ("sports", "Спорт", sports_html),
            ("all", "Все события", all_html)]
    nav = "".join(f'<a class="tab" href="#{t}" data-tab="{t}">{html.escape(l)}</a>' for t, l, _ in tabs)
    panels = "".join(f'<section class="panel" id="{t}">{c}</section>' for t, _, c in tabs)
    warn = _muted("Polymarket недоступен из этого хоста — открой терминал там, где он не заблокирован.") if offline else ""
    return _HEAD + f'<div class="bar">{cta}<button class="theme" onclick="tt()">◐</button></div>' + warn \
        + f'<nav class="tabs">{nav}</nav>' + panels + _JS + _FOOT


def _crypto_board(board: list[dict]) -> str:
    cards = []
    for m in board:
        up = m.get("up_price")
        up_pct = f'{up*100:.0f}%' if isinstance(up, (int, float)) else "—"
        up_w = int((up or 0) * 100)
        trade = f"{_REF.rstrip('/')}/event/{html.escape(m.get('slug',''))}"
        cards.append(
            f'<div class="mk"><div class="mkh"><b>{html.escape(m["asset"])}</b>'
            f'<span class="win">{html.escape(m["window"])}</span>'
            f'<span class="cd" data-end="{m["end"]}">…</span></div>'
            f'<div class="updown"><span class="up">Вверх {up_pct}</span>'
            f'<span class="track"><span class="fill" style="width:{up_w}%"></span></span></div>'
            f'<a class="go" href="{trade}" target="_blank" rel="noopener">Открыть / торговать ↗</a></div>')
    return f'<div class="grid">{"".join(cards)}</div>'


def _events(evs: list[dict]) -> str:
    rows = []
    for e in evs:
        mks = e.get("markets") or []
        legs = []
        for m in mks[:4]:
            outs, prs = m.get("outcomes") or [], m.get("prices") or []
            leg = " / ".join(f"{html.escape(str(o))} {float(p)*100:.0f}%"
                             for o, p in zip(outs, prs) if _isnum(p))
            legs.append(f'<div class="leg">{html.escape(m.get("question") or "")[:80]}<span class="pr">{leg}</span></div>')
        link = f"{_REF.rstrip('/')}/event/{html.escape(e.get('slug',''))}"
        rows.append(f'<div class="ev"><a class="evt" href="{link}" target="_blank" rel="noopener">'
                    f'{html.escape(e.get("title") or "")[:110]} ↗</a>{"".join(legs)}</div>')
    return "".join(rows) or _muted("пусто")


def _isnum(x) -> bool:
    try:
        float(x)
        return True
    except Exception:
        return False


def _muted(t: str) -> str:
    return f'<div class="card"><p class="muted">{html.escape(t)}</p></div>'


_HEAD = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bentlyk — терминал Polymarket</title>
<style>
 :root{--bg:#0e1116;--card:#161b22;--b:#232b36;--txt:#cdd3da;--mut:#7d8794;--acc:#2fb39b;--accbg:#1f6f68;--up:#2fb39b;}
 body.light{--bg:#f7f8fa;--card:#fff;--b:#e2e6ea;--txt:#1d2430;--mut:#6b7480;--acc:#1f8f80;--accbg:#d6f1ec;}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,-apple-system,sans-serif}
 .wrap{max-width:980px;margin:0 auto;padding:1rem 1rem 4rem}
 h1{font-size:1.4rem;margin:.3rem 0}
 .bar{display:flex;gap:.6rem;align-items:center;margin:.6rem 0}
 .cta{flex:1;text-align:center;background:var(--accbg);color:var(--acc);border:1px solid var(--acc);
      border-radius:12px;padding:.7rem 1rem;text-decoration:none;font-weight:700}
 .theme{background:transparent;color:var(--mut);border:1px solid var(--b);border-radius:8px;padding:.4rem .6rem;cursor:pointer}
 .tabs{display:flex;gap:.4rem;flex-wrap:wrap;position:sticky;top:0;background:var(--bg);padding:.5rem 0;border-bottom:1px solid var(--b);margin-bottom:.5rem}
 .tab{padding:.45rem .9rem;border-radius:9px;font-size:.9rem;color:var(--mut);text-decoration:none;border:1px solid var(--b);background:var(--card)}
 .tab.active{background:var(--accbg);color:var(--acc);border-color:var(--acc);font-weight:600}
 .panel{display:none}.panel.active{display:block}
 .card{background:var(--card);border:1px solid var(--b);border-radius:14px;padding:1rem;margin:.6rem 0}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.6rem}
 .mk{background:var(--card);border:1px solid var(--b);border-radius:14px;padding:.8rem}
 .mkh{display:flex;align-items:center;gap:.5rem;font-size:1rem}.win{color:var(--mut);font-size:.8rem}
 .cd{margin-left:auto;font-variant-numeric:tabular-nums;color:var(--acc);font-weight:700}
 .updown{margin:.6rem 0 .5rem}.up{font-size:.85rem;color:var(--up)}
 .track{display:block;height:8px;background:var(--b);border-radius:6px;overflow:hidden;margin-top:.3rem}
 .fill{display:block;height:100%;background:var(--up)}
 .go{display:inline-block;font-size:.82rem;color:var(--acc);text-decoration:none}
 .ev{background:var(--card);border:1px solid var(--b);border-radius:12px;padding:.7rem .9rem;margin:.5rem 0}
 .evt{color:var(--txt);text-decoration:none;font-weight:600;display:block;margin-bottom:.3rem}
 .leg{display:flex;justify-content:space-between;gap:1rem;font-size:.82rem;color:var(--mut);padding:.15rem 0}
 .pr{color:var(--txt);white-space:nowrap}
 .muted{color:var(--mut)}
</style></head><body><div class="wrap">
 <h1>&#128202; Терминал Polymarket <a href="/api/dashboard" style="font-size:.8rem;color:var(--acc);text-decoration:none">← дашборд</a></h1>
"""

_JS = """
<script>
function tt(){var l=document.body.classList.toggle('light');try{localStorage.setItem('bk_theme',l?'light':'dark')}catch(e){}}
(function(){
 try{if(localStorage.getItem('bk_theme')==='light')document.body.classList.add('light')}catch(e){}
 function show(id){document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id===id));
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===id));}
 var f=(location.hash||'#crypto').slice(1);show(document.getElementById(f)?f:'crypto');
 document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>show(t.dataset.tab)));
 function tick(){var now=Date.now()/1000;document.querySelectorAll('.cd').forEach(function(c){
  var s=Math.max(0,(+c.dataset.end)-now),m=Math.floor(s/60),ss=Math.floor(s%60);
  c.textContent=s<=0?'закрыт':(m+':'+(ss<10?'0':'')+ss);});}
 tick();setInterval(tick,1000);
})();
</script>
"""

_FOOT = f'<div class="muted" style="text-align:center;margin-top:1.5rem;font-size:.74rem">обновлено {time.strftime("%H:%M:%S")} · данные Polymarket (public) · v1 read-only</div></div></body></html>'
