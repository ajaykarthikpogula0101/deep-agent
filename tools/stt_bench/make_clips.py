"""Multilingual speech clips for the speech-to-text benchmark (neural TTS voices, then recorded-like conditions).

Writes clips/<id>.webm (Opus 48 kHz mono, what Chrome's MediaRecorder produces) and clips.json with the reference text.
Conditions: clean (0.4 s lead-in), pause (1.5 s silence before and after, like a slow start), noise (office-like noise at
~12 dB SNR), and three non-speech clips (silence, noise, a cough-like burst) to catch hallucinations.
"""
import asyncio
import json
import os
import subprocess
from pathlib import Path

import edge_tts
import imageio_ffmpeg
import numpy as np

FF = imageio_ffmpeg.get_ffmpeg_exe()
WORK = Path(os.environ.get("STT_BENCH_DIR") or Path(__file__).parent / "out")
OUT = WORK / "clips"
OUT.mkdir(exist_ok=True)
SR = 16000

SENTENCES = [
    ("en", "en-US-AriaNeural", "I would like to book a discovery call with Deep about LakeB2B intent data for our sales team."),
    ("en-in", "en-IN-PrabhatNeural", "Can you tell me how Champions Group and SPAN Global Services help with account based marketing in India?"),
    ("en-long", "en-GB-RyanNeural", "We are a mid sized fintech company in London and we are planning an outbound campaign for the first quarter, "
                                    "so I want to understand what kind of verified contact data you have for banks in Europe and how fresh it is."),
    ("hi", "hi-IN-SwaraNeural", "मुझे दीप के साथ एक कॉल बुक करनी है, क्या आप मुझे अगले हफ्ते का समय बता सकते हैं?"),
    ("te", "te-IN-ShrutiNeural", "నేను మీ కంపెనీ గురించి తెలుసుకోవాలనుకుంటున్నాను, మీరు ఏ సేవలు అందిస్తారు?"),
    ("ta", "ta-IN-PallaviNeural", "உங்கள் நிறுவனம் என்ன சேவைகளை வழங்குகிறது என்று சொல்ல முடியுமா?"),
    ("kn", "kn-IN-SapnaNeural", "ನಿಮ್ಮ ಕಂಪನಿ ಯಾವ ಸೇವೆಗಳನ್ನು ನೀಡುತ್ತದೆ ಎಂದು ತಿಳಿಸಬಹುದೇ?"),
    ("ml", "ml-IN-SobhanaNeural", "നിങ്ങളുടെ കമ്പനി എന്ത് സേവനങ്ങളാണ് നൽകുന്നത് എന്ന് പറയാമോ?"),
    ("mr", "mr-IN-AarohiNeural", "मला तुमच्या कंपनीबद्दल अधिक माहिती हवी आहे, तुम्ही कोणत्या सेवा देता?"),
    ("bn", "bn-IN-TanishaaNeural", "আমি আপনার কোম্পানি সম্পর্কে আরও জানতে চাই, আপনারা কী কী পরিষেবা দেন?"),
    ("es", "es-ES-ElviraNeural", "Quiero reservar una llamada con Deep para hablar sobre datos de clientes en España."),
    ("fr", "fr-FR-DeniseNeural", "Je voudrais savoir quels services votre entreprise propose pour le marketing B2B en France."),
    ("de", "de-DE-KatjaNeural", "Ich möchte einen Termin vereinbaren, um über Ihre Daten für den deutschen Markt zu sprechen."),
    ("pt", "pt-BR-FranciscaNeural", "Gostaria de agendar uma conversa sobre dados de empresas no Brasil."),
    ("ar", "ar-SA-ZariyahNeural", "أريد أن أحجز مكالمة لمعرفة المزيد عن خدماتكم في الشرق الأوسط."),
    ("zh", "zh-CN-XiaoxiaoNeural", "我想预约一个电话，了解你们公司的数据服务。"),
    ("ja", "ja-JP-NanamiNeural", "御社のデータサービスについて詳しく知りたいので、電話を予約したいです。"),
]


def run(args, data=None):
    return subprocess.run([FF, "-hide_banner", "-loglevel", "error", *args], input=data, capture_output=True, check=True).stdout


def to_pcm(path: Path) -> np.ndarray:
    raw = run(["-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"])
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def office_noise(n: int, rng) -> np.ndarray:
    w = rng.standard_normal(n).astype(np.float32)
    b = np.cumsum(w) / 60  # brown-ish rumble
    b -= np.convolve(b, np.ones(400) / 400, mode="same")
    hum = 0.3 * np.sin(2 * np.pi * 100 * np.arange(n) / SR)
    x = 0.6 * w + b + hum
    return (x / (np.sqrt(np.mean(x ** 2)) + 1e-9)).astype(np.float32)


def to_webm(pcm: np.ndarray, out: Path) -> None:
    data = (np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes()
    run(["-y", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-", "-ar", "48000", "-c:a", "libopus", "-b:a", "32k", str(out)], data)


async def main():
    rng = np.random.default_rng(7)
    meta = []
    for code, voice, text in SENTENCES:
        mp3 = OUT / f"{code}.mp3"
        if not mp3.exists():
            await edge_tts.Communicate(text, voice).save(str(mp3))
        s = to_pcm(mp3)
        s = s / (np.max(np.abs(s)) + 1e-9) * 0.5
        sil = lambda sec: np.zeros(int(sec * SR), np.float32)  # noqa: E731
        conds = {"clean": np.concatenate([sil(0.4), s, sil(0.4)]),
                 "pause": np.concatenate([sil(1.5), s, sil(1.5)])}
        x = np.concatenate([sil(0.8), s, sil(0.8)])
        ps = np.sqrt(np.mean(s ** 2))
        conds["noise"] = x + office_noise(len(x), rng) * ps / (10 ** (12 / 20))
        for cond, pcm in conds.items():
            cid = f"{code}.{cond}"
            to_webm(pcm, OUT / f"{cid}.webm")
            meta.append({"id": cid, "lang": code.split("-")[0], "text": text, "cond": cond, "seconds": round(len(pcm) / SR, 2),
                         "speech_start": 0.4 if cond == "clean" else 1.5 if cond == "pause" else 0.8})
    n = 4 * SR
    for cid, pcm in (("silence", np.zeros(n, np.float32) + rng.standard_normal(n).astype(np.float32) * 0.0005),
                     ("roomnoise", office_noise(n, rng) * 0.02),
                     ("cough", np.concatenate([np.zeros(SR), rng.standard_normal(int(0.25 * SR)).astype(np.float32) * 0.3 * np.hanning(int(0.25 * SR)), np.zeros(int(2.75 * SR))]))):
        to_webm(pcm.astype(np.float32), OUT / f"{cid}.webm")
        meta.append({"id": cid, "lang": "", "text": "", "cond": "nonspeech", "seconds": 4.0, "speech_start": 0})
    (WORK / "clips.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(meta), "clips")


if __name__ == "__main__":
    asyncio.run(main())
