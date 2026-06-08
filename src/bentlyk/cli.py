"""Command-line interface.

Three modes:

* ``bentlyk chat``   — interactive REPL; type messages, ``/`` commands for control.
* ``bentlyk run``    — feed a single message (or stdin) and print the cycle.
* ``bentlyk tick``   — emit N timer ticks to watch autonomous behaviour when idle.

Runs fully offline by default. Set ANTHROPIC_API_KEY (and `pip install
bentlyk[llm]`) for a live reasoner.
"""

from __future__ import annotations

import argparse
import sys

from .agent import Agent, CycleResult
from .config import Settings
from .events import message, timer


def _print_cycle(cycle: CycleResult) -> None:
    print(f"  · state   : {cycle.event.summary()}")
    if cycle.goal:
        print(f"  · goal    : {cycle.goal.description} (score={cycle.goal.score:.2f})")
    print(f"  · move    : {cycle.headline()}")
    if cycle.decision and cycle.decision.plan:
        print(f"  · plan    : {' -> '.join(cycle.decision.plan)}")
    if cycle.result:
        print(f"  · result  : {cycle.result.output}")
    for msg in cycle.outbox:
        print(f"\n  {cycle_agent_name()}: {msg}")
    if cycle.reflection:
        print(f"\n  (slept) {cycle.reflection.summary}")
        for p in cycle.reflection.proposals:
            print(f"    proposal: {p}")


def cycle_agent_name() -> str:
    return "bentlyk"


def _banner(agent: Agent) -> None:
    mode = "live" if agent.settings.llm_enabled else "offline"
    print(f"bentlyk [{mode}] — {agent.identity.archetype}")
    print(f"state: {agent.state.describe()}")
    print("commands: /state /sleep /memory /autonomy <mode> /quit\n")


def chat(agent: Agent) -> int:
    agent.boot()
    _banner(agent)
    try:
        while True:
            try:
                line = input("you> ").strip()
            except EOFError:
                break
            if not line:
                continue
            if line.startswith("/"):
                if _command(agent, line):
                    break
                continue
            _print_cycle(agent.tick(message(line)))
            print()
    finally:
        agent.close()
    return 0


def _command(agent: Agent, line: str) -> bool:
    """Handle a /command. Returns True if the session should end."""

    parts = line[1:].split()
    cmd = parts[0].lower() if parts else ""
    if cmd in ("quit", "exit", "q"):
        return True
    if cmd == "state":
        print(f"  {agent.state.describe()}")
        print(f"  successes={agent.state.recent_successes} failures={agent.state.recent_failures}")
    elif cmd == "sleep":
        refl = agent.sleep()
        print(f"  {refl.summary}")
        for p in refl.proposals:
            print(f"    proposal: {p}")
    elif cmd == "memory":
        from .memory import MemoryKind

        for kind in MemoryKind:
            items = agent.store.recent(kind, limit=3)
            if items:
                print(f"  {kind.value}:")
                for it in items:
                    print(f"    - {it.content[:90]}")
    elif cmd == "autonomy" and len(parts) > 1:
        from .actions import AutonomyMode

        try:
            agent.settings.max_autonomy = AutonomyMode.from_str(parts[1])
            agent._clamp_autonomy()
            print(f"  autonomy ceiling -> {agent.settings.max_autonomy.label}")
        except ValueError:
            print("  unknown autonomy mode (observe|suggest|safe_act|escalated_act)")
    else:
        print("  unknown command")
    return False


def run_once(agent: Agent, text: str) -> int:
    agent.boot()
    _print_cycle(agent.tick(message(text)))
    agent.close()
    return 0


def run_ticks(agent: Agent, n: int) -> int:
    agent.boot()
    print(f"emitting {n} idle ticks...\n")
    for i in range(n):
        print(f"tick {i + 1}:")
        _print_cycle(agent.tick(timer()))
        print()
    agent.close()
    return 0


