"""Content-addressed raw store + append-only manifest (the provenance root).

Every fetched payload is hashed (sha256) and written once to
raw/blobs/<ab>/<cd>/<sha256>.<ext>; re-fetching identical bytes is a no-op.
Each retrieval event is one line in raw/manifest.jsonl — the immutable record
that documents.retrieval_id points back to.
"""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def _hex(content_hash: str) -> str:
    return content_hash.split(":", 1)[-1]


def blob_relpath(content_hash: str, ext: str) -> str:
    h = _hex(content_hash)
    ext = ext.lstrip(".")
    return f"raw/blobs/{h[:2]}/{h[2:4]}/{h}.{ext}"


def write_blob(corpus_dir: Path, data: bytes, ext: str = "txt") -> tuple[str, str]:
    """Write bytes content-addressed. Returns (content_hash, relative blob path)."""
    content_hash = sha256_bytes(data)
    rel = blob_relpath(content_hash, ext)
    dest = corpus_dir / rel
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return content_hash, rel


def append_manifest(corpus_dir: Path, record: dict) -> str:
    """Append one retrieval event. Returns its retrieval_id (generated if absent)."""
    rid = record.get("retrieval_id") or ("r_" + uuid.uuid4().hex[:24])
    record["retrieval_id"] = rid
    mpath = corpus_dir / "raw" / "manifest.jsonl"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    with mpath.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return rid


_WS = re.compile(r"[ \t]+")
_NL = re.compile(r"\n{3,}")


def normalize_text(s: str) -> str:
    """Stable normalization so char offsets are reproducible across runs.

    Normalizes line endings and collapses runs of spaces/blank lines. The
    result is stored as its own blob (norm_hash); all chunk/quote offsets are
    relative to THIS string.
    """
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _WS.sub(" ", s)
    s = _NL.sub("\n\n", s)
    return s.strip()


def canonical_url(url: str) -> str:
    """Strip tracking params + fragment, lowercase host."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    try:
        sp = urlsplit(url)
    except ValueError:
        return url
    q = [(k, v) for k, v in parse_qsl(sp.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    return urlunsplit((sp.scheme.lower(), sp.netloc.lower(), sp.path, urlencode(q), ""))
