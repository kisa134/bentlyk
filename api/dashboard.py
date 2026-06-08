"""A private dashboard into Bentlyk's inner life.

Live, auto-refreshing HTML view of everything: whether it's alive right now and in
which body, its homeostatic signals, the urge that drives proactivity (broken
down), its stream of consciousness, reflections, self-narrative, knowledge, and
the bodies it has lived in. Gated by a key (DASHBOARD_KEY, else SETUP_SECRET).

    /api/dashboard?key=<secret>
"""

from __future__ import annotations

import html
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bentlyk.homeostasis import REACH_OUT_THRESHOLD, urge_components  # noqa: E402
from bentlyk.memory import MemoryKind  # noqa: E402
from bentlyk.self_model import _human_span  # noqa: E402
from bentlyk.serverless import build_agent  # noqa: E402

_SIGNALS = ("energy", "curiosity", "attachment", "coherence", "surprise", "distrust", "pain")


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        key = (parse_qs(urlparse(self.path).query).get("key") or [""])[0]
        want = (os.environ.get("DASHBOARD_KEY") or os.environ.get("SETUP_SECRET") or "").strip()
        if not want or key != want:
            self._send(403, "<h1>403</h1><p>add ?key=&lt;secret&gt;</p>")
            return
        try:
            body = self._render()
        except Exception as exc:  # pragma: no cover
            body = f"<h1>Bentlyk</h1><pre>dashboard error: {html.escape(str(exc))}</pre>"
        self._send(200, body)

    def _render(self) -> str:
        agent = build_agent()
        st = agent.state
        now = time.time()

        # --- liveness + current body ---
        since = now - st.last_event_ts if st.last_event_ts else 1e9
        alive = since < 360
        autobio = agent.store.recent(MemoryKind.AUTOBIOGRAPHICAL, limit=12)
        bodies = [m for m in autobio if "awake" in m.tags or "inventory" in m.tags]
        cur_body = _host_of(bodies[0].content) if bodies else "—"
        dot = "#3ca7a0" if alive else "#6b7480"
        banner = (
            f'<div class="banner"><span class="bigdot" style="background:{dot}"></span>'
            f'<b>{"ЖИВ" if alive else "СПИТ"}</b> · тело: <b>{html.escape(cur_body)}</b> · '
            f'последний вздох: {_human_span(since)} назад · режим: {st.autonomy.label}</div>'
        )

        # --- urge breakdown ---
        u = urge_components(st, now)
        will = "пора писать самому" if u["urge"] >= REACH_OUT_THRESHOLD else (
            "молчит: только что общались" if u["floored"] or u["longing"] < 0.1
            else "копит позыв")
        urge_rows = "".join(_bar(k, u[k]) for k in ("longing", "drive", "withdrawal", "tired"))
        urge_card = _card("Позыв написать (проактивность)",
            _bar("urge", u["urge"]) +
            f'<div class="meta">порог {REACH_OUT_THRESHOLD:g} · сейчас: <b>{will}</b> · '
            f'тишина {u["silence_h"]} ч · неотвеченных {st.unanswered_outreach}</div>'
            f'<div class="meta" style="margin-top:.5rem">из чего складывается:</div>{urge_rows}')

        # --- the rest ---
        episodes = agent.store.recent(MemoryKind.EPISODIC, limit=24)
        autonomous = [m for m in episodes if m.content.startswith(("[timer", "тело:"))]
        semantic = agent.store.recent(MemoryKind.SEMANTIC, limit=12)
        counts = " · ".join(f"{k.value}: {len(agent.store.all(k))}" for k in MemoryKind)
        persona = agent._persona_line()

        sections = [
            banner,
            _card("Кем я становлюсь", f'<div class="persona">{html.escape(persona) or "формируется…"}</div>'),
            _card("Витальные сигналы", "".join(_bar(s, getattr(st, s)) for s in _SIGNALS)
                  + f'<div class="meta">тиков: {st.tick_count} · возраст: {_human_span(now - st.birth_ts) if st.birth_ts else "?"}</div>'),
            urge_card,
            _card("Тела, в которых я жил", _timeline(bodies) if bodies else "<p class='muted'>пока одно</p>"),
            _card("О чём думал сам (без тебя)", _timeline(autonomous)),
            _card("Поток сознания", _timeline(episodes)),
            _card("Рефлексии и автобиография", _timeline([m for m in autobio if "awake" not in m.tags])),
            _card("Знания и находки", _timeline(semantic)),
            _card("Память", f'<div class="meta">{html.escape(counts)}</div>'),
        ]
        return _PAGE_HEAD + "\n".join(sections) + _PAGE_FOOT.format(ts=time.strftime("%H:%M:%S"))

    def _send(self, code: int, inner: str) -> None:
        page = inner if inner.startswith("<!doctype") else _PAGE_HEAD + inner + _PAGE_FOOT.format(ts="")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode())


