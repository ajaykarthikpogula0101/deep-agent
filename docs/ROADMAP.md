# Roadmap: Snitcher-style messenger and backend hardening (agreed 2026-10-28)

Reference: the chat on snitcher.com, inspected 2026-10-28. It is Intercom's Messenger with **Fin**, Intercom's AI agent
("answers questions based on your support content", "The team can also help"), next to Snitcher's own visitor
identification (`radar.min.js`) and HubSpot. Its help center (help.snitcher.com) has 8 collections and 99 articles.

## What the Snitcher messenger has, and where we stand

| Snitcher / Fin | deependhq assistant today | Gap |
|---|---|---|
| **Home** tab: greeting, "Ask a question" card, "Search for help" with top articles, featured news card | Welcome screen inside the chat view, quick replies, outreach pop-ups | **Done 2026-10-29**: Home tab (hero, recent message, Ask a question, Book a call, Search for help + top articles) |
| **Messages** tab: conversation list, unread badge, "Ask a question" | Messages view with AI titles, unread badge (`app/conversations.py`) | Done |
| **Help** tab: searchable help center, 8 collections, 99 articles; Fin answers from it | Help view is "Get in touch" actions; answers come from the crawled site | **Done 2026-10-29** (`app/help.py`): collections, articles, search, article view, Console → Help center; owner and builtin articles are answer sources ("Get in touch" kept under the collections) |
| **News** tab: product updates with labels, images, unread dot | None | **On hold: the user will provide the sites to post from** |
| AI agent grounded in support content, cites sources, many languages | RAG with citations, multilingual, guidance, custom answers, small talk, follow-ups, date-scoped questions | Done |
| "The team can also help": hand-off **in the same conversation**, team replies appear in the messenger, email when the visitor has left | Hand-over form, then email to Deep; Deep answers by email | **Done 2026-10-29** (`app/team.py`): console reply → widget + email when unread; waiting / replied / closed |
| Resolution tracking and CSAT at the end of a conversation | Thumbs on each answer | **Done 2026-10-29**: 1–5 conversation rating + "I don't know" answers in the gap list |
| Procedures / data connectors / actions | Booking, reschedule, cancel tools | Later: more tools (booking status, send a resource, subscribe) |
| Insights: topics, trends, real-time alerts, recommendations | Metrics, knowledge-gap drafts, weekly digest | Topics, resolution rate, alerts (incl. "model down") |
| Simulations and regression testing before changes go live | 587 unit tests | A fixed question set run against the real index and model |
| Composer: attachments, emoji, GIF, voice | All four | Done |
| Proactive greeting with unread badge | Outreach rules + greeting bubble | Done |

## Order of work

1. **Reliability (done 2026-10-28):** health checks for model, key credit, database, mailbox, booking robot;
   alert emails to the owner; a 30 s timeout and a backup model for chat answers.
2. **Conversations like Fin (done 2026-10-29):** unanswered answers ("I don't know" on a strong match) reach the gap list; resolution
   and CSAT; live hand-off thread (console reply in the widget, email when away, open/waiting/closed).
3. **Help center + Home tab + Intercom look (done 2026-10-29):** articles and collections (owner-written, plus generated from site pages), search, article
   view, answers that cite articles; Home tab with search, top articles and a featured card.
4. **Insights and safety:** topics and resolution dashboards, regression question set, saved email queue, one-runner
   lock for scheduled jobs, nightly database backups, numbered migrations, booking as a background job.
5. **News tab:** after the user names the sources.
