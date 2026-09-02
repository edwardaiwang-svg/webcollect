"""sqlite-vec vector store. embed_id joins back to DuckDB chunks.embed_id."""
from __future__ import annotations
import sqlite3
from pathlib import Path

import sqlite_vec


def open_vec(path: Path, dim: int) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
          embed_id INTEGER PRIMARY KEY,
          embedding float[{dim}],
          +chunk_id TEXT,
          +doc_id TEXT,
          +source_tier INTEGER,
          +published_at INTEGER
        )
        """
    )
    conn.commit()
    return conn


def add(conn, embed_id, vec, chunk_id, doc_id, source_tier=3, published_at=None):
    conn.execute(
        "INSERT OR REPLACE INTO vec_chunks(embed_id, embedding, chunk_id, doc_id, source_tier, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (int(embed_id), sqlite_vec.serialize_float32(list(vec)), chunk_id, doc_id, int(source_tier), published_at),
    )


def add_many(conn, rows):
    """rows: iterable of (embed_id, vec, chunk_id, doc_id, source_tier, published_at)."""
    for r in rows:
        add(conn, *r)
    conn.commit()


def knn(conn, qvec, k: int = 10):
    """Return [(embed_id, chunk_id, doc_id, distance), ...] nearest to qvec."""
    cur = conn.execute(
        "SELECT embed_id, chunk_id, doc_id, distance FROM vec_chunks "
        "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (sqlite_vec.serialize_float32(list(qvec)), int(k)),
    )
    return cur.fetchall()


def count(conn) -> int:
    return conn.execute("SELECT count(*) FROM vec_chunks").fetchone()[0]
