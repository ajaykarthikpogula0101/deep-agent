# Return-visitor memory and multilingual voice (version 2026.10.10.1)

## Return-visitor memory (`app/memory.py`)

The widget already keeps a persistent visitor id in the site's localStorage (`dh_vid`) and every chat session is
tagged with it. Memory joins what that device did before, nothing new is stored:

| Fact | Source |
|---|---|
| returning, visit number, first/last seen | `sessions` rows with the same visitor id (or verified user id) that had messages |
| name, email, company | the latest booking or lead they created themselves (unverified hints) |
| earlier topics | the AI titles of their earlier conversations |
| earlier questions | the last three answered questions |
| upcoming booking | next `bookings` row (confirmed or pending Zoom) |
| open hand-over | a `leads.status='handover'` row in the last 14 days |
| language | the last `language` event (non-English visitors) |

Where it shows:

* **Welcome screen**: "Welcome back, Ada! 👋" with one line that prefers the upcoming booking ("Your LakeB2B
  Discovery Call with Deep on Thu 15 Oct, 16:30 is held, waiting for your confirmation on Zoom"), then an open
  hand-over, then the last topic. A "Join your call" / "Confirm your call on Zoom" card appears above the actions.
* **Forms**: the booking and hand-over forms prefill the name and email typed on an earlier visit (never for signed-in
  users, whose verified identity wins).
* **The model**: `GET /chat` adds a `VISITOR MEMORY` section to the system prompt, framed as data with the rules
  "welcome back once, use facts only when relevant, never recite, never share". So "when is my call?" is answered.
* **No "forget me" control** (removed in 2026.10.14.2): the device id stays, so every return visit is recognised. A
  visitor who asks to be forgotten is pointed to Deep's team ("Message the team"), who can delete their data on request.

Endpoints: `GET /me` now returns `memory` (`returning, visits, name, email, company, lang, last_topic, upcoming,
headline, line`) for the `X-Visitor-Id` header. `VISITOR_MEMORY=false` turns everything off.

### Reschedules and cancels (added 2026-10-13)

`profile()` also returns `recent_change`: the latest booking the visitor moved or cancelled in the last 14 days. The
welcome line then reads "Your … moved to … and it's confirmed. A reminder lands in your inbox the day before" or "You
cancelled your … on …. Whenever it suits you, pick a new time", the welcome screen offers "Book a new time" after a
cancel, the chat shows a toast right after the action, and the model's memory block carries the change (and the fact
that a reminder email is coming) so "when is my call?" is answered from the current state.

### The current conversation (2026.10.13.5)

Booking facts are read from every session of the device including the current one, so a call booked, moved or cancelled a
minute ago is in the very next answer, for first-time visitors too (and without a visitor id, from the current session
alone). History facts (welcome back, earlier topics and questions) still come only from earlier sessions. A session
where the visitor only used the booking buttons counts as a visit.

## Multilingual voice

