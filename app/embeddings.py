"""Embeddings: local (fastembed) by default, or a remote OpenAI-compatible /embeddings endpoint.

local (EMBED_PROVIDER=local): a Hugging Face model (BAAI/bge-small-en-v1.5 by default) via fastembed. No API key,
no cost, runs on CPU with ONNX Runtime (no PyTorch). The model (~130 MB) is downloaded once to FASTEMBED_CACHE_PATH
(or the user cache dir) and reused. The corpus is ~200 chunks, so a full re-embed takes seconds.
bge models expect a short instruction in front of *queries* (not documents); fastembed's query_embed() adds it.

api (EMBED_PROVIDER=api): the same OpenAI client the chat uses, against EMBED_BASE_URL (default LLM_BASE_URL) with
EMBED_API_KEY (default LLM_API_KEY). Nothing runs on the server's CPU and the fastembed stack is never imported.
Note: OpenRouter has no /embeddings endpoint; point EMBED_BASE_URL at a provider that has one (api.openai.com, ...).

Vector size: EMBED_DIM when set, else the model's known size, else 384. The `chunks` table is created with that
size, so switching provider or model means re-running `python -m app.ingest.pipeline`.
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
    # common API models
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}
EMBED_DIM = settings.embed_dim or EMBED_DIMS.get(settings.embed_model.split("/")[-1], EMBED_DIMS.get(settings.embed_model, 384))

_model = None
_client = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding

                _model = TextEmbedding(model_name=settings.embed_model)
    return _model


def _get_client():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                from openai import OpenAI

                key = settings.embed_api_key or settings.chat_api_key
                if not key:
                    raise RuntimeError("EMBED_PROVIDER=api needs EMBED_API_KEY (or LLM_API_KEY)")
                _client = OpenAI(api_key=key, base_url=settings.embed_base_url or settings.llm_base_url or None)
    return _client


def _api_embed(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), 64):  # modest batches keep requests small
        resp = _get_client().embeddings.create(model=settings.embed_model, input=texts[i:i + 64])
        out.extend(list(d.embedding) for d in sorted(resp.data, key=lambda d: d.index))
    if out and len(out[0]) != EMBED_DIM:
        raise RuntimeError(f"embedding size {len(out[0])} != EMBED_DIM {EMBED_DIM}: set EMBED_DIM and re-ingest")
    return out


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    """Document embeddings, normalised (so cosine == dot)."""
    items = list(texts)
    if settings.embed_provider == "api":
        return _api_embed(items)
    return [v.tolist() for v in _get_model().embed(items, batch_size=32)]


def embed_query(q: str) -> list[float]:
    if settings.embed_provider == "api":
        return _api_embed([q])[0]  # API models take the query as-is; no bge instruction prefix
    return next(iter(_get_model().query_embed(q))).tolist()
