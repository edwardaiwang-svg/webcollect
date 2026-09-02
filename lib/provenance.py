"""Walk the provenance chain so every output claim links back to origin.

resolve_claim() returns, for one claim, the full evidence list joined through
chunks -> documents -> sources, each row carrying the verbatim quote, exact char
span, source_url, retrieved_at and content_hash (proof the text was unaltered).
"""
from __future__ import annotations

_SQL = """
SELECT
  e.evidence_id, e.quote, e.char_start, e.char_end, e.stance,
  c.chunk_id, c.ord AS chunk_ord,
  d.doc_id, d.source_url, d.canonical_url, d.title, d.author,
  d.published_at, d.retrieved_at, d.content_hash, d.blob_path, d.source_tier,
  s.source_id, s.display_name, s.tier AS source_tier_meta
FROM claim_evidence e
JOIN chunks    c ON c.chunk_id = e.chunk_id
JOIN documents d ON d.doc_id   = e.doc_id
LEFT JOIN sources s ON s.source_id = d.source_id
WHERE e.claim_id = ?
ORDER BY e.stance DESC, d.source_tier ASC, d.published_at DESC
"""


def resolve_claim(con, claim_id: str) -> list[dict]:
    cols = [
        "evidence_id", "quote", "char_start", "char_end", "stance",
        "chunk_id", "chunk_ord", "doc_id", "source_url", "canonical_url",
        "title", "author", "published_at", "retrieved_at", "content_hash",
        "blob_path", "source_tier", "source_id", "display_name", "source_tier_meta",
    ]
    rows = con.execute(_SQL, [claim_id]).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def footnote(ev: dict, n: int | None = None) -> str:
    """Render one evidence row as a human-readable footnote string."""
    who = ev.get("display_name") or ev.get("source_url") or ev.get("source_id") or "source"
    when = ev.get("published_at") or ""
    got = ev.get("retrieved_at") or ""
    ch = ev.get("content_hash") or ""
    head = f"[{n}] " if n else ""
    quote = (ev.get("quote") or "").strip()
    quote = (quote[:200] + "…") if len(quote) > 200 else quote
    return f'{head}"{quote}" — {who} ({when}; retrieved {got}; {ch}) {ev.get("source_url","")}'.strip()


def claim_supported(con, claim_id: str) -> bool:
    """True if the claim has at least one supporting (stance>0) evidence row."""
    n = con.execute(
        "SELECT count(*) FROM claim_evidence WHERE claim_id=? AND stance > 0", [claim_id]
    ).fetchone()[0]
    return n > 0
