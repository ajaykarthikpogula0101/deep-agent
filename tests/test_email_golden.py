"""The email redesign changed HTML only: every send path still produces the text parts, subjects, recipients, reply_to,
mailer kind/ref, attachments and send order recorded in tests/fixtures/email_golden.json, which was captured from the
code before the redesign touched the send paths (tests/email_golden.py)."""
from __future__ import annotations

import json

from tests.email_golden import FIXTURE, capture


def test_send_paths_match_the_golden_snapshot(monkeypatch):
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    now = json.loads(json.dumps(capture(monkeypatch.setattr), ensure_ascii=False, default=str))
    assert [e["case"] for e in now] == [e["case"] for e in golden]           # same messages, same order
    for got, want in zip(now, golden):
        assert got == want, got["case"]


def test_every_lifecycle_email_has_the_new_html_and_the_other_visitor_emails_stay_text_only(monkeypatch):
    sink: list[dict] = []
    capture(monkeypatch.setattr, html_sink=sink)
    for m in sink:
        case = m["case"]
        text_only = case.split(":")[1] in ("handoff", "booked", "enquiry", "handover") or case in (
            "send_test:host", "send_test:visitor_booking", "send_test:visitor_handover")
        if text_only:                                     # the hand-off / hand-over emails are unchanged: no HTML part
            assert m["html"] is None, case
        elif case == "send_test:visitor_gap":             # out of scope: the simple card
            assert m["html"] and "dm-card" not in m["html"], case
        else:
            h = m["html"]
            assert h and 'class="card dm-card"' in h and "<img" not in h and "#F28C28" not in h, (case, m["to"])
            assert len(h.encode()) < 100_000, case
