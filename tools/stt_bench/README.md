# Speech-to-text benchmark

Measures how well spoken questions become text, per language, with the same Groq Whisper calls the server makes.
Clips are synthesised with neural voices (edge-tts), then played under three conditions: clean, a slow start
(1.5 s of silence around the sentence) and office noise at ~12 dB SNR, plus three clips with no speech at all
(silence, room noise, a cough) that must come back empty.

```
uv venv .venv --python 3.11 && uv pip install --python .venv edge-tts imageio-ffmpeg numpy httpx
.venv/Scripts/python make_clips.py          # out/clips/*.webm + out/clips.json (17 languages x 3 conditions + 3 non-speech)
.venv/Scripts/python bench.py               # every variant; a table of character error rate per language
STT_SERVER=http://127.0.0.1:8089/stt .venv/Scripts/python bench.py server   # the running app, end to end
.venv/Scripts/python make_wavs.py           # out/wav/ for the in-browser check
node ../../scripts/browser_check_voice.mjs http://127.0.0.1:8089 out/voice out/wav
```

Set `STT_BENCH_DIR` to keep the audio elsewhere. Groq allows 20 transcription requests a minute; the script paces
itself, so a full run of all variants takes about 20 minutes. Results and the 2026-10-14 numbers: docs/MEMORY_VOICE.md.
