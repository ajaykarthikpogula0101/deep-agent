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


def _seg(text, start=0.0, end=2.0, lp=-0.2, nsp=0.01, cr=1.2):
    return {"text": text, "start": start, "end": end, "avg_logprob": lp, "no_speech_prob": nsp, "compression_ratio": cr}


def _stt_on(monkeypatch):
    monkeypatch.setattr(media.settings, "stt_provider", "openai"); monkeypatch.setattr(media.settings, "stt_api_key", "key")
    monkeypatch.setattr(media.settings, "stt_base_url", "https://api.groq.com/openai/v1"); monkeypatch.setattr(media.settings, "stt_model", "whisper-large-v3")
    monkeypatch.setattr(media.settings, "stt_hint_recheck", True)


@respx.mock
def test_transcribe_posts_multipart_to_an_openai_compatible_endpoint(monkeypatch):
    _stt_on(monkeypatch)
    route = respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(return_value=httpx.Response(
        200, json={"language": "English", "text": " What does Lake B2B do? ", "segments": [_seg(" What does Lake B2B do? ")]}))
    assert media.transcribe(b"RIFF....", "a.wav", "audio/wav", "en") == {"text": "What does Lake B2B do?", "language": "en"}
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer key" and b"whisper-large-v3" in req.content and b"filename=\"audio.wav\"" in req.content
    assert b"verbose_json" in req.content and b'name="prompt"' not in req.content  # segments for the no-speech filter; no names prompt
    # a plain json reply (endpoint without verbose_json) still works
    route.mock(return_value=httpx.Response(200, json={"text": " hello there "}))
    assert media.transcribe(b"x", "a.webm", "audio/webm")["text"] == "hello there"


@respx.mock
def test_auto_language_is_detected_not_forced_and_safari_audio_keeps_its_format(monkeypatch):
    """The old widget sent the browser's language in "auto", so Whisper translated Hindi or Telugu into English."""
    _stt_on(monkeypatch)
    route = respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(return_value=httpx.Response(
        200, json={"language": "Telugu", "text": "x", "segments": [_seg(" మీరు ఏ సేవలు అందిస్తారు?")]}))
    out = media.transcribe(b"x", "audio.webm", "audio/mp4", None, "te,en")
    assert out == {"text": "మీరు ఏ సేవలు అందిస్తారు?", "language": "te"} and len(route.calls) == 1  # detected one of their languages: one call
    body = route.calls[0].request.content
    assert b'name="language"' not in body and b'filename="audio.m4a"' in body and b"audio/mp4" in body
    # a picked language is passed through and never rechecked
    route.mock(return_value=httpx.Response(200, json={"language": "Hindi", "segments": [_seg(" मुझे कॉल बुक करनी है")]}))
    media.transcribe(b"x", "a.webm", "audio/webm", "hi-IN", "en")
    assert b'name="language"\r\n\r\nhi' in route.calls[1].request.content and len(route.calls) == 2


@respx.mock
def test_detection_outside_the_visitors_languages_is_rechecked_and_the_likelier_reading_wins(monkeypatch):
    _stt_on(monkeypatch)
    urdu = httpx.Response(200, json={"language": "Urdu", "segments": [_seg(" مجھے دیپ کے ساتھ کال بک کرنی ہے", lp=-0.55)]})
    hindi = httpx.Response(200, json={"language": "Hindi", "segments": [_seg(" मुझे दीप के साथ कॉल बुक करनी है", lp=-0.25)]})
    route = respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(side_effect=[urdu, hindi])
    assert media.transcribe(b"x", "a.webm", "audio/webm", None, "hi,en") == {"text": "मुझे दीप के साथ कॉल बुक करनी है", "language": "hi"}
    assert b'name="language"\r\n\r\nhi' in route.calls[1].request.content
    # the recheck reads worse: the detected language stays
    route.mock(side_effect=[httpx.Response(200, json={"language": "Telugu", "segments": [_seg(" నమస్కారం", lp=-0.3)]}),
                            httpx.Response(200, json={"language": "English", "segments": [_seg(" Namaskaram", lp=-0.9)]})])
    assert media.transcribe(b"x", "a.webm", "audio/webm", None, "en")["language"] == "te"
    monkeypatch.setattr(media.settings, "stt_hint_recheck", False)
    route.mock(side_effect=[urdu])
    assert media.transcribe(b"x", "a.webm", "audio/webm", None, "hi")["language"] == "ur"


