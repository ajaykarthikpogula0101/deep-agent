"""Fetch deependhq.com content from its three sources, cleanest first.

1. llms-full.txt  : every journey entry + essay as markdown (the site publishes this for agents)
2. data.js        : the whole site as one JSON object (companies, pillars, toolkit, now)
3. HTML pages     : anything in sitemap.xml not covered above (privacy, company pages' prose, etc.)

The site pre-renders its text into HTML, so requests + BeautifulSoup is enough; no Playwright.
robots.txt is honoured (we are an 'assistant', which the site explicitly allows) and we send a
descriptive User-Agent so Cloudflare AI Crawl Control can identify us.
"""
from __future__ import annotations

import json
import re
import urllib.robotparser as robotparser
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.ingest.chunker import Doc, split_markdown_sections

_DAY_RE = re.compile(r"^Day (\d+), (\d{4}-\d{2}-\d{2})(?: \((\w+)\))?", re.I)
_LINK_RE = re.compile(r"(?m)^Link:\s*(\S+)\s*$")


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": settings.crawl_user_agent},
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
    )


def robots_allows(url: str, client: httpx.Client) -> bool:
    rp = robotparser.RobotFileParser()
    try:
        r = client.get(f"{settings.site_base_url}/robots.txt")
        rp.parse(r.text.splitlines())
    except httpx.HTTPError:
        return True  # robots unreachable: default allow for our own site
    return rp.can_fetch(settings.crawl_user_agent.split("/")[0], url)


# ---------------------------------------------------------------- llms-full.txt
def docs_from_llms_full(client: httpx.Client) -> list[Doc]:
    r = client.get(f"{settings.site_base_url}/llms-full.txt")
    r.raise_for_status()
    return parse_llms_full(r.text)


def parse_llms_full(md: str) -> list[Doc]:
    """Pure parser (unit-tested). One Doc per '### ' section (one per day / essay)."""
    docs: list[Doc] = []
    # The file has '## Journey' and '## Essays' top sections; track which we're in.
    current_top = "Journey"
    for top_heading, top_body in _split_top(md):
        current_top = top_heading
        for heading, body in split_markdown_sections(top_body):
            m = _DAY_RE.match(heading)
            link = _LINK_RE.search(body)
            url = link.group(1) if link else settings.site_base_url + "/journey"
            body_clean = _LINK_RE.sub("", body).strip()
            meta: dict = {"kind": "journey" if current_top.lower().startswith("journey") else "essay"}
            if m:
                meta.update({"day": int(m.group(1)), "date": m.group(2), "mode": m.group(3)})
            docs.append(
                Doc(url=url, title=heading, source="llms-full", text=body_clean, section=current_top, metadata=meta)
            )
    return docs


def _split_top(md: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^(##\s+.+)$", md)
    out: list[tuple[str, str]] = []
    for i in range(1, len(parts) - 1, 2):
        out.append((parts[i].lstrip("#").strip(), parts[i + 1]))
    return out


# ---------------------------------------------------------------- data.js
def docs_from_data_js(client: httpx.Client) -> list[Doc]:
    r = client.get(f"{settings.site_base_url}/data.js")
    r.raise_for_status()
    return parse_data_js(r.text)


def parse_data_js(js: str) -> list[Doc]:
    """data.js is `window.DH_DATA = {...};` with a JSON body. Pull the structured parts."""
    m = re.search(r"window\.DH_DATA\s*=\s*(\{.*\})\s*;?\s*$", js, re.S)
    if not m:
        return []
    data = json.loads(m.group(1))
    base = settings.site_base_url
    docs: list[Doc] = []

    for c in data.get("companies", []):
        slug = c.get("slug")
        lines = [f"{c.get('name')} — {c.get('desc', '')}".strip()]
        if c.get("tag"):
            lines.append(f"Tag: {c['tag']}")
        if c.get("pillar"):
            lines.append(f"Pillar: {c['pillar']}")
        if c.get("products"):
            lines.append("Products: " + ", ".join(c["products"]))
        if c.get("url"):
            lines.append(f"Website: {c['url']}")
        if c.get("body"):
            lines.append(_as_text(c["body"]))
        docs.append(
            Doc(url=f"{base}/company/{slug}", title=c.get("name", slug), source="data.js",
                text="\n\n".join(lines), section="Companies", metadata={"kind": "company", "slug": slug})
        )

    for key, section, path in (("pillars", "Pillars", "/pillars"), ("toolkit", "Stack", "/toolkit"), ("now", "Now", "/now")):
        if key in data:
            text = _as_text(data[key])
            if text.strip():
                docs.append(Doc(url=base + path, title=section, source="data.js", text=text, section=section,
                                metadata={"kind": key}))
    return docs


def _as_text(obj, depth: int = 0) -> str:
    """Flatten nested JSON into readable lines (keys become labels)."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float, bool)) or obj is None:
        return str(obj)
    if isinstance(obj, list):
        return "\n".join(_as_text(x, depth + 1) for x in obj)
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            if k in ("arc_color", "color", "id"):
                continue
            inner = _as_text(v, depth + 1)
            if isinstance(v, (dict, list)):
                lines.append(f"{k}:\n{inner}")
            else:
                lines.append(f"{k}: {inner}")
        return "\n".join(lines)
    return str(obj)


# ---------------------------------------------------------------- HTML pages via sitemap
_NOISE_TAGS = ("script", "style", "nav", "footer", "noscript", "svg", "pre")


def sitemap_urls(client: httpx.Client) -> list[str]:
    r = client.get(f"{settings.site_base_url}/sitemap.xml")
    r.raise_for_status()
    return re.findall(r"<loc>\s*(\S+?)\s*</loc>", r.text)


def docs_from_html(client: httpx.Client, urls: Iterable[str], skip: set[str]) -> list[Doc]:
    docs: list[Doc] = []
    for url in urls:
        if url in skip or not robots_allows(url, client):
            continue
        try:
            r = client.get(url)
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        d = html_to_doc(url, r.text)
        if d and len(d.text.split()) >= 40:
            docs.append(d)
    return docs


def html_to_doc(url: str, html: str) -> Doc | None:
    soup = BeautifulSoup(html, "lxml")
    for t in soup.find_all(_NOISE_TAGS):
        t.decompose()
    title = (soup.title.string.strip() if soup.title and soup.title.string else url)
    main = soup.find("main") or soup.body or soup
    # Keep headings as section labels inside the text so the chunker can see them.
    for h in main.find_all(["h1", "h2", "h3"]):
        h.insert_before("\n\n")
        h.insert_after("\n\n")
    text = re.sub(r"[ \t]+", " ", main.get_text("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # Drop the ASCII-art banner lines (box-drawing / braille glyphs carry no meaning for retrieval).
    text = "\n".join(l for l in text.splitlines() if not re.fullmatch(r"[\s─-▟⠀-⣿]+", l))
    if not text:
        return None
    return Doc(url=url, title=title, source="html", text=text, section=None, metadata={"kind": "page"})


# ---------------------------------------------------------------- orchestration
def fetch_all_docs() -> list[Doc]:
    with _client() as client:
        docs = docs_from_llms_full(client)
        docs += docs_from_data_js(client)
        covered = {d.url for d in docs}
        # journey/writing index pages are summaries of what llms-full already covers; skip them
        covered |= {f"{settings.site_base_url}/journey", f"{settings.site_base_url}/writing",
                    f"{settings.site_base_url}/field-notes"}
        extra = [u for u in sitemap_urls(client) if u.rstrip("/") not in covered and "/post/" not in u]
        docs += docs_from_html(client, extra, skip=covered)
    return docs
