#!/usr/bin/env python3
"""webcollect CLI — the deterministic, $0 glue the skills drive.

LLM map/reduce orchestration lives in the SKILL.md files (Workflow tool); this
CLI handles everything non-LLM: init, ingest (url/file/reddit/stats), the
deterministic consolidation steps (chunk+embed, load validated extractions,
resolve conflicts), sharding for the map step, hybrid query, and provenance.

  python cli.py init <corpus> [--zh]
  python cli.py ingest-url <corpus> <url> [--tier N]
  python cli.py ingest-file <corpus> <path> [--tier N --source-url U]
  python cli.py ingest-reddit <corpus> <subreddit> [--limit N --sort new --query Q]
  python cli.py ingest-stats <corpus> --fred SERIES [--fred ...] [--finnhub SYM]
  python cli.py chunk-embed <corpus>            # embed all 'parsed' docs
  python cli.py build-fts <corpus>
  python cli.py shards <corpus> [--shard-tokens 100000]   # emit shard plans (chunk_ids) as JSON
  python cli.py load-extraction <corpus> <doc_id> <extraction.json>
  python cli.py resolve-conflicts <corpus>
  python cli.py query <corpus> "<question>" [--k 10 --rerank --tier-max N]
  python cli.py prov <corpus> <claim_id>
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import db, consolidate, provenance, embed  # noqa: E402


def load_env():
    """Load the repo-local .env into os.environ."""
    for envf in (Path(__file__).with_name(".env"),):
        if envf.exists():
            for line in envf.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cmd_init(a):
    model = "intfloat/multilingual-e5-small" if a.zh else embed.DEFAULT_MODEL
    p = db.init_corpus(a.corpus, embed_model=model, embed_dim=embed.DEFAULT_DIM)
    print(f"initialized corpus '{a.corpus}' at {p['dir']} (model={model})")


def cmd_ingest_url(a):
    from lib import fetch
    con, vc, _ = db.connect(a.corpus)
    p = db.corpus_paths(a.corpus)
    doc_id, new = fetch.ingest_http(con, p["dir"], a.url, source_tier=a.tier)
    con.close(); vc.close()
    print(f"{'+' if new else '='} {doc_id}  {a.url}")


def cmd_ingest_file(a):
    from lib import fetch
    con, vc, _ = db.connect(a.corpus)
    p = db.corpus_paths(a.corpus)
    text = Path(a.path).read_text(errors="ignore")
    doc_id, new = fetch.ingest_text(con, p["dir"], text=text,
                                    source_url=a.source_url or f"file://{Path(a.path).resolve()}",
                                    channel="web", source_tier=a.tier, title=Path(a.path).name)
    con.close(); vc.close()
    print(f"{'+' if new else '='} {doc_id}  {a.path}")


def cmd_ingest_reddit(a):
    load_env()
    from lib import sources_reddit
    con, vc, _ = db.connect(a.corpus)
    p = db.corpus_paths(a.corpus)
    n = sources_reddit.collect_subreddit(con, p["dir"], a.subreddit, limit=a.limit,
                                         sort=a.sort, query=a.query, comment_expand=a.comment_expand)
    con.close(); vc.close()
    print(f"ingested {n} new posts from r/{a.subreddit}")


def cmd_ingest_stats(a):
    load_env()
    from lib import sources_stats
    con, vc, _ = db.connect(a.corpus)
    p = db.corpus_paths(a.corpus)
    for s in a.fred or []:
        n = sources_stats.fred_series(con, p["dir"], s)
        print(f"FRED {s}: {n} observations")
    if a.finnhub:
        j = sources_stats.finnhub_quote(con, p["dir"], a.finnhub)
        print(f"Finnhub {a.finnhub}: {j.get('c')}")
    con.close(); vc.close()


def cmd_chunk_embed(a):
    con, vc, cfg = db.connect(a.corpus)
    docs = con.execute("SELECT doc_id, blob_path, source_tier FROM documents WHERE ingest_status='parsed'").fetchall()
    p = db.corpus_paths(a.corpus)
    from lib import raw_store
    total = 0
    for doc_id, blob_path, tier in docs:
        raw = (p["dir"] / blob_path).read_text(errors="ignore")
        norm = raw_store.normalize_text(raw)
        chunks = consolidate.chunk_and_embed_document(con, vc, doc_id=doc_id, norm_text=norm,
                                                      model_name=cfg["embed_model"], dim=cfg["embed_dim"],
                                                      source_tier=tier or 3)
        total += len(chunks)
    con.close(); vc.close()
    print(f"chunked+embedded {len(docs)} docs -> {total} chunks")


def cmd_build_fts(a):
    con, vc, _ = db.connect(a.corpus)
    ok = db.build_fts(con)
    con.close(); vc.close()
    print("FTS index built" if ok else "FTS unavailable (BM25 fallback will be used)")


def cmd_shards(a):
    con, vc, _ = db.connect(a.corpus)
    rows = con.execute("SELECT chunk_id, doc_id, token_count FROM chunks ORDER BY doc_id, ord").fetchall()
    con.close(); vc.close()
    shards, cur, tok = [], [], 0
    for cid, _doc, tc in rows:
        if tok + (tc or 0) > a.shard_tokens and cur:
            shards.append(cur); cur, tok = [], 0
        cur.append(cid); tok += (tc or 0)
    if cur:
        shards.append(cur)
    print(json.dumps([{"shard": i, "chunk_ids": s} for i, s in enumerate(shards)]))


def cmd_load_extraction(a):
    con, vc, _ = db.connect(a.corpus)
    payload = json.loads(Path(a.json).read_text())
    rows = con.execute("SELECT chunk_id, text FROM chunks WHERE doc_id=?", [a.doc_id]).fetchall()
    ctext = {r[0]: r[1] for r in rows}
    ids, rejected = consolidate.load_extraction(con, payload, ctext, a.doc_id)
    con.close(); vc.close()
    print(json.dumps({"loaded": ids, "rejected": rejected}))


def cmd_resolve(a):
    con, vc, _ = db.connect(a.corpus)
    consolidate.resolve_conflicts(con)
    cont = con.execute("SELECT count(*) FROM contested_claims").fetchone()[0]
    con.close(); vc.close()
    print(f"conflicts resolved; {cont} contested claim(s)")


def cmd_query(a):
    from lib import query as q
    con, vc, cfg = db.connect(a.corpus)
    hits = q.hybrid_search(con, vc, cfg, a.question, k=a.k, rerank=a.rerank, tier_max=a.tier_max)
    con.close(); vc.close()
    for h in hits:
        print(f"[tier {h.get('source_tier')}] {h['source_url']}  {h['content_hash']}")
        print(f"    {h['text'][:200].strip()}")


def cmd_prov(a):
    con, vc, _ = db.connect(a.corpus)
    ev = provenance.resolve_claim(con, a.claim_id)
    con.close(); vc.close()
    for i, e in enumerate(ev, 1):
        print(provenance.footnote(e, i))


def main():
    ap = argparse.ArgumentParser(prog="webcollect")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("corpus"); s.add_argument("--zh", action="store_true"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("ingest-url"); s.add_argument("corpus"); s.add_argument("url"); s.add_argument("--tier", type=int, default=3); s.set_defaults(fn=cmd_ingest_url)
    s = sub.add_parser("ingest-file"); s.add_argument("corpus"); s.add_argument("path"); s.add_argument("--tier", type=int, default=3); s.add_argument("--source-url", default=None); s.set_defaults(fn=cmd_ingest_file)
    s = sub.add_parser("ingest-reddit"); s.add_argument("corpus"); s.add_argument("subreddit"); s.add_argument("--limit", type=int, default=50); s.add_argument("--sort", default="new"); s.add_argument("--query", default=None); s.add_argument("--comment-expand", type=int, default=0); s.set_defaults(fn=cmd_ingest_reddit)
    s = sub.add_parser("ingest-stats"); s.add_argument("corpus"); s.add_argument("--fred", action="append"); s.add_argument("--finnhub", default=None); s.set_defaults(fn=cmd_ingest_stats)
    s = sub.add_parser("chunk-embed"); s.add_argument("corpus"); s.set_defaults(fn=cmd_chunk_embed)
    s = sub.add_parser("build-fts"); s.add_argument("corpus"); s.set_defaults(fn=cmd_build_fts)
    s = sub.add_parser("shards"); s.add_argument("corpus"); s.add_argument("--shard-tokens", type=int, default=100000); s.set_defaults(fn=cmd_shards)
    s = sub.add_parser("load-extraction"); s.add_argument("corpus"); s.add_argument("doc_id"); s.add_argument("json"); s.set_defaults(fn=cmd_load_extraction)
    s = sub.add_parser("resolve-conflicts"); s.add_argument("corpus"); s.set_defaults(fn=cmd_resolve)
    s = sub.add_parser("query"); s.add_argument("corpus"); s.add_argument("question"); s.add_argument("--k", type=int, default=10); s.add_argument("--rerank", action="store_true"); s.add_argument("--tier-max", type=int, default=None); s.set_defaults(fn=cmd_query)
    s = sub.add_parser("prov"); s.add_argument("corpus"); s.add_argument("claim_id"); s.set_defaults(fn=cmd_prov)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
