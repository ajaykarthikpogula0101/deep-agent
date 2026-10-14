"""WAV clips for scripts/browser_check_voice.mjs: 1 s of quiet room tone, the sentence, 3.5 s of room tone (48 kHz mono 16-bit).
The browser plays one as its microphone, so the widget's recorder must find the start and the end of speech by itself."""
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from make_clips import SENTENCES, OUT, WORK, office_noise, to_pcm  # noqa: E402

SR = 16000
PICK = {"en": True, "en-long": True, "hi": True, "te": True, "ta": False, "kn": False, "bn": False, "es": False, "ar": False, "zh": False, "ja": False}
dest = WORK / "wav"
dest.mkdir(exist_ok=True)
rng = np.random.default_rng(3)
meta = []


def write(name, pcm):
    up = np.interp(np.arange(0, len(pcm), SR / 48000), np.arange(len(pcm)), pcm)
    with wave.open(str(dest / f"{name}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes((np.clip(up, -1, 1) * 32767).astype(np.int16).tobytes())


for code, voice, text in SENTENCES:
    if code not in PICK:
        continue
    s = to_pcm(OUT / f"{code}.mp3")
    s = s / (np.max(np.abs(s)) + 1e-9) * 0.5
    room = lambda sec: office_noise(int(sec * SR), rng) * 0.003  # noqa: E731
    pcm = np.concatenate([room(1.0), s + room(len(s) / SR)[: len(s)], room(3.5)])
    write(code, pcm)
    meta.append({"id": code, "lang": code.split("-")[0], "text": text, "voice": PICK[code]})
# Hindi in a noisy office, and a recording with no speech at all
s = to_pcm(OUT / "hi.mp3"); s = s / (np.max(np.abs(s)) + 1e-9) * 0.5
x = np.concatenate([np.zeros(SR), s, np.zeros(int(3.5 * SR))])
write("hi-noise", x + office_noise(len(x), rng) * np.sqrt(np.mean(s ** 2)) / (10 ** (15 / 20)))
meta.append({"id": "hi-noise", "lang": "hi", "text": SENTENCES[3][2], "voice": False})
write("silence", office_noise(8 * SR, rng) * 0.003)
meta.append({"id": "silence", "lang": "", "text": "", "voice": False})
(dest / "clips.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(meta), "wav clips in", dest)
