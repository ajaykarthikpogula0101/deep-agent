# Answer cards (version 2026.10.13.1)

An answer may end with one small card under the prose: a table comparing companies, KPI tiles, a dated journey
timeline, a fact sheet, next-step buttons. The model writes it in **openui-lang** (a tiny declarative language from
`@openuidev/lang-core`) inside a fenced block after its prose; the server routes that block out of the token stream as
`ui` SSE events; the widget renders it progressively with `static/deep-ui.js`. The prose is always complete on its own:
a card never replaces it and never adds information (every string must restate a fact from the prose and `<sources>`).

Everything sits behind `UI_CARDS_ENABLED`; with it off the `/chat` byte stream is identical to before.

## 1. Server side (`app/ui_cards.py`, `app/chat.py`)

### Trigger
`ui_cards.wanted(cited, booking)` = `UI_CARDS_ENABLED and cited and not booking` (and the prompt file exists). Only a
confident, non-booking answer gets the card section; refusals, injection refusals, hand-over, custom answers and the
spend cap never reach it. On an eligible turn:

* the prompt section `app/rag/ui_cards_prompt.txt` is appended **last** to the system message, after the fixed rules,
  the owner guidance, the timezone, the language note, memory and the signed-in note, so all of those precede it and win;
* `max_tokens` is `UI_CARDS_MAX_TOKENS` (800) instead of 500.

**Known behavioural change:** on eligible turns the section (~1,600 tokens), its "under 80 chars / under 20 statements"
rules and the larger completion cap sit in the same completion as the prose, so the model may phrase the prose slightly
differently even when it emits no card. Byte-identical behaviour is guaranteed only with `UI_CARDS_ENABLED=false`
(`tests/test_ui_cards.py::test_disabled_cards_give_the_old_byte_stream`).

### The splitter (`FenceSplitter`)
`_agent_loop` feeds every model delta through `FenceSplitter.feed()` and flushes it with `finish()` in a `finally`, so a
provider error mid-stream still releases the held prose before `error` + the fallback token.

* Opens on ```` ```openui-lang ````, ```` ```openui ```` or a bare `root = Card(` — all only at a **line start**
  (an explicit `line_start` flag, never a regex `^` on a trimmed buffer, so `The field is called root = Card(x)` is prose
  in every chunking) and only **outside any other fence**: the splitter tracks ```` ```json ````/```` ```python ````/bare
  ```` ``` ```` fences in the prose (closed by ```` ``` ```` alone on a line), so a `root = Card(` quoted inside one is
  prose too and cannot swallow the rest of the answer. An untagged ```` ``` ````, a ```` ```python ```` fence, inline
  backticks and prose lines starting with `r` pass through untouched.
* Prose before the block is emitted with the newline run before the block stripped. While no opener is in sight the
  splitter holds back at most the longest line-start suffix that could still become an opener (≤ 15 chars) plus the
  trailing newline run; output is identical for every chunking.
* A fence closes on ```` ``` ```` on its own line (or at stream end); ≤ 4 chars (a prefix of `\n```\n`) are held while
  streaming. A bare program closes at the first blank line followed by a non-statement line (`STMT_RE`, decided once the
  line is complete or 24 chars long) or at stream end; the prose after it is re-fed as tokens. `\r\n` is normalised in
  `feed`, programs never contain `\r`.
* Over `UI_CARDS_MAX_CHARS` (4,000): the block ends `complete:false, reason:"too_long"` with what fits, the rest is
  swallowed, prose after the close still streams. A second block is swallowed silently (`stats["dropped"]`). A fence left
  open at stream end ends `complete:false, reason:"unclosed"` (partial program for logging; the widget shows nothing).

### SSE events (new type `ui`; every existing event and shape untouched)
```
{"type":"ui","op":"start"}
{"type":"ui","op":"chunk","text":"root = Card(\"Champions Group companies\", [t, a])\nt = Ta"}
{"type":"ui","op":"end","program":"root = Card(...)\nt = Table(...)","complete":true}
{"type":"ui","op":"end","program":"root = Card(\"x\", [t])\nt = List([","complete":false,"reason":"unclosed"}
{"type":"ui","op":"end","program":"<first 4000 chars>","complete":false,"reason":"too_long"}
```
Order on an answer turn: `status`… `lang` `sources` `status(writing)` `token`* `ui start` `ui chunk`* `ui end` `token`*
(rare trailing prose) `meta` `done`. On a mid-stream provider error: `token`* (incl. the flushed holdback) `ui end
complete:false`? (only inside a fence) `error` `token(fallback)` `done`. On Stop / a dropped connection the generators
are closed (`GeneratorExit`): nothing more is sent, the splitter is not flushed, and the inbox row is `stopped` as
before. A custom answer with a block: `[sources]` `custom` `token` `ui start` `ui chunk`+ `ui end` `done` — the
`" [1]"` marker goes on the prose before the block (`ui_cards.with_marker`); a custom answer without a block keeps the
single `token` event with its own bytes (`ui_cards.has_block`), exactly as before.

