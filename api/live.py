"""A live console into Bentlyk — a streaming log of what it's doing and thinking,
right now, updating every few seconds without a full reload.

The HTML shell polls this same endpoint with ``?format=json`` and renders the feed
(newest first) plus a "СЕЙЧАС" line driven by the worker's heartbeat. Gated by a
key (DASHBOARD_KEY, else SETUP_SECRET).

    /api/live?key=<secret>
"""

from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bentlyk.attention import describe as _describe_focus  # noqa: E402
from bentlyk.memory import MemoryKind  # noqa: E402
from bentlyk.serverless import build_agent  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        q = parse_qs(urlparse(self.path).query)
        key = (q.get("key") or [""])[0]
        want = (os.environ.get("DASHBOARD_KEY") or os.environ.get("SETUP_SECRET") or "").strip()
        if not want or key != want:
            self._send(403, "text/html", "<h1>403</h1><p>add ?key=&lt;secret&gt;</p>")
            return
        if (q.get("format") or [""])[0] == "json":
            try:
                payload = json.dumps(self._feed())
            except Exception as exc:  # pragma: no cover
                payload = json.dumps({"error": str(exc), "items": []})
            self._send(200, "application/json", payload)
            return
        self._send(200, "text/html", _PAGE)

    # --- data ---------------------------------------------------------------
    def _feed(self) -> dict:
        agent = build_agent()
        st = agent.state
        now = time.time()
        since = now - st.last_event_ts if st.last_event_ts else 1e9
        store = agent.store
        if hasattr(store, "recent_any"):
            items = store.recent_any(60)
        else:  # fallback: merge per-kind recents
            items = []
            for k in MemoryKind:
                items += store.recent(k, 20)
            items.sort(key=lambda m: m.created_at, reverse=True)
            items = items[:60]
        return {
            "alive": since < 360,
            "since": int(since),
            "now": st.now_doing or "—",
            "autonomy": st.autonomy.label,
            "energy": round(st.energy, 2),
            "focus": _describe_focus(st),
            "items": [
                {
                    "ts": m.created_at,
                    "icon": _icon(m),
                    "label": _label(m),
                    "text": m.content[:600],
                }
                for m in items
            ],
        }

    def _send(self, code: int, ctype: str, body: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body.encode())


def _tagset(m) -> set:
    return set(m.tags or [])


def _icon(m) -> str:
    t = _tagset(m)
    if "proactive" in t:
        return "\U0001f4ac"  # speech
    if "reply" in t:
        return "↩"  # reply arrow
    if "message" in t:
        return "\U0001f464"  # person
    if "published" in t or "code" in t:
        return "\U0001f6e0"  # tools
    if "tool_result" in t and "failure" in t:
        return "⚠"  # warning
    if "self_work" in t:
        return "\U0001f3af"  # target
    if "reflection" in t:
        return "\U0001f319"  # moon
    if "self_narrative" in t:
        return "✨"  # sparkles
    if "consolidated" in t:
        return "\U0001f9e9"  # puzzle
    if "web" in t:
        return "\U0001f310"  # globe
    if "body" in t or "inventory" in t:
        return "\U0001f9e0"  # brain
    if "thought:" in (m.content or ""):
        return "\U0001f4ad"  # thought
    return "·"


def _label(m) -> str:
    t = _tagset(m)
    if "proactive" in t:
        return "сам написал"
    if "reply" in t:
        return "ответил"
    if "message" in t:
        return "человек"
    if "published" in t or "code" in t:
        return "код"
    if "tool_result" in t and "failure" in t:
        return "сбой"
    if "tool_result" in t:
        return "действие"
    if "self_work" in t:
        return "само-работа"
    if "reflection" in t:
        return "рефлексия"
    if "self_narrative" in t:
        return "само-образ"
    if "consolidated" in t:
        return "вывод"
    if "web" in t:
        return "веб"
    if "body" in t or "inventory" in t:
        return "тело"
    return m.kind.value if hasattr(m, "kind") else "—"


_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bentlyk — live</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#0a0c10; color:#cdd3da;
         font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:13px; }
  .top { position:sticky; top:0; background:#0d1117; border-bottom:1px solid #1d242e;
         padding:.7rem .9rem; z-index:5; }
  .row1 { display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; }
  .dot { width:11px; height:11px; border-radius:50%; background:#6b7480;
         animation:breathe 3.2s ease-in-out infinite; }
  @keyframes breathe { 0%,100%{opacity:.35;transform:scale(.8)} 50%{opacity:1;transform:scale(1.25)} }
  .name { font-weight:700; letter-spacing:.04em; }
  .pill { color:#7d8794; }
  .now { margin-top:.45rem; color:#e7ecf2; }
  .now b { color:#7fd1c9; }
  .meta { color:#5a636e; font-size:11px; margin-top:.25rem; }
  .feed { padding:.4rem .6rem 3rem; }
  .item { display:flex; gap:.6rem; padding:.42rem .2rem; border-bottom:1px solid #12181f; }
  .item.fresh { animation:flash 1.6s ease-out; }
  @keyframes flash { 0%{background:#15493f} 100%{background:transparent} }
  .when { color:#5a636e; white-space:nowrap; font-variant-numeric:tabular-nums; }
  .ic { width:1.3rem; text-align:center; }
  .tag { color:#52826f; white-space:nowrap; min-width:5.5rem; }
  .txt { flex:1; color:#cdd3da; white-space:pre-wrap; word-break:break-word; }
  a { color:#7fd1c9; }
</style></head>
<body>
  <div class="top">
    <div class="row1"><span class="dot" id="dot"></span>
      <span class="name">&#128062; Bentlyk LIVE</span>
      <span class="pill" id="state"></span></div>
    <div class="now">СЕЙЧАС: <b id="now">…</b></div>
    <div class="meta" id="meta">подключаюсь…</div>
  </div>
  <div class="feed" id="feed"></div>
<script>
  const key = new URLSearchParams(location.search).get("key") || "";
  let lastTs = 0;
  function fmt(ts){ return new Date(ts*1000).toLocaleTimeString(); }
  async function tick(){
    try{
      const r = await fetch(`/api/live?format=json&key=${encodeURIComponent(key)}`, {cache:"no-store"});
      const d = await r.json();
      document.getElementById("dot").style.background = d.alive ? "#3ca7a0" : "#6b7480";
      document.getElementById("now").textContent = d.now || "—";
      document.getElementById("state").textContent =
        `· ${d.alive?"жив":"спит"} · ${d.autonomy} · energy ${d.energy} · ${d.focus}`;
      document.getElementById("meta").textContent =
        `последний вздох ${d.since}s назад · обновлено ${new Date().toLocaleTimeString()} · авто-каждые 3s`;
      const feed = document.getElementById("feed");
      feed.textContent = "";
      let newest = lastTs;
      for(const it of (d.items||[])){
        const row = document.createElement("div");
        row.className = "item" + (it.ts > lastTs ? " fresh" : "");
        if(it.ts > newest) newest = it.ts;
        const w = document.createElement("span"); w.className="when"; w.textContent = fmt(it.ts);
        const ic = document.createElement("span"); ic.className="ic"; ic.textContent = it.icon;
        const tg = document.createElement("span"); tg.className="tag"; tg.textContent = it.label;
        const tx = document.createElement("span"); tx.className="txt"; tx.textContent = it.text;
        row.append(w, ic, tg, tx); feed.append(row);
      }
      lastTs = newest;
    }catch(e){
      document.getElementById("meta").textContent = "связь потеряна, повтор…";
    }
  }
  tick(); setInterval(tick, 3000);
</script>
</body></html>
"""
