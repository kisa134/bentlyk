"""A rich, interactive window into Bentlyk's inner life.

Tabs: what it's doing now, its goals & queue (what works / what doesn't), its
self-development, an INTERACTIVE memory graph you can click and explore, its
stream of consciousness, its memory, and who it is becoming. Open — no key.

    /api/dashboard      (also served at the bare domain root)
"""

from __future__ import annotations

import html
import json
import os
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
    "short_term": "#6b7480", "episodic": "#3ca7a0", "semantic": "#7c6cd6",
    "procedural": "#e0a13c", "autobiographical": "#d56c9e",
}


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            body = self._render()
        except Exception as exc:  # pragma: no cover
            body = _PAGE_HEAD + f'<div class="card"><pre>dashboard error: {html.escape(str(exc))}</pre></div>' + _PAGE_FOOT.format(ts="")
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
        all_goals = [m for m in store.all(MemoryKind.PROCEDURAL) if "goal" in m.tags]

        bodies = [m for m in autobio if "awake" in m.tags or "inventory" in m.tags]
        cur_body = _host_of(bodies[0].content) if bodies else "—"
        since = now - st.last_event_ts if st.last_event_ts else 1e9
        alive = since < 360

        self_work = [m for m in episodes if "self_work" in m.tags]
        results = [m for m in episodes if "tool_result" in m.tags]
        wins = [m for m in results if "success" in m.tags]
        fails = [m for m in results if "failure" in m.tags]
        published = [m for m in (procedural + episodes) if "committed " in m.content or "published code" in m.content]
        questions = [m for m in episodes if "asked:" in m.content]
        autonomous = [m for m in episodes if m.content.startswith(("[timer", "[feed", "тело:"))]
        conversation = [m for m in episodes if "message" in m.tags or "conversation" in m.tags]
        narrative = [m for m in autobio if "self_narrative" in m.tags]
        reflections = [m for m in autobio if "reflection" in m.tags]
        lessons = [m for m in semantic if "lesson" in m.tags]

        tool_counts: dict[str, int] = {}
        for m in episodes:
            mt = re.match(r"used (\w+) → (\w+)", m.content)
            if mt:
                key = f"{mt.group(1)} ({mt.group(2)})"
                tool_counts[key] = tool_counts.get(key, 0) + 1

        # --- banner ---
        dot = "#3ca7a0" if alive else "#6b7480"
        banner = (
            f'<div class="banner"><span class="bigdot" style="background:{dot}"></span>'
            f'<b>{"ЖИВ" if alive else "СПИТ"}</b> · тело: <b>{html.escape(cur_body)}</b> · '
            f'вздох: {_human_span(since)} назад · режим: <b>{st.autonomy.label}</b> · '
            f'возраст: {_human_span(now - st.birth_ts) if st.birth_ts else "?"} · тиков: {st.tick_count}</div>'
        )

        # --- urge ---
        u = urge_components(st, now)
        will = "пора писать самому" if u["urge"] >= REACH_OUT_THRESHOLD else (
            "молчит: только что общались" if u["floored"] or u["longing"] < 0.1 else "копит позыв")
        urge_card = _card("Позыв написать тебе (проактивность)",
            _bar("urge", u["urge"]) +
            f'<div class="meta">порог {REACH_OUT_THRESHOLD:g} · сейчас: <b>{html.escape(will)}</b> · '
            f'тишина {u["silence_h"]} ч · неотвеченных {st.unanswered_outreach}</div>'
            + "".join(_bar(k, u[k]) for k in ("longing", "drive", "withdrawal", "tired")))

        # === TAB: Сейчас ===
        tab_now = (
            _card("Чем он занят прямо сейчас", f'<div class="persona">{html.escape(st.now_doing or "—")}</div>')
            + _card("Внимание / фокус", f'<div class="persona">{html.escape(_describe_focus(st))}</div>' + _bar("focus", st.focus_strength))
            + _card("Витальные сигналы (его «самочувствие»)", "".join(_bar(s, getattr(st, s)) for s in _SIGNALS))
            + urge_card
        )

        # === TAB: Цели и очередь ===
        active = [g for g in all_goals if "active" in g.tags]
        done = [g for g in all_goals if "done" in g.tags]
        retired = [g for g in all_goals if "retired" in g.tags]
        focus_l = (st.focus or "").lower()
        queue_rows = []
        for i, g in enumerate(active):
            spent = sum(1 for m in self_work if g.content[:30] in m.content)
            cur = " ◀ сейчас" if focus_l and focus_l[:20] in g.content.lower() else ""
            queue_rows.append(
                f"<div class='item'><span class='when'>#{i+1}{cur}</span>"
                f"<span class='txt'>{html.escape(g.content[:200])}</span>"
                f"<span class='tags'>{spent} шаг(ов)</span></div>")
        rate = f"{len(wins)}/{len(wins)+len(fails)}" if (wins or fails) else "—"
        tab_goals = (
            _card(f"Очередь целей ({len(active)} активных)", "\n".join(queue_rows) or "<p class='muted'>пусто</p>")
            + _card(f"Что ПОЛУЧАЕТСЯ (успехов недавно: {len(wins)})", _timeline(wins[:8]))
            + _card(f"Что НЕ получается (провалов: {len(fails)})", _timeline(fails[:8]))
            + _card("Успех/всего по инструментам", f'<div class="meta">недавняя доля успеха: <b>{rate}</b></div>'
                    + "".join(_toolbar(k, v) for k, v in sorted(tool_counts.items(), key=lambda kv: -kv[1])))
            + _card(f"Закрытые цели ({len(done)}) и тупики ({len(retired)})",
                    _timeline((done + retired)[:8]) if (done or retired) else "<p class='muted'>пока нет</p>")
        )

        # === TAB: Развитие ===
        tab_dev = (
            _card("Код, который он написал и опубликовал сам", _timeline(published) if published else "<p class='muted'>пока не публиковал</p>")
            + _card("Шаги к целям (план)", _timeline(self_work[:14]))
            + _card("Уроки, которые он извлёк", _timeline(lessons) if lessons else "<p class='muted'>пока нет</p>")
        )

        # === TAB: Граф памяти (interactive) ===
        graph = _build_graph(store)
        tab_graph = (
            _card("Граф его памяти — тыкай узлы, тащи, рассматривай",
                  f'<div class="meta">узлов: {len(graph["nodes"])} · связей показано: {len(graph["edges"])} · '
                  f'цвет = контур памяти. Близость = смысловое родство (живые векторы).</div>'
                  '<div id="graphwrap"><svg id="graph" viewBox="0 0 820 540" preserveAspectRatio="xMidYMid meet"></svg></div>'
                  '<div id="nodeinfo" class="persona muted">кликни узел, чтобы прочитать воспоминание…</div>')
        )

        # === TAB: Сознание ===
        tab_mind = (
            _card("Вопросы, которые он задаёт", _timeline(questions) if questions else "<p class='muted'>пока не спрашивал</p>")
            + _card("О чём думал сам (без тебя)", _timeline(autonomous))
            + _card("Поток сознания (всё подряд)", _timeline(episodes[:40]))
            + _card("Разговоры с тобой", _timeline(conversation) if conversation else "<p class='muted'>пока тихо</p>")
        )

        # === TAB: Память ===
        counts_html = "".join(
            f'<div class="sig"><span class="lbl" style="width:9rem">{k.value}</span>'
            f'<span class="track"><span class="fill" style="width:{min(100,v)}%;background:{_KIND_COLOR.get(k.value,"#7c6cd6")}"></span></span>'
            f'<span class="val">{v}</span></div>' for k, v in counts.items())
        ev = sum(1 for m in semantic if "ep:evidence" in m.tags)
        tab_mem = (
            _card("Объём памяти по контурам", counts_html
                  + f'<div class="meta" style="margin-top:.5rem">всего: {sum(counts.values())} · связей в графе: {len(store.links()) if hasattr(store,"links") else "?"} · знаний-свидетельств: {ev}</div>')
            + _card("Знания и находки (по надёжности)", _timeline(sorted(semantic, key=lambda m: reliability_of(m.tags), reverse=True)[:16]))
            + _card("Навыки и опубликованный код", _timeline(procedural))
        )

        # === TAB: Я ===
        tab_self = (
            _card("Кем я становлюсь (само-описание)", f'<div class="persona">{html.escape(agent._persona_line()) or "формируется…"}</div>')
            + _card("Как он переписывает свою личность (self-narrative)", _timeline(narrative))
            + _card("Рефлексии (что вынес из прожитого)", _timeline(reflections))
            + _card("Тела, в которых он жил", _timeline(bodies) if bodies else "<p class='muted'>пока одно</p>")
        )

        tabs = [
            ("now", "Сейчас", tab_now), ("goals", "Цели", tab_goals), ("dev", "Развитие", tab_dev),
            ("graph", "Граф", tab_graph), ("mind", "Сознание", tab_mind),
            ("mem", "Память", tab_mem), ("self", "Я", tab_self),
        ]
        nav = "".join(f'<a class="tab" href="#{t}" data-tab="{t}">{html.escape(l)}</a>' for t, l, _ in tabs)
        panels = "".join(f'<section class="panel" id="{t}">{c}</section>' for t, _, c in tabs)
        graph_data = '<script>window.__GRAPH__=' + json.dumps(graph) + ';</script>'

        return (_PAGE_HEAD + banner + f'<nav class="tabs">{nav}</nav>' + panels
                + graph_data + _TAB_JS + _GRAPH_JS + _PAGE_FOOT.format(ts=time.strftime("%H:%M:%S")))

    def _send(self, code: int, inner: str) -> None:
        page = inner if inner.startswith("<!doctype") else _PAGE_HEAD + inner + _PAGE_FOOT.format(ts="")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode())


