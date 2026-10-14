"""Knowledge-gap loop (app/gaps.py): which messages count as questions, grouping rewordings, the drafted answer and its
checks, the email to the people who asked, and (against Postgres) the whole loop on this test's own chats only:
nightly drafting, approving into custom answers, one email per person, opting out."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import gaps, links, templates
from app.config import settings
from tests.test_precall import M
from tests.test_reminders import _db_up


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "link_secret", "test-link-secret")
    monkeypatch.setattr(settings, "public_base_url", "https://assistant.example.com")


def hit(n, url="https://deependhq.com/lakeb2b", score=0.7):
    return SimpleNamespace(url=url + (f"#{n}" if n > 1 else ""), title=f"Page {n}", text=f"Excerpt {n} about LakeB2B data.", score=score)


def test_only_real_questions_count():
    assert gaps.question_text("Do you have fintech contacts in Germany?") == "Do you have fintech contacts in Germany?"
    for t in ("hi", "thanks!", "book a call", "I want to reschedule my call", "talk to a human", "ok", "[confirm] discovery-call 2026-10-14", "why?"):
        assert gaps.question_text(t) == "", t


def test_rewordings_join_one_group_or_an_existing_draft():
    v = lambda *xs: [x / sum(y * y for y in xs) ** 0.5 for x in xs]
    items = [{"ts": i} for i in range(5)]
    vecs = [v(1, 0, 0), v(0.95, 0.1, 0), v(0, 1, 0), v(0, 0, 1), v(0, 0.97, 0.1)]
    attach, groups = gaps.group(items, vecs, [(7, v(0, 0, 1))], 0.9)
    assert attach == {7: [3]} and groups == [[0, 1], [2, 4]]
    assert gaps.representative(["how much?", "pricing please", "How much?", "price"]) == "How much?"


def test_draft_is_checked_before_anyone_sees_it():
    hits = [hit(1), hit(2)]
    d = gaps.parse_draft(json.dumps({"relevant": True, "question": "Do you cover fintech in Germany?", "answer": "Yes, LakeB2B covers DACH fintech. See https://x.example",
                                     "grounded": True, "missing": "", "source": 2}), hits)
    assert d["link"] == hits[1].url and "https://" not in d["answer"] and d["grounded"]
    ph = gaps.parse_draft(json.dumps({"question": "What does it cost?", "answer": "Pricing starts at [price per contact] per record.", "grounded": True,
                                      "missing": "the price", "source": 9}), hits)
    assert not ph["grounded"] and ph["missing"] == "the price" and ph["link"] is None    # a placeholder is never "grounded"; source 9 does not exist
    off = gaps.parse_draft(json.dumps({"relevant": False, "question": "Weather today?", "answer": ""}), hits)
    assert off["relevant"] is False
    assert gaps.parse_draft("sorry, I can't", hits) is None and gaps.parse_draft('{"question": "q?", "answer": "short"}', hits) is None
    fb = gaps.compose(["what is the price", "What is the price"], hits, ask=lambda s, f: (_ for _ in ()).throw(TimeoutError("slow")))
    assert fb["composer"] == "rules" and fb["answer"] == "" and fb["question"] == "What is the price" and fb["model_error"] == "slow"
    with pytest.raises(ValueError, match=r"placeholders first: \[price\]"):
        gaps.approve(1, "What is the price?", "It costs [price].")


def test_the_email_quotes_their_words_and_carries_the_answer():
    subject, body, cta = gaps.render_followup(gaps.SAMPLE_PERSON, gaps.SAMPLE_ITEMS)
    assert subject == "Your question, answered: do u have fintech contacts in germany"
    assert body.startswith("Hi Ada,\n\nWhen you visited deependhq.com on 9 Oct,") and "YOUR QUESTION\n“do u have fintech contacts in germany”" in body
    assert "DACH region" in body and "Read more: https://deependhq.com/lakeb2b" in body and settings.zoom_booking_base in body
    t = links.sign("optout", "ada@lovelace.org")
    assert f"https://assistant.example.com/email/optout?e=ada%40lovelace.org&t={t}" in body
    assert cta == ("Ask Deep more", "https://deependhq.com/?utm_source=ask-deep&utm_medium=email&utm_campaign=gap-followup")
    two = gaps.render_followup(gaps.SAMPLE_PERSON, gaps.SAMPLE_ITEMS + [dict(gaps.SAMPLE_ITEMS[0], asked="and pricing?", answer="On a call.", link=None)])
    assert two[0].endswith("(+1 more)") and two[1].count("YOU ASKED") == 2
    html = templates.html_wrap(subject, body, cta)
    assert "YOUR QUESTION</p>" in html and "utm_campaign=gap-followup" in html
    tpl = dict(templates.get_templates(), visitor_gap_enabled="false")
    assert gaps.render_followup(gaps.SAMPLE_PERSON, gaps.SAMPLE_ITEMS, tpl) is None
    assert templates.preview("visitor_gap")["subject"] == subject


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_whole_loop_on_this_tests_chats_only(monkeypatch):
    from fastapi.testclient import TestClient

    from app.db import conn
    from app.main import app

    tag = uuid.uuid4().hex[:8]
    vid, s1, s2, s3, s4 = f"gp-vid-{tag}", f"gp1-{tag}", f"gp2-{tag}", f"gp3-{tag}", f"gp4-{tag}"
    email = f"ada.{tag}@lovelace-engines.com"
    sids = [s1, s2, s3, s4]
    real = gaps.candidates
    monkeypatch.setattr(gaps, "candidates", lambda *a, **k: [c for c in real(*a, **k) if c["session_id"] in sids])  # never real visitors' questions
    monkeypatch.setattr(gaps, "since", lambda: (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    calls = []

    def ask(system, facts):
        calls.append(facts)
        if "weather" in facts:
            return json.dumps({"relevant": False, "question": "What is the weather?", "answer": ""})
        return json.dumps({"relevant": True, "question": "Do you have fintech contacts in Germany?", "answer": "Yes. LakeB2B covers fintech decision makers in "
                           "[number] German companies.", "grounded": False, "missing": "how many companies", "source": 1})

    try:
        with conn() as c:
            for sid in sids:
                c.execute("INSERT INTO sessions(session_id, visitor_id, messages) VALUES (%s, %s, 2)", (sid, vid if sid in (s1, s2) else None))
            for sid, q in ((s1, "do u have fintech contacts in germany"), (s3, "Do you have fintech contacts in Germany?"), (s4, "what is the weather in pune today"),
                           (s4, "hello")):
                c.execute("INSERT INTO messages(session_id, role, text) VALUES (%s, 'user', %s)", (sid, q))
                c.execute("INSERT INTO messages(session_id, role, text, question, outcome, reason) VALUES (%s, 'assistant', 'Sorry…', %s, 'refused', 'low_confidence')", (sid, q))
            # the person who asked in s1 left their email later, on the same browser (s2)
            c.execute("INSERT INTO leads(name, email, reason, status, session_id) VALUES ('Ada Lovelace', %s, 'Please call me', 'handover', %s)", (email, s2))
            c.commit()
        r = gaps.run(ask=ask, search_fn=lambda q, k=6, vec=None: [hit(1)], match_custom=lambda v: False)
        assert r["checked"] == 4 and r["ignored"] == 1 and r["new_drafts"] == 1 and r["off_topic"] == 1 and len(calls) == 2, r
        assert gaps.run(ask=ask, search_fn=lambda q, k=6, vec=None: [hit(1)], match_custom=lambda v: False)["checked"] == 0   # each message once
        with conn() as c:
            did, = c.execute("SELECT DISTINCT draft_id FROM gap_asks WHERE session_id = %s", (s1,)).fetchone()
            off, = c.execute("SELECT status FROM gap_drafts WHERE id = (SELECT draft_id FROM gap_asks WHERE session_id = %s AND draft_id > 0)", (s4,)).fetchone()
        assert off == "dismissed"
        d = next(x for x in gaps.list_drafts() if x["id"] == did)
        assert d["asked"] == 2 and d["can_email"] == 1 and d["known"] == 1 and d["link"] == hit(1).url and not d["grounded"]
        assert set(d["variants"]) == {"do u have fintech contacts in germany", "Do you have fintech contacts in Germany?"}
        with pytest.raises(ValueError, match="placeholders"):
            gaps.approve(did, d["question"], d["answer"], d["link"])
        res = gaps.approve(did, d["question"], "Yes. LakeB2B covers fintech decision makers in 4,000 German companies.", d["link"])
        assert res["queued"] == 1 and res["skipped"] == {"no email known": 1} and len(res["custom_answer_ids"]) == 2   # the question + "do u have…"
        with conn() as c:
            assert c.execute("SELECT count(*) FROM custom_answers WHERE id = ANY(%s) AND answer LIKE '%%4,000 German%%'", (res["custom_answer_ids"],)).fetchone()[0] == 2
            pending = c.execute("SELECT email, due_at > now() FROM gap_followups WHERE draft_id = %s", (did,)).fetchall()
        assert pending == [(email, True)]                         # waits ten minutes, time to undo
        m = M()
        assert gaps.send_due(mailer=m)["sent"] == 0 or not [x for x in m.items if x[0] == email]
        with conn() as c:
            c.execute("UPDATE gap_followups SET due_at = now() WHERE draft_id = %s", (did,))
            c.commit()
        m = M()
        gaps.send_due(mailer=m)
        mine = [x for x in m.items if x[0] == email]
        assert len(mine) == 1 and mine[0][1] == "Your question, answered: do u have fintech contacts in germany"
        assert "4,000 German companies" in mine[0][2] and mine[0][3]["reply_to"] == settings.host_email and "utm_campaign=gap-followup" in mine[0][3]["html"]
        m = M()
        gaps.send_due(mailer=m)
        assert not [x for x in m.items if x[0] == email]          # once
        # the unsubscribe link: a page with a button, then no more of these emails
        client = TestClient(app)
        t = links.sign("optout", email)
        assert client.get(f"/email/optout?e={email}&t=bad").status_code == 404
        assert "Yes, stop these emails" in client.get(f"/email/optout?e={email}&t={t}").text and not gaps.opted_out(email)
        assert "won't get emails like this" in client.post(f"/email/optout?e={email}&t={t}").text and gaps.opted_out(email)
        assert next(p for p in gaps.askers(did) if p.get("email") == email)["why"] in ("already emailed", "opted out")
    finally:
        with conn() as c:
            dids = [r[0] for r in c.execute("SELECT DISTINCT draft_id FROM gap_asks WHERE session_id = ANY(%s) AND draft_id > 0", (sids,)).fetchall()]
            ca = [i for (ids,) in c.execute("SELECT custom_answer_ids FROM gap_drafts WHERE id = ANY(%s)", (dids,)).fetchall() for i in ids]
            c.execute("DELETE FROM custom_answers WHERE id = ANY(%s)", (ca,))
            c.execute("DELETE FROM gap_followups WHERE draft_id = ANY(%s)", (dids,))
            c.execute("DELETE FROM gap_drafts WHERE id = ANY(%s)", (dids,))
            c.execute("DELETE FROM gap_asks WHERE session_id = ANY(%s)", (sids,))
            c.execute("DELETE FROM email_optouts WHERE email = %s", (email,))
            c.execute("DELETE FROM events WHERE kind IN ('gap_approved', 'gap_followup', 'email_optout') AND (detail->>'email' = %s OR detail->>'draft_id' = ANY(%s))",
                      (email, [str(x) for x in dids]))
            c.execute("DELETE FROM leads WHERE email = %s", (email,))
            c.execute("DELETE FROM messages WHERE session_id = ANY(%s)", (sids,))
            c.execute("DELETE FROM sessions WHERE session_id = ANY(%s)", (sids,))
            c.commit()
