"""Recursive, offset-preserving chunker.

Guarantees chunk["text"] == norm_text[char_start:char_end] for every chunk, so
extracted-quote spans can be validated against the stored text exactly.
"""
from __future__ import annotations
import re

_PARA = re.compile(r"[^\n]+(?:\n(?!\n)[^\n]+)*", re.MULTILINE)

_enc = None


def _encoder():
    global _enc
    if _enc is None:
        try:
            import tiktoken

            _enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _enc = False  # offline / unavailable -> heuristic fallback
    return _enc


def count_tokens(s: str) -> int:
    enc = _encoder()
    if enc:
        return len(enc.encode(s))
    return max(1, len(s) // 4)


def chunk_text(norm_text: str, max_tokens: int = 512, overlap_tokens: int = 64) -> list[dict]:
    """Greedy paragraph packing with character overlap.

    Paragraphs are accumulated until the token budget is hit; an oversize single
    paragraph is hard-split by character windows. Successive chunks overlap by
    ~overlap_tokens worth of characters (ranges may overlap; each chunk["text"]
    is still an exact slice of norm_text).
    """
    if not norm_text:
        return []
    spans = [(m.start(), m.end()) for m in _PARA.finditer(norm_text)]
    if not spans:
        spans = [(0, len(norm_text))]

    overlap_chars = overlap_tokens * 4
    chunks: list[dict] = []
    cur_start = None
    cur_end = None

    def emit(start: int, end: int):
        text = norm_text[start:end]
        if not text.strip():
            return
        chunks.append(
            {
                "ord": len(chunks),
                "char_start": start,
                "char_end": end,
                "token_count": count_tokens(text),
                "text": text,
            }
        )

    for (ps, pe) in spans:
        # hard-split a single paragraph that exceeds the budget
        if count_tokens(norm_text[ps:pe]) > max_tokens:
            if cur_start is not None:
                emit(cur_start, cur_end)
                cur_start = cur_end = None
            step = max_tokens * 4
            i = ps
            while i < pe:
                j = min(pe, i + step)
                emit(i, j)
                i = j
            continue

        if cur_start is None:
            cur_start, cur_end = ps, pe
            continue

        if count_tokens(norm_text[cur_start:pe]) <= max_tokens:
            cur_end = pe
        else:
            emit(cur_start, cur_end)
            new_start = max(cur_start + 1, cur_end - overlap_chars)
            cur_start, cur_end = new_start, pe
            # if even the overlapped window is too big, drop the overlap
            if count_tokens(norm_text[cur_start:cur_end]) > max_tokens:
                cur_start = ps

    if cur_start is not None:
        emit(cur_start, cur_end)
    # renumber ord after any skipped-empty
    for i, c in enumerate(chunks):
        c["ord"] = i
    return chunks
