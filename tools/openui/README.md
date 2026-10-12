# tools/openui — Node-side OpenUI helpers

Three jobs, none of them on the chat path:

| Script | What it does | Who calls it |
|---|---|---|
| `render_email.mjs` | Renders ONE openui-lang program (the model-composed weekly digest) to email HTML with `@openuidev/react-email`; applies the link / component policy on the parsed tree | `app/digest_rich.py` as a subprocess (JSON on stdin, one JSON line on stdout) |
| `gen_prompts.mjs` (`npm run gen:prompts`) | Writes the two committed prompt texts: `app/rag/ui_cards_prompt.txt` (chat answer cards, from `static/deep-ui-lib.mjs` + `prompts.mjs`) and `tools/openui/email_prompt.txt` (digest, from `prompts.mjs`) | a developer after bumping lang-core / react-email; `tests/lib.test.mjs` fails until the committed files match |
| `build_vendor.mjs` (`npm run build:vendor`) | Bundles `@openuidev/lang-core` for the browser into `static/vendor/openui-lang-core.min.mjs` | a developer; a rebuild must give no git diff |

Python never needs Node for the chat: the prompt text and the browser bundle are committed. Only the rich digest
e-mail runs Node at runtime.

## Install

```
cd tools/openui
OPENUI_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1 npm ci      # PowerShell: $env:OPENUI_TELEMETRY_DISABLED="1"; $env:DO_NOT_TRACK="1"; npm ci
npm test                                               # node --test (runs tests/*.test.mjs; Node 24 rejects a bare directory argument)
```

Node 20+ (verified on 24.19). `package.json` pins exact versions; `package-lock.json` is committed; `node_modules/` is
git-ignored (root `.gitignore`). The two env variables keep the OpenUI packages from phoning home; `app/digest_rich.py`
sets them (plus `NODE_ENV=production`) on every subprocess as well.

## Where the rich digest runs (decision 18, option b)

The rich digest needs Node on the host: the Windows `run.ps1` deployment (Node on PATH, or `DIGEST_NODE=<path to
node.exe>`). The Cloud Run image (`python:3.11-slim`, copies only `app` and `static`) has no Node and no `tools/`, so
`digest_rich.available()` is False there and the digest is always sent as plain text with `fallback_reason:
"unavailable"`. The Dockerfile is deliberately unchanged; see docs/AUTOMATIONS.md §6 for the fallback reasons and the
privacy note.

## Browser bundle (static/vendor/openui-lang-core.min.mjs)

The chat widget renders answer cards (docs/UI_CARDS.md) with a committed browser build of `@openuidev/lang-core`
0.4.1 (MIT; licence text in `static/vendor/LICENSE-openui-lang-core.txt`, build notes in `static/vendor/README.md`).
The chat path has no Node dependency at runtime: the bundle is a static file. Rebuild it only when the package is
bumped:

    cd tools\openui
    $env:OPENUI_TELEMETRY_DISABLED="1"; $env:DO_NOT_TRACK="1"; npm ci
    npm run build:vendor          # = node build_vendor.mjs -> ../../static/vendor/openui-lang-core.min.mjs

`build_vendor.mjs` runs esbuild (JS API; `format: esm`, `platform: browser`, `target: es2020`, `minify: true`)
on `node_modules/@openuidev/lang-core/dist/index.mjs` with two aliases: `zod/v4` and `zod/v4/core` ->
`stubs/zod-stub.mjs` (lang-core only touches zod inside `createLibrary`/`defineComponent`, which a hand-written
LibrarySpec never calls; both throw in this build) and `ci-info` -> `stubs/empty.mjs`, plus a resolve plugin that
swaps lang-core's shared telemetry module (`dist/shared-*.mjs`: PostHog key, capture URL, env gates) for
`stubs/telemetry-stub.mjs` (every gate answers "disabled"; no key or endpoint ships to the browser). The output has no
bare and no dynamic imports; the build is deterministic (a second run gives no git diff; 78,952 bytes for 0.4.1).
`tests/parser.test.mjs` exercises the committed file against `tests/fixtures/*.openui`
and records its size; `tests/renderer.test.mjs` tests `static/deep-ui.js` on top of it (jsdom when installed,
otherwise `tests/fakedom.mjs`). Update the version in the banner inside `build_vendor.mjs` and in
`static/vendor/README.md` when bumping `@openuidev/lang-core`, then `npm run gen:prompts` and commit all three.

## `render_email.mjs` contract (frozen)

```
stdin : {"task":"render","program":"<openui-lang, fences tolerated>","subject":"...","preview_text":"...","lang":"en",
         "allowed_hosts":["deependhq.com","www.deependhq.com","scheduler.zoom.us"],"max_chars":150000}
      | {"task":"prompt"}
stdout: {"ok":true,"html":"<!DOCTYPE html PUBLIC ...>...","root":"EmailTemplate","statements":19,"errors":[],"unresolved":[],"orphaned":[],"links":["https://deependhq.com/admin"],"html_chars":10455,"ms":499}
      | {"ok":true,"prompt":"...","chars":18988}
      | {"ok":false,"status":"bad_program"|"unsafe"|"too_large"|"render_error","message":"..."}
exit  : 0 whenever a JSON line was written (also for ok:false); 1 on an uncaught crash (Python treats "no JSON line" as render_error)
```

Policy in the tree walk: any component whose name matches `Markdown|Link|Image|Avatar|Social|Header|Footer|Product|
Pricing|Testimonial|Survey|Bento|Code|Checkout|Review|Article|Feature|NavLink` is `unsafe` (`EmailMarkdown` renders raw
HTML, the others carry arbitrary URLs or marketing furniture); every `href`/`src`/`url` string prop must be `https:` on an
allowed host with no userinfo and no port; every `*Color` string prop must be a `#hex` value (react-email writes it into
a `style` attribute, where `url(...)` would fetch a remote image). Python (`app/digest_rich.py`) runs a broader
text-based pre-check on the program before calling Node (same components; every URL-looking token incl. `//host` and
`https:host`; no `mailto:`/`javascript:`/`data:` URLs, no CSS `url(`, button colour `#hex`) and then requires `ok`,
`root == "EmailTemplate"`, `errors == []` and the content sanity check `sane_html` on the HTML (every headline number,
question and lead present, the e-mail addresses exactly those in DATA). An unresolved reference is dropped by the
parser, counted in `last_stats()["unresolved"]` and logged; `sane_html` is what catches a dropped tile or lead.

Node is started with a minimal environment (`PATH`, `SYSTEMROOT`, `TEMP`, `APPDATA`, `HOME`, locale, plus
`OPENUI_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1 NODE_ENV=production`): the app's API keys, SMTP, Zoom and admin secrets
never reach the child process or its packages.

Try it: `echo {"task":"prompt"} | node render_email.mjs` prints the digest prompt; `tests/render_email.test.mjs` renders
the example program (10,455 chars of HTML) and exercises every refusal.

## Files

- `prompts.mjs` — the exact texts (`CHAT_*`, `EMAIL_*`) that feed the generators; never shipped to the browser.
- `email_prompt.txt` — generated, committed; the system message of the digest call.
- `tests/lib.test.mjs` — drift test for both prompt texts + the chat examples parse cleanly.
- `tests/render_email.test.mjs` — the subprocess contract above.
- `tests/parser.test.mjs`, `tests/renderer.test.mjs`, `tests/fixtures/`, `build_vendor.mjs`, `stubs/` — the widget side
  (docs/UI_CARDS.md).