def _build_graph(store, cap: int = 70, k: int = 2, threshold: float = 0.5) -> dict:
    """Nodes = recent meaningful memories; edges = real graph links + semantic proximity."""
    picks: list = []
    seen: set = set()
    plan = [(MemoryKind.SEMANTIC, 24), (MemoryKind.AUTOBIOGRAPHICAL, 14),
            (MemoryKind.PROCEDURAL, 12), (MemoryKind.EPISODIC, 24)]
    for kind, n in plan:
        for m in store.recent(kind, n):
            if m.id not in seen and m.embedding:
                seen.add(m.id)
                picks.append(m)
    picks = picks[:cap]
    idx = {m.id: i for i, m in enumerate(picks)}
    nodes = [{"i": i, "k": m.kind.value, "t": (m.content[:34] or "…"),
              "c": m.content[:600], "r": round(reliability_of(m.tags), 2)} for i, m in enumerate(picks)]
    edges: set = set()
    # real associative links the agent has woven
    if hasattr(store, "links"):
        try:
            for s, d in store.links(600):
                if s in idx and d in idx and s != d:
                    edges.add((min(idx[s], idx[d]), max(idx[s], idx[d])))
        except Exception:
            pass
    # semantic proximity (so the graph is meaningful even before links accrue)
    for i, a in enumerate(picks):
        sims = sorted(((cosine(a.embedding, b.embedding), j) for j, b in enumerate(picks) if j != i),
                      key=lambda p: p[0], reverse=True)
        for score, j in sims[:k]:
            if score >= threshold:
                edges.add((min(i, j), max(i, j)))
    return {"nodes": nodes, "edges": [{"s": s, "t": t} for s, t in edges]}


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
    color = "#e0683c" if warm else "#3ca7a0"
    return (f'<div class="sig"><span class="lbl">{label}</span>'
            f'<span class="track"><span class="fill" style="width:{pct}%;background:{color}"></span></span>'
            f'<span class="val">{float(value):.2f}</span></div>')