def test_silence_and_noise_never_become_words():
    phantom = {"language": "English", "segments": [_seg(" Thank you.", nsp=0.7, lp=-0.6)]}
    assert media.clean_transcript(phantom)[0] == ""
    assert media.clean_transcript({"language": "English", "segments": [_seg(" you", nsp=0.3, lp=-1.4)]})[0] == ""
    assert media.clean_transcript({"language": "English", "segments": [_seg(" no speech here", nsp=0.9, lp=-1.3)]})[0] == ""
    loop = {"language": "English", "segments": [_seg(" Deep Deep Deep Deep Deep Deep", cr=3.1)]}
    assert media.clean_transcript(loop)[0] == ""
    # a real "thank you" said clearly is kept
    assert media.clean_transcript({"language": "English", "segments": [_seg(" Thank you.", nsp=0.02, lp=-0.1)]})[0] == "Thank you."
    assert media.parse_hints("en-US, hi-IN,xx,en,te") == ["en", "hi", "te"]
    assert media.clean_transcript({"language": "English", "segments": [_seg(" .", nsp=0.2)]})[0] == ""
    looped = {"language": "Malayalam", "segments": [_seg(" എന്നു പര്യാമ് ക്ക്ക്ക്ക്ക്ക്ക്ക്ക്ക്")]}
    assert media.clean_transcript(looped)[0] == "എന്നു പര്യാമ് ക്"
    assert media.clean_transcript({"language": "English", "segments": [_seg(" Book a call, call me")]})[0] == "Book a call, call me"
    cough = {"language": "Indonesian", "segments": [_seg(" Terima kasih.", nsp=0.66, lp=-0.6)]}  # a real cough on the 2026-10-14 benchmark
    assert media.clean_transcript(cough)[0] == ""
    assert media.clean_transcript({"language": "English", "segments": [_seg(" book it", nsp=0.7, lp=-0.4)]})[0] == ""


@respx.mock
def test_right_language_in_the_wrong_script_is_read_again_in_its_own_script(monkeypatch):
    """Whisper large-v3 detects Malayalam but writes it in Gurmukhi (seen on the benchmark); a Malayalam greeting as
    preceding text makes it write Malayalam."""
    _stt_on(monkeypatch)
    gurmukhi = httpx.Response(200, json={"language": "Malayalam", "segments": [_seg(" ਨੀਂਗੋਡੇ ਕੰਪਨੀ ਏਂਦੁ ਸੇਵਨੁੰਗੋ")]})
    malayalam = httpx.Response(200, json={"language": "Malayalam", "segments": [_seg(" നിങ്ങളുടെ കമ്പനി എന്ത് സേവനങ്ങളാണ്")]})
    route = respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(side_effect=[gurmukhi, malayalam])
    assert media.transcribe(b"x", "a.webm", "audio/webm", None, "ml") == {"text": "നിങ്ങളുടെ കമ്പനി എന്ത് സേവനങ്ങളാണ്", "language": "ml"}
    second = route.calls[1].request.content
    assert b'name="language"\r\n\r\nml' in second and "നമസ്കാരം".encode() in second
    assert media.script_ok("मुझे LakeB2B का डेटा चाहिए", "hi") and not media.script_ok("مجھے کال بک کرنی ہے", "hi") and media.script_ok("Hola", "es")


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


@respx.mock
def test_groq_rate_limit_is_waited_out_once_and_an_optional_reread_never_fails_the_request(monkeypatch):
    _stt_on(monkeypatch)
    monkeypatch.setattr(media.time, "sleep", lambda s: None)
    ok = httpx.Response(200, json={"language": "Telugu", "segments": [_seg(" నమస్కారం")]})
    limited = httpx.Response(429, headers={"retry-after": "3"}, json={"error": {"message": "rate limit"}})
    route = respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(side_effect=[limited, ok])
    assert media.transcribe(b"x", "a.webm", "audio/webm")["text"] == "నమస్కారం" and len(route.calls) == 2
    # the language re-check hits the cap twice: the first reading stands instead of an error
    route.mock(side_effect=[ok, limited, limited])
    assert media.transcribe(b"x", "a.webm", "audio/webm", None, "en") == {"text": "నమస్కారం", "language": "te"}
