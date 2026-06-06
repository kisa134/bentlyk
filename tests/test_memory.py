import time

from bentlyk.memory import MemoryItem, MemoryKind, SqliteMemoryStore
from bentlyk.memory.base import cosine, embed


def make_store():
    return SqliteMemoryStore(":memory:")


def test_add_and_get():
    store = make_store()
    item = store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="the sky is blue"))
    got = store.get(item.id)
    assert got is not None and got.content == "the sky is blue"
    assert got.embedding  # auto-embedded on add


def test_recall_ranks_relevant_first():
    store = make_store()
    store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="python is a programming language"))
    store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="bananas are yellow fruit"))
    hits = store.recall("which programming language do I use", limit=1)
    assert hits and "python" in hits[0].content


def test_recall_filters_by_kind():
    store = make_store()
    store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="fact about cats"))
    store.add(MemoryItem(kind=MemoryKind.EPISODIC, content="cats appeared in the conversation"))
    hits = store.recall("cats", kinds=[MemoryKind.EPISODIC])
    assert all(h.kind == MemoryKind.EPISODIC for h in hits)


def test_decay_prunes_faded_episodic_but_keeps_semantic():
    store = make_store()
    old = time.time() - 86400 * 30  # 30 days ago
    store.add(MemoryItem(kind=MemoryKind.EPISODIC, content="trivial", salience=0.1, created_at=old))
    store.add(
        MemoryItem(kind=MemoryKind.SEMANTIC, content="durable fact", salience=0.1, created_at=old)
    )
    forgotten = store.decay_and_prune()
    assert forgotten == 1
    assert store.all(MemoryKind.EPISODIC) == []
    assert len(store.all(MemoryKind.SEMANTIC)) == 1


def test_embedding_is_deterministic():
    assert embed("hello world") == embed("hello world")
    assert cosine(embed("dog"), embed("dog")) > 0.99


def test_recall_increments_use_count():
    store = make_store()
    item = store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="reusable knowledge"))
    store.recall("reusable knowledge")
    refreshed = store.get(item.id)
    assert refreshed.use_count >= 1
