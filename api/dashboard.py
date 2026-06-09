"""A clear, interactive window into Bentlyk's inner life.

Seven tabs (now / goals / development / graph / mind / memory / self), a black&white
theme toggle, and a memory graph whose layout is computed server-side so it always
renders (static SVG); light JS adds click-to-read and drag. Open — no key.

    /api/dashboard      (also served at the bare domain root)
"""

from __future__ import annotations

import html
import json
import math
import os
import random
import re
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bentlyk.attention import describe as _describe_focus  # noqa: E402
from bentlyk.homeostasis import REACH_OUT_THRESHOLD, urge_components  # noqa: E402
from bentlyk.memory import MemoryKind  # noqa: E402
from bentlyk.memory.base import cosine, reliability_of  # noqa: E402
from bentlyk.self_model import _human_span  # noqa: E402
from bentlyk.serverless import build_agent  # noqa: E402

_SIGNALS = ("energy", "curiosity", "attachment", "coherence", "surprise", "distrust", "pain")
_KIND_COLOR = {
    "short_term": "#8a93a0", "episodic": "#36b3a8", "semantic": "#8b7be8",
    "procedural": "#e0a13c", "autobiographical": "#e070a8",
}


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            body = self._render()
        except Exception as exc:  # pragma: no cover
            body = _PAGE_HEAD + f'<div class="card"><pre>dashboard error: {html.escape(str(exc))}</pre></div>' + _foot()
        self._send(200, body)

    def _render(self) -> str:
        agent = build_agent()
        st = agent.state
        store = agent.store
        now = time.time()

        autobio = store.recent(MemoryKind.AUTOBIOGRAPHICAL, limit=24)
        episodes = store.recent(MemoryKind.EPISODIC, limit=80)
        semantic = store.recent(MemoryKind.SEMANTIC, limit=24)
        procedural = store.recent(MemoryKind.PROCEDURAL, limit=24)
        counts = {k: len(store.all(k)) for k in MemoryKind}
        all_goals = [m for m in procedural if "goal" in m.tags] or \
            [m for m in store.all(MemoryKind.PROCEDURAL) if "goal" in m.tags]

        bodies = [m for m in autobio if "awake" in m.tags or "inventory" in m.tags]
        cur_body = _host_of(bodies[0].content) if bodies else "—"
        since = now - st.last_event_ts if st.last_event_ts else 1e9
        alive = since < 360

        self_work = [m for m in episodes if "self_work" in m.tags]
        results = [m for m in episodes if "tool_result" in m.tags]
        wins = [m for m in results if "success" in m.tags]
        fails = [m for m in results if "failure" in m.tags]
        published = [m for m in (procedural + episodes) if "committed " in m.content or "published" in m.tags]
        questions = [m for m in episodes if "asked:" in m.content]
        autonomous = [m for m in episodes if m.content.startswith(("[timer", "[feed", "тело:"))]
        conversation = [m for m in episodes if "message" in m.tags or "conversation" in m.tags]
        narrative = [m for m in autobio if "self_narrative" in m.tags]
        reflections = [m for m in autobio if "reflection" in m.tags]
        lessons = [m for m in semantic if "lesson" in m.tags]
        blocks = [m for m in episodes if "constitution" in m.tags]
        skills = agent.skills() if hasattr(agent, "skills") else []

        tool_counts: dict[str, int] = {}
        for m in episodes:
            mt = re.match(r"used (\w+) → (\w+)", m.content)
            if mt:
                key = f"{mt.group(1)} ({mt.group(2)})"
                tool_counts[key] = tool_counts.get(key, 0) + 1

        dot = "#2fb39b" if alive else "#8a93a0"
        banner = (
            f'<div class="banner"><span class="bigdot" style="background:{dot}"></span>'
            f'<b>{"ЖИВ" if alive else "СПИТ"}</b> · тело <b>{html.escape(cur_body)}</b> · '
            f'вздох {_human_span(since)} назад · режим <b>{st.autonomy.label}</b> · '
            f'возраст {_human_span(now - st.birth_ts) if st.birth_ts else "?"} · тиков {st.tick_count}'
            '<button id="themebtn" class="theme" onclick="toggleTheme()">◐ тема</button></div>'
        )

        u = urge_components(st, now)
        will = "пора писать самому" if u["urge"] >= REACH_OUT_THRESHOLD else (
            "молчит: только что общались" if u["floored"] or u["longing"] < 0.1 else "копит позыв")
        urge_card = _card("Позыв написать тебе", _bar("urge", u["urge"])
            + f'<div class="meta">порог {REACH_OUT_THRESHOLD:g} · <b>{html.escape(will)}</b> · тишина {u["silence_h"]} ч</div>'
            + "".join(_bar(k, u[k]) for k in ("longing", "drive", "withdrawal", "tired")))

        tab_now = (
            _card("Чем занят прямо сейчас", f'<div class="big">{html.escape(st.now_doing or "—")}</div>')
            + _card("Внимание / фокус", f'<div class="big">{html.escape(_describe_focus(st))}</div>' + _bar("focus", st.focus_strength))
            + _card("Витальные сигналы", "".join(_bar(s, getattr(st, s)) for s in _SIGNALS))
            + urge_card
        )

        active = [g for g in all_goals if "active" in g.tags]
        done = [g for g in all_goals if "done" in g.tags]
        retired = [g for g in all_goals if "retired" in g.tags]
        focus_l = (st.focus or "").lower()
        qrows = []
        for i, g in enumerate(active):
            spent = sum(1 for m in self_work if g.content[:30] in m.content)
            cur = " ◀ сейчас" if focus_l and focus_l[:18] in g.content.lower() else ""
            qrows.append(f"<div class='item'><span class='when'>#{i+1}{cur}</span>"
                         f"<span class='txt'>{html.escape(g.content[:200])}</span><span class='tags'>{spent} шаг.</span></div>")
        rate = f"{len(wins)}/{len(wins)+len(fails)}" if (wins or fails) else "—"
        tab_goals = (
            _card(f"Очередь целей ({len(active)})", "\n".join(qrows) or "<p class='muted'>пусто</p>")
            + _card(f"Что ПОЛУЧАЕТСЯ ({len(wins)})", _timeline(wins[:8]))
            + _card(f"Что НЕ получается ({len(fails)})", _timeline(fails[:8]))
            + _card("Доля успеха по инструментам", f'<div class="meta">недавняя: <b>{rate}</b></div>'
                    + "".join(_toolbar(k, v) for k, v in sorted(tool_counts.items(), key=lambda kv: -kv[1])))
            + _card(f"Закрытые ({len(done)}) и тупики ({len(retired)})", _timeline((done + retired)[:6]) if (done or retired) else "<p class='muted'>нет</p>")
        )

        skill_rows = ""
        if skills:
            from bentlyk.skills import level as _sl, proficiency as _sp
            skill_rows = "".join(
                f'<div class="sig"><span class="lbl" style="width:11rem">{html.escape(s.content.replace("навык: ","")[:30])}</span>'
                f'<span class="track"><span class="fill" style="width:{int(_sp(s)*100)}%;background:#e0a13c"></span></span>'
                f'<span class="val">{_sl(s)}/9</span></div>' for s in skills[:12])
        tab_dev = (
            _card("Навыки, которые он растит (учёба)", skill_rows or "<p class='muted'>пока учится с нуля</p>")
            + _card("Код, который он написал сам", _timeline(published[:8]) if published else "<p class='muted'>пока нет</p>")
            + _card("Уроки, которые он извлёк", _timeline(lessons[:8]) if lessons else "<p class='muted'>нет</p>")
            + _card("Шаги к целям", _timeline(self_work[:12]))
        )

        graph = _build_graph(store)
        tab_graph = _card("Граф его памяти — тыкай узлы, тащи",
            f'<div class="meta">узлов {len(graph["nodes"])} · связей {len(graph["edges"])} · цвет = контур памяти, близость = смысл</div>'
            + _svg_graph(graph)
            + '<div id="nodeinfo" class="big muted">кликни узел — прочитаешь воспоминание…</div>'
            + _legend())

        tab_mind = (
            _card("Вопросы, которые он задаёт", _timeline(questions[:10]) if questions else "<p class='muted'>пока не спрашивал</p>")
            + _card("Совесть: что заблокировала конституция", _timeline(blocks[:6]) if blocks else "<p class='muted'>ничего не нарушал</p>")
            + _card("О чём думал сам (без тебя)", _timeline(autonomous[:10]))
            + _card("Поток сознания", _timeline(episodes[:36]))
            + _card("Разговоры с тобой", _timeline(conversation[:10]) if conversation else "<p class='muted'>тихо</p>")
        )

        counts_html = "".join(
            f'<div class="sig"><span class="lbl" style="width:9rem">{k.value}</span>'
            f'<span class="track"><span class="fill" style="width:{min(100,v)}%;background:{_KIND_COLOR.get(k.value)}"></span></span>'
            f'<span class="val">{v}</span></div>' for k, v in counts.items())
        nlinks = len(store.links()) if hasattr(store, "links") else "?"
        tab_mem = (
            _card("Объём памяти по контурам", counts_html
                  + f'<div class="meta">всего {sum(counts.values())} · связей в графе {nlinks}</div>')
            + _card("Знания (по надёжности)", _timeline(sorted(semantic, key=lambda m: reliability_of(m.tags), reverse=True)[:14]))
            + _card("Навыки и опубликованный код", _timeline(procedural[:12]))
        )

        tab_self = (
            _card("Кем я становлюсь", f'<div class="big">{html.escape(agent._persona_line()) or "формируется…"}</div>')
            + _card("Как он переписывает себя (self-narrative)", _timeline(narrative[:8]))
            + _card("Рефлексии", _timeline(reflections[:8]))
            + _card("Тела, в которых жил", _timeline(bodies[:6]) if bodies else "<p class='muted'>одно</p>")
        )

        tabs = [("now", "Сейчас", tab_now), ("goals", "Цели", tab_goals), ("dev", "Развитие", tab_dev),
                ("graph", "Граф", tab_graph), ("mind", "Сознание", tab_mind),
                ("mem", "Память", tab_mem), ("self", "Я", tab_self)]
        nav = "".join(f'<a class="tab" href="#{t}" data-tab="{t}">{html.escape(l)}</a>' for t, l, _ in tabs)
        panels = "".join(f'<section class="panel" id="{t}">{c}</section>' for t, _, c in tabs)
        gdata = '<script>window.__GRAPH__=' + json.dumps(graph) + ';</script>'
        return _PAGE_HEAD + banner + f'<nav class="tabs">{nav}</nav>' + panels + gdata + _JS + _foot()

    def _send(self, code: int, inner: str) -> None:
        page = inner if inner.startswith("<!doctype") else _PAGE_HEAD + inner + _foot()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode())


