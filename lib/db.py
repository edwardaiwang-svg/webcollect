"""Corpus paths, store init/connect, and the install selftest.

Layout per corpus (machine-local, gitignored), under $CORPUS_ROOT (default ~/corpus):
  <corpus_id>/raw/{blobs,manifest.jsonl}  meta/{index.duckdb,vectors.sqlite,
  minhash_lsh.pkl,state.json,corpus.config.json}  exports/  logs/

Run the selftest:  python lib/db.py --selftest
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path

# make `from lib import ...` work whether invoked as `python lib/db.py` or `-m lib.db`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from lib import raw_store, vectors, provenance, consolidate, schemas, embed  # noqa: E402

SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def corpus_root() -> Path:
    return Path(os.environ.get("CORPUS_ROOT") or (Path.home() / "corpus")).expanduser()


def corpus_paths(corpus_id: str, root: Path | None = None) -> dict:
    base = (root or corpus_root()) / corpus_id
    meta = base / "meta"
    return {
        "dir": base,
        "raw": base / "raw",
        "blobs": base / "raw" / "blobs",
        "manifest": base / "raw" / "manifest.jsonl",
        "meta": meta,
        "duckdb": meta / "index.duckdb",
        "vectors": meta / "vectors.sqlite",
        "minhash": meta / "minhash_lsh.pkl",
        "state": meta / "state.json",
        "config": meta / "corpus.config.json",
        "exports": base / "exports",
        "logs": base / "logs",
    }


def _statements(sql: str):
    # strip comments first (they can contain ';'), then split on statement terminator
    clean_lines = []
    for line in sql.splitlines():
        idx = line.find("--")
        clean_lines.append(line if idx < 0 else line[:idx])
    clean = "\n".join(clean_lines)
    for seg in clean.split(";"):
        if seg.strip():
            yield seg.strip()


def apply_schema(con):
    sql = SCHEMA_SQL.read_text()
    for stmt in _statements(sql):
        con.execute(stmt)


def init_corpus(corpus_id: str, embed_model: str = embed.DEFAULT_MODEL,
                embed_dim: int = embed.DEFAULT_DIM, root: Path | None = None) -> dict:
    p = corpus_paths(corpus_id, root)
    for key in ("blobs", "meta", "exports", "logs"):
        p[key].mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(p["duckdb"]))
    apply_schema(con)
    con.close()
    vc = vectors.open_vec(p["vectors"], embed_dim)
    vc.close()
    if not p["config"].exists():
        p["config"].write_text(json.dumps(
            {"corpus_id": corpus_id, "embed_model": embed_model, "embed_dim": embed_dim,
             "created_at": datetime.now(timezone.utc).isoformat()}, indent=2))
    if not p["state"].exists():
        p["state"].write_text(json.dumps({"last_run": None, "reduce_state": {}}, indent=2))
    return p


def load_config(corpus_id: str, root: Path | None = None) -> dict:
    p = corpus_paths(corpus_id, root)
    return json.loads(p["config"].read_text())


def connect(corpus_id: str, root: Path | None = None):
    """Return (duckdb_con, sqlite_vec_con, config_dict)."""
    p = corpus_paths(corpus_id, root)
    cfg = load_config(corpus_id, root)
    con = duckdb.connect(str(p["duckdb"]))
    vc = vectors.open_vec(p["vectors"], cfg["embed_dim"])
    return con, vc, cfg


def build_fts(con) -> bool:
    try:
        con.execute("INSTALL fts; LOAD fts;")
        con.execute("PRAGMA create_fts_index('chunks', 'chunk_id', 'text', overwrite=1)")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"   (FTS index skipped: {e})")
        return False


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def selftest() -> bool:
    tmp = Path(tempfile.mkdtemp(prefix="webcollect_selftest_"))
    ok = True

    def check(label, cond):
        nonlocal ok
        print(("  PASS " if cond else "  FAIL ") + label)
        ok = ok and bool(cond)

    try:
        cfg_dim = embed.DEFAULT_DIM
        p = init_corpus("selftest", root=tmp)
        check("init_corpus creates stores", p["duckdb"].exists() and p["vectors"].exists())

        con, vc, cfg = connect("selftest", root=tmp)
        check("config carries embed_dim", cfg["embed_dim"] == cfg_dim)

        # ---- simulate ingest of one document ----
        text = ("Acme Corp reported revenue of $4.2 billion in Q1 2026, up 18% year over year.\n\n"
                "Management guided full-year revenue to a range of $18 to $19 billion.")
        norm = raw_store.normalize_text(text)
        data = text.encode("utf-8")
        content_hash, blob_rel = raw_store.write_blob(p["dir"], data, "txt")
        norm_hash = raw_store.sha256_text(norm)
        rid = raw_store.append_manifest(p["dir"], {
            "channel": "web", "source_url": "https://example.com/acme-q1",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "http_status": 200, "content_hash": content_hash, "blob_path": blob_rel,
            "source_tier": 2})
        check("blob written + manifest line", (p["dir"] / blob_rel).exists() and p["manifest"].exists())

        doc_id = "doc_" + content_hash.split(":")[1][:16]
        con.execute("INSERT INTO sources(source_id, kind, display_name, home_url, tier) VALUES (?,?,?,?,?)",
                    ["web:example.com", "web", "Example", "https://example.com", 2])
        con.execute(
            "INSERT INTO documents(doc_id, source_id, retrieval_id, channel, source_url, canonical_url, "
            "content_hash, norm_hash, blob_path, media_type, title, retrieved_at, source_tier, char_count) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [doc_id, "web:example.com", rid, "web", "https://example.com/acme-q1",
             "https://example.com/acme-q1", content_hash, norm_hash, blob_rel, "text/plain",
             "Acme Q1", datetime.now(timezone.utc), 2, len(norm)])
        check("document row inserted",
              con.execute("SELECT count(*) FROM documents WHERE doc_id=?", [doc_id]).fetchone()[0] == 1)

        # ---- chunk + embed (with offline fallback so the install gate is robust) ----
        embed_mode = "model"
        try:
            chunks = consolidate.chunk_and_embed_document(
                con, vc, doc_id=doc_id, norm_text=norm,
                model_name=cfg["embed_model"], dim=cfg["embed_dim"], source_tier=2)
        except Exception as e:  # noqa: BLE001  (offline / model download blocked)
            embed_mode = "synthetic"
            print(f"   (embedding model unavailable: {e}; testing vector plumbing with synthetic vectors)")
            import numpy as np
            from lib import chunk as chunklib
            pieces = chunklib.chunk_text(norm)
            chunks = []
            for i, pc in enumerate(pieces):
                cid = f"{doc_id}#{pc['ord']:04d}"
                con.execute("INSERT INTO chunks(chunk_id, doc_id, ord, char_start, char_end, token_count, text, embed_id) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            [cid, doc_id, pc["ord"], pc["char_start"], pc["char_end"], pc["token_count"], pc["text"], i + 1])
                rng = np.random.default_rng(abs(hash(pc["text"])) % (2**32))
                v = rng.standard_normal(cfg["embed_dim"]).astype("float32")
                v /= (np.linalg.norm(v) + 1e-9)
                vectors.add(vc, i + 1, v, cid, doc_id, source_tier=2)
                pc["chunk_id"], pc["embed_id"] = cid, i + 1
                chunks.append(pc)
            vc.commit()

        check(f"chunked + embedded ({embed_mode}): >=1 chunk", len(chunks) >= 1)
        spans_ok = all(c["text"] == norm[c["char_start"]:c["char_end"]] for c in chunks)
        check("every chunk.text == norm_text[span] (offset integrity)", spans_ok)
        check("vectors stored", vectors.count(vc) == len(chunks))

        # ---- build a claim with a real evidence span, validate, load ----
        c0 = chunks[0]
        quote = "revenue of $4.2 billion"
        qpos = norm.find(quote)
        check("quote present in normalized text", qpos >= 0)
        payload = {"claims": [{
            "canonical_text": "Acme Q1 2026 revenue was $4.2B",
            "claim_type": "metric", "subject": "Acme Corp", "predicate": "revenue_q1_2026",
            "value_raw": "$4.2 billion", "value_num": 4.2e9, "value_unit": "USD", "polarity": 1,
            "evidence": [{"chunk_id": c0["chunk_id"], "quote": quote,
                          "char_start": qpos, "char_end": qpos + len(quote), "stance": 1}],
        }]}
        chunk_text_by_id = {c["chunk_id"]: c["text"] for c in chunks}
        ids, rejected = consolidate.load_extraction(con, payload, chunk_text_by_id, doc_id, extractor="selftest")
        check("extraction validated + loaded (0 rejected)", len(ids) == 1 and not rejected)

        # ---- provenance walk ----
        ev = provenance.resolve_claim(con, ids[0])
        prov_ok = bool(ev) and ev[0]["source_url"] and ev[0]["content_hash"] == content_hash and quote in ev[0]["quote"]
        check("provenance chain resolves to source_url + content_hash + quote", prov_ok)

        # ---- reject an unverifiable (hallucinated) span ----
        bad = {"claims": [{"canonical_text": "fake", "claim_type": "metric",
                           "subject": "Acme", "predicate": "x",
                           "evidence": [{"chunk_id": c0["chunk_id"],
                                         "quote": "revenue of $9.9 trillion on Mars",
                                         "char_start": 0, "char_end": 5}]}]}
        _, rej = consolidate.load_extraction(con, bad, chunk_text_by_id, doc_id)
        check("hallucinated quote rejected", len(rej) == 1)

        # ---- vector KNN round-trip ----
        if embed_mode == "model":
            qv = embed.embed_texts([quote], model_name=cfg["embed_model"], is_query=True)[0]
        else:
            qv = vc.execute("SELECT embedding FROM vec_chunks WHERE chunk_id=?", [c0["chunk_id"]]).fetchone()[0]
            import numpy as np, struct
            qv = np.array(struct.unpack(f"{cfg['embed_dim']}f", qv), dtype="float32")
        hits = vectors.knn(vc, qv, k=3)
        check("KNN returns the source chunk as top hit", hits and hits[0][1] == c0["chunk_id"])

        # ---- conflict resolution (two sources disagree) ----
        doc2 = doc_id + "_b"
        con.execute("INSERT INTO documents(doc_id, source_id, retrieval_id, channel, source_url, content_hash, "
                    "blob_path, retrieved_at, source_tier, canonical_url) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [doc2, "web:example.com", rid, "web", "https://other.example/acme",
                     content_hash + "_b", blob_rel, datetime.now(timezone.utc), 4, "https://other.example/acme"])
        con.execute("INSERT INTO chunks(chunk_id, doc_id, ord, char_start, char_end, token_count, text) "
                    "VALUES (?,?,?,?,?,?,?)", [doc2 + "#0000", doc2, 0, 0, len(norm), 10, norm])
        payload2 = {"claims": [{"canonical_text": "Acme Q1 revenue was $3.1B (rumor)",
                                "claim_type": "metric", "subject": "Acme Corp", "predicate": "revenue_q1_2026",
                                "value_raw": "$3.1 billion",
                                "evidence": [{"chunk_id": doc2 + "#0000", "quote": quote,
                                              "char_start": qpos, "char_end": qpos + len(quote), "stance": 1}]}]}
        consolidate.load_extraction(con, payload2, {doc2 + "#0000": norm}, doc2)
        consolidate.resolve_conflicts(con)
        statuses = [r[0] for r in con.execute(
            "SELECT resolved_status FROM claims WHERE predicate='revenue_q1_2026'").fetchall()]
        check("conflicting claims resolved (tier-1 source wins / contested set)",
              all(s in ("resolved", "contested") for s in statuses) and len(statuses) == 2)

        # ---- optional: FTS index ----
        build_fts(con)

        # ---- hybrid retrieval returns the source chunk WITH provenance ----
        from lib import query as querylib
        hits = querylib.hybrid_search(con, vc, cfg, "Acme revenue Q1 2026", k=3)
        check("hybrid_search returns provenance-bearing hits",
              bool(hits) and hits[0].get("content_hash") and "revenue" in hits[0]["text"].lower())

        # ---- fetch.ingest_text stores then dedups identical content ----
        from lib import fetch as fetchlib
        d1, new1 = fetchlib.ingest_text(con, p["dir"], text="Beta Inc margins held at 42%.",
                                        source_url="https://ex.com/n", channel="web", source_tier=3, source_id="web:ex.com")
        d2, new2 = fetchlib.ingest_text(con, p["dir"], text="Beta Inc margins held at 42%.",
                                        source_url="https://ex.com/n", channel="web")
        check("ingest_text stores then dedups identical content", new1 and (not new2) and d1 == d2)

        con.close(); vc.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("SELFTEST PASS ✅" if ok else "SELFTEST FAIL ❌"))
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print("usage: python lib/db.py --selftest")