### Storage
The inbox (`messages.text`), the next-turn history, titles and voice see **prose only**. The program is logged as an
`events` row `ui_card` `{message_id, complete, reason, chars, program (≤ 2,000 chars)}`; the insert is best-effort
(try/except) so `done` always leaves. No schema change. Cards live only on the device that received them: the widget
keeps the program in its sessionStorage transcript (`ui` field) and the server never sends one back, so a conversation
reopened on another device shows the prose without the card.

### Settings (`app/config.py`, `.env.example`)
| Setting | Default | Meaning |
|---|---|---|
| `UI_CARDS_ENABLED` | `true` | the feature; `false` = today's byte stream |
| `UI_CARDS_MAX_CHARS` | `4000` | per-turn cap on the block (`too_long` beyond it) |
| `UI_CARDS_MAX_TOKENS` | `800` | completion cap on card-eligible turns (500 elsewhere) |

## 2. Prompt text and bundle regeneration
`app/rag/ui_cards_prompt.txt` is **generated** by `node tools/openui/gen_prompts.mjs` from `static/deep-ui-lib.mjs`
(`LIBRARY`) and `tools/openui/prompts.mjs` (preamble, examples, rules) through lang-core's `generateSystemPrompt`, then
trimmed deterministically, and committed. `tools/openui/tests/lib.test.mjs` regenerates it and asserts byte equality;
`tests/test_ui_cards.py` asserts every component name in the library appears in it. Python never needs Node for the chat
path. To change the library or the rules: edit the `.mjs` sources, run `npm --prefix tools\openui run gen:prompts`, commit
both. The browser parser bundle `static/vendor/openui-lang-core.min.mjs` is built by `npm --prefix tools\openui run
build:vendor` (esbuild, zod and ci-info stubbed); a second build gives no git diff.

## 3. Widget side (`static/deep-ui.js`, `static/deep-ui-lib.mjs`, `static/deep-assistant.js`)
The renderer loads lazily (`import()` on the first `ui` event; one failure disables cards for the page load), injects
its own CSS once, builds DOM with `textContent` only (no `innerHTML`), and applies its own slot/type allowlists on top of
lang-core. `@OpenUrl` is allowed only for `https://deependhq.com`/`www.deependhq.com` (any path) and the exact booking
URL; buttons with any other URL are not rendered. `ask` buttons always send **their label** as the visitor's next message
(the `@ToAssistant` argument is ignored; labels with an e-mail or `://` are not rendered), through the normal `_send`
pipeline including the injection pre-filter. `plan()` takes the **first surviving step** of an `Action([...])`: a button
whose `@OpenUrl` is rejected but which also carries a `@ToAssistant` step degrades to an `ask` button with the same
label (never with the step's argument); with no surviving step it is not rendered.

Hooks: `.row.bot .msg .ui-card[data-ui-state="streaming"|"done"][data-ui-root="Card"][data-ui-statements]`,
`.ui-actions .ui-btn[data-ui-action="ask"|"open"][data-ui-url]`; events `deep-assistant:ui`
`{ state: 'rendered'|'dropped'|'failed', statements?, reason? }` and `deep-assistant:action` with `action: 'ui_button'`.
Transcript entry: `{ role:'bot', text, sources, ts, mid, err?, fb?, ui?: "<program>" }`. See `docs/WIDGET.md` §7.

## 4. Tests
`tests/test_ui_cards.py` (splitter under every chunking: whole, 1/3/7-char, every single cut, random 5-cut splits;
trigger policy; prompt content; chat routing with a fake model incl. the disabled byte-identical path, the contained
`ui_card` log failure, the provider-error flush, Stop mid-card, booking and custom-answer turns),
`tools/openui/tests/*.test.mjs` (prompt drift, parser bundle, renderer) and the card block of
`scripts/browser_check_widget.mjs`. One quirk of that suite: `/demo` sets the component's `api` attribute after it has
booted, so the boot-time restore reads an api-less sessionStorage key; the suite calls `el._restore()` after the reload
and therefore proves "a stored program renders again on restore", not "restore on boot on `/demo`". Hosts that load
the widget through `widget.js` set `api` first and restore on boot.
