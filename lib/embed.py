"""Local, free embeddings (sentence-transformers). Voyage is a drop-in later.

Default model bge-small-en-v1.5 (384-dim). For ZH/bilingual corpora switch to
intfloat/multilingual-e5-small (also 384-dim -> schema unchanged). The model
name + dim are recorded in corpus.config.json; mixed-dim KNN is refused upstream.
"""
from __future__ import annotations
import functools

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_DIM = 384

# query-side instruction prefixes (improve retrieval for these model families)
_QUERY_PREFIX = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "intfloat/multilingual-e5-small": "query: ",
    "intfloat/e5-base-v2": "query: ",
}
_PASSAGE_PREFIX = {
    "intfloat/multilingual-e5-small": "passage: ",
    "intfloat/e5-base-v2": "passage: ",
}


def _device() -> str:
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


@functools.lru_cache(maxsize=2)
def get_model(name: str = DEFAULT_MODEL):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name, device=_device())


def _apply_prefix(texts: list[str], model_name: str, is_query: bool) -> list[str]:
    table = _QUERY_PREFIX if is_query else _PASSAGE_PREFIX
    pfx = table.get(model_name, "")
    return [pfx + t for t in texts] if pfx else list(texts)


def embed_texts(texts, model_name: str = DEFAULT_MODEL, is_query: bool = False):
    """Return an (n, dim) float32 numpy array of L2-normalized embeddings."""
    import numpy as np

    if isinstance(texts, str):
        texts = [texts]
    model = get_model(model_name)
    prepared = _apply_prefix(texts, model_name, is_query)
    vecs = model.encode(
        prepared,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
        batch_size=64,
    )
    return vecs.astype(np.float32)
