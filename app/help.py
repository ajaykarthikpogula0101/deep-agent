"""Help center (docs/ROADMAP.md step 3, like the Help tab of Intercom's messenger on snitcher.com).

Collections of articles, shown in the widget's Help tab (collections -> articles -> article) and in the Home tab's
"Search for help" card. Three kinds of article (help_articles.source):

  site     made from a deependhq.com page (companies, toolkit, Now page, home page). Retrieval already indexes those
           pages, so these articles never feed the answers twice. "Refresh from the site" rebuilds them; editing one in
           the console turns it into an owner article, which a refresh then leaves alone.
  builtin  written for the assistant itself: booking, rescheduling, joining, talking to the team, languages, privacy.
  owner    written in Console -> Help.

builtin and owner articles feed the answers: retrieve.search() adds the closest ones as sources, linked to
`#dh-help=<slug>`, which opens the article in the widget.

Bodies use a small Markdown subset (paragraphs, "## " headings, "- " bullets, **bold**, [text](url)); the widget renders
it, never raw HTML.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any

from app.config import settings
from app.db import conn

log = logging.getLogger("help")

BASE = "https://deependhq.com"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:80] or "article"


def article_url(slug: str) -> str:
    """Where an article lives: the site with the widget opened on it (static/widget.js reads #dh-help=)."""
    return f"{settings.site_base_url.rstrip('/')}/#dh-help={slug}"


# ---------------------------------------------------------------- starter content
COLLECTIONS = [
    ("about-deep", "About Deep", "Who Deep is, what he is working on, and how the build-in-public log works."),
    ("companies", "Champions Group companies", "The twelve companies, grouped by pillar, with their products and websites."),
    ("tools", "Tools Deep uses", "The tools and products Deep builds and uses every day."),
    ("booking", "Booking a call with Deep", "Book, reschedule or cancel a call, and join it on Zoom."),
    ("assistant", "Using this assistant", "What the assistant can do, talking to a person, languages and your data."),
]

BUILTIN = [
    ("booking", "How do I book a call with Deep?", "Pick a time in the chat; the call is booked on Deep's Zoom scheduler.",
     "Ask in the chat (for example **\"Book a call with Deep\"**) or tap **Book a meeting**.\n\n"
     "- Pick the type of call.\n- Pick a day and a time. Times are shown in your own timezone, and times that are taken "
     "are greyed out.\n- Add your name, email, what you would like to talk about and, if you like, colleagues to invite.\n"
     "- Check the summary and press **Confirm booking**.\n\n"
     "The call is booked on Deep's Zoom scheduler. You get a confirmation email with a calendar invite and the Zoom link."),
    ("booking", "Which kinds of call can I book?", "The call types come live from Deep's Zoom scheduler.",
     "The list in the chat always shows the call types Deep currently offers, with their length.\n\n"
     "- A short **discovery call** suits a first conversation.\n- A **product walkthrough** suits people evaluating "
     "LakeB2B.\n- A **strategy session** suits go-to-market, data or AI planning.\n\n"
     "Not sure which one fits? Ask the assistant and it will suggest one."),
    ("booking", "How do I reschedule or cancel my call?", "In the chat, from Messages, or from your confirmation email.",
     "- In the chat, write **\"reschedule my call\"** or **\"cancel my call\"**.\n- Or open **Messages**, then "
     "**Your bookings**, and choose the call.\n- Or use the **Reschedule** and **Cancel** links in your confirmation "
     "email.\n\nThe assistant moves or cancels the call on Zoom for you, and both you and Deep get an email."),
    ("booking", "How do I join the call?", "Use the Join button in your confirmation email.",
     "Your confirmation email has a **Join Zoom meeting** button, the meeting ID and passcode, and phone numbers if you "
     "prefer to dial in. A reminder with the same details arrives the day before the call."),
    ("assistant", "What can this assistant do?", "Answer questions from deependhq.com, book calls, and pass you to the team.",
     "- Answer questions about Deep, his companies, the daily log and his tools, with links to the pages it used.\n"
     "- Book, reschedule or cancel a call with Deep.\n- Pass your question to the team when it cannot answer.\n"
     "- Talk with you by voice, read files you attach, and answer in your language.\n\n"
     "It only answers from what is published on deependhq.com and never guesses."),
    ("assistant", "How do I talk to a person?", "Use \"Message the team\"; Deep replies here and by email.",
     "Ask **\"Can I talk to a person?\"** or tap **Ask the team directly** under an answer, then leave your name, email "
     "and message.\n\nDeep replies in this chat. If you have left by then, the reply also comes to your email with a "
     "link back to the conversation."),
    ("assistant", "Which languages can I use?", "Write or speak in your own language.",
     "Write in any language and the assistant answers in the same one, even though the site is in English. In a voice "
     "conversation you can pick the language, or leave it on automatic."),
    ("assistant", "What happens to my data?", "What the chat stores and for how long.",
     "The chat stores your messages, the page you came from and an approximate location so the team can follow up and "
     "improve the answers. Network details are removed after 90 days. Booking details are shared with Zoom to make the "
     "booking. The privacy policy has the details: [deependhq.com/privacy](https://deependhq.com/privacy)."),
]


# ---------------------------------------------------------------- articles made from site pages
def _page_text(c, url: str) -> str:
    rows = c.execute("SELECT text FROM chunks WHERE url = %s ORDER BY position", (url,)).fetchall()
    return "\n".join(r[0] for r in rows)


def _fields(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z][A-Za-z ]{1,20}):\s*(.+?)\s*$", line)
        if m:
            out[m.group(1).strip().lower()] = m.group(2)
    return out


