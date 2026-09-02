"""Near-duplicate detection over normalized document text (datasketch MinHash LSH).

Exact dup is handled upstream by content_hash. This catches reworded/syndicated
copies: a >=threshold Jaccard hit marks the later/lower-tier doc as superseded
(its blob + manifest line are KEPT for provenance + corroboration counting).
"""
from __future__ import annotations
import pickle
import re
from pathlib import Path

from datasketch import MinHash, MinHashLSH

_TOK = re.compile(r"\w+")


def _shingles(text: str, k: int = 5):
    toks = _TOK.findall(text.lower())
    if len(toks) < k:
        yield " ".join(toks)
        return
    for i in range(len(toks) - k + 1):
        yield " ".join(toks[i : i + k])


def minhash(text: str, num_perm: int = 128) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for sh in _shingles(text):
        m.update(sh.encode("utf-8"))
    return m


def new_lsh(threshold: float = 0.85, num_perm: int = 128) -> MinHashLSH:
    return MinHashLSH(threshold=threshold, num_perm=num_perm)


def load_lsh(path: Path):
    if Path(path).exists():
        with open(path, "rb") as fh:
            return pickle.load(fh)
    return None


def save_lsh(lsh, path: Path):
    with open(path, "wb") as fh:
        pickle.dump(lsh, fh)


def query_then_insert(lsh, doc_id: str, mh: MinHash):
    """Return list of existing near-dup doc_ids, then insert this doc."""
    dups = list(lsh.query(mh))
    if doc_id not in lsh:
        lsh.insert(doc_id, mh)
    return dups
