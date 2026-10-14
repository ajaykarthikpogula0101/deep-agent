"""Speech-to-text benchmark: the widget's current Groq Whisper calls vs candidate fixes, character error rate per language.

Usage: python bench.py [variant ...]   (default: all variants)   -> results/<variant>.json and a table on stdout
Variant "server" posts each clip to a running app (STT_SERVER, default http://127.0.0.1:8089/stt) with English browser hints.
"""
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import httpx
import imageio_ffmpeg

HERE = Path(os.environ.get("STT_BENCH_DIR") or Path(__file__).parent / "out")
env = (Path(__file__).resolve().parents[2] / ".env").read_text(encoding="utf-8")
KEY = re.search(r"^STT_API_KEY=(\S+)", env, re.M).group(1).strip('"')
URL = "https://api.groq.com/openai/v1/audio/transcriptions"
CLIPS = json.loads((HERE / "clips.json").read_text(encoding="utf-8"))
FF = imageio_ffmpeg.get_ffmpeg_exe()
PROMPT = ("Deep, Sreedeep, Champions Group, LakeB2B, SPAN Global Services, Ampliz, MetricFox, Recruit Champ, "
          "discovery call, GTM strategy session, ABM, B2B data, intent data.")
NAMES = {"english": "en", "hindi": "hi", "telugu": "te", "tamil": "ta", "kannada": "kn", "malayalam": "ml", "marathi": "mr",
         "bengali": "bn", "spanish": "es", "french": "fr", "german": "de", "portuguese": "pt", "arabic": "ar", "chinese": "zh",
         "japanese": "ja", "urdu": "ur", "gujarati": "gu", "punjabi": "pa", "nepali": "ne", "sinhala": "si"}
_client = httpx.Client(timeout=90)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith(("P", "S")))
    return re.sub(r"\s+", "", s)


def cer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hc in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    return min(1.0, prev[-1] / len(r))


_last = [0.0]


def _pace():  # Groq allows 20 audio requests a minute: keep under it instead of bouncing off 429s
    wait = _last[0] + float(os.environ.get("STT_PACE", "3.2")) - time.time()
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def groq(audio: bytes, **params) -> dict:
    data = {"model": "whisper-large-v3", **{k: str(v) for k, v in params.items() if v is not None}}
    for attempt in range(40):
        _pace()
        r = _client.post(URL, headers={"Authorization": f"Bearer {KEY}"}, data=data, files={"file": ("audio.webm", audio, "audio/webm")})
        if r.status_code == 429:
            time.sleep(float(r.headers.get("retry-after", "5")) + 1)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("rate limited")


def cut(path: Path, seconds: float) -> bytes:
    return subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-i", str(path), "-t", str(seconds), "-c:a", "libopus", "-b:a", "32k",
                           "-f", "webm", "-"], capture_output=True, check=True).stdout


HALLU = re.compile(r"^\W*(thank you( (so much|very much|for watching|for listening))?|thanks( for watching)?|you|bye|okay|subtitles by .*|"
                   r"please subscribe.*|ご視聴ありがとうございました|продолжение следует|字幕.*|sous-titr.*|untertitel.*)\W*$", re.I)


def clean(d: dict) -> tuple[str, str, float]:
    """Text without no-speech segments; known silence hallucinations dropped. Returns (text, lang_code, avg_logprob)."""
    segs = d.get("segments") or []
    keep = [s for s in segs if not (s.get("no_speech_prob", 0) > 0.6 and s.get("avg_logprob", 0) < -1.0) and s.get("compression_ratio", 1) < 2.6]
    text = "".join(s.get("text", "") for s in keep).strip() if segs else (d.get("text") or "").strip()
    if HALLU.match(text) and all(s.get("no_speech_prob", 0) > 0.2 for s in keep):
        text = ""
    lp = sum(s.get("avg_logprob", 0) * max(0.01, s.get("end", 0) - s.get("start", 0)) for s in keep) / max(0.01, sum(max(0.01, s.get("end", 0) - s.get("start", 0)) for s in keep)) if keep else -9
    return text, NAMES.get((d.get("language") or "").lower(), (d.get("language") or "")[:2].lower()), lp


