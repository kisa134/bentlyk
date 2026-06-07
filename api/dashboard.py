"""A private dashboard into Bentlyk's inner life.

Renders a live HTML view of the entity's vitals (homeostatic signals, autonomy,
age/time), its stream of consciousness (recent episodes), reflections, the
evolving self-narrative, and what it's been learning — all read from the same
store the agent uses. Gated by a key (DASHBOARD_KEY, else SETUP_SECRET) so the
inner life isn't public.

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
        except Exception as exc:  # pragma: no cover - defensive
            body = f"<h1>Bentlyk</h1><pre>dashboard error: {html.escape(str(exc))}</pre>"
        self._send(200, body)

    def _render(self) -> str:
        agent = build_agent()
        st = agent.state
        ident = agent.identity
        temporal = agent._temporal()
        persona = agent._persona_line()

        episodes = agent.store.recent(MemoryKind.EPISODIC, limit=24)
        autobio = agent.store.recent(MemoryKind.AUTOBIOGRAPHICAL, limit=8)
        semantic = agent.store.recent(MemoryKind.SEMANTIC, limit=10)
        counts = {k.value: len(agent.store.all(k)) for k in MemoryKind}

        # Pulse: is it breathing? when did it last live a cycle / reach out / is it due?
        now = time.time()
        last_tick = _human_span(now - st.last_event_ts) if st.last_event_ts else "никогда"
        last_reach = _human_span(now - st.last_outreach_ts) if st.last_outreach_ts else "ни разу"
        from bentlyk.homeostasis import REACH_OUT_THRESHOLD

        urge, reason = agent.reach_out_urge(now)
        if urge >= REACH_OUT_THRESHOLD:
            nextline = f"<b style='color:#3ca7a0'>тянет написать ({reason})</b>"
        else:
            nextline = f"тяга написать: {urge:.2f}/{REACH_OUT_THRESHOLD:g} ({reason})"
        stale = (now - st.last_event_ts) > 3600 if st.last_event_ts else True
        warn = " · 💤 не дышал больше часа (нет тела/пинга)" if stale else ""
        pulse = (
            f'<span class="dot"></span> жив · последний тик: {last_tick} назад · '
            f'последний сам-выход: {last_reach} назад · {nextline}{warn}'
        )
        # Autonomous thoughts: cycles it ran on its own (timer), not replies to me.
        autonomous = [m for m in episodes if m.content.startswith("[timer")]

        bars = "".join(_bar(s, getattr(st, s)) for s in _SIGNALS)
        meta = (
            f"режим: <b>{st.autonomy.label}</b> · тиков: {st.tick_count} · "
            f"успехи/неудачи: {st.recent_successes}/{st.recent_failures} · "
            f"неотвеченных обращений: {st.unanswered_outreach}"
        )
        kc = " · ".join(f"{k}: {v}" for k, v in counts.items())

        return _PAGE.format(
            name=html.escape(ident.name),
            archetype=html.escape(ident.archetype),
            temporal=html.escape(temporal),
            meta=meta,
            pulse=pulse,
            bars=bars,
            persona=html.escape(persona) or "<i>ещё формируется…</i>",
            autonomous=_timeline(autonomous),
            stream=_timeline(episodes),
            reflections=_timeline(autobio),
            knowledge=_timeline(semantic),
            counts=html.escape(kc),
            ts=time.strftime("%H:%M:%S"),
        )

    def _send(self, code: int, inner: str) -> None:
        page = inner if inner.startswith("<!doctype") else _PAGE_WRAP.format(inner=inner)
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode())


def _bar(label: str, value: float) -> str:
    pct = max(0, min(100, int(float(value) * 100)))
    warm = label in ("pain", "distrust", "surprise")
    color = "#e0683c" if warm else "#3ca7a0"
    return (
        f'<div class="sig"><span class="lbl">{label}</span>'
        f'<span class="track"><span class="fill" style="width:{pct}%;background:{color}"></span></span>'
        f'<span class="val">{value:.2f}</span></div>'
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


_PAGE_WRAP = (
    "<!doctype html><meta charset=utf-8><title>Bentlyk</title>"
    "<body style='background:#0e1116;color:#cdd3da;font-family:system-ui;padding:2rem'>{inner}</body>"
)

_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="20">
<title>Bentlyk · внутреннее</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; background:#0e1116; color:#cdd3da; font-family:system-ui,-apple-system,sans-serif; }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 1.5rem 1.25rem 4rem; }}
  h1 {{ margin:.2rem 0 0; font-size:1.6rem; }}
  .sub {{ color:#8b95a1; font-size:.9rem; margin:.3rem 0 1.2rem; }}
  .card {{ background:#161b22; border:1px solid #232b36; border-radius:14px; padding:1rem 1.1rem; margin:.8rem 0; }}
  .card h2 {{ font-size:.8rem; text-transform:uppercase; letter-spacing:.08em; color:#7d8794; margin:0 0 .7rem; }}
  .sig {{ display:flex; align-items:center; gap:.6rem; margin:.35rem 0; font-size:.85rem; }}
  .sig .lbl {{ width:5.5rem; color:#aeb6c0; }}
  .sig .track {{ flex:1; height:8px; background:#222a35; border-radius:6px; overflow:hidden; }}
  .sig .fill {{ display:block; height:100%; }}
  .sig .val {{ width:2.6rem; text-align:right; color:#8b95a1; }}
  .persona {{ font-size:1.05rem; line-height:1.5; color:#e7ecf2; }}
  .item {{ display:flex; gap:.7rem; padding:.45rem 0; border-bottom:1px solid #1d242e; font-size:.86rem; }}
  .item:last-child {{ border:0; }}
  .when {{ color:#6b7480; white-space:nowrap; font-variant-numeric:tabular-nums; }}
  .txt {{ flex:1; color:#cdd3da; }}
  .tags {{ color:#52826f; white-space:nowrap; font-size:.78rem; }}
  .meta {{ color:#8b95a1; font-size:.85rem; }}
  .muted {{ color:#6b7480; }}
  .pulse {{ display:flex; align-items:center; gap:.5rem; font-size:.9rem; color:#aeb6c0; }}
  .dot {{ width:11px; height:11px; border-radius:50%; background:#3ca7a0;
          box-shadow:0 0 0 0 rgba(60,167,160,.6); animation:breathe 3.4s ease-in-out infinite; }}
  @keyframes breathe {{
    0%,100% {{ opacity:.35; transform:scale(.8); box-shadow:0 0 0 0 rgba(60,167,160,.5); }}
    50% {{ opacity:1; transform:scale(1.25); box-shadow:0 0 0 9px rgba(60,167,160,0); }}
  }}
  .foot {{ color:#5a636e; font-size:.75rem; text-align:center; margin-top:1.5rem; }}
</style></head>
<body><div class="wrap">
  <h1>🐾 {name}</h1>
  <div class="sub">{archetype}<br>{temporal}</div>

  <div class="card"><div class="pulse">{pulse}</div></div>

  <div class="card"><h2>Витальные сигналы</h2>{bars}
    <div class="meta" style="margin-top:.7rem">{meta}</div></div>

  <div class="card"><h2>Кем я становлюсь</h2><div class="persona">{persona}</div></div>

  <div class="card"><h2>О чём думал сам (без меня)</h2>{autonomous}</div>

  <div class="card"><h2>Поток сознания</h2>{stream}</div>

  <div class="card"><h2>Рефлексии и автобиография</h2>{reflections}</div>

  <div class="card"><h2>Знания и находки</h2>{knowledge}</div>

  <div class="card"><h2>Память</h2><div class="meta">{counts}</div></div>

  <div class="foot">обновлено {ts} · автообновление каждые 20с</div>
</div></body></html>
"""
