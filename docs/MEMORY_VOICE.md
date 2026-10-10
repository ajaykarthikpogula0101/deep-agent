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
* **Forget me on this device** (⋯ menu) rotates the device id: the browser is no longer linked to the earlier visits
  (the server rows remain under the old id until the retention purge).

Endpoints: `GET /me` now returns `memory` (`returning, visits, name, email, company, lang, last_topic, upcoming,
headline, line`) for the `X-Visitor-Id` header. `VISITOR_MEMORY=false` turns everything off.

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

## Testing

* `pytest tests/test_memory.py`: greeting precedence, prompt framing, the profile query across two sessions of one device.
* Manually: ask something, press ⋯ → New conversation: the welcome now says "Welcome back" with the last topic. Book a
  call, start a new conversation: the line shows the booking and a "Confirm your call on Zoom" card. Ask "when is my
  call?" in chat: the model answers from memory. ⋯ → Forget me: the greeting returns to the first-visit copy.
* Voice: press Speak to Deep, tap the language button until it reads HI, speak Hindi: the transcript and the answer are
  Hindi and the status reads "सुन रहा हूँ…"; the reply is spoken with the Hindi voice when the device has one.