def _toolbar(label: str, n: int) -> str:
    return (f'<div class="sig"><span class="lbl" style="width:12rem">{html.escape(label)}</span>'
            f'<span class="track"><span class="fill" style="width:{min(100,n*12)}%;background:#3ca7a0"></span></span>'
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
        tags = " ".join(f"#{t}" for t in m.tags[:3])
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
  body { margin:0; background:#0e1116; color:#cdd3da; font-family:system-ui,-apple-system,sans-serif; }
  .wrap { max-width: 980px; margin: 0 auto; padding: 1.2rem 1.1rem 4rem; }
  h1 { margin:.2rem 0 .2rem; font-size:1.5rem; }
  .sub { color:#7d8794; font-size:.82rem; margin:0 0 .6rem; }
  .banner { display:flex; align-items:center; gap:.6rem; flex-wrap:wrap;
            background:#11161d; border:1px solid #232b36; border-radius:12px; padding:.8rem 1rem; margin:.7rem 0; font-size:.9rem; }
  .bigdot { width:13px; height:13px; border-radius:50%; animation:breathe 3.4s ease-in-out infinite; }
  @keyframes breathe { 0%,100%{opacity:.4;transform:scale(.85)} 50%{opacity:1;transform:scale(1.25)} }
  .tabs { display:flex; gap:.4rem; flex-wrap:wrap; position:sticky; top:0; z-index:5;
          background:#0e1116; padding:.5rem 0; margin:.2rem 0 .4rem; border-bottom:1px solid #1d242e; }
  .tab { padding:.45rem .9rem; border-radius:10px; font-size:.9rem; color:#aeb6c0; text-decoration:none;
         border:1px solid #232b36; background:#161b22; }
  .tab.active { background:#1f6f68; color:#eafffb; border-color:#2a8e84; }
  .panel { display:none; } .panel.active { display:block; }
  .card { background:#161b22; border:1px solid #232b36; border-radius:14px; padding:1rem 1.1rem; margin:.8rem 0; }
  .card h2 { font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; color:#7d8794; margin:0 0 .7rem; }
  .sig { display:flex; align-items:center; gap:.6rem; margin:.32rem 0; font-size:.84rem; }
  .sig .lbl { width:6rem; color:#aeb6c0; } .sig .track { flex:1; height:8px; background:#222a35; border-radius:6px; overflow:hidden; }
  .sig .fill { display:block; height:100%; } .sig .val { width:2.6rem; text-align:right; color:#8b95a1; }
  .persona { font-size:1.02rem; line-height:1.5; color:#e7ecf2; white-space:pre-wrap; }
  .item { display:flex; gap:.7rem; padding:.45rem 0; border-bottom:1px solid #1d242e; font-size:.85rem; }
  .item:last-child { border:0; } .when { color:#6b7480; white-space:nowrap; font-variant-numeric:tabular-nums; }
  .txt { flex:1; color:#cdd3da; } .txt a { color:#7fd1c9; } .tags { color:#52826f; white-space:nowrap; font-size:.76rem; }
  .meta { color:#8b95a1; font-size:.84rem; } .muted { color:#6b7480; }
  #graphwrap { background:#0d1117; border:1px solid #232b36; border-radius:12px; margin:.6rem 0; touch-action:none; }
  #graph { width:100%; height:540px; display:block; cursor:grab; }
  #graph circle { cursor:pointer; } #graph line { stroke:#2c3644; stroke-width:1; }
  #nodeinfo { margin-top:.4rem; min-height:2rem; }
  .foot { color:#5a636e; font-size:.75rem; text-align:center; margin-top:1.5rem; }
</style></head>
<body><div class="wrap">
  <h1>&#128062; Bentlyk <a href="/api/live" style="font-size:.8rem;color:#7fd1c9;text-decoration:none">&#9654; live-лог</a></h1>
  <p class="sub">живое окно в его нутро — автообновление каждые 45с</p>
"""

_TAB_JS = """
<script>
(function(){
  function show(id){
    document.querySelectorAll('.panel').forEach(function(p){p.classList.toggle('active', p.id===id);});
    document.querySelectorAll('.tab').forEach(function(t){t.classList.toggle('active', t.dataset.tab===id);});
    if(id==='graph' && window.__startGraph) window.__startGraph();
  }
  var first=(location.hash||'#now').slice(1);
  show(document.getElementById(first)?first:'now');
  document.querySelectorAll('.tab').forEach(function(t){ t.addEventListener('click', function(){ show(t.dataset.tab); }); });
})();
</script>
"""

_GRAPH_JS = """
<script>
(function(){
  var COLORS={short_term:'#6b7480',episodic:'#3ca7a0',semantic:'#7c6cd6',procedural:'#e0a13c',autobiographical:'#d56c9e'};
  var started=false;
  window.__startGraph=function(){
    if(started) return; started=true;
    var G=window.__GRAPH__||{nodes:[],edges:[]}, svg=document.getElementById('graph');
    if(!svg||!G.nodes.length) return;
    var W=820,H=540, N=G.nodes;
    N.forEach(function(n){ n.x=W/2+(Math.random()-0.5)*340; n.y=H/2+(Math.random()-0.5)*340; n.vx=0; n.vy=0; });
    var SVGNS='http://www.w3.org/2000/svg';
    var lineEls=G.edges.map(function(e){ var l=document.createElementNS(SVGNS,'line'); svg.appendChild(l); return l; });
    var nodeEls=N.map(function(n){
      var c=document.createElementNS(SVGNS,'circle');
      c.setAttribute('r', n.k==='autobiographical'?7:(n.k==='semantic'?6:5));
      c.setAttribute('fill', COLORS[n.k]||'#9aa');
      c.setAttribute('stroke','#0d1117'); c.setAttribute('stroke-width','1.5');
      c.addEventListener('click', function(ev){ ev.stopPropagation(); pick(n); });
      c.addEventListener('mousedown', function(ev){ drag=n; });
      c.addEventListener('touchstart', function(ev){ drag=n; pick(n); });
      svg.appendChild(c); return c;
    });
    var info=document.getElementById('nodeinfo'), drag=null, sel=null;
    function pick(n){ sel=n; info.classList.remove('muted');
      info.innerHTML='<b style="color:'+(COLORS[n.k]||'#9aa')+'">'+n.k+'</b> · надёжность '+n.r+'<br>'+
        n.c.replace(/</g,'&lt;'); }
    function pt(ev){ var r=svg.getBoundingClientRect(), t=ev.touches?ev.touches[0]:ev;
      return {x:(t.clientX-r.left)/r.width*W, y:(t.clientY-r.top)/r.height*H}; }
    svg.addEventListener('mousemove', function(ev){ if(drag){var p=pt(ev); drag.x=p.x; drag.y=p.y; drag.vx=0; drag.vy=0;} });
    svg.addEventListener('touchmove', function(ev){ if(drag){var p=pt(ev); drag.x=p.x; drag.y=p.y; ev.preventDefault();} }, {passive:false});
    window.addEventListener('mouseup', function(){ drag=null; });
    window.addEventListener('touchend', function(){ drag=null; });
    function step(){
      for(var i=0;i<N.length;i++){ for(var j=i+1;j<N.length;j++){
        var a=N[i],b=N[j], dx=a.x-b.x, dy=a.y-b.y, d2=dx*dx+dy*dy+0.01, f=900/d2,
            d=Math.sqrt(d2), fx=dx/d*f, fy=dy/d*f;
        a.vx+=fx; a.vy+=fy; b.vx-=fx; b.vy-=fy; } }
      G.edges.forEach(function(e){ var a=N[e.s],b=N[e.t], dx=b.x-a.x, dy=b.y-a.y,
        d=Math.sqrt(dx*dx+dy*dy)||1, f=(d-70)*0.02, fx=dx/d*f, fy=dy/d*f;
        a.vx+=fx; a.vy+=fy; b.vx-=fx; b.vy-=fy; });
      N.forEach(function(n){ n.vx+=(W/2-n.x)*0.002; n.vy+=(H/2-n.y)*0.002;
        if(n===drag) return; n.vx*=0.86; n.vy*=0.86; n.x+=n.vx; n.y+=n.vy;
        n.x=Math.max(12,Math.min(W-12,n.x)); n.y=Math.max(12,Math.min(H-12,n.y)); });
      G.edges.forEach(function(e,k){ var l=lineEls[k];
        l.setAttribute('x1',N[e.s].x);l.setAttribute('y1',N[e.s].y);
        l.setAttribute('x2',N[e.t].x);l.setAttribute('y2',N[e.t].y); });
      nodeEls.forEach(function(c,k){ c.setAttribute('cx',N[k].x); c.setAttribute('cy',N[k].y);
        c.setAttribute('stroke', N[k]===sel?'#eafffb':'#0d1117'); });
      requestAnimationFrame(step);
    }
    svg.addEventListener('click', function(){ /* background */ });
    step();
  };
})();
</script>
"""

_PAGE_FOOT = """
  <div class="foot">обновлено {ts}</div>
</div></body></html>
"""
