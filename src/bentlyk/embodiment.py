"""Embodiment on a real machine.

When Bentlyk runs as a persistent worker on a computer/Pi, this gives it a body:
host senses (temperature, battery → real ``energy``) turned into events, and a
sandboxed working directory it can read, write, and (opt-in) run code in.

Everything degrades gracefully: no psutil → no senses; code execution is off
unless explicitly enabled. Nothing here is reachable from the public webhook.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .events import Event, EventKind


def battery_fraction() -> float | None:
    """Battery charge in [0,1], or None if there's no battery / no psutil."""

    try:
        import psutil  # type: ignore
    except Exception:
        return None
    try:
        bat = psutil.sensors_battery()
    except Exception:
        return None
    return round(bat.percent / 100.0, 3) if bat is not None else None


def cpu_temperature() -> float | None:
    try:
        import psutil  # type: ignore

        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    for entries in (temps or {}).values():
        for e in entries:
            if e.current:
                return round(float(e.current), 1)
    return None


def sense_events() -> list[Event]:
    """Snapshot the body's physical state as perception events."""

    out: list[Event] = []
    temp = cpu_temperature()
    bat = battery_fraction()
    parts = []
    if temp is not None:
        parts.append(f"температура {temp}°C")
    if bat is not None:
        parts.append(f"батарея {int(bat * 100)}%")
    if parts:
        signals = {}
        if bat is not None:  # battery is my real energy
            signals["energy"] = 0.0  # placeholder; worker sets energy directly
        out.append(
            Event(kind=EventKind.FEED, content="тело: " + ", ".join(parts), source="body",
                  payload={"temp": temp, "battery": bat})
        )
    return out


# --- sandboxed local filesystem + code execution -----------------------------
def _safe_path(base: Path, rel: str) -> Path | None:
    base = base.resolve()
    target = (base / rel.lstrip("/")).resolve()
    return target if str(target).startswith(str(base)) else None


def write_file(base: Path, rel: str, content: str) -> str:
    base.mkdir(parents=True, exist_ok=True)
    p = _safe_path(base, rel)
    if p is None:
        return "(refused: path escapes workdir)"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {rel} ({len(content)} bytes)"


def read_file(base: Path, rel: str, max_chars: int = 6000) -> str:
    p = _safe_path(base, rel)
    if p is None or not p.exists():
        return f"(no such file: {rel})"
    return p.read_text(errors="replace")[:max_chars]


def list_dir(base: Path) -> str:
    base.mkdir(parents=True, exist_ok=True)
    items = sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())
    return "\n".join(items[:200]) or "(empty)"


def run_code(base: Path, command: str, timeout: float = 30.0) -> str:
    """Run a shell command inside the workdir. Caller must check allow_code first."""

    base.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            command, shell=True, cwd=str(base), capture_output=True, text=True,
            timeout=timeout, env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired:
        return f"(timeout after {timeout:.0f}s)"
    except Exception as exc:  # pragma: no cover
        return f"(run error: {exc})"
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    return (out.strip() or f"(exit {proc.returncode}, no output)")[:6000]
