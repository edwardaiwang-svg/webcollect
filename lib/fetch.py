"""Ingest fetched content into the raw store + structured index, with dedup.

ingest_text(): the universal entry — content already pulled by any fetcher
(firecrawl-scrape, article-extractor, yt-dlp transcript, a stats API, ...) is
hashed, blob-stored, manifest-logged and registered as a document. Exact dups
(same content_hash) are skipped. ingest_http(): a thin httpx fetcher for plain
pages so the pipeline has a built-in free path.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from lib import raw_store

UA = os.environ.get("WEBCOLLECT_USER_AGENT", "webcollect/0.1 (+https://github.com/edwardaiwang-svg/webcollect)")


def register_source(con, source_id, kind, display_name=None, home_url=None, tier=3, trust_weight=0.5):
    con.execute(
        "INSERT INTO sources(source_id, kind, display_name, home_url, tier, trust_weight) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT (source_id) DO NOTHING",
        [source_id, kind, display_name, home_url, tier, trust_weight],
    )


def _to_dt(v):
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def ingest_text(con, corpus_dir, *, text, source_url, channel, source_tier=3,
                source_id=None, title=None, author=None, published_at=None,
                media_type="text/plain", ext="txt", http_status=200, extra=None):
    """Store one document. Returns (doc_id, is_new)."""
    data = text.encode("utf-8")
    content_hash = raw_store.sha256_bytes(data)
    existing = con.execute("SELECT doc_id FROM documents WHERE content_hash=?", [content_hash]).fetchone()
    if existing:
        return existing[0], False

    blob_hash, blob_rel = raw_store.write_blob(corpus_dir, data, ext)
    norm = raw_store.normalize_text(text)
    norm_hash = raw_store.sha256_text(norm)
    canon = raw_store.canonical_url(source_url)
    rec = {
        "channel": channel, "source_url": source_url, "canonical_url": canon,
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "http_status": http_status,
        "content_hash": content_hash, "blob_path": blob_rel, "source_tier": source_tier,
        "title": title, "author": author, "published_at": published_at,
    }
    if extra:
        rec["extra"] = extra
    rid = raw_store.append_manifest(corpus_dir, rec)

    doc_id = "doc_" + content_hash.split(":")[1][:16]
    if source_id:
        register_source(con, source_id, channel, display_name=source_id, tier=source_tier)
    con.execute(
        "INSERT INTO documents(doc_id, source_id, retrieval_id, channel, source_url, canonical_url, "
        "content_hash, norm_hash, blob_path, media_type, title, author, published_at, retrieved_at, "
        "source_tier, char_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (doc_id) DO NOTHING",
        [doc_id, source_id, rid, channel, source_url, canon, content_hash, norm_hash, blob_rel,
         media_type, title, author, _to_dt(published_at), datetime.now(timezone.utc), source_tier, len(norm)],
    )
    return doc_id, True


def _extract_html(html: str) -> tuple[str, str | None]:
    try:
        from selectolax.parser import HTMLParser

        tree = HTMLParser(html)
        for tag in tree.css("script,style,noscript,nav,footer,header"):
            tag.decompose()
        title = tree.css_first("title")
        title = title.text(strip=True) if title else None
        body = tree.body or tree.root
        return (body.text(separator="\n", strip=True) if body else html), title
    except Exception:  # noqa: BLE001
        return html, None


def ingest_http(con, corpus_dir, url, *, channel="web", source_tier=3, source_id=None, timeout=30):
    """Fetch a plain page with httpx (UA set), extract text, ingest. Returns (doc_id, is_new)."""
    import httpx

    r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=timeout)
    ctype = r.headers.get("content-type", "")
    if "html" in ctype:
        text, title = _extract_html(r.text)
        ext = "html"
    else:
        text, title, ext = r.text, None, "txt"
    return ingest_text(con, corpus_dir, text=text, source_url=str(r.url), channel=channel,
                       source_tier=source_tier, source_id=source_id, title=title,
                       media_type=ctype or "text/plain", ext=ext, http_status=r.status_code)