def company_article(title: str, text: str, url: str) -> dict[str, str] | None:
    """'Lake B2B — The B2B growth stack. Data, demand, delivery.' + Tag / Pillar / Products / Website lines."""
    first = (text.strip().splitlines() or [""])[0]
    tagline = first.split("—", 1)[1].strip() if "—" in first else ""
    f = _fields(text)
    if not tagline and not f:
        return None
    lines = [tagline] if tagline else []
    facts = [(k.title(), f[k]) for k in ("tag", "pillar", "products") if f.get(k)]
    if facts:
        lines.append("\n".join(f"- **{k}:** {v}" for k, v in facts))
    if f.get("website"):
        lines.append(f"Website: [{f['website'].replace('https://', '').replace('http://', '').rstrip('/')}]({f['website']})")
    return {"title": title, "summary": tagline or f"{title} is one of the Champions Group companies.",
            "body": "\n\n".join(lines) + f"\n\nSource: [{url.replace('https://', '')}]({url})", "source_url": url,
            "pillar": f.get("pillar", "")}


def toolkit_items(text: str) -> list[dict[str, str]]:
    """The toolkit page as records: 'title: X | description: Y | url: … | category: tool | site: …'."""
    items, cur = [], {}
    for line in text.splitlines():
        m = re.match(r"^\s*(title|description|url|category|featured|site):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "title" and cur.get("title"):
            items.append(cur)
            cur = {}
        cur[key] = val
    if cur.get("title"):
        items.append(cur)
    return [i for i in items if i.get("title") and i.get("description")]


def now_items(text: str) -> tuple[str | None, list[tuple[str, str]]]:
    """The Now page: its 'updated' date and the (label, text) focus pairs."""
    updated = re.search(r"updated:\s*(\d{4}-\d{2}-\d{2})", text)
    pairs, label = [], None
    for line in text.splitlines():
        m = re.match(r"^\s*k:\s*(.+)$", line)
        if m:
            label = m.group(1).strip()
            continue
        m = re.match(r"^\s*text:\s*(.+)$", line)
        if m and label:
            pairs.append((label.capitalize(), m.group(1).strip()))
            label = None
    return (updated.group(1) if updated else None), pairs


def site_articles(c) -> list[tuple[str, dict[str, Any]]]:
    """(collection slug, article) pairs built from the indexed site pages. Empty when the site is not indexed yet."""
    out: list[tuple[str, dict[str, Any]]] = []
    if not c.execute("SELECT 1 FROM pages LIMIT 1").fetchone():
        return out
    home = f"{BASE}/"
    out.append(("about-deep", {
        "title": "Who is Deep?", "summary": "Sreedeep Surapaneni: Group CMO at Champions Group and CEO of Champions Accelerator.",
        "body": "Deep is **Sreedeep Surapaneni**, based in Bangalore. He is Group CMO at Champions Group and CEO of "
                "Champions Accelerator, across twelve companies.\n\nHe builds in public: every weekday he ships something "
                "and writes it up on deependhq.com.\n\nSource: [deependhq.com](https://deependhq.com/)", "source_url": home,
        "featured": True}))
    out.append(("about-deep", {
        "title": "How the build-in-public log works", "summary": "One entry every weekday, live by 2 AM IST.",
        "body": "Every weekday gets one entry in the public log: what shipped, what it connects to, and what Deep thinks "
                "about it. Each entry starts as a note in his vault and goes live on deependhq.com by 2 AM IST. Gaps stay "
                "visible.\n\nWeekly essays sum up each week.\n\nRead the log: [deependhq.com/journey](https://deependhq.com/journey)",
        "source_url": f"{BASE}/journey"}))
    updated, pairs = now_items(_page_text(c, f"{BASE}/now"))
    if pairs:
        out.append(("about-deep", {
            "title": "What Deep is focused on", "summary": "The Now page: what has his attention" + (f" (updated {updated})." if updated else "."),
            "body": (f"From the Now page, last updated {updated}:\n\n" if updated else "")
                    + "\n".join(f"- **{k}:** {v}" for k, v in pairs)
                    + "\n\nSource: [deependhq.com/now](https://deependhq.com/now)", "source_url": f"{BASE}/now", "featured": True}))
    companies = c.execute("SELECT p.url, p.title FROM pages p WHERE p.url LIKE %s ORDER BY p.title", (f"{BASE}/company/%",)).fetchall()
    by_pillar: dict[str, list[str]] = {}
    for url, title in companies:
        a = company_article(title or url.rsplit("/", 1)[-1], _page_text(c, url), url)
        if a:
            by_pillar.setdefault(a.pop("pillar") or "other", []).append(a["title"])
            out.append(("companies", a))
    if by_pillar:
        names = {"accelerator": "Accelerator", "lakeb2b": "LakeB2B (data and services)", "champ": "Champ (product suite)",
                 "infratech": "InfraTech and Lagoons", "infratech-lagoons": "InfraTech and Lagoons"}
        body = "\n\n".join(f"## {names.get(p, p.title())}\n" + "\n".join(f"- {n}" for n in sorted(v)) for p, v in sorted(by_pillar.items()))
        total = sum(len(v) for v in by_pillar.values())
        out.insert(3, ("companies", {
            "title": "The Champions Group companies", "summary": f"All {total} companies, grouped by pillar.",
            "body": f"Champions Group has {total} companies, grouped by pillar.\n\n{body}\n\nSource: [deependhq.com/pillars](https://deependhq.com/pillars)",
            "source_url": f"{BASE}/pillars", "featured": True}))
    tools = toolkit_items(_page_text(c, f"{BASE}/toolkit"))
    if tools:
        out.append(("tools", {
            "title": "Deep's toolkit", "summary": f"{len(tools)} tools Deep builds and uses.",
            "body": "\n".join(f"- **{t['title']}:** {t['description']}" for t in tools)
                    + "\n\nSource: [deependhq.com/toolkit](https://deependhq.com/toolkit)", "source_url": f"{BASE}/toolkit"}))
        for t in tools:
            link = t.get("site") or t.get("url") or ""
            out.append(("tools", {"title": t["title"], "summary": t["description"][:200],
                                  "body": t["description"] + (f"\n\nLink: [{link.replace('https://', '')}]({link})" if link else "")
                                          + "\n\nSource: [deependhq.com/toolkit](https://deependhq.com/toolkit)",
                                  "source_url": f"{BASE}/toolkit"}))
    return out


# ---------------------------------------------------------------- storage
def _embed(article: dict[str, Any]) -> list[float] | None:
    try:
        from app.embeddings import embed_texts

        text = f"{article['title']}\n{article.get('summary') or ''}\n{(article.get('body') or '')[:1500]}"
        return embed_texts([text])[0]
    except Exception as e:
        log.warning("help article embedding failed: %s", e)
        return None


def _collection_id(c, slug: str) -> int | None:
    row = c.execute("SELECT id FROM help_collections WHERE slug = %s", (slug,)).fetchone()
    return int(row[0]) if row else None


def _unique_slug(c, base: str, own_id: int | None = None) -> str:
    slug, n = base, 2
    while True:
        row = c.execute("SELECT id FROM help_articles WHERE slug = %s", (slug,)).fetchone()
        if not row or (own_id and int(row[0]) == own_id):
            return slug
        slug, n = f"{base}-{n}", n + 1


def seed(force_site: bool = False) -> dict[str, int]:
    """Create the starter collections and builtin articles once, and (re)build the site articles. Owner and builtin
    articles someone edited are never overwritten."""
    made = {"collections": 0, "builtin": 0, "site": 0}
    with conn() as c:
        for i, (slug, title, desc) in enumerate(COLLECTIONS):
            if not _collection_id(c, slug):
                c.execute("INSERT INTO help_collections(slug, title, description, position) VALUES (%s, %s, %s, %s)", (slug, title, desc, i))
                made["collections"] += 1
        seeded = c.execute("SELECT value FROM settings WHERE key = 'help:builtin_seeded'").fetchone()
        if not seeded:
            for i, (coll, title, summary, body) in enumerate(BUILTIN):
                slug = slugify(title)
                if c.execute("SELECT 1 FROM help_articles WHERE slug = %s", (slug,)).fetchone():
                    continue
                c.execute("""INSERT INTO help_articles(collection_id, slug, title, summary, body, author, source, position)
                             VALUES (%s, %s, %s, %s, %s, %s, 'builtin', %s)""",
                          (_collection_id(c, coll), slug, title, summary, body, "Deep's team", i))
                made["builtin"] += 1
            c.execute("INSERT INTO settings(key, value) VALUES ('help:builtin_seeded', 'true') ON CONFLICT (key) DO NOTHING")
        have_site = c.execute("SELECT count(*) FROM help_articles WHERE source = 'site'").fetchone()[0]
        if force_site or not have_site:
            items = site_articles(c)
            if items:
                c.execute("DELETE FROM help_articles WHERE source = 'site'")
                for i, (coll, a) in enumerate(items):
                    slug = _unique_slug(c, slugify(a["title"]))
                    c.execute("""INSERT INTO help_articles(collection_id, slug, title, summary, body, author, source, source_url,
                                                           featured, position)
                                 VALUES (%s, %s, %s, %s, %s, 'deependhq.com', 'site', %s, %s, %s)""",
                              (_collection_id(c, coll), slug, a["title"], a["summary"], a["body"], a.get("source_url"),
                               bool(a.get("featured")), i))
                    made["site"] += 1
        c.commit()
    embed_missing()
    return made


def embed_missing(limit: int = 500) -> int:
    with conn() as c:
        rows = c.execute("SELECT id, title, summary, body FROM help_articles WHERE embedding IS NULL LIMIT %s", (limit,)).fetchall()
        for aid, title, summary, body in rows:
            vec = _embed({"title": title, "summary": summary, "body": body})
            if vec is not None:
                c.execute("UPDATE help_articles SET embedding = %s WHERE id = %s", (vec, aid))
        c.commit()
    return len(rows)


def seed_async() -> None:
    """At start-up, in the background: starter content and any missing vectors. Never raises."""
    def _go():
        try:
            r = seed()
            if any(r.values()):
                log.info("help center seeded: %s", r)
        except Exception as e:
            log.warning("help center seed failed: %s", e)
    threading.Thread(target=_go, name="help-seed", daemon=True).start()


# ---------------------------------------------------------------- reading (widget)
def _art(r) -> dict[str, Any]:
    return {"id": r[0], "slug": r[1], "title": r[2], "summary": r[3]}


def overview(top: int = 4) -> dict[str, Any]:
    """The Help tab and the Home search card: collections with counts, and the top articles."""
    with conn() as c:
        cols = c.execute(
            """SELECT hc.slug, hc.title, hc.description, count(ha.id) FILTER (WHERE ha.published)
               FROM help_collections hc LEFT JOIN help_articles ha ON ha.collection_id = hc.id
               GROUP BY hc.id ORDER BY hc.position, hc.id""").fetchall()
        tops = c.execute(
            """SELECT id, slug, title, summary FROM help_articles WHERE published
               ORDER BY featured DESC, views DESC, position, id LIMIT %s""", (top,)).fetchall()
    return {"collections": [{"slug": s, "title": t, "description": d, "articles": int(n)} for s, t, d, n in cols if n],
            "top": [_art(r) for r in tops]}


def collection(slug: str) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT id, slug, title, description FROM help_collections WHERE slug = %s", (slug,)).fetchone()
        if not row:
            return None
        arts = c.execute("""SELECT id, slug, title, summary FROM help_articles WHERE collection_id = %s AND published
                            ORDER BY featured DESC, position, id""", (row[0],)).fetchall()
        authors = [r[0] for r in c.execute("""SELECT DISTINCT author FROM help_articles WHERE collection_id = %s AND published
                                                AND author <> ''""", (row[0],)).fetchall()]
    return {"slug": row[1], "title": row[2], "description": row[3], "authors": authors, "articles": [_art(r) for r in arts]}


def article(slug: str, count_view: bool = True) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute(
            """SELECT a.id, a.slug, a.title, a.summary, a.body, a.author, a.updated_at, a.source_url, hc.slug, hc.title, a.collection_id
               FROM help_articles a LEFT JOIN help_collections hc ON hc.id = a.collection_id
               WHERE a.slug = %s AND a.published""", (slug,)).fetchone()
        if not row:
            return None
        if count_view:
            c.execute("UPDATE help_articles SET views = views + 1 WHERE id = %s", (row[0],))
            c.commit()
        related = c.execute("""SELECT id, slug, title, summary FROM help_articles WHERE collection_id = %s AND published AND id <> %s
                               ORDER BY featured DESC, position, id LIMIT 3""", (row[10], row[0])).fetchall() if row[10] else []
    return {"id": row[0], "slug": row[1], "title": row[2], "summary": row[3], "body": row[4], "author": row[5],
            "updated_at": row[6], "source_url": row[7], "collection": {"slug": row[8], "title": row[9]} if row[8] else None,
            "related": [_art(r) for r in related], "url": article_url(row[1])}


def search(q: str, limit: int = 8) -> list[dict[str, Any]]:
    """Meaning plus words: the embedding of the query against each article, with a lift for title and text matches."""
    q = (q or "").strip()[:200]
    if not q:
        return []
    like = f"%{q}%"
    vec = None
    try:
        from app.embeddings import embed_query

        vec = embed_query(q)
    except Exception as e:
        log.warning("help search embedding failed: %s", e)
    with conn() as c:
        if vec is not None:
            rows = c.execute(
                """SELECT id, slug, title, summary,
                          COALESCE(1 - (embedding <=> %s::vector), 0)
                          + CASE WHEN title ILIKE %s THEN 0.25 ELSE 0 END
                          + CASE WHEN summary ILIKE %s OR body ILIKE %s THEN 0.08 ELSE 0 END AS score
                   FROM help_articles WHERE published ORDER BY score DESC LIMIT %s""",
                (vec, like, like, like, limit)).fetchall()
            rows = [r for r in rows if r[4] >= settings.help_search_min_score]
        else:
            rows = c.execute("""SELECT id, slug, title, summary, 1.0 FROM help_articles
                                WHERE published AND (title ILIKE %s OR summary ILIKE %s OR body ILIKE %s)
                                ORDER BY featured DESC, views DESC LIMIT %s""", (like, like, like, limit)).fetchall()
    return [{**_art(r), "score": round(float(r[4]), 3)} for r in rows]


def retrieval_hits(vec: list[float], k: int = 2) -> list[dict[str, Any]]:
    """builtin and owner articles closest to a chat question, for retrieve.search() to cite (site ones are indexed already)."""
    with conn() as c:
        rows = c.execute(
            """SELECT slug, title, summary, body, 1 - (embedding <=> %s::vector) AS score FROM help_articles
               WHERE published AND source IN ('builtin', 'owner') AND embedding IS NOT NULL
               ORDER BY embedding <=> %s::vector LIMIT %s""", (vec, vec, k)).fetchall()
    return [{"url": article_url(r[0]), "title": r[1], "text": f"{r[1]}\n{r[2]}\n\n{r[3]}", "score": float(r[4]),
             "metadata": {"kind": "help", "slug": r[0]}} for r in rows]


# ---------------------------------------------------------------- console
def admin_list() -> dict[str, Any]:
    with conn() as c:
        cols = c.execute("SELECT id, slug, title, description, position FROM help_collections ORDER BY position, id").fetchall()
        arts = c.execute(
            """SELECT id, collection_id, slug, title, summary, body, author, source, source_url, published, featured, position, views, updated_at
               FROM help_articles ORDER BY collection_id NULLS LAST, featured DESC, position, id""").fetchall()
    ac = ["id", "collection_id", "slug", "title", "summary", "body", "author", "source", "source_url", "published", "featured",
          "position", "views", "updated_at"]
    return {"collections": [dict(zip(["id", "slug", "title", "description", "position"], r)) for r in cols],
            "articles": [dict(zip(ac, r)) for r in arts]}


def save_collection(data: dict[str, Any], cid: int | None = None) -> dict[str, Any]:
    title = (data.get("title") or "").strip()[:120]
    if not title:
        raise ValueError("title is required")
    desc = (data.get("description") or "").strip()[:400]
    pos = int(data.get("position") or 0)
    with conn() as c:
        if cid:
            row = c.execute("""UPDATE help_collections SET title = %s, description = %s, position = %s, updated_at = now()
                               WHERE id = %s RETURNING id, slug""", (title, desc, pos, cid)).fetchone()
            if not row:
                raise LookupError("no such collection")
        else:
            base, slug, n = slugify(title), slugify(title), 2
            while c.execute("SELECT 1 FROM help_collections WHERE slug = %s", (slug,)).fetchone():
                slug, n = f"{base}-{n}", n + 1
            row = c.execute("""INSERT INTO help_collections(slug, title, description, position) VALUES (%s, %s, %s, %s)
                               RETURNING id, slug""", (slug, title, desc, pos)).fetchone()
        c.commit()
    return {"id": int(row[0]), "slug": row[1], "title": title, "description": desc, "position": pos}


def delete_collection(cid: int) -> bool:
    with conn() as c:
        n = c.execute("DELETE FROM help_collections WHERE id = %s", (cid,)).rowcount
        c.commit()
    return n > 0


def save_article(data: dict[str, Any], aid: int | None = None) -> dict[str, Any]:
    """Create or edit an article. An edited site article becomes an owner article ("Refresh from the site" keeps it)."""
    title = (data.get("title") or "").strip()[:200]
    if not title:
        raise ValueError("title is required")
    fields = {"title": title, "summary": (data.get("summary") or "").strip()[:400], "body": (data.get("body") or "").strip()[:20000],
              "author": (data.get("author") or "").strip()[:80], "published": bool(data.get("published", True)),
              "featured": bool(data.get("featured", False)), "position": int(data.get("position") or 0),
              "collection_id": int(data["collection_id"]) if data.get("collection_id") not in (None, "") else None}
    vec = _embed(fields)
    with conn() as c:
        if aid:
            cur = c.execute("SELECT source FROM help_articles WHERE id = %s", (aid,)).fetchone()
            if not cur:
                raise LookupError("no such article")
            source = "owner" if cur[0] == "site" else cur[0]
            c.execute("""UPDATE help_articles SET title = %s, summary = %s, body = %s, author = %s, published = %s, featured = %s,
                                position = %s, collection_id = %s, source = %s, embedding = %s, updated_at = now() WHERE id = %s""",
                      (fields["title"], fields["summary"], fields["body"], fields["author"], fields["published"], fields["featured"],
                       fields["position"], fields["collection_id"], source, vec, aid))
            slug = c.execute("SELECT slug FROM help_articles WHERE id = %s", (aid,)).fetchone()[0]
        else:
            slug = _unique_slug(c, slugify(title))
            aid = int(c.execute("""INSERT INTO help_articles(collection_id, slug, title, summary, body, author, source, published,
                                                             featured, position, embedding)
                                   VALUES (%s, %s, %s, %s, %s, %s, 'owner', %s, %s, %s, %s) RETURNING id""",
                                (fields["collection_id"], slug, fields["title"], fields["summary"], fields["body"], fields["author"],
                                 fields["published"], fields["featured"], fields["position"], vec)).fetchone()[0])
        c.commit()
    return {"id": aid, "slug": slug, **{k: v for k, v in fields.items()}}


def delete_article(aid: int) -> bool:
    with conn() as c:
        n = c.execute("DELETE FROM help_articles WHERE id = %s", (aid,)).rowcount
        c.commit()
    return n > 0
