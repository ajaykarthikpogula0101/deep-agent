"""Composer media: attachment validation and text extraction, GIF result normalisation, speech config gating."""
from __future__ import annotations

import io

import httpx
import pytest
import respx

from app import media


def test_validate_accepts_known_types_and_rejects_others(monkeypatch):
    monkeypatch.setattr(media.settings, "upload_max_mb", 1)
    assert media.validate("Report Q3.pdf", 1000) == ("Report Q3.pdf", "application/pdf")
    assert media.validate("../../etc/passwd.txt", 10)[0] == ".._.._etc_passwd.txt"
    with pytest.raises(ValueError, match="not supported"):
        media.validate("malware.exe", 10)
    with pytest.raises(ValueError, match="larger than 1 MB"):
        media.validate("big.png", 2 * 1024 * 1024)
    with pytest.raises(ValueError, match="empty"):
        media.validate("x.txt", 0)


def test_text_extraction_for_text_and_pdf(tmp_path):
    t = tmp_path / "notes.txt"; t.write_text("hello from a text file", encoding="utf-8")
    assert media.extract_text(t, "text/plain") == "hello from a text file"
    from pypdf import PdfWriter

    p = tmp_path / "blank.pdf"; w = PdfWriter(); w.add_blank_page(width=200, height=200); w.write(p)
    assert media.extract_text(p, "application/pdf") == ""  # blank page: no text, no crash
    assert media.extract_text(tmp_path / "pic.png", "image/png") == ""


@respx.mock
def test_gif_search_normalises_tenor_and_giphy(monkeypatch):
    monkeypatch.setattr(media.settings, "gif_api_key", "k")
    monkeypatch.setattr(media.settings, "gif_provider", "tenor")
    respx.get("https://tenor.googleapis.com/v2/search").mock(return_value=httpx.Response(200, json={"results": [
        {"id": "1", "content_description": "cat", "media_formats": {"gif": {"url": "https://t/1.gif"}, "tinygif": {"url": "https://t/1s.gif"}}}]}))
    r = media.gif_search("cat")
    assert r == {"items": [{"id": "1", "title": "cat", "url": "https://t/1.gif", "preview": "https://t/1s.gif"}]}
    monkeypatch.setattr(media.settings, "gif_provider", "giphy")
    respx.get("https://api.giphy.com/v1/gifs/trending").mock(return_value=httpx.Response(200, json={"data": [
        {"id": "g", "title": "dog", "images": {"original": {"url": "https://g/o.gif"}, "fixed_height_small": {"url": "https://g/s.gif"}}}]}))
    assert media.gif_search("")["items"][0] == {"id": "g", "title": "dog", "url": "https://g/o.gif", "preview": "https://g/s.gif"}
    monkeypatch.setattr(media.settings, "gif_api_key", "")
    assert media.gif_search("cat") == {"items": [], "error": "not configured"}


def test_speech_is_optional_and_config_reflects_it(monkeypatch):
    monkeypatch.setattr(media.settings, "stt_provider", "browser"); monkeypatch.setattr(media.settings, "stt_api_key", "")
    monkeypatch.setattr(media.settings, "tts_provider", "browser"); monkeypatch.setattr(media.settings, "gif_api_key", "")
    cfg = media.widget_config()
    assert cfg["stt"] == "browser" and cfg["tts"] == "browser" and cfg["gif"] is False and ".pdf" in cfg["upload_types"]
    with pytest.raises(RuntimeError):
        media.transcribe(b"x")
    monkeypatch.setattr(media.settings, "stt_provider", "openai"); monkeypatch.setattr(media.settings, "stt_api_key", "key")
    assert media.widget_config()["stt"] == "server"


@respx.mock
def test_transcribe_posts_multipart_to_an_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setattr(media.settings, "stt_provider", "openai"); monkeypatch.setattr(media.settings, "stt_api_key", "key")
    monkeypatch.setattr(media.settings, "stt_base_url", "https://api.groq.com/openai/v1"); monkeypatch.setattr(media.settings, "stt_model", "whisper-large-v3")
    route = respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(return_value=httpx.Response(200, json={"text": " What does Lake B2B do? "}))
    assert media.transcribe(b"RIFF....", "a.wav", "audio/wav", "en") == "What does Lake B2B do?"
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer key" and b"whisper-large-v3" in req.content and b"filename=\"a.wav\"" in req.content


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
def test_upload_round_trip_and_session_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(media.settings, "upload_dir", str(tmp_path))
    from app.db import conn

    up = media.save_upload("sess-a", "brief.txt", b"Lake B2B wants EU fintech data.")
    try:
        assert up["has_text"] and up["url"] == f"/uploads/{up['id']}" and (tmp_path / f"{up['id']}.txt").exists()
        block, meta = media.attachments_block([up["id"]], "sess-a")
        assert "EU fintech" in block and meta[0]["name"] == "brief.txt"
        assert media.attachments_block([up["id"]], "sess-b") == ("", [])  # another session cannot use it
        assert media.get_upload("nope") is None and media.get_upload("../x") is None
    finally:
        with conn() as c:
            c.execute("DELETE FROM uploads WHERE id = %s", (up["id"],)); c.commit()
