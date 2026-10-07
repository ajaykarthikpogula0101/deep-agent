"""Email templates: rendering, brand derivation, host brief and visitor confirmation. Pure (DEFAULTS passed explicitly)."""
from __future__ import annotations

import pytest

from app import templates as T


def test_render_leaves_no_trace_of_unknown_or_empty_variables():
    assert T.render("Hi {first_name}, {missing}!", {"first_name": "Ada"}) == "Hi Ada, !"
    assert T.render("", {}) == ""


def test_brand_follows_the_call_type_then_the_default():
    assert T.brand_for("LakeB2B Discovery Call", "discovery-call", T.DEFAULTS) == "LakeB2B"
    assert T.brand_for("SPAN Services Intro", "span-intro", T.DEFAULTS) == "SPAN Global Services"
    assert T.brand_for("GTM Strategy Session", "gtm-strategy", T.DEFAULTS) == "Champions Group"
    custom = dict(T.DEFAULTS, brand_map="gtm=Champions Accelerator", brand_default="Deep's team")
    assert T.brand_for("GTM Strategy Session", "gtm-strategy", custom) == "Champions Accelerator"
    assert T.brand_for("Something else", "x", custom) == "Deep's team"


def test_host_subject_carries_brand_kind_name_title_and_date():
    subject, body = T.render_host(T.SAMPLE_LEAD, T.DEFAULTS)
    assert subject == "[LakeB2B] Demo request, handing off to Zoom: Ada Lovelace · LakeB2B Discovery Call · Wed 07 Oct, 19:00 (Asia/Kolkata)"
    assert "Where:   Bengaluru" in body and "Note:" not in body  # empty variables drop their line


def test_host_subject_without_a_slot_has_no_dangling_separators():
    lead = dict(T.SAMPLE_LEAD, status="handover", schedule="-", slot_label_host="-", slot_label_visitor="-")
    subject, _ = T.render_host(lead, T.DEFAULTS)
    assert subject == "[Champions Group] Visitor wants a human reply: Ada Lovelace · a call with Deep"


def test_visitor_booking_email_thanks_by_brand_and_points_to_the_zoom_link():
    subject, body = T.render_visitor(T.SAMPLE_LEAD, T.DEFAULTS)
    assert subject == "Thank you for booking with LakeB2B: LakeB2B Discovery Call on Wed 07 Oct, 09:30 (America/New_York)"
    assert body.startswith("Hi Ada,") and "Thank you for booking with LakeB2B." in body
    assert "confirm the time on Zoom" in body and T.SAMPLE_LEAD["handoff_url"] in body
    booked = T.render_visitor(dict(T.SAMPLE_LEAD, status="booked"), T.DEFAULTS)[1]
    assert "It's confirmed" in booked and "scheduler.zoom.us" not in booked


def test_visitor_handover_ack_and_disabled_kinds():
    subject, body = T.render_visitor(dict(T.SAMPLE_LEAD, status="handover", schedule="-"), T.DEFAULTS)
    assert subject == "Thanks for your message to Champions Group" and "will reply to this address" in body
    off = dict(T.DEFAULTS, visitor_booking_enabled="false")
    assert T.render_visitor(T.SAMPLE_LEAD, off) is None
    assert T.render_visitor(dict(T.SAMPLE_LEAD, status="slot_taken"), T.DEFAULTS) is None


def test_owner_can_change_the_subject_with_dynamic_variables():
    tpl = dict(T.DEFAULTS, visitor_booking_subject="Thank you for booking with the {brand}, {first_name} ({email})")
    subject, _ = T.render_visitor(T.SAMPLE_LEAD, tpl)
    assert subject == "Thank you for booking with the LakeB2B, Ada (ada@lovelace.org)"


def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_saved_templates_round_trip_and_empty_restores_default():
    before = T.get_templates()
    try:
        saved = T.set_templates({"visitor_booking_subject": "Thanks from {brand}!", "unknown_key": "ignored"})
        assert saved["visitor_booking_subject"] == "Thanks from {brand}!"
        assert T.previews()["visitor_booking"]["subject"] == "Thanks from LakeB2B!"
        restored = T.set_templates({"visitor_booking_subject": ""})
        assert restored["visitor_booking_subject"] == T.DEFAULTS["visitor_booking_subject"]
    finally:
        T.set_templates({"visitor_booking_subject": before["visitor_booking_subject"] if before["visitor_booking_subject"] != T.DEFAULTS["visitor_booking_subject"] else ""})
