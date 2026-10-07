# Agent UI: activity, streaming animations, the living orb (version 2026.10.07.2)

The widget now looks like an agent at work rather than a chatbot: a real-time activity row driven by backend
events, soft token streaming, staggered reveals, action cards for things the agent did, a capability strip, a
header orb with a status, and an audio-reactive voice call view. No functionality changed; everything respects
`prefers-reduced-motion`.

## 0. The "purple blobs"

Searched the whole codebase (`static/`, `app/`, `widget/`, docs) for `#7C5CFF`, `#8B5CF6`, `violet`, `purple`,
`magenta`, `indigo` and every `::before` / `::after` / `position:fixed` rule: nothing purple exists. The only
pseudo-elements are the list bullet (`.li::before`) and the select arrow (`.sel::after`); the only fixed elements
are the panel, the launcher and the greeting card. Headless screenshots never show the shapes. They are Windows'
**Text cursor indicator** (Settings → Accessibility → Text cursor → "Text cursor indicator"): the OS draws two
coloured teardrops (purple by default) at the active text caret in every app. They appeared in the call view because
the composer textarea kept keyboard focus under the overlay. The call view now blurs the composer (and the view is
focus-trapped on its buttons), so no caret exists there; in the chat the caret is wanted, so the indicator follows
it until the Windows setting is turned off.

## 1. Response animations

* **Activity row** (`_activity`): inserted above the answer bubble as soon as a message is sent: a pulsing orange
  orb and a shimmer label. Labels come from `status` events the backend emits at the real point in the flow
  (`app/chat.py`, `status(step, label)`):

  | step | label | emitted when |
  |---|---|---|
  | thinking | Thinking… | right after the injection filter |
  | translating | Translating… | the message is not English (before the translation call) |
  | searching | Searching deependhq.com… | before the embedding + retrieval |
  | reading | Reading N sources… | retrieval was confident (N numbered sources) |
  | calendar | Looking at the booking options… / Checking Deep's calendar… | booking intent / before `get_available_slots` |
  | checking_slot | Checking that time with Zoom… | before `book_slot` (review) |
  | writing | Writing… | before each model call (also after tools) |

  When the stream ends the row collapses into **"Worked for 4s · 3 sources"**; clicking it lists the steps with
  their offsets. Nothing is timer-based.
* **Skeleton bubble** (three shimmering lines) until the first token; then **token fade** (`.tok`: opacity + 2px
  blur → sharp over 150 ms on the newest chunk) with a blinking orange caret (`.msg.streaming::after`).
* After the answer: context chip, sources row, meta line and action icons slide in with 60 ms stagger (`.in`).
* Booking cards, slots, forms and confirmation cards use `da-pop` (scale .96 → 1 + fade); the success card draws
  its check mark (`.chk` stroke-dash animation).

## 2. Voice call view (`static/deep-orb.js` + `startVoice` in the component)

* **Orb**: 160 px sphere on a 220 px `<canvas>` (2D, 2× backing store), orange → coral → rose radial gradient,
  morphing outline (sum of sines on the polar radius), two slowly rotating translucent lobes (the fluid surface), a
  halo, an outer ring on louder speech, 14 orbiting particles while thinking. State targets lerp with a ~400 ms time
  constant; levels lerp fast up / slow down so the surface never jitters.
* **Audio wiring** (`AudioMeter`):
  * listening: `getUserMedia` → `MediaStreamSource` → `AnalyserNode` (fftSize 512); `sample('listen')` returns
    level / low / high bands from `getByteFrequencyData`. Opened once per call, muted by disabling the track.
  * speaking, server TTS (`TTS_PROVIDER=openai`): the `<audio>` element → `MediaElementSource` → `AnalyserNode` →
    destination, so the orb pulses with the agent's actual voice; captions advance with `currentTime / duration`.
  * speaking, browser TTS (`TTS_PROVIDER=browser`, the default today): `SpeechSynthesis` exposes no audio stream,
    so each `onboundary` word event pulses the meter (`pulse()`, decaying 10 %/frame) and advances the captions
    word by word. The orb therefore moves per word, not per waveform; switch to server TTS for true sync.
  * thinking: no audio; the orb shrinks and swirls with particles. Idle / muted: slow breathing, grey when muted
    with a "muted" badge.