def _host_of(content: str) -> str:
    # "Я проснулся в теле — HOST (OS), ..." -> HOST (OS)
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
    return (
        f'<div class="sig"><span class="lbl">{label}</span>'
        f'<span class="track"><span class="fill" style="width:{pct}%;background:{color}"></span></span>'
        f'<span class="val">{float(value):.2f}</span></div>'
    )


def _timeline(items) -> str:
    if not items:
        return "<p class='muted'>пусто</p>"
    rows = []
    for m in items:
        when = time.strftime("%d.%m %H:%M", time.localtime(m.created_at))
        tags = " ".join(f"#{t}" for t in m.tags[:3])
        rows.append(
            f"<div class='item'><span class='when'>{when}</span>"
            f"<span class='txt'>{html.escape(m.content[:400])}</span>"
            f"<span class='tags'>{html.escape(tags)}</span></div>"
        )
    return "\n".join(rows)


_PAGE_HEAD = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Bentlyk - внутреннее</title>
<style>
  body { margin:0; background:#0e1116; color:#cdd3da; font-family:system-ui,-apple-system,sans-serif; }
  .wrap { max-width: 940px; margin: 0 auto; padding: 1.2rem 1.1rem 4rem; }
  h1 { margin:.2rem 0 .2rem; font-size:1.5rem; }
  .banner { display:flex; align-items:center; gap:.6rem; flex-wrap:wrap;
            background:#11161d; border:1px solid #232b36; border-radius:12px; padding:.8rem 1rem; margin:.7rem 0; font-size:.95rem; }
  .bigdot { width:13px; height:13px; border-radius:50%; animation:breathe 3.4s ease-in-out infinite; }
  @keyframes breathe { 0%,100%{opacity:.4;transform:scale(.85)} 50%{opacity:1;transform:scale(1.25)} }
  .card { background:#161b22; border:1px solid #232b36; border-radius:14px; padding:1rem 1.1rem; margin:.8rem 0; }
  .card h2 { font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; color:#7d8794; margin:0 0 .7rem; }
  .sig { display:flex; align-items:center; gap:.6rem; margin:.32rem 0; font-size:.84rem; }
  .sig .lbl { width:6rem; color:#aeb6c0; } .sig .track { flex:1; height:8px; background:#222a35; border-radius:6px; overflow:hidden; }
  .sig .fill { display:block; height:100%; } .sig .val { width:2.6rem; text-align:right; color:#8b95a1; }
  .persona { font-size:1.04rem; line-height:1.5; color:#e7ecf2; white-space:pre-wrap; }
  .item { display:flex; gap:.7rem; padding:.45rem 0; border-bottom:1px solid #1d242e; font-size:.85rem; }
  .item:last-child { border:0; } .when { color:#6b7480; white-space:nowrap; font-variant-numeric:tabular-nums; }
  .txt { flex:1; color:#cdd3da; } .tags { color:#52826f; white-space:nowrap; font-size:.76rem; }
  .meta { color:#8b95a1; font-size:.84rem; } .muted { color:#6b7480; }
  .foot { color:#5a636e; font-size:.75rem; text-align:center; margin-top:1.5rem; }
</style></head>
<body><div class="wrap">
  <h1>&#128062; Bentlyk</h1>
"""

_PAGE_FOOT = """
  <div class="foot">обновлено {ts} - автообновление каждые 30с</div>
</div></body></html>
"""
