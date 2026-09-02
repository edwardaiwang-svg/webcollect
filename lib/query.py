"""Hybrid retrieval with provenance attached to every hit.

Stage 1: dense (sqlite-vec KNN over local embeddings) + sparse (DuckDB FTS
BM25, with a rank_bm25 fallback if the FTS extension is unavailable), fused by
reciprocal-rank fusion. Stage 2 (optional): local cross-encoder rerank
(BAAI/bge-reranker-v2-m3). Every returned hit carries source_url, content_hash,
retrieved_at and source_tier so downstream claims stay traceable.
"""
from __future__ import annotations
import functools

from lib import embed as embedlib
from lib import vectors as veclib

RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


def _dense(vc, cfg, query, k):
    try:
        qv = embedlib.embed_texts([query], model_name=cfg["embed_model"], is_query=True)[0]
    except Exception:  # noqa: BLE001  (model offline -> dense skipped)
        return []
    return [(cid, rank) for rank, (_eid, cid, _doc, _dist) in enumerate(veclib.knn(vc, qv, k=k))]


def _sparse(con, query, k):
    # DuckDB FTS first
    try:
        rows = con.execute(
            "SELECT chunk_id, fts_main_chunks.match_bm25(chunk_id, ?) AS s "
            "FROM chunks WHERE s IS NOT NULL ORDER BY s DESC LIMIT ?",
            [query, k],
        ).fetchall()
        if rows:
            return [(r[0], rank) for rank, r in enumerate(rows)]
    except Exception:  # noqa: BLE001  (no FTS index)
        pass
    # rank_bm25 fallback over all chunks
    try:
        from rank_bm25 import BM25Okapi

        allrows = con.execute("SELECT chunk_id, text FROM chunks").fetchall()
        if not allrows:
            return []
        corpus = [t.lower().split() for _, t in allrows]
        bm = BM25Okapi(corpus)
        scores = bm.get_scores(query.lower().split())
        order = sorted(range(len(allrows)), key=lambda i: scores[i], reverse=True)[:k]
        return [(allrows[i][0], rank) for rank, i in enumerate(order)]
    except Exception:  # noqa: BLE001
        return []


def _rrf(rank_lists, kconst: int = 60):
    fused: dict[str, float] = {}
    for rl in rank_lists:
        for cid, rank in rl:
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (kconst + rank)
    return sorted(fused.items(), key=lambda kv: kv[1], reverse=True)


@functools.lru_cache(maxsize=1)
def _reranker(name: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(name)


def _attach_provenance(con, chunk_ids):
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    rows = con.execute(
        f"""SELECT c.chunk_id, c.text, c.doc_id, d.source_url, d.content_hash,
                   d.retrieved_at, d.published_at, d.source_tier, d.title
            FROM chunks c JOIN documents d ON d.doc_id = c.doc_id
            WHERE c.chunk_id IN ({placeholders})""",
        list(chunk_ids),
    ).fetchall()
    cols = ["chunk_id", "text", "doc_id", "source_url", "content_hash",
            "retrieved_at", "published_at", "source_tier", "title"]
    return {r[0]: dict(zip(cols, r)) for r in rows}


def hybrid_search(con, vc, cfg, query: str, k: int = 10, candidates: int = 50,
                  rerank: bool = False, tier_max: int | None = None) -> list[dict]:
    dense = _dense(vc, cfg, query, candidates)
    sparse = _sparse(con, query, candidates)
    fused = _rrf([dense, sparse])
    cand_ids = [cid for cid, _ in fused[:candidates]]
    prov = _attach_provenance(con, cand_ids)

    hits = []
    for cid, score in fused:
        meta = prov.get(cid)
        if not meta:
            continue
        if tier_max is not None and (meta.get("source_tier") or 99) > tier_max:
            continue
        meta["fused_score"] = score
        hits.append(meta)
        if len(hits) >= max(k, candidates if rerank else k):
            break

    if rerank and hits:
        try:
            pairs = [(query, h["text"]) for h in hits]
            scores = _reranker(RERANK_MODEL).predict(pairs)
            for h, s in zip(hits, scores):
                h["rerank_score"] = float(s)
            hits.sort(key=lambda h: h["rerank_score"], reverse=True)
        except Exception as e:  # noqa: BLE001
            for h in hits:
                h.setdefault("rerank_score", None)
            hits[0]["_rerank_note"] = f"rerank skipped: {e}"

    return hits[:k]
