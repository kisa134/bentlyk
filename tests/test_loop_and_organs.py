"""Closing the loop + organ integration: self-code validation, memory-graph
weaving, and loading self-authored tools as real organs."""

from __future__ import annotations

from bentlyk.actions import default_registry
from bentlyk.agent import Agent
from bentlyk.config import Settings
from bentlyk.memory import MemoryItem, MemoryKind, open_store


def test_weave_graph_links_similar_memories():
    agent = Agent(settings=Settings.from_env(), store=open_store("sqlite"))
    for c in ["cache strategy improves memory speed",
              "memory cache speed optimization",
              "weather is sunny today"]:
        agent.store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content=c, tags=["x"]))
    assert agent._weave_graph(threshold=0.2) >= 1
    # the two cache memories should now be neighbours; recall can expand along them.
    # (neighbors() excludes nodes inside the query set, so ask from a single node.)
    one_cache = next(m.id for m in agent.store.all(MemoryKind.SEMANTIC) if "cache" in m.content)
    assert agent.store.neighbors([one_cache], limit=4)


def test_write_program_validates_its_own_syntax(monkeypatch):
    import bentlyk.github as gh
    import bentlyk.actions.tools as tools

    monkeypatch.setattr(gh, "commit_file",
                        lambda repo, path, text, msg, token, branch="main": f"committed {path}")
    s = Settings.from_env()
    s.gh_token, s.self_repo = "t", "x/y"

    class _Coder:
        def __init__(self, code): self.code = code
        def complete(self, system, prompt, max_tokens=2000): return self.code

    good = tools._write_program(
        {"path": "tools/g.py", "spec": "x"},
        {"settings": s, "code_reasoner": _Coder("def f():\n    return 1\n"), "store": open_store("sqlite")},
    )
    bad = tools._write_program(
        {"path": "tools/b.py", "spec": "x"},
        {"settings": s, "code_reasoner": _Coder("def f(:\n  pass"), "store": open_store("sqlite")},
    )
    assert good.ok and "syntax OK" in good.output
    assert (not bad.ok) and "SYNTAX ERROR" in bad.output  # commit succeeds but it learns it's broken


def test_load_plugins_registers_self_authored_tool(monkeypatch):
    import bentlyk.github as gh
    import bentlyk.plugins as plugins

    plugin = (
        "def register(registry):\n"
        "    def handler(args, context):\n"
        "        return ActionResult(ok=True, output='organ ran')\n"
        "    registry.register(Tool(name='my_organ', description='self-made',\n"
        "        risk=RiskLevel.NONE, reversible=True, handler=handler))\n"
    )

    def fake_read_repo(repo, path, token, branch="main", max_chars=6000):
        return "tools contains:\nfil  tools/my_organ.py" if path == "tools" else plugin

    monkeypatch.setattr(gh, "read_repo", fake_read_repo)
    s = Settings.from_env()
    s.gh_token, s.self_repo, s.load_plugins = "t", "x/y", True
    registry = default_registry()
    loaded = plugins.load_plugins(registry, s)
    assert loaded == ["tools/my_organ.py"]
    assert registry.get("my_organ") is not None


def test_plugins_off_by_default():
    s = Settings.from_env()
    s.gh_token, s.self_repo = "t", "x/y"  # load_plugins stays False
    import bentlyk.plugins as plugins
    assert plugins.load_plugins(default_registry(), s) == []
