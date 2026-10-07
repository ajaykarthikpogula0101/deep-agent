"""Crawl -> chunk -> embed -> upsert. Idempotent: unchanged pages are skipped by content hash."""
from __future__ import annotations

import hashlib
import logging
import time

from app.config import settings
from app.db import conn, init_schema
from app.embeddings import embed_texts
from app.ingest.chunker import Chunk, chunk_doc
from app.ingest.sources import fetch_all_docs

log = logging.getLogger("ingest")

# Bump when the embedding input format changes so every page is re-embedded on the next run.
EMBED_VERSION = "v2-title-prefix"


def embed_input(chunk: Chunk) -> str:
    """What gets embedded: title + section in front of the text, so a query like 'what tools does Deep use'
    matches the Stack page even when the chunk body never says the word 'tools'. The stored text is unchanged."""
    title = chunk.metadata.get("title") or ""
    head = " · ".join(p for p in (title, chunk.section) if p)
    return f"{head}\n\n{chunk.text}" if head else chunk.text


def run_ingest() -> dict:
    t0 = time.time()
    init_schema()
    docs = fetch_all_docs()
    # Group docs by URL (several journey days share journey.html#day-N anchors -> distinct URLs; fine)
    by_url: dict[str, list] = {}
    for d in docs:
        by_url.setdefault(d.url, []).append(d)

    stats = {"pages_seen": len(by_url), "pages_updated": 0, "chunks_written": 0, "pages_removed": 0}
    with conn() as c:
        existing = {r[0]: r[1] for r in c.execute("SELECT url, content_sha FROM pages").fetchall()}
        for url, group in by_url.items():
            full_text = "\n\n".join(d.text for d in group)
            sha = hashlib.sha256(f"{settings.embed_model}|{EMBED_VERSION}|{full_text}".encode("utf-8")).hexdigest()
            if existing.get(url) == sha:
                continue
            chunks: list[Chunk] = []
            for d in group:
                chunks.extend(chunk_doc(d))
            if not chunks:
                continue
            vectors = embed_texts([embed_input(ch) for ch in chunks])
            c.execute(
                """INSERT INTO pages(url, title, source, content_sha, crawled_at)
                   VALUES (%s, %s, %s, %s, now())
                   ON CONFLICT (url) DO UPDATE SET title = EXCLUDED.title, source = EXCLUDED.source,
                       content_sha = EXCLUDED.content_sha, crawled_at = now()""",
                (url, group[0].title, group[0].source, sha),
            )
            c.execute("DELETE FROM chunks WHERE url = %s", (url,))
            for ch, vec in zip(chunks, vectors):
                c.execute(
                    """INSERT INTO chunks(url, section, position, text, tokens, embedding, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)""",
                    (ch.url, ch.section, ch.position, ch.text, ch.tokens, vec, __import__("json").dumps(ch.metadata)),
                )
            stats["pages_updated"] += 1
            stats["chunks_written"] += len(chunks)
        # Remove pages that disappeared from the site
        gone = set(existing) - set(by_url)
        for url in gone:
            c.execute("DELETE FROM pages WHERE url = %s", (url,))
        stats["pages_removed"] = len(gone)
        c.commit()
    stats["seconds"] = round(time.time() - t0, 1)
    log.info("ingest done %s", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_ingest())
