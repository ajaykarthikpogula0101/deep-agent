"""Split a document into retrieval chunks, keeping URL + section on every chunk.

Pure functions, no I/O, so this is unit-testable without a database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")

TARGET_TOKENS = 350
OVERLAP_TOKENS = 50
MIN_TOKENS = 40


@dataclass
class Doc:
    url: str
    title: str
    source: str  # 'llms-full' | 'data.js' | 'html'
    text: str
    section: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Chunk:
    url: str
    section: str | None
    position: int
    text: str
    tokens: int
    metadata: dict


def count_tokens(s: str) -> int:
    return len(_enc.encode(s))


def _split_paragraphs(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    # Never let one paragraph exceed ~2x target: hard-split on sentences.
    out: list[str] = []
    for p in paras:
        if count_tokens(p) <= TARGET_TOKENS * 2:
            out.append(p)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", p)
        buf = ""
        for s in sentences:
            if count_tokens(buf + " " + s) > TARGET_TOKENS:
                if buf:
                    out.append(buf.strip())
                buf = s
            else:
                buf = (buf + " " + s).strip()
        if buf:
            out.append(buf)
    return out


def chunk_doc(doc: Doc) -> list[Chunk]:
    """Greedy paragraph packing to ~TARGET_TOKENS with a small overlap."""
    paras = _split_paragraphs(doc.text)
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_tokens = 0

    def flush() -> None:
        nonlocal buf, buf_tokens
        if not buf:
            return
        text = "\n\n".join(buf)
        chunks.append(
            Chunk(
                url=doc.url,
                section=doc.section,
                position=len(chunks),
                text=text,
                tokens=count_tokens(text),
                metadata={"title": doc.title, "source": doc.source, **doc.metadata},
            )
        )
        # overlap: carry the tail paragraph forward if it is small
        tail = buf[-1]
        if count_tokens(tail) <= OVERLAP_TOKENS:
            buf, buf_tokens = [tail], count_tokens(tail)
        else:
            buf, buf_tokens = [], 0

    for p in paras:
        t = count_tokens(p)
        if buf_tokens + t > TARGET_TOKENS and buf:
            flush()
        buf.append(p)
        buf_tokens += t
    flush()

    # Merge a trailing tiny chunk into its predecessor so we don't embed noise.
    if len(chunks) >= 2 and chunks[-1].tokens < MIN_TOKENS:
        last = chunks.pop()
        prev = chunks[-1]
        prev.text = prev.text + "\n\n" + last.text
        prev.tokens = count_tokens(prev.text)
    return chunks


def split_markdown_sections(md: str) -> list[tuple[str, str]]:
    """Return (heading, body) pairs for '### ' sections; used for llms-full.txt."""
    parts = re.split(r"(?m)^(###\s+.+)$", md)
    out: list[tuple[str, str]] = []
    # parts: [preamble, heading1, body1, heading2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        heading = parts[i].lstrip("#").strip()
        body = parts[i + 1].strip()
        if body:
            out.append((heading, body))
    return out