def v_old_dictation(c, audio):   # composer mic, "auto" in an English browser -> language=en forced
    return groq(audio, language="en", response_format="json").get("text", "").strip(), "en"


def v_old_voice(c, audio):       # call view: auto, recording stopped after 6 s
    return groq(cut(HERE / "clips" / f"{c['id']}.webm", 6.0), response_format="json").get("text", "").strip(), ""


def v_auto(c, audio):            # auto, full clip, as before otherwise
    return groq(audio, response_format="json").get("text", "").strip(), ""


def v_clean(c, audio):           # auto + verbose_json + temperature 0 + no-speech filter
    t, lang, _ = clean(groq(audio, response_format="verbose_json", temperature=0))
    return t, lang


def v_prompt(c, audio):          # + vocabulary prompt
    t, lang, _ = clean(groq(audio, response_format="verbose_json", temperature=0, prompt=PROMPT))
    return t, lang


def v_hint(c, audio, hints=("en",)):  # + when the detected language is not one the visitor uses, also try theirs; keep the likelier
    t, lang, lp = clean(groq(audio, response_format="verbose_json", temperature=0, prompt=PROMPT))
    if t and lang and lang not in hints:
        t2, lang2, lp2 = clean(groq(audio, response_format="verbose_json", temperature=0, prompt=PROMPT, language=hints[0]))
        if t2 and lp2 > lp + 0.15:
            return t2, lang2 + "*"
    return t, lang


def v_server(c, audio):
    url = os.environ.get("STT_SERVER", "http://127.0.0.1:8089/stt")
    for attempt in range(40):
        _pace()
        r = _client.post(url, headers={"Origin": "http://localhost:8080"}, data={"hints": "en-US,en"},
                         files={"file": ("audio.webm", audio, "audio/webm")})
        if r.status_code == 429:
            time.sleep(3)
            continue
        r.raise_for_status()
        d = r.json()
        return d.get("text", ""), d.get("language", "")
    raise RuntimeError("server rate limited")


VARIANTS = {"old_dictation": v_old_dictation, "old_voice": v_old_voice, "auto": v_auto, "clean": v_clean, "prompt": v_prompt,
            "hint": v_hint, "server": v_server}


def run(name):
    fn, out = VARIANTS[name], []
    for c in CLIPS:
        audio = (HERE / "clips" / f"{c['id']}.webm").read_bytes()
        try:
            text, lang = fn(c, audio)
        except Exception as e:
            text, lang = f"<error {e}>", ""
        out.append({**c, "hyp": text, "hyp_lang": lang, "cer": round(cer(c["text"], text), 3)})
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"{name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def summary(names):
    res = {n: json.loads((HERE / "results" / f"{n}.json").read_text(encoding="utf-8")) for n in names}
    langs = []
    for c in CLIPS:
        k = c["id"].split(".")[0]
        if c["cond"] != "nonspeech" and k not in langs:
            langs.append(k)
    print("lang".ljust(9) + "".join(n[:13].rjust(14) for n in names))
    for k in langs:
        print(k.ljust(9) + "".join(f"{100 * sum(x['cer'] for x in res[n] if x['id'].split('.')[0] == k) / 3:13.0f}%" for n in names))
    for cond in ("clean", "pause", "noise"):
        print(("ALL " + cond).ljust(9) + "".join(f"{100 * sum(x['cer'] for x in res[n] if x['cond'] == cond) / len(langs):13.1f}%" for n in names))
    print("speech".ljust(9) + "".join(f"{100 * sum(x['cer'] for x in res[n] if x['cond'] != 'nonspeech') / (3 * len(langs)):13.1f}%" for n in names))
    print("phantom".ljust(9) + "".join(f"{sum(1 for x in res[n] if x['cond'] == 'nonspeech' and x['hyp']):13d} " for n in names))


if __name__ == "__main__":
    names = sys.argv[1:] or [n for n in VARIANTS if n != "server"]
    for n in names:
        if not (HERE / "results" / f"{n}.json").exists() or os.environ.get("RERUN"):
            t0 = time.time()
            run(n)
            print(f"{n}: {time.time() - t0:.0f}s", flush=True)
    summary(names)
