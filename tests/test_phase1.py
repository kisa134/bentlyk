from bentlyk.actions import default_registry
from bentlyk.memory import MemoryItem, MemoryKind, SqliteMemoryStore
from bentlyk.web import _html_to_text, _is_internal, fetch_url, web_search


def make_store():
    return SqliteMemoryStore(":memory:")


# --- graph memory -------------------------------------------------------------
def test_links_and_neighbors():
    store = make_store()
    a = store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="zettelkasten is a note method"))
    b = store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="graphs connect ideas"))
    store.add_link(a.id, b.id, "relates")
    n = store.neighbors([a.id])
    assert [m.id for m in n] == [b.id]
    # reverse direction too
    assert [m.id for m in store.neighbors([b.id])] == [a.id]


def test_forget_removes_links():
    store = make_store()
    a = store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="a"))
    b = store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="b"))
    store.add_link(a.id, b.id)
    store.forget(a.id)
    assert store.neighbors([b.id]) == []


def test_write_note_tool_autolinks():
    store = make_store()
    store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="memory graphs link related notes"))
    tool = default_registry().get("write_note")
    res = tool.run({"content": "a memory graph connects notes into a web"}, {"store": store})
    assert res.ok and "linked to" in res.output
    # the new note exists and has at least one edge
    notes = [m for m in store.all(MemoryKind.SEMANTIC) if "note" in m.tags]
    assert notes and store.neighbors([notes[0].id])


# --- web ----------------------------------------------------------------------
def test_web_search_without_key_is_graceful():
    out = web_search("anything", api_key="", base_url="https://x", model="m")
    assert "no web access" in out


def test_fetch_url_guards():
    assert "http/https" in fetch_url("ftp://example.com")
    assert "internal" in fetch_url("http://localhost:8000/")


def test_is_internal():
    assert _is_internal("localhost")
    assert _is_internal("printer.local")


def test_html_to_text_strips_markup():
    txt = _html_to_text("<html><body><h1>Hi</h1><script>x=1</script><p>there &amp; you</p></body></html>")
    assert "Hi" in txt and "there & you" in txt and "x=1" not in txt


# --- consult ------------------------------------------------------------------
def test_consult_model_without_settings_is_graceful():
    tool = default_registry().get("consult_model")
    assert tool.run({"question": "hi"}, {}).ok is False


def test_new_tools_are_registered():
    names = set(default_registry().names())
    assert {"web_search", "fetch_url", "consult_model", "write_note"} <= names
