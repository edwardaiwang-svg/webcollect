"""Deterministic consolidation primitives the corpus-consolidate skill calls.

The LLM map/reduce orchestration lives in the skill (Workflow tool); this module
is the $0, non-LLM machinery: chunk+embed a document into both stores, load a
validated shard extraction into claims/evidence, and resolve conflicts by
tier/recency/corroboration.
"""
from __future__ import annotations
import uuid

from lib import chunk as chunklib
from lib import embed as embedlib
from lib import vectors as veclib
from lib import schemas as schemalib


def _next_embed_id(vecconn) -> int:
    row = vecconn.execute("SELECT COALESCE(MAX(embed_id), 0) FROM vec_chunks").fetchone()
    return int(row[0]) + 1


def chunk_and_embed_document(
    con, vecconn, *, doc_id, norm_text, model_name, dim,
    source_tier=3, published_at=None, max_tokens=512, overlap_tokens=64,
):
    """Chunk norm_text, embed each chunk, write chunks (DuckDB) + vectors (sqlite-vec).

    Returns the list of inserted chunk dicts (with chunk_id + embed_id).
    """
    pieces = chunklib.chunk_text(norm_text, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
    if not pieces:
        return []
    vecs = embedlib.embed_texts([p["text"] for p in pieces], model_name=model_name, is_query=False)
    if vecs.shape[1] != dim:
        raise ValueError(f"embedding dim {vecs.shape[1]} != corpus dim {dim} (model mismatch)")

    eid = _next_embed_id(vecconn)
    inserted = []
    for p, v in zip(pieces, vecs):
        chunk_id = f"{doc_id}#{p['ord']:04d}"
        con.execute(
            "INSERT OR REPLACE INTO chunks(chunk_id, doc_id, ord, char_start, char_end, token_count, text, embed_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [chunk_id, doc_id, p["ord"], p["char_start"], p["char_end"], p["token_count"], p["text"], eid],
        )
        veclib.add(vecconn, eid, v, chunk_id, doc_id, source_tier=source_tier, published_at=published_at)
        p["chunk_id"], p["embed_id"] = chunk_id, eid
        inserted.append(p)
        eid += 1
    con.execute("UPDATE documents SET ingest_status='chunked' WHERE doc_id=?", [doc_id])
    vecconn.commit()
    return inserted


def insert_claim_with_evidence(con, *, claim: "schemalib.ExtractedClaim", doc_id, extractor="manual"):
    """Insert one validated claim + its evidence rows. Returns claim_id."""
    claim_id = "clm_" + uuid.uuid4().hex[:20]
    con.execute(
        "INSERT INTO claims(claim_id, canonical_text, claim_type, subject_entity, predicate, "
        "value_raw, value_num, value_unit, polarity, first_seen_at, last_seen_at) "
        "VALUES (?,?,?,?,?,?,?,?,?, current_timestamp, current_timestamp)",
        [claim_id, claim.canonical_text, claim.claim_type, claim.subject, claim.predicate,
         claim.value_raw, claim.value_num, claim.value_unit, claim.polarity],
    )
    for ev in claim.evidence:
        con.execute(
            "INSERT INTO claim_evidence(evidence_id, claim_id, chunk_id, doc_id, quote, char_start, char_end, stance, extractor) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ["ev_" + uuid.uuid4().hex[:20], claim_id, ev.chunk_id, doc_id, ev.quote, ev.char_start, ev.char_end, ev.stance, extractor],
        )
    return claim_id


def load_extraction(con, payload: dict, chunk_text_by_id: dict, doc_id: str, extractor="workflow"):
    """Validate a shard extraction (rejecting unverifiable spans) and load it."""
    accepted, rejected = schemalib.validate_extraction(payload, chunk_text_by_id)
    ids = [insert_claim_with_evidence(con, claim=c, doc_id=doc_id, extractor=extractor) for c in accepted]
    return ids, rejected


def resolve_conflicts(con):
    """Group claims by (subject_entity, predicate); set resolved_status/value by
    tier precedence + recency + corroboration. Dissent is left intact as -1
    evidence rows. Pure SQL/python, no LLM."""
    import math

    groups = con.execute(
        "SELECT subject_entity, predicate FROM claims "
        "WHERE subject_entity IS NOT NULL AND predicate IS NOT NULL "
        "GROUP BY subject_entity, predicate HAVING count(*) > 1"
    ).fetchall()
    for subj, pred in groups:
        rows = con.execute(
            """SELECT cl.claim_id, cl.value_raw,
                      MIN(d.source_tier) AS best_tier,
                      MAX(d.published_at) AS newest,
                      COUNT(DISTINCT d.canonical_url) AS indep
               FROM claims cl
               JOIN claim_evidence e ON e.claim_id = cl.claim_id
               JOIN documents d ON d.doc_id = e.doc_id
               WHERE cl.subject_entity=? AND cl.predicate=?
               GROUP BY cl.claim_id, cl.value_raw""",
            [subj, pred],
        ).fetchall()
        if not rows:
            continue
        scored = []
        for cid, vraw, tier, newest, indep in rows:
            tier = tier if tier is not None else 5
            score = 0.5 * (6 - tier) + 0.2 * math.log(1 + (indep or 1))
            scored.append((score, cid, vraw))
        scored.sort(reverse=True)
        top = scored[0]
        contested = len(scored) > 1 and (scored[0][0] - scored[1][0]) < 0.3
        status = "contested" if contested else "resolved"
        for _, cid, _ in scored:
            con.execute(
                "UPDATE claims SET resolved_status=?, resolved_value=?, corroboration_count=? WHERE claim_id=?",
                [status, top[2], len(scored), cid],
            )