* Text already answers in the visitor's language (docs/AUTOMATIONS.md §10). The call view now follows:
  * **Language button** in the call controls (next to captions) cycles through `VOICE_LANGUAGES`
    (`auto,en,hi,te,ta,es,fr,de` by default; the component knows 17 tags). The choice is remembered per device.
  * **Listening**: Web Speech recognition uses the chosen tag (`hi-IN`, `te-IN`, …); the server path (Groq Whisper)
    gets `language=<code>` so Hindi or Telugu speech is transcribed as such. "Auto" lets Whisper detect.
  * **Speaking**: the chat stream now carries a `lang` event with the detected language of the turn; in "Auto" the
    reply is spoken with a voice matching it, otherwise with the chosen language. Browser speech picks an installed
    voice for the tag (exact match, then language family) and warns once when the device has none ("No Telugu voice
    is installed on this device; using the default voice"). Server TTS (`TTS_PROVIDER=openai`) handles every language
    natively.
  * **Labels**: Listening / Thinking / Speaking / Muted are shown in Hindi, Telugu, Tamil, Spanish, French, German and
    Portuguese when that language is active.
  * The dictation button in the composer honours the same choice.
* Windows ships Hindi voices (Microsoft Hemant/Kalpana, plus "Natural" voices on Windows 11); Telugu and Tamil voices
  exist on Windows 11 and on Android; iOS has Hindi. Where a voice is missing the text answer is still in the right
  language, only the audio falls back.

## Accuracy (2026-10-14, version 2026.10.14.1)

The user reported that voice "is not able to catch the voice properly". Measured first, then fixed.

**What was wrong** (server speech-to-text, `STT_PROVIDER=openai`, Groq whisper-large-v3):

1. Composer mic in "Auto" sent the *browser's* language (`en` in an English browser) as Whisper's `language`, so Hindi,
   Telugu, Arabic or Japanese speech came back **translated into English** (69% character error rate).
2. The voice call stopped recording after a fixed 6 s: long sentences were cut in half, a slow start lost the end.
3. Silence, room noise and a cough became words ("Thank you for watching.", "Terima kasih.") and were sent as messages.
4. The file was always named `audio.webm`, also for Safari's mp4 recordings.

**What it does now**

* Widget (`_capture`): records until the visitor stops talking. A level meter tracks the room's noise floor (the quietest
  50 ms of the last 3 s) and ends the recording 1.3 s (call) / 2.5 s (mic button) after speech stops; nothing is sent
  when nobody spoke ("I didn't hear anything…"); at most 30 s / 120 s. The browser's own noise suppression is off
  (it made Whisper hear Bengali as Hindi); echo cancellation and gain control stay on. The container the browser really
  records is named correctly (webm / ogg / m4a). "Auto" no longer forces a language; the visitor's languages travel as
  `hints` (the conversation's language, then `navigator.languages`).
* Server (`app/media.py` `transcribe`): `verbose_json`, temperature 0; Whisper's own no-speech and looping signals drop
  segments; known silence phrases in 12 languages, punctuation-only results and 1–3 words Whisper itself rates as
  "probably not speech" are dropped; stutter loops ("ക്ക്ക്ക്…") collapse. When the detected language is none of the
  hints, the audio is read again in the first hint and the more confident reading wins (`STT_HINT_RECHECK`). When the
  text comes back in the wrong alphabet (Whisper writes Malayalam in Gurmukhi), it is read again with a greeting in the
  right script as context. Optional second readings never fail a request; a Groq 429 is waited out once.
  Returns `{"text", "language"}`; the widget remembers the language for the next turn and for the spoken reply.
* `STT_PROMPT` (product names as context) is **off**: on the benchmark it raised the error rate from 9.8% to 12.3% and
  made Kannada come back translated.

**Measured** (character error rate, lower is better; 17 languages x clean / slow start / office
noise, an English browser):

| | old mic button | old voice call | now (server) |
|---|---|---|---|
| all speech | 69.4% | 18.4% | **8.0%** |
| long English sentence | 0% | 52% | **0%** |
| slow start | 69.5% | 26.6% | **8.8%** |
| noise / silence turned into words | 3 of 3 | 3 of 3 | **0 of 3** |

In a real browser (each clip played as the microphone through the widget's own recorder, endpointing and
`/stt`): 17 of 17 pass, mean 3.3% over English, Hindi, Telugu, Tamil, Kannada, Bengali, Spanish, Arabic,
Chinese, Japanese, Hindi in office noise, and silence (nothing sent).

**Limits.** Malayalam stays weak (whisper-large-v3 itself; ~50–70% character errors even in the right script); Kannada
and Bengali come back with small spelling slips (11–20%) the chat model reads fine. The visitor can pin a language with
the voice language button. Groq's free tier allows **20 transcriptions a minute for all visitors together**; a busy site
needs the paid tier (or `STT_HINT_RECHECK=false`, one call per utterance).

## Testing

* `pytest tests/test_memory.py`: greeting precedence, prompt framing, the profile query across two sessions of one device.
* Manually: ask something, press ⋯ → New conversation: the welcome now says "Welcome back" with the last topic. Book a
  call, start a new conversation: the line shows the booking and a "Confirm your call on Zoom" card. Ask "when is my
  call?" in chat: the model answers from memory.
* Speech accuracy: `pytest tests/test_media.py` (silence, noise, wrong script, language re-check, Groq 429).
* Voice: press Speak to Deep, tap the language button until it reads HI, speak Hindi: the transcript and the answer are
  Hindi and the status reads "सुन रहा हूँ…"; the reply is spoken with the Hindi voice when the device has one.
