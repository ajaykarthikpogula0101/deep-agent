# Fin-style operation: what the assistant does, mapped to Intercom's Fin AI Agent

The owner asked for the bot to work "the Fin way". Fin's public description (fin.ai, Intercom help centre) boils
down to: answer from configured knowledge, hand over to a human when it can't or when asked, let the owner steer
it without engineering (guidance, custom answers), and report on it (resolution rate, satisfaction, gaps). This is
how each of those maps onto the assistant, and what is deliberately not copied.

| Fin capability | Here | Where |
|---|---|---|
| Knowledge from your content | Nightly crawl of deependhq.com, chunked, embedded locally, cited with `[n]` markers and a sources list under each answer | `app/ingest`, `app/rag` |
| Guidance (tone, what to push, when to escalate), no code | Free text in **Console → Guidance**, appended to the fixed rules; live within 30 s; cannot loosen the hard rules (cite only, no outside knowledge, anonymity) | `app/guidance.py`, `/admin/guidance` |
| Custom answers | **Console → Custom answers**: a question plus the exact reply (and optional link). A visitor question within `CUSTOM_ANSWER_MIN_SCORE` (0.86 cosine) gets it verbatim, no model call; hit counts shown | `guidance.match_custom_answer`, runs before retrieval |
| Hand over to a human | Explicit requests ("talk to a real person", "live agent") show a name/email/message form; every refusal offers **Ask Deep directly** with the question prefilled. Submitting stores a lead (`status=handover`) and emails the host the message, the visitor's origin and the last eight turns | `inbox.save_handover`, `POST /handover` |
| Resolution / satisfaction reporting | **Console → Overview**: conversations, resolution rate (answered + custom + booking over all assistant turns that were asked something), satisfaction from thumbs, bookings, hand-overs, median answer time, daily bars, most-asked questions | `inbox.metrics`, `/admin/metrics` |
| Conversation inbox | **Console → Conversations**: one row per session with outcomes and feedback; click for the transcript with per-turn outcome, latency, sources, ratings, and the session's leads and origin | `inbox.conversations/transcript` |
| Content gaps | **Console → Gaps**: unanswered questions grouped with counts and a "write answer" shortcut into Custom answers; answers marked "not helpful" with the visitor's note | `inbox.gaps` |
| Visitor feedback | Thumbs on every answer; thumbs-down asks an optional "what was wrong?" | `POST /feedback` |
| Procedures (multi-step actions in other systems) | One procedure exists and is hard-wired: book a call (live Zoom availability, lead saved, host briefed, Zoom hand-off or API booking) | `app/booking` |
| Audience / roles | Not needed: one public site, one role (visitors of deependhq.com) | — |
| Multi-channel (email, Slack, voice) | Web chat only. Email replies happen through the hand-over brief | — |
| Testing suite | `pytest` (47 tests) plus `node scripts/browser_check.mjs`, a real-browser run of 30 checks against the live API | `tests/`, `scripts/` |

## How a conversation is scored

Every assistant turn is stored in `messages` with an `outcome`:

* `answered` cited answer from the site · `custom` owner-written answer · `booking` any booking step
* `refused` nothing on the site · `handover_offered` the visitor asked for a human · `handover` the form was sent
* `injection` prompt-injection attempt · `error` provider failure · `stopped` the visitor pressed stop

Resolution rate = (answered + custom + booking) ÷ (answered + custom + booking + refused + handover + error).
`handover_offered` and `stopped` are neither resolved nor failed and are excluded.

## What the owner should do weekly

1. Open the console, look at the resolution rate and the Gaps tab.
2. For each recurring unanswered question: either add the information to the site (the nightly crawl picks it
   up) or write a custom answer right from the Gaps row.
3. Read thumbs-down answers and the visitor notes; adjust Guidance if the tone or emphasis is off.
4. Hand-over leads arrive by email; reply from your inbox, the visitor's address is the reply-to.

## Deliberately not copied

* No per-resolution billing, no proprietary model: cost is the OpenRouter usage, visible on `/healthz`.
* No autonomous actions in third-party systems beyond Zoom booking; every other request becomes a human hand-over.
* No "AI insights" generator. The Gaps and Most-asked lists are plain counts, which is what a one-site assistant needs.
