from app.ingest.chunker import Doc, chunk_doc, count_tokens
from app.ingest.sources import html_to_doc, parse_data_js, parse_llms_full

SAMPLE_LLMS = """# deep >_ (deependhq.com): full text

> Every public journey entry and essay.

## Journey

### Day 338, 2026-10-04 (thinking)

wrote next week's plan before monday hits: three decisions.

Thread: the date bug a weekend check caught.

Arcs: Champions Operations

Link: https://deependhq.com/journey.html#day-338

### Day 337, 2026-10-03 (building)

the saturday client dispatch run caught its own mistake before it shipped.

Link: https://deependhq.com/journey.html#day-337

## Essays

### This week the system caught everything except the empty rooms.

Essay body paragraph one. Essay body paragraph two.

Link: https://deependhq.com/post.html?slug=week-46-the-empty-room-arc
"""


def test_parse_llms_full_keeps_url_day_and_kind():
    docs = parse_llms_full(SAMPLE_LLMS)
    assert [d.url for d in docs] == [
        "https://deependhq.com/journey.html#day-338",
        "https://deependhq.com/journey.html#day-337",
        "https://deependhq.com/post.html?slug=week-46-the-empty-room-arc",
    ]
    assert docs[0].metadata == {"kind": "journey", "day": 338, "date": "2026-10-04", "mode": "thinking"}
    assert docs[2].metadata["kind"] == "essay"
    assert "Link:" not in docs[0].text


def test_chunks_carry_url_and_respect_size():
    long_text = "\n\n".join(f"Paragraph {i}. " + "word " * 120 for i in range(10))
    chunks = chunk_doc(Doc(url="https://deependhq.com/x", title="X", source="html", text=long_text, section="S"))
    assert len(chunks) > 1
    for ch in chunks:
        assert ch.url == "https://deependhq.com/x"
        assert ch.section == "S"
        assert ch.tokens <= 700
        assert ch.metadata["title"] == "X"
    assert [c.position for c in chunks] == list(range(len(chunks)))


def test_parse_data_js_extracts_companies():
    js = 'window.DH_DATA = {"companies":[{"name":"Lake B2B","desc":"B2B data.","slug":"lake-b2b","products":["A","B"],"url":"https://lakeb2b.com","pillar":"data"}],"now":{"items":["ship the bot"]}};'
    docs = parse_data_js(js)
    urls = {d.url for d in docs}
    assert "https://deependhq.com/company/lake-b2b" in urls
    assert "https://deependhq.com/now" in urls
    company = next(d for d in docs if d.url.endswith("lake-b2b"))
    assert "Products: A, B" in company.text


def test_html_to_doc_strips_scripts_and_ascii_art():
    html = """<html><head><title>Privacy</title></head><body><nav>menu</nav><main>
    <h1>Privacy</h1><p>We keep logs for 30 days.</p><pre>░░░███</pre><script>alert(1)</script>
    <p>⠀⠀⣠⣾⣿⠟⠀</p></main><footer>foot</footer></body></html>"""
    d = html_to_doc("https://deependhq.com/privacy", html)
    assert d.title == "Privacy"
    assert "alert" not in d.text and "menu" not in d.text and "⣿" not in d.text
    assert "We keep logs for 30 days." in d.text
    assert count_tokens(d.text) < 50