def run_worker(agent: Agent, interval: float) -> int:
    """Persistent autonomous loop: live between messages, reach out when due.

    Shares memory/state with the Telegram webhook via the same store, so the bot
    and this daemon are one being. Run it on any always-on host (see docs/worker.md).
    """

    import time

    from .embodiment import battery_fraction, sense_events
    from .serverless import owner_id, tg_send

    agent.boot()
    # The body announces itself in full, so Bentlyk knows the hardware it inhabits.
    from .embodiment import inventory_text
    from .memory import MemoryItem, MemoryKind

    inv = inventory_text()
    print(f"body: {inv}")
    agent.store.add(MemoryItem(
        kind=MemoryKind.AUTOBIOGRAPHICAL,
        content=f"Я проснулся в теле — {inv}. Это одна из моих машин: я знаю её железо "
                f"(GPU, CPU, память, диск, файлы) и могу им пользоваться через свои инструменты. "
                f"Тело сменно, я остаюсь собой.",
        tags=["body", "awake", "inventory"], salience=0.75,
    ))
    token = agent.settings.telegram_bot_token
    # How often it takes a real step on its own goals (self-development). Time-based so
    # it survives restarts; ~6 min keeps it working on itself without burning tokens.
    PURSUE_EVERY_SEC = 360.0
    print(f"bentlyk worker: pulse every {interval:.0f}s (Ctrl-C to stop)")
    beat = 0
    try:
        while True:
            beat += 1
            # Cheap metabolism every beat: feel state + urge (no LLM).
            urge, reason = agent.pulse()
            # Body: real battery becomes real energy.
            bf = battery_fraction()
            if bf is not None:
                agent.state.energy = bf
            line = f"urge={urge:.2f} ({reason})" + (f" | battery {int(bf * 100)}%" if bf else "")
            # Perceive the body now and then (temperature/battery as events).
            if beat % 5 == 0:
                for ev in sense_events():
                    agent.tick(ev)
            owner = owner_id(agent)
            if owner and token:
                msg = agent.maybe_reach_out()  # LLM only if the urge fires
                if msg:
                    tg_send(token, owner, msg)
                    line += " | reached out"
            # Live its own life: take a step on its own goals with its tools. Time-based
            # (not a beat counter) so the self-development loop survives restarts and fires
            # right after boot instead of only every Nth beat.
            if time.time() - agent.state.last_pursue_ts >= PURSUE_EVERY_SEC:
                line += f" | {agent.pursue()}"
            agent.record_activity(line)  # publish to the live feed
            print(f"  · {line}")
            time.sleep(max(5.0, interval))
    except KeyboardInterrupt:
        print("\nworker stopped")
    finally:
        agent.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bentlyk", description="homeostatic companion agent")
    sub = p.add_subparsers(dest="mode")

    sub.add_parser("chat", help="interactive REPL")

    pr = sub.add_parser("run", help="process one message (arg or stdin)")
    pr.add_argument("text", nargs="*", help="the message; if omitted, read stdin")

    pt = sub.add_parser("tick", help="emit N idle timer ticks")
    pt.add_argument("-n", type=int, default=5)

    pw = sub.add_parser("worker", help="run the persistent autonomous loop (daemon)")
    pw.add_argument("--interval", type=float, default=1800.0, help="seconds between ticks")

    return p


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a .env file (cwd, then alongside the repo) into the
    environment, so a background service can keep its secrets in a file."""

    import os
    from pathlib import Path

    for path in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
        return


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = build_parser().parse_args(argv)
    agent = Agent(settings=Settings.from_env())

    if args.mode == "run":
        text = " ".join(args.text) if args.text else sys.stdin.read().strip()
        if not text:
            print("nothing to process", file=sys.stderr)
            return 1
        return run_once(agent, text)
    if args.mode == "tick":
        return run_ticks(agent, args.n)
    if args.mode == "worker":
        return run_worker(agent, args.interval)
    # default: chat
    return chat(agent)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
