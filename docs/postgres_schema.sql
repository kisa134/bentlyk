-- Reference DDL for the production memory store (Postgres + pgvector).
-- The MVP ships a SQLite store; implement PgMemoryStore behind the
-- bentlyk.memory.store.MemoryStore protocol to use this.
--
--   createdb bentlyk
--   psql bentlyk -f docs/postgres_schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

-- Embedding dimension must match the embedding model you wire into
-- bentlyk.memory.base.embed (the MVP hashing embedder uses 256).
CREATE TABLE IF NOT EXISTS memory (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN
                   ('short_term','episodic','semantic','procedural','autobiographical')),
    content      TEXT NOT NULL,
    salience     REAL NOT NULL DEFAULT 0.5,
    tags         JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at   DOUBLE PRECISION NOT NULL,
    last_used_at DOUBLE PRECISION NOT NULL,
    use_count    INTEGER NOT NULL DEFAULT 0,
    embedding    vector(256)
);

CREATE INDEX IF NOT EXISTS idx_memory_kind ON memory (kind);
CREATE INDEX IF NOT EXISTS idx_memory_created ON memory (created_at);
-- Approximate nearest-neighbour over cosine distance for recall.
CREATE INDEX IF NOT EXISTS idx_memory_embedding
    ON memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- The self-model sidecar (one row). In SQLite this is a JSON file beside the db.
CREATE TABLE IF NOT EXISTS self_model (
    id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    identity    JSONB NOT NULL,
    state       JSONB NOT NULL,
    updated_at  DOUBLE PRECISION NOT NULL
);

-- Optional audit trail of goals / actions / reflections for observability.
CREATE TABLE IF NOT EXISTS journal (
    id         TEXT PRIMARY KEY,
    ts         DOUBLE PRECISION NOT NULL,
    kind       TEXT NOT NULL,   -- 'goal' | 'decision' | 'action' | 'reflection'
    payload    JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_ts ON journal (ts);
