"""Real (provider-agnostic) embeddings with a safe fallback to the hash embedding."""

import bentlyk.memory.base as mb
from bentlyk.agent import Agent
from bentlyk.config import Settings
from bentlyk.memory import MemoryItem, MemoryKind
from bentlyk.memory.base import configure_embeddings, cosine, embed, embeddings_active


def teardown_function():
    configure_embeddings()  # always reset to hash mode so other tests are unaffected


def test_default_is_hash_mode():
    configure_embeddings()
    assert not embeddings_active()
    assert len(embed("привет мир")) == mb._DIM


def test_configured_uses_remote(monkeypatch):
    configure_embeddings(model="m", base_url="https://x/v1", key="k")
    assert embeddings_active()
    monkeypatch.setattr(mb, "_remote_embed", lambda text, timeout=20.0: [0.0, 0.0, 1.0])
    assert embed("hello") == [0.0, 0.0, 1.0]


def test_falls_back_to_hash_on_error(monkeypatch):
    configure_embeddings(model="m", base_url="https://x/v1", key="k")

    def boom(text, timeout=20.0):
        raise RuntimeError("provider down")

    monkeypatch.setattr(mb, "_remote_embed", boom)
    assert len(embed("hello")) == mb._DIM  # degraded to hash, never raised


def test_cosine_is_dimension_safe():
    # Old hash vectors (256-d) and new real vectors coexist without crashing.
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0
    assert abs(cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9


def test_reembed_backfills_legacy_vectors(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "_remote_embed", lambda text, timeout=20.0: [1.0, 2.0, 3.0])
    s = Settings(
        sqlite_path=tmp_path / "b.db", supabase_url="", supabase_key="",
        embed_model="m", embed_base_url="https://x/v1", embed_key="k",
    )
    agent = Agent(settings=s)  # __init__ configures embeddings from settings
    try:
        # a legacy item carrying a hash-dimension (256) vector
        agent.store.add(MemoryItem(
            kind=MemoryKind.SEMANTIC, content="legacy", embedding=[0.0] * mb._DIM
        ))
        migrated = agent.reembed()
        assert migrated >= 1
    finally:
        agent.close()