* **Layout**: header strip (`ask deep >_`, live dot, `mm:ss` timer, minimize), orb with radial glow behind it,
  fading status label, captions (your words muted italic, Deep's reply white with word highlighting, two lines),
  controls: 56 px round Mute (white with a dark mic-off icon when active), 56 px red (#E5484D) hang-up button with a
  proper handset icon and no text (tooltips on hover/focus), and a captions toggle.
* **Minimize** hides the view and shows an "In a call" pill in the header; the loop keeps running. **End** collapses
  the orb (350 ms), closes the AudioContext and stops tracks, and leaves a "Voice call · 2m 14s" card in the chat
  with an expandable transcript.

## 3. Agent-style UI

* Header: 36 px mini orb (CSS gradient) that breathes when idle, pulses while working or in a call; status next to
  the name: **Online / Working… / In a call**.
* Empty chat: four capability cards under the greeting (Answers from Deep's work, Books calls on Deep's calendar,
  Sends Zoom invites by email, Voice conversation); each starts that action.
* Action cards (`_actionCard`): "Checked Deep's calendar · 120 open times in the next 14 days ✓", "Checked that time
  ✓/✕", "Booking your slot (in progress → done ✓ / failed ✕)", "Sending confirmation ✓", "Sent to Deep ✓".
* Context chip above an answer: "Using 3 sources from deependhq.com", toggles the source row.
* Micro-interactions: hover lift on chips/cards/times/dates, pointer ripple on buttons, animated composer height,
  pulsing orange glow on the composer while the agent responds.

## 4. Performance and accessibility

* The orb pauses on `visibilitychange` (hidden tab), when the panel is closed, and when the call view is minimized;
  it resumes when shown. `stopVoice` stops the loop, closes the `AudioContext` and stops all tracks.
* `prefers-reduced-motion`: no morphing, lobes, particles or shimmer; the orb is a static sphere whose brightness
  follows the state; chips and cards use opacity only; the token fade and ripple are off; status labels change
  without transitions.
* A visually hidden `role="status" aria-live="polite"` region announces activity labels, call states and action
  card results; the header status is announced as "Deep is working / in a call / online".

## Files

`static/deep-orb.js` (new), `static/deep-assistant.js` (CSS, template, `_activity`, `_setText`/`_wrapTail`,
`_contextChip`, `_actionCard`, `_renderCaps`, `_setStatus`/`_announce`/`_ripple`, voice section rewritten),
`app/chat.py` (`status()` events), `scripts/browser_check_widget.mjs` (fake microphone flags, 15 new checks),
`tests/test_guardrails.py` (ignores status events), `static/embed-test.html` (version).

## Testing each state

1. Open `/` (or `/site`), ask anything: watch the activity row ("Thinking… → Searching deependhq.com… → Reading 3
   sources… → Writing…"), the skeleton, the token fade with the caret, then "Worked for Ns · 3 sources" (click it).
2. Press **Speak to Deep**. Allow the microphone. *Listening*: speak, the orb expands with your voice and a ring
   appears when you are loud. *Thinking*: after you stop, the orb shrinks and swirls with particles while the
   answer is fetched. *Speaking*: the orb pulses per word (browser TTS) or with the waveform (server TTS) and the
   captions highlight. *Muted*: press the mic button, the orb greys with the badge, the button turns white.
   *Minimize*: the chevron returns to chat with the "In a call" pill; click it to come back. *Ended*: the hang-up
   button collapses the orb and leaves the call summary card.
3. Reduced motion: enable it in the OS (Windows: Settings → Accessibility → Visual effects → Animation effects off)
   and repeat: static orb, no shimmer, instant reveals.
4. Automated: `node scripts/browser_check_widget.mjs <base> <out>` runs with a fake microphone and checks the
   activity row and steps, the context chip, the capability cards, the working state, and the call view's
   buttons, orb, meter, mute, minimize, pill and summary card. Screenshots: `widget_working.png`, `widget_voice.png`.
