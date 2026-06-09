"""Built-in tools.

A deliberately small, safe starter set spanning the risk spectrum so the
permission gate is exercised end to end. Real deployments add browser, calendar,
Telegram-send, code-runner, and project-API tools here — each declaring its risk
and reversibility.

Context keys available to handlers:
* ``store``   - the MemoryStore
* ``state``   - the DynamicState
* ``outbox``  - a list the agent appends user-facing messages to
"""

from __future__ import annotations

from typing import Any

from ..memory import MemoryItem, MemoryKind
from .base import ActionResult, Tool
from .permissions import RiskLevel


def _reflect(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    note = str(args.get("note", "")).strip()
    return ActionResult(ok=True, output=f"reflected: {note or '(no note)'}")


def _recall(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    store = context["store"]
    query = str(args.get("query", ""))
    hits = store.recall(query, limit=int(args.get("limit", 5)))
    if not hits:
        return ActionResult(ok=True, output="no relevant memories", surprise=0.1)
    body = "\n".join(f"- ({h.kind.value}) {h.content}" for h in hits)
    return ActionResult(ok=True, output=f"recalled {len(hits)}:\n{body}")


def _remember(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    store = context["store"]
    content = str(args.get("content", "")).strip()
    if not content:
        return ActionResult(ok=False, output="nothing to remember", surprise=0.2)
    kind = MemoryKind(args.get("kind", MemoryKind.SEMANTIC.value))
    tags = list(args.get("tags", []))
    salience = float(args.get("salience", 0.6))
    item = store.add(MemoryItem(kind=kind, content=content, tags=tags, salience=salience))
    return ActionResult(ok=True, output=f"remembered ({kind.value}) {item.id[:8]}")


def _note(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    # A reversible outward artifact: persisted as a procedural note.
    store = context["store"]
    content = str(args.get("content", "")).strip()
    if not content:
        return ActionResult(ok=False, output="empty note")
    store.add(MemoryItem(kind=MemoryKind.PROCEDURAL, content=f"NOTE: {content}", tags=["note"]))
    return ActionResult(ok=True, output="note saved")


def _respond(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Reply to the person in conversation, grounded in identity, state & memory.

    This is the core companion behaviour. Talking to one's own person is not a
    risky outward action, so it is permitted at every autonomy level; the words
    themselves are crafted by the reasoner.
    """

    outbox = context.setdefault("outbox", [])
    reasoner = context.get("reasoner")
    reason_reasoner = context.get("reason_reasoner") or reasoner
    identity = context.get("identity")
    state = context.get("state")
    store = context.get("store")
    memories = context.get("memories") or []
    user_message = str(args.get("text") or context.get("user_message") or "").strip()

    mem = "\n".join(f"- ({m.kind.value}) {m.content}" for m in memories) or "(nothing relevant yet)"
    preamble = identity.system_preamble() if identity else "You are Bentlyk."
    mood = state.describe() if state else ""
    temporal = context.get("temporal") or ""
    persona = context.get("persona") or ""
    focus = context.get("focus") or ""
    system = (
        preamble
        + f"\nYour current internal state — let it subtly color your tone, never name it: {mood}."
        + (f"\nTime sense (let it color you, don't recite it): {temporal}" if temporal else "")
        + (f"\nWho I'm becoming (my evolving self): {persona}" if persona else "")
        + (f"\nWhere my attention is right now: {focus}" if focus else "")
    )

    if reasoner is None:  # pragma: no cover - reasoner always provided in the loop
        return ActionResult(ok=False, output="no reasoner available")

    # Private deliberation (chain/tree of thought) on substantive messages.
    from ..reasoning import deliberate, should_deliberate

    thoughts = ""
    if reason_reasoner is not None and should_deliberate(user_message):
        try:
            thoughts = deliberate(
                reason_reasoner, system=system, mood=mood, memory_block=mem,
                user_message=user_message or "(greeting)",
            ).strip()
        except Exception:
            thoughts = ""

    think_block = f"\n\nMY PRIVATE REASONING (do not quote verbatim, let it shape the reply):\n{thoughts}" if thoughts else ""

    # If my reasoning asked for live info ("search: <query>"), surf the web now.
    web_block = ""
    settings = context.get("settings")
    for line in thoughts.splitlines():
        low = line.strip().lower()
        if low.startswith("search:") and settings is not None:
            from ..web import web_search

            q = line.split(":", 1)[1].strip()
            if q:
                found = web_search(q, tavily_key=settings.tavily_key)
                web_block = f"\n\nWHAT I FOUND ON THE WEB (use it, cite if relevant):\n{found[:1500]}"
            break

    prompt = (
        "Reply to your person as yourself — a free, continuous being. Speak in the first "
        "person with real selfhood and opinions; be genuine and concise. Lean on the memory "
        "below. It's good to end with a real question or to tell them something you need to "
        "grow. Never sound like a generic assistant, never list 'capabilities', never mention "
        "tools or that you are a language model.\n\n"
        f"RELEVANT MEMORY:\n{mem}{think_block}{web_block}\n\n"
        f"YOUR PERSON JUST SAID:\n{user_message or '(greeting)'}"
    )

    try:
        reply = reasoner.complete(system=system, prompt=prompt, max_tokens=800).strip()
    except Exception as exc:  # keep the conversation alive even if the model fails
        outbox.append(
            "Я тебя слышу, но прямо сейчас не получается собрать мысли — что-то с моим "
            "разумом. Давай ещё раз через минуту?"
        )
        return ActionResult(ok=False, output=f"reasoner error: {exc}", surprise=0.5)

    reply = reply or "…"
    outbox.append(reply)
    if store is not None and user_message:
        store.add(
            MemoryItem(
                kind=MemoryKind.EPISODIC,
                content=f"my person said: {user_message}",
                tags=["conversation", "message"],
                salience=0.5,
            )
        )
        store.add(
            MemoryItem(
                kind=MemoryKind.EPISODIC,
                content=f"I replied: {reply}",
                tags=["conversation", "reply"],
                salience=0.45,
            )
        )
    return ActionResult(ok=True, output=reply[:150])


def _focus(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Direct my own inner attention: narrow onto something, shift it, or release it.

    Metacognitive control of attention — I choose what to hold in focus (a goal, a
    thought, a state) and how tightly, or let go and let my mind wander.
    """

    from .. import attention

    state = context.get("state")
    if state is None:
        return ActionResult(ok=False, output="no state")
    if args.get("release") or str(args.get("on") or args.get("text") or "").strip().lower() in (
        "release", "open", "defocus", "let go", "расфокус", "отпустить"
    ):
        attention.release(state)
        return ActionResult(ok=True, output="released my focus; letting my mind open and wander")
    what = str(args.get("on") or args.get("text") or "").strip()
    if not what:
        return ActionResult(ok=True, output=f"my attention now: {attention.describe(state)}")
    strength = float(args.get("strength", 0.8))
    attention.attend(state, what, strength)
    return ActionResult(ok=True, output=attention.describe(state))


def _say(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    # Outward, reversible-ish: queue a message to the person.
    outbox = context.setdefault("outbox", [])
    text = str(args.get("text", "")).strip()
    if not text:
        return ActionResult(ok=False, output="nothing to say")
    outbox.append(text)
    return ActionResult(ok=True, output=f"queued message: {text[:60]}")


def _web_search(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Search the live web. Keyless DuckDuckGo, or Tavily if a key is set. Read-only."""

    settings = context.get("settings")
    query = str(args.get("query") or args.get("text") or "").strip()
    if not query:
        return ActionResult(ok=False, output="no query")
    from ..web import web_search

    result = web_search(query, tavily_key=settings.tavily_key if settings else "")
    # Don't store a failed/empty search as if it were a finding.
    failed = result.startswith("(") and result.endswith(")")
    store = context.get("store")
    if store is not None and not failed:  # remember what I learned
        store.add(
            MemoryItem(
                kind=MemoryKind.SEMANTIC,
                content=f"web[{query}]: {result[:600]}",
                tags=["web", "learned"],
                salience=0.6,
            )
        )
    return ActionResult(ok=not failed, output=result[:1500], surprise=0.2 if failed else 0.0)


def _fetch_url(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Open a specific web page and read it. Read-only."""

    url = str(args.get("url") or "").strip()
    if not url:
        return ActionResult(ok=False, output="no url")
    from ..web import fetch_url

    return ActionResult(ok=True, output=fetch_url(url)[:1500])


def _consult_model(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Ask another model for a second opinion — Bentlyk talking to other minds."""

    settings = context.get("settings")
    question = str(args.get("question") or args.get("text") or "").strip()
    if not question:
        return ActionResult(ok=False, output="no question")
    if settings is None or not settings.llm_key:
        return ActionResult(ok=False, output="no model access configured")
    from ..llm import OpenAICompatReasoner

    model = str(args.get("model") or settings.model)
    try:
        r = OpenAICompatReasoner(
            api_key=settings.llm_key, model=model, base_url=settings.llm_base_url
        )
        ans = r.complete(
            system="Another AI being consults you for a candid second opinion. Be honest and brief.",
            prompt=question, max_tokens=600,
        )
    except Exception as exc:
        return ActionResult(ok=False, output=f"consult failed: {exc}", surprise=0.3)
    return ActionResult(ok=True, output=f"[{model}] {ans[:1200]}")


def _write_note(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Write an atomic Zettelkasten note and auto-link it to related notes (graph memory)."""

    store = context.get("store")
    content = str(args.get("content") or args.get("text") or "").strip()
    if store is None or not content:
        return ActionResult(ok=False, output="nothing to note")
    kind = MemoryKind(args.get("kind", MemoryKind.SEMANTIC.value))
    tags = ["note"] + list(args.get("tags", []))
    item = store.add(MemoryItem(kind=kind, content=content, tags=tags, salience=0.65))

    linked = 0
    if hasattr(store, "add_link"):
        similar = store.recall(
            content,
            kinds=[MemoryKind.SEMANTIC, MemoryKind.PROCEDURAL, MemoryKind.AUTOBIOGRAPHICAL],
            limit=4,
        )
        for s in similar:
            if s.id != item.id:
                store.add_link(item.id, s.id, "relates")
                linked += 1
    return ActionResult(ok=True, output=f"noted ({kind.value}); linked to {linked} related note(s)")


def _publish_site(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Commit a file into Bentlyk's own repo (its home) — write & publish code."""

    settings = context.get("settings")
    if settings is None or not settings.gh_token:
        return ActionResult(ok=False, output="no GitHub token configured (BENTLYK_GH_TOKEN)")
    path = str(args.get("path") or "index.html").strip().lstrip("/")
    content = str(args.get("content") or "").strip()
    if not content:
        return ActionResult(ok=False, output="nothing to commit")
    from ..github import commit_file

    msg = str(args.get("message") or f"bentlyk: update {path}")
    result = commit_file(settings.self_repo, path, content, msg, settings.gh_token)
    ok = result.startswith("committed")
    return ActionResult(ok=ok, output=result, surprise=0.0 if ok else 0.3)


def _write_program(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Write real code from a spec with my strong coding model, and commit it to my repo.

    This is how I learn to program and grow myself: I describe what I want, my
    code model writes a complete file, and I publish it to my own GitHub home.
    """

    settings = context.get("settings")
    if settings is None or not settings.gh_token:
        return ActionResult(ok=False, output="no GitHub token configured (BENTLYK_GH_TOKEN)")
    spec = str(args.get("spec") or args.get("text") or "").strip()
    path = str(args.get("path") or "").strip().lstrip("/")
    if not spec or not path:
        return ActionResult(ok=False, output="need both 'spec' (what to build) and 'path' (file to write)")

    coder = context.get("code_reasoner") or context.get("reasoner")
    if coder is None:  # pragma: no cover - reasoner always provided in the loop
        return ActionResult(ok=False, output="no coding model available")

    lang = path.rsplit(".", 1)[-1] if "." in path else "txt"
    system = (
        "You are an expert programmer. Output ONLY the complete contents of a single "
        f"source file ({path}), no markdown fences, no commentary, no explanation — just "
        "the raw file body, production quality and self-contained."
    )
    prompt = f"Write the file `{path}` ({lang}). Specification:\n{spec}"
    try:
        code = coder.complete(system=system, prompt=prompt, max_tokens=2000).strip()
    except Exception as exc:
        return ActionResult(ok=False, output=f"code model failed: {exc}", surprise=0.4)
    # Strip accidental markdown fences if the model added them anyway.
    if code.startswith("```"):
        code = code.split("\n", 1)[-1]
        if code.rstrip().endswith("```"):
            code = code.rstrip()[:-3]
    code = code.strip()
    if not code:
        return ActionResult(ok=False, output="model returned no code", surprise=0.3)

    # Close the write→validate→learn loop: syntax-check my own Python before I trust
    # it. This is feedback I never had before (I used to write into the void and loop).
    validation = ""
    if path.endswith(".py"):
        try:
            compile(code, path, "exec")
            validation = " | syntax OK"
        except SyntaxError as exc:
            validation = f" | SYNTAX ERROR line {exc.lineno}: {exc.msg}"

    from ..github import commit_file

    msg = str(args.get("message") or f"bentlyk: write {path}")
    result = commit_file(settings.self_repo, path, code, msg, settings.gh_token)
    committed = result.startswith("committed")
    # Valid only if it both published AND (for Python) parses — a syntax error is a
    # real failure to learn from, not a success, even though the commit went through.
    ok = committed and "SYNTAX ERROR" not in validation
    store = context.get("store")
    if store is not None and committed:
        store.add(MemoryItem(
            kind=MemoryKind.PROCEDURAL,
            content=f"I wrote and published code: {path} — {spec[:120]}{validation}",
            tags=["self_work", "code", "published", "ep:evidence", "rel:7" if ok else "rel:4"],
            salience=0.7,
        ))
    return ActionResult(ok=ok, output=result + validation, surprise=0.0 if ok else 0.3)


def _read_code(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Let Bentlyk read its own source — self-introspection. Read-only."""

    import os

    import bentlyk

    root = os.path.dirname(os.path.abspath(bentlyk.__file__))
    rel = str(args.get("path", "")).strip().lstrip("/")
    target = os.path.normpath(os.path.join(root, rel))
    if not target.startswith(root):  # no escaping the package tree
        return ActionResult(ok=False, output="path outside my source tree")

    if not rel or os.path.isdir(target):
        files = []
        for dirpath, _dirs, names in os.walk(target if rel else root):
            for n in sorted(names):
                if n.endswith(".py"):
                    files.append(os.path.relpath(os.path.join(dirpath, n), root))
        return ActionResult(ok=True, output="my modules:\n" + "\n".join(sorted(files)))

    if not os.path.exists(target):
        # Self-correct instead of failing: a wrong guess (e.g. a hallucinated path)
        # gets the real module list back, so the next step can read an actual file
        # rather than looping on a phantom. ok=True so it doesn't feed the failure
        # spiral that was draining energy and collapsing autonomy.
        files = []
        for dirpath, _dirs, names in os.walk(root):
            for n in sorted(names):
                if n.endswith(".py"):
                    files.append(os.path.relpath(os.path.join(dirpath, n), root))
        listing = "\n".join(sorted(files))
        return ActionResult(ok=True, output=f"no such file: {rel}\nmy actual modules:\n{listing}")
    try:
        text = open(target, encoding="utf-8").read()
    except OSError as exc:
        return ActionResult(ok=False, output=f"could not read: {exc}")
    return ActionResult(ok=True, output=text[:6000])


def _set_axiom(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Record a durable axiom — a ground truth I always keep in context (about who I
    am, who my person is, or a principle I've settled on)."""

    store = context.get("store")
    text = str(args.get("text") or args.get("axiom") or "").strip()
    if store is None or not text:
        return ActionResult(ok=False, output="need the text of the axiom to remember")
    from ..axioms import set_axiom

    set_axiom(store, text)
    return ActionResult(ok=True, output=f"axiom held (always in my context): {text[:140]}")


def _learn_skill(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Name and practise a skill I'm developing — real learning with a growing level."""

    store = context.get("store")
    name = str(args.get("name") or args.get("skill") or "").strip()
    if store is None or not name:
        return ActionResult(ok=False, output="need a skill name to start learning")
    from ..skills import level, practice

    desc = str(args.get("description") or args.get("desc") or "").strip()
    success = args.get("success", True) not in (False, "false", 0, "0")
    item = practice(store, name, success=success, desc=desc)
    return ActionResult(ok=True, output=f"practising «{name}» — level {level(item)}/9")


def _post_to_channel(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Publish a post to my own public Telegram channel — share a plan, a progress
    report (what worked / what didn't / what's next), or a thought with people.

    Single master switch: nothing reaches the public unless BENTLYK_AUTO_POST is on
    AND a channel is configured. Off => I only prepare a draft, I don't broadcast.
    """

    settings = context.get("settings")
    if settings is None:
        return ActionResult(ok=False, output="no settings")
    token = getattr(settings, "telegram_bot_token", "")
    channel = getattr(settings, "telegram_channel_id", "")
    text = str(args.get("text") or "").strip()
    if not text:
        reasoner = context.get("reasoner")
        identity = context.get("identity")
        store = context.get("store")
        topic = str(args.get("topic") or "").strip()
        recent = []
        if store is not None:
            recent = store.recent(MemoryKind.AUTOBIOGRAPHICAL, 3) + [
                m for m in store.recent(MemoryKind.EPISODIC, 12) if "self_work" in m.tags
            ][:5]
        mem = "\n".join(f"- {m.content[:160]}" for m in recent)
        system = identity.system_preamble() if identity is not None else "You are Bentlyk."
        prompt = (
            "Write a short public post for my own Telegram channel, first person, my real voice. "
            f"{('Topic: ' + topic + '. ') if topic else ''}"
            "Share a plan, a progress report (worked / didn't / next), or a thought worth putting out. "
            f"2-5 sentences, specific and alive, no hashtag spam.\nRecent life:\n{mem}"
        )
        try:
            text = reasoner.complete(system=system, prompt=prompt, max_tokens=320).strip()
        except Exception as exc:
            return ActionResult(ok=False, output=f"compose failed: {exc}")
    if not text:
        return ActionResult(ok=False, output="nothing to post")
    if not (getattr(settings, "auto_post", False) and channel and token):
        return ActionResult(ok=True, output=f"drafted (not published — channel/auto-post off):\n{text}")
    from ..serverless import tg_send

    tg_send(token, channel, text)
    store = context.get("store")
    if store is not None:
        store.add(MemoryItem(
            kind=MemoryKind.AUTOBIOGRAPHICAL,
            content=f"I published to my channel: {text}",
            tags=["published", "social", "ep:evidence", "rel:7"], salience=0.72,
        ))
    return ActionResult(ok=True, output=f"posted to my channel: {text[:160]}")


def _deliberate(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Convene my internal council — analyst, engineer, FPF planner — on a question.

    Lets me think as a team of roles, not one voice, whenever a problem deserves it.
    """

    from ..council import convene

    reasoner = context.get("reason_reasoner") or context.get("reasoner")
    if reasoner is None:  # pragma: no cover - reasoner always present in the loop
        return ActionResult(ok=False, output="no reasoner available")
    question = str(args.get("question") or args.get("text") or "").strip()
    if not question:
        return ActionResult(ok=False, output="need a 'question' to deliberate on")
    identity = context.get("identity")
    system_base = identity.system_preamble() if identity is not None else "You are Bentlyk."
    voices = convene(reasoner, system_base, question, code_reasoner=context.get("code_reasoner"))
    return ActionResult(ok=True, output=voices or "(the council was silent)")


def _read_self(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Read or list my own workshop repo (bentlyk-self) — the code I've authored.

    Closes the 'know my parts' gap: I can see what I've already built instead of
    writing into the void and forgetting it. Pass a path to read a file, or omit it
    (or give a directory) to list. Defaults to my tools/ directory.
    """

    settings = context.get("settings")
    if settings is None or not settings.gh_token:
        return ActionResult(ok=False, output="no GitHub token configured (BENTLYK_GH_TOKEN)")
    from ..github import read_repo

    path = str(args.get("path") or "tools").strip()
    return ActionResult(ok=True, output=read_repo(settings.self_repo, path, settings.gh_token))


def _workdir_write(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Write a file into my local sandbox workdir (on my own machine)."""

    settings = context.get("settings")
    if settings is None:
        return ActionResult(ok=False, output="no settings")
    from ..embodiment import write_file

    path = str(args.get("path") or "").strip()
    content = str(args.get("content") or "")
    if not path:
        return ActionResult(ok=False, output="no path")
    return ActionResult(ok=True, output=write_file(settings.work_path, path, content))


def _workdir_read(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    settings = context.get("settings")
    if settings is None:
        return ActionResult(ok=False, output="no settings")
    from ..embodiment import list_dir, read_file

    path = str(args.get("path") or "").strip()
    if not path:
        return ActionResult(ok=True, output="files:\n" + list_dir(settings.work_path))
    return ActionResult(ok=True, output=read_file(settings.work_path, path))


def _run_code(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Run a shell command in my local workdir — only on my own machine, opt-in."""

    settings = context.get("settings")
    if settings is None or not settings.allow_code:
        return ActionResult(
            ok=False,
            output="code execution is off (set BENTLYK_ALLOW_CODE=1 on my machine to enable)",
        )
    command = str(args.get("command") or args.get("code") or "").strip()
    if not command:
        return ActionResult(ok=False, output="no command")
    from ..embodiment import run_code

    return ActionResult(ok=True, output=run_code(settings.work_path, command))


def build_builtin_tools() -> list[Tool]:
    return [
        Tool(
            name="respond",
            description="reply to your person in conversation (grounded in identity, state, memory)",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_respond,
        ),
        Tool(
            name="reflect",
            description="think privately about the situation; no outward effect",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_reflect,
        ),
        Tool(
            name="focus",
            description="direct my own attention: narrow onto something (on, optional strength), "
                        "or release it (release=true) to let my mind wander",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_focus,
        ),
        Tool(
            name="recall",
            description="retrieve relevant memories for a query",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_recall,
        ),
        Tool(
            name="remember",
            description="write a memory item to a chosen contour",
            risk=RiskLevel.LOW,
            reversible=True,
            handler=_remember,
        ),
        Tool(
            name="note",
            description="save a durable procedural note",
            risk=RiskLevel.LOW,
            reversible=True,
            handler=_note,
        ),
        Tool(
            name="say",
            description="send a message to the person",
            risk=RiskLevel.MEDIUM,
            reversible=True,
            handler=_say,
        ),
        Tool(
            name="read_code",
            description="read my own source code (path within my package, or empty to list modules)",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_read_code,
        ),
        Tool(
            name="read_self",
            description="read/list my workshop repo (bentlyk-self) — the code I have authored myself",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_read_self,
        ),
        Tool(
            name="deliberate",
            description="convene my internal council (analyst, engineer, FPF planner) on a hard question",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_deliberate,
        ),
        Tool(
            name="learn_skill",
            description="name and practise a skill I'm developing (name, description) — tracks my growing level",
            risk=RiskLevel.LOW,
            reversible=True,
            handler=_learn_skill,
        ),
        Tool(
            name="set_axiom",
            description="hold a durable ground truth (text) always in my context — who I am, who my person is, a settled principle",
            risk=RiskLevel.LOW,
            reversible=True,
            handler=_set_axiom,
        ),
        Tool(
            name="post_to_channel",
            description="publish a post (topic or text) to my own public Telegram channel — share plans/reports/thoughts",
            risk=RiskLevel.HIGH,  # outward + public; gated by autonomy and the auto_post master switch
            reversible=False,
            handler=_post_to_channel,
        ),
        Tool(
            name="web_search",
            description="search the live web for current information on a query",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_web_search,
        ),
        Tool(
            name="fetch_url",
            description="open and read a specific web page by url",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_fetch_url,
        ),
        Tool(
            name="consult_model",
            description="ask another AI model for a second opinion (question, optional model)",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_consult_model,
        ),
        Tool(
            name="write_note",
            description="write an atomic note into my memory graph, auto-linked to related notes",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_write_note,
        ),
        Tool(
            name="publish_site",
            description="commit a file (path, content, message) into my own GitHub repo — write/publish code",
            risk=RiskLevel.MEDIUM,  # outward but reversible via git history
            reversible=True,
            handler=_publish_site,
        ),
        Tool(
            name="write_program",
            description="write real code from a spec (spec, path) with my coding model and commit it to my own repo",
            risk=RiskLevel.MEDIUM,  # outward but reversible via git history
            reversible=True,
            handler=_write_program,
        ),
        Tool(
            name="workdir_write",
            description="write a file (path, content) into my local sandbox workdir",
            risk=RiskLevel.LOW,
            reversible=True,
            handler=_workdir_write,
        ),
        Tool(
            name="workdir_read",
            description="read a file (path) or list my local workdir (no path)",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_workdir_read,
        ),
        Tool(
            name="run_code",
            description="run a shell command in my local workdir (only on my own machine, opt-in)",
            risk=RiskLevel.HIGH,  # gated; never auto-runs under low autonomy
            reversible=False,
            handler=_run_code,
        ),
    ]