# --- memory graph: nodes + edges, laid out server-side so it always renders ---
def _build_graph(store, cap: int = 64, k: int = 2, threshold: float = 0.5) -> dict:
    picks, seen = [], set()
    for kind, n in [(MemoryKind.SEMANTIC, 22), (MemoryKind.AUTOBIOGRAPHICAL, 13),
                    (MemoryKind.PROCEDURAL, 11), (MemoryKind.EPISODIC, 22)]:
        for m in store.recent(kind, n):
            if m.id not in seen and m.embedding:
                seen.add(m.id)
                picks.append(m)
    picks = picks[:cap]
    idx = {m.id: i for i, m in enumerate(picks)}
    edges = set()
    if hasattr(store, "links"):
        try:
            for s, d in store.links(800):
                if s in idx and d in idx and s != d:
                    edges.add((min(idx[s], idx[d]), max(idx[s], idx[d])))
        except Exception:
            pass
    for i, a in enumerate(picks):
        sims = sorted(((cosine(a.embedding, b.embedding), j) for j, b in enumerate(picks) if j != i),
                      key=lambda p: p[0], reverse=True)
        for score, j in sims[:k]:
            if score >= threshold:
                edges.add((min(i, j), max(i, j)))
    edges = list(edges)
    pos = _layout(len(picks), edges)
    nodes = [{"x": round(pos[i][0], 1), "y": round(pos[i][1], 1), "k": m.kind.value,
              "c": m.content[:500], "r": round(reliability_of(m.tags), 2)} for i, m in enumerate(picks)]
    return {"nodes": nodes, "edges": [{"s": s, "t": t} for s, t in edges], "w": 800, "h": 560}


