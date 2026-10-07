"""Local embeddings with a Hugging Face model (BAAI/bge-small-en-v1.5 by default) via fastembed.

No API key, no cost, runs on CPU with ONNX Runtime (no PyTorch). The model (~130 MB) is downloaded once to
FASTEMBED_CACHE_PATH (or the user cache dir) and reused. The corpus is ~200 chunks, so a full re-embed takes seconds.

bge models expect a short instruction in front of *queries* (not documents); fastembed's query_embed() adds it.
"""
from __future__ import annotations

import threading
from typing import Iterable

from app.config import settings

EMBED_DIMS = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "snowflake/snowflake-arctic-embed-s": 384,
}
EMBED_DIM = EMBED_DIMS.get(settings.embed_model, 384)

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding

                _model = TextEmbedding(model_name=settings.embed_model)
    return _model


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    """Document embeddings, normalised (so cosine == dot)."""
    return [v.tolist() for v in _get_model().embed(list(texts), batch_size=32)]


def embed_query(q: str) -> list[float]:
    return next(iter(_get_model().query_embed(q))).tolist()
