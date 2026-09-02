---
name: corpus-query
description: Hybrid retrieval (dense sqlite-vec + sparse BM25, RRF-fused, optional local rerank) over a consolidated webcollect corpus, returning passages with full provenance. The shared retrieval primitive behind corpus-stats / corpus-anecdotes / corpus-brief.
allowed-tools: [Bash, Read]
---

# corpus-query

Retrieve the most relevant chunks for a question, each carrying source_url +
content_hash + tier so answers stay traceable.

```
.venv/bin/python cli.py query <corpus> "your question" --k 10
.venv/bin/python cli.py query <corpus> "your question" --k 10 --rerank --tier-max 2
```
- `--rerank` adds a local cross-encoder (BAAI/bge-reranker-v2-m3) pass over the fused
  top candidates (first use downloads the model; falls back to fused order if unavailable).
- `--tier-max N` restricts to sources at tier ≤ N (e.g. `--tier-max 2` = primary + reputable only).

Pipeline: dense KNN (local embeddings) ⊕ BM25 (DuckDB FTS, rank_bm25 fallback) → reciprocal-
rank fusion → optional rerank. Programmatic use: `lib/query.py:hybrid_search(con, vc, cfg, q)`
returns dicts with `text, source_url, content_hash, retrieved_at, source_tier, fused_score`.

To resolve a specific claim's evidence: `.venv/bin/python cli.py prov <corpus> <claim_id>`.