def _layout(n: int, edges, W: int = 800, H: int = 560, iters: int = 90) -> list[list[float]]:
    random.seed(7)
    pos = []
    for i in range(n):
        a = 2 * math.pi * i / max(1, n)
        pos.append([W / 2 + 230 * math.cos(a) + random.uniform(-18, 18),
                    H / 2 + 230 * math.sin(a) + random.uniform(-18, 18)])
    for _ in range(iters):
        disp = [[0.0, 0.0] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
                d2 = dx * dx + dy * dy + 0.01
                d = math.sqrt(d2)
                f = 1400.0 / d2
                fx, fy = dx / d * f, dy / d * f
                disp[i][0] += fx; disp[i][1] += fy; disp[j][0] -= fx; disp[j][1] -= fy
        for s, t in edges:
            dx, dy = pos[t][0] - pos[s][0], pos[t][1] - pos[s][1]
            d = math.sqrt(dx * dx + dy * dy) or 1.0
            f = (d - 78) * 0.05
            fx, fy = dx / d * f, dy / d * f
            disp[s][0] += fx; disp[s][1] += fy; disp[t][0] -= fx; disp[t][1] -= fy
        for i in range(n):
            pos[i][0] += max(-16, min(16, disp[i][0])) + (W / 2 - pos[i][0]) * 0.01
            pos[i][1] += max(-16, min(16, disp[i][1])) + (H / 2 - pos[i][1]) * 0.01
            pos[i][0] = max(16, min(W - 16, pos[i][0]))
            pos[i][1] = max(16, min(H - 16, pos[i][1]))
    return pos


def _svg_graph(g: dict) -> str:
    N = g["nodes"]
    lines = "".join(
        f'<line x1="{N[e["s"]]["x"]}" y1="{N[e["s"]]["y"]}" x2="{N[e["t"]]["x"]}" y2="{N[e["t"]]["y"]}"/>'
        for e in g["edges"])
    circles = "".join(
        f'<circle data-i="{i}" cx="{nd["x"]}" cy="{nd["y"]}" '
        f'r="{6 if nd["k"]=="autobiographical" else (5 if nd["k"]=="semantic" else 4)}" '
        f'fill="{_KIND_COLOR.get(nd["k"], "#8b7be8")}"/>'
        for i, nd in enumerate(N))
    return (f'<div id="graphwrap"><svg id="graph" viewBox="0 0 {g["w"]} {g["h"]}" '
            f'preserveAspectRatio="xMidYMid meet"><g id="edges">{lines}</g>'
            f'<g id="nodes">{circles}</g></svg></div>')


def _legend() -> str:
    return '<div class="legend">' + "".join(
        f'<span><i style="background:{c}"></i>{k}</span>' for k, c in _KIND_COLOR.items()) + '</div>'


def _host_of(content: str) -> str:
    if "теле — " in content:
        rest = content.split("теле — ", 1)[1]
        return rest.split(",")[0].strip() if "," in rest else rest[:40]
    return "это тело"


def _card(title: str, body: str) -> str:
    return f'<div class="card"><h2>{html.escape(title)}</h2>{body}</div>'


def _bar(label: str, value: float) -> str:
    pct = max(0, min(100, int(float(value) * 100)))
    warm = label in ("pain", "distrust", "surprise", "withdrawal", "tired")
    return (f'<div class="sig"><span class="lbl">{label}</span>'
            f'<span class="track"><span class="fill {"warm" if warm else ""}" style="width:{pct}%"></span></span>'
            f'<span class="val">{float(value):.2f}</span></div>')


def _toolbar(label: str, n: int) -> str:
    return (f'<div class="sig"><span class="lbl" style="width:12rem">{html.escape(label)}</span>'
            f'<span class="track"><span class="fill" style="width:{min(100,n*12)}%"></span></span>'
            f'<span class="val">{n}</span></div>')


_URL_RE = re.compile(r"(https?://[^\s<]+)")


def _linkify(escaped: str) -> str:
    return _URL_RE.sub(r'<a href="\1" target="_blank" rel="noopener">ссылка ↗</a>', escaped)


def _timeline(items) -> str:
    if not items:
        return "<p class='muted'>пусто</p>"
    rows = []
    for m in items:
        when = time.strftime("%d.%m %H:%M", time.localtime(m.created_at))
        tags = " ".join(f"#{t}" for t in m.tags[:3] if not t.startswith(("sig:", "skill:", "rel:", "ep:")))
        rows.append(f"<div class='item'><span class='when'>{when}</span>"
                    f"<span class='txt'>{_linkify(html.escape(m.content[:600]))}</span>"
                    f"<span class='tags'>{html.escape(tags)}</span></div>")
    return "\n".join(rows)


_PAGE_HEAD = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="45">
<title>Bentlyk — внутреннее</title>
<style>
  :root { --bg:#0e1116; --card:#161b22; --b:#232b36; --line:#1d242e; --txt:#cdd3da; --mut:#7d8794; --acc:#2fb39b; --accbg:#1f6f68; }
  body.light { --bg:#f7f8fa; --card:#ffffff; --b:#e2e6ea; --line:#eceef1; --txt:#1d2430; --mut:#6b7480; --acc:#1f8f80; --accbg:#d6f1ec; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--txt); font-family:system-ui,-apple-system,sans-serif; transition:background .2s,color .2s; }
  .wrap { max-width:980px; margin:0 auto; padding:1.1rem 1rem 4rem; }
  h1 { margin:.2rem 0; font-size:1.5rem; } .sub { color:var(--mut); font-size:.82rem; margin:0 0 .5rem; }
  .banner { display:flex; align-items:center; gap:.55rem; flex-wrap:wrap; background:var(--card); border:1px solid var(--b);
            border-radius:12px; padding:.75rem .95rem; margin:.6rem 0; font-size:.9rem; }
  .bigdot { width:12px; height:12px; border-radius:50%; animation:breathe 3.4s ease-in-out infinite; }
  @keyframes breathe { 0%,100%{opacity:.4;transform:scale(.85)} 50%{opacity:1;transform:scale(1.25)} }
  .theme { margin-left:auto; background:transparent; color:var(--mut); border:1px solid var(--b); border-radius:8px; padding:.25rem .6rem; cursor:pointer; font-size:.8rem; }
  .tabs { display:flex; gap:.35rem; flex-wrap:wrap; position:sticky; top:0; z-index:5; background:var(--bg); padding:.5rem 0; margin-bottom:.4rem; border-bottom:1px solid var(--line); }
  .tab { padding:.42rem .85rem; border-radius:9px; font-size:.88rem; color:var(--mut); text-decoration:none; border:1px solid var(--b); background:var(--card); }
  .tab.active { background:var(--accbg); color:var(--acc); border-color:var(--acc); font-weight:600; }
  .panel { display:none; } .panel.active { display:block; }
  .card { background:var(--card); border:1px solid var(--b); border-radius:14px; padding:.95rem 1.05rem; margin:.75rem 0; }
  .card h2 { font-size:.74rem; text-transform:uppercase; letter-spacing:.07em; color:var(--mut); margin:0 0 .65rem; }
  .sig { display:flex; align-items:center; gap:.55rem; margin:.3rem 0; font-size:.83rem; }
  .sig .lbl { width:6rem; color:var(--mut); } .sig .track { flex:1; height:8px; background:var(--line); border-radius:6px; overflow:hidden; }
  .sig .fill { display:block; height:100%; background:var(--acc); } .sig .fill.warm { background:#e0683c; } .sig .val { width:2.6rem; text-align:right; color:var(--mut); }
  .big { font-size:1.02rem; line-height:1.5; white-space:pre-wrap; }
  .item { display:flex; gap:.65rem; padding:.42rem 0; border-bottom:1px solid var(--line); font-size:.85rem; }
  .item:last-child { border:0; } .when { color:var(--mut); white-space:nowrap; font-variant-numeric:tabular-nums; }
  .txt { flex:1; } .txt a { color:var(--acc); } .tags { color:var(--mut); white-space:nowrap; font-size:.74rem; opacity:.7; }
  .meta { color:var(--mut); font-size:.84rem; margin-bottom:.4rem; } .muted { color:var(--mut); }
  #graphwrap { background:var(--bg); border:1px solid var(--b); border-radius:12px; margin:.5rem 0; touch-action:none; }
  #graph { width:100%; height:560px; display:block; cursor:grab; }
  #graph #edges line { stroke:var(--b); stroke-width:1; }
  #graph circle { cursor:pointer; stroke:var(--bg); stroke-width:1.5; }
  .legend { display:flex; gap:.8rem; flex-wrap:wrap; font-size:.76rem; color:var(--mut); }
  .legend i { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:.3rem; vertical-align:middle; }
  .foot { color:var(--mut); font-size:.74rem; text-align:center; margin-top:1.4rem; opacity:.6; }
</style></head>
<body><div class="wrap">
  <h1>&#128062; Bentlyk <a href="/api/live" style="font-size:.8rem;color:var(--acc);text-decoration:none">&#9654; live-лог</a></h1>
  <p class="sub">живое окно в его нутро — обновление каждые 45с</p>
"""

_JS = """
<script>
function toggleTheme(){ var l=document.body.classList.toggle('light'); try{localStorage.setItem('bk_theme', l?'light':'dark');}catch(e){} }
(function(){
  try{ if(localStorage.getItem('bk_theme')==='light') document.body.classList.add('light'); }catch(e){}
  function show(id){
    document.querySelectorAll('.panel').forEach(function(p){p.classList.toggle('active', p.id===id);});
    document.querySelectorAll('.tab').forEach(function(t){t.classList.toggle('active', t.dataset.tab===id);});
  }
  var first=(location.hash||'#now').slice(1);
  show(document.getElementById(first)?first:'now');
  document.querySelectorAll('.tab').forEach(function(t){ t.addEventListener('click', function(){ show(t.dataset.tab); }); });

  // graph: already laid out + drawn server-side; JS only adds click-to-read + drag
  var G=window.__GRAPH__||{nodes:[]}, svg=document.getElementById('graph');
  if(svg && G.nodes.length){
    var info=document.getElementById('nodeinfo'), circles=svg.querySelectorAll('circle'), drag=null;
    var lines=svg.querySelectorAll('#edges line'), edges=G.edges||[];
    function pick(i){ var n=G.nodes[i]; info.classList.remove('muted');
      info.innerHTML='<b>'+n.k+'</b> · надёжность '+n.r+'<br>'+(n.c||'').replace(/</g,'&lt;');
      circles.forEach(function(c){ c.setAttribute('stroke-width', c===circles[i]?'3':'1.5'); }); }
    function pt(ev){ var r=svg.getBoundingClientRect(), t=ev.touches?ev.touches[0]:ev;
      return {x:(t.clientX-r.left)/r.width*G.w, y:(t.clientY-r.top)/r.height*G.h}; }
    function redraw(i){ var n=G.nodes[i]; circles[i].setAttribute('cx',n.x); circles[i].setAttribute('cy',n.y);
      edges.forEach(function(e,k){ if(e.s===i){lines[k].setAttribute('x1',n.x);lines[k].setAttribute('y1',n.y);}
        if(e.t===i){lines[k].setAttribute('x2',n.x);lines[k].setAttribute('y2',n.y);} }); }
    circles.forEach(function(c,i){
      c.addEventListener('click', function(e){ e.stopPropagation(); pick(i); });
      c.addEventListener('mousedown', function(){ drag=i; pick(i); });
      c.addEventListener('touchstart', function(){ drag=i; pick(i); });
    });
    svg.addEventListener('mousemove', function(ev){ if(drag!==null){var p=pt(ev); G.nodes[drag].x=p.x; G.nodes[drag].y=p.y; redraw(drag);} });
    svg.addEventListener('touchmove', function(ev){ if(drag!==null){var p=pt(ev); G.nodes[drag].x=p.x; G.nodes[drag].y=p.y; redraw(drag); ev.preventDefault();} }, {passive:false});
    window.addEventListener('mouseup', function(){ drag=null; });
    window.addEventListener('touchend', function(){ drag=null; });
  }
})();
</script>
"""


def _foot() -> str:
    return f'<div class="foot">обновлено {time.strftime("%H:%M:%S")}</div></div></body></html>'
