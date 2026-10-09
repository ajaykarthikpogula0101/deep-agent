/* <deep-assistant> : the Deep assistant as a framework-agnostic web component (no build step, no dependencies).
 *
 *   <script type="module" src="https://assistant.example.com/static/deep-assistant.js"></script>
 *   <deep-assistant api="https://assistant.example.com" mode="launcher"></deep-assistant>
 *
 * Attributes
 *   api          base URL of the assistant server (required)
 *   mode         "panel" (fills its container; default) | "launcher" (floating button + pop-over panel)
 *   theme        "light" (default) | "dark" | "auto" (follow the OS)
 *   open         present = pop-over open (launcher mode)
 *   token        signed-in visitor token minted by YOUR backend (HMAC) or a Clerk session JWT; see docs/WIDGET.md
 *   user-name / user-email   unverified prefill hints when no token is available
 *   title / subtitle         header copy (default "Deep" / "AI assistant")
 *   greeting     intro line on the welcome screen
 *   suggestions  "|"-separated welcome actions (default: picked from the host page, see page-context)
 *   page-context "general" | "product" | "solutions" | "contact" (default: inferred from the page URL)
 *   tabs         sections, comma-separated from home,messages,help (default all; "messages" is always kept)
 *   shortcut     "Label|https://…" external scheduler link in Help (default: the Zoom booking page); "" hides it
 *   privacy-url  footer link (default: the server's PRIVACY_URL)
 * Methods      ask(text), book(callType?), open(), close(), toggle(), newChat() / reset(), openConversation(id),
 *              showView('chat'|'history'|'help'), setToken(token), download(), startVoice(), stopVoice()
 * Events       deep-assistant:ready | :open | :close | :question | :answer | :sources | :booking | :handover
 *              | :feedback | :error | :view | :upload | :voice | :action   (CustomEvent, bubbles + composed)
 * Theming      Indigo Dream tokens, override on the element: --da-primary --da-primary-hover --da-navy --da-lavender
 *              --da-bg --da-surface --da-success --da-text --da-muted --da-line --da-font --da-radius
 */
const VERSION = '2026.10.09.1';
const DEFAULT_SHORTCUT = 'Open the Zoom scheduler|https://scheduler.zoom.us/sreedeep';
const ALL_TABS = ['home', 'messages', 'help'];
const INTRO = "I can help you explore LakeB2B's solutions, answer questions about our services, or connect you with the right expert.";
const BOOK_RE = /\b(book|schedule|meeting|appointment|demo call|call with)\b/i;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const EMOJI = [['😀', 'grin smile happy'], ['😂', 'laugh joy tears'], ['🙂', 'smile'], ['😉', 'wink'], ['😍', 'love heart eyes'], ['🤔', 'thinking hmm'], ['😅', 'sweat smile'], ['😎', 'cool sunglasses'], ['🥳', 'party celebrate'], ['😢', 'sad cry'], ['😡', 'angry'], ['🙏', 'thanks please pray'],
  ['👋', 'wave hello hi'], ['👍', 'thumbs up yes'], ['👎', 'thumbs down no'], ['👏', 'clap'], ['🙌', 'hands raised'], ['🤝', 'handshake deal'], ['💪', 'strong muscle'], ['✌️', 'peace'], ['🤞', 'fingers crossed'], ['👀', 'eyes look'],
  ['❤️', 'heart love'], ['🔥', 'fire hot'], ['✨', 'sparkles'], ['⭐', 'star'], ['🎉', 'tada party'], ['🚀', 'rocket launch ship'], ['💡', 'idea bulb'], ['✅', 'check done yes'], ['❌', 'cross no'], ['⚡', 'bolt fast'], ['💯', 'hundred'], ['🎯', 'target goal'],
  ['📅', 'calendar date'], ['📞', 'phone call'], ['📧', 'email mail'], ['💼', 'briefcase work'], ['📈', 'chart growth'], ['📊', 'bar chart data'], ['🧠', 'brain'], ['🤖', 'robot bot ai'], ['💬', 'chat message'], ['📝', 'note memo'], ['🔗', 'link'], ['🕒', 'clock time'],
  ['☕', 'coffee'], ['🍕', 'pizza'], ['🌍', 'world globe'], ['🏢', 'office building'], ['🏆', 'trophy win'], ['🎓', 'graduate'], ['🙈', 'monkey see no'], ['🤷', 'shrug'], ['🫡', 'salute'], ['😴', 'sleep tired'], ['🤩', 'star struck wow'], ['😬', 'grimace awkward']];

// Welcome actions. Each one either asks a real question through /chat or opens the in-chat booking flow.
const ACTIONS = {
  explore: { icon: 'layers', label: 'Explore data solutions', ask: 'What data solutions does LakeB2B offer?' },
  fit: { icon: 'compass', label: 'Find the right solution for my business', ask: 'Help me find the right LakeB2B solution for my business.' },
  about: { icon: 'building', label: 'Learn about LakeB2B', ask: 'What is LakeB2B and what does it do?' },
  book: { icon: 'cal', label: 'Book a meeting', book: true },
  product: { icon: 'spark', label: 'Explain this product', askPage: (t) => (t ? `Tell me about ${t}.` : 'Tell me about this product.') },
  usecases: { icon: 'target', label: 'Show me real use cases', ask: 'What are some real use cases for LakeB2B data?' },
  demo: { icon: 'play', label: 'Book a product walkthrough', book: 'walkthrough' },
  human: { icon: 'user', label: 'Talk to a person', ask: 'Can I talk to a real person?' },
};
const CONTEXT_ACTIONS = { general: ['explore', 'fit', 'about', 'book'], product: ['product', 'usecases', 'demo', 'about'], solutions: ['fit', 'explore', 'usecases', 'book'], contact: ['book', 'human', 'fit', 'about'] };

const DARK = `--da-ink:#ADA4FF; --da-bg:#0F1324; --da-surface:#171C33; --da-subtle:#1E2441; --da-line:#2A3152; --da-line-strong:#3A4268; --da-text:#ECEEF8; --da-muted:#9BA3C0;
  --da-lavender:#26234F; --da-user:#2D2A6E; --da-user-text:#F1EFFF; --da-head:#0A0D1C; --da-primary-soft:rgba(124,112,255,.16); --da-danger-soft:rgba(232,72,108,.14); --da-danger-text:#FF9DB2; --da-ok-text:#5BE0B5;
  --da-thumb:rgba(255,255,255,.18); --da-shadow-sm:0 1px 2px rgba(0,0,0,.3); --da-shadow-md:0 10px 28px -10px rgba(0,0,0,.6); --da-shadow-lg:0 28px 64px -16px rgba(0,0,0,.7), 0 0 0 1px rgba(255,255,255,.06)`;

const CSS = `
:host {
  /* Indigo Dream design tokens */
  --da-primary:#5546F7; --da-primary-hover:#4537E8; --da-ink:var(--da-primary); --da-navy:#151B32; --da-lavender:#EEECFF; --da-bg:#F6F7FC; --da-surface:#FFFFFF;
  --da-success:#19B887; --da-text:#151B32; --da-muted:#68718A; --da-line:#E4E7F2; --da-line-strong:#CDD2E3; --da-subtle:#F0F2F9;
  --da-user:var(--da-lavender); --da-user-text:var(--da-navy); --da-head:var(--da-navy); --da-head-text:#FFFFFF; --da-head-muted:rgba(255,255,255,.66);
  --da-danger:#D6345B; --da-danger-soft:#FDEEF2; --da-danger-text:#A61E43; --da-ok-text:#0E8A64;
  --da-primary-soft:rgba(85,70,247,.10); --da-primary-ring:rgba(85,70,247,.35); --da-thumb:rgba(21,27,50,.20);
  --da-radius:20px; --da-r-lg:16px; --da-r-md:12px; --da-r-sm:8px;
  --da-shadow-sm:0 1px 2px rgba(21,27,50,.06); --da-shadow-md:0 10px 28px -10px rgba(21,27,50,.22); --da-shadow-lg:0 28px 64px -16px rgba(21,27,50,.34), 0 0 0 1px rgba(21,27,50,.06);
  --da-ease:cubic-bezier(.2,.8,.2,1); --da-grad:linear-gradient(145deg, #7466FF 0%, var(--da-primary) 55%, #3E31D4 100%);
  /* isolation: reset everything the host page could leak in through inheritance */
  display:block; box-sizing:border-box; font-family:var(--da-font, "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif);
  font-size:14px; line-height:1.5; font-weight:400; font-style:normal; letter-spacing:normal; word-spacing:normal; text-align:left; text-transform:none; text-indent:0;
  color:var(--da-text); -webkit-font-smoothing:antialiased; -moz-osx-font-smoothing:grayscale; -webkit-tap-highlight-color:transparent }
:host([theme="dark"]) { ${DARK} }
@media (prefers-color-scheme: dark) { :host([theme="auto"]) { ${DARK} } }
*, *::before, *::after { box-sizing:border-box } [hidden] { display:none !important }
button, input, textarea, select { font:inherit; color:inherit; letter-spacing:inherit; margin:0 } button { -webkit-appearance:none; appearance:none }
:focus { outline:none } :focus-visible { outline:2px solid var(--da-primary); outline-offset:2px }
.vh { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); clip-path:inset(50%); white-space:nowrap }
.scroll { scrollbar-width:thin; scrollbar-color:transparent transparent; overscroll-behavior:contain } .scroll:hover, .scroll.scrolling { scrollbar-color:var(--da-thumb) transparent }
.scroll::-webkit-scrollbar { width:6px; height:6px } .scroll::-webkit-scrollbar-track { background:transparent } .scroll::-webkit-scrollbar-thumb { background:transparent; border-radius:3px } .scroll:hover::-webkit-scrollbar-thumb, .scroll.scrolling::-webkit-scrollbar-thumb { background:var(--da-thumb) }
@keyframes da-in { from { opacity:0; transform:translateY(6px) } to { opacity:1; transform:none } }
@keyframes da-pop { from { opacity:0; transform:scale(.97) } to { opacity:1; transform:none } }
@keyframes da-blink { 50% { opacity:.35 } }
@keyframes da-shimmer { from { background-position:200% 0 } to { background-position:-200% 0 } }
@keyframes da-spin { to { transform:rotate(360deg) } }

/* ---------------------------------------------------------------- panel + launcher */
.panel { display:flex; flex-direction:column; height:100%; min-height:420px; background:var(--da-bg); color:var(--da-text); border-radius:var(--da-radius); overflow:hidden; position:relative; isolation:isolate }
:host([mode="launcher"]) { display:contents }
:host([mode="launcher"]) .panel { position:fixed; z-index:2147482999; right:max(20px, env(safe-area-inset-right)); bottom:calc(max(20px, env(safe-area-inset-bottom)) + 72px);
  width:min(400px, calc(100vw - 40px)); height:min(700px, calc(100vh - 112px)); height:min(700px, calc(100dvh - 112px)); min-height:0; box-shadow:var(--da-shadow-lg);
  opacity:0; visibility:hidden; transform:translateY(14px) scale(.98); transform-origin:bottom right; pointer-events:none;
  transition:opacity .2s var(--da-ease), transform .26s var(--da-ease), visibility 0s linear .26s }
:host([mode="launcher"][open]) .panel { opacity:1; visibility:visible; transform:none; pointer-events:auto; transition:opacity .2s var(--da-ease), transform .26s var(--da-ease), visibility 0s }
.launcher { display:none; position:fixed; z-index:2147483000; right:max(20px, env(safe-area-inset-right)); bottom:max(20px, env(safe-area-inset-bottom)); width:56px; height:56px; padding:0; border:0; border-radius:50%;
  background:var(--da-grad); color:#fff; cursor:pointer; align-items:center; justify-content:center; box-shadow:0 12px 28px -10px rgba(85,70,247,.65), 0 2px 6px rgba(21,27,50,.18); transition:transform .18s var(--da-ease), box-shadow .18s var(--da-ease) }
:host([mode="launcher"]) .launcher { display:flex }
.launcher:hover { transform:translateY(-2px); box-shadow:0 16px 32px -10px rgba(85,70,247,.75), 0 3px 8px rgba(21,27,50,.2) } .launcher:active { transform:scale(.96) }
.launcher:focus-visible { outline:3px solid var(--da-primary-ring); outline-offset:3px }
.launcher .lic { position:absolute; inset:0; display:grid; place-items:center; transition:opacity .18s var(--da-ease), transform .24s var(--da-ease) } .launcher svg { width:26px; height:26px }
.launcher .lic-close { opacity:0; transform:rotate(-60deg) scale(.7) } :host([open]) .launcher .lic-open { opacity:0; transform:rotate(60deg) scale(.7) } :host([open]) .launcher .lic-close { opacity:1; transform:none }
.ldot { position:absolute; right:2px; bottom:2px; width:13px; height:13px; border-radius:50%; background:var(--da-success); box-shadow:0 0 0 2.5px #fff } :host([open]) .ldot { display:none }
.lbadge { position:absolute; top:-3px; right:-3px; min-width:20px; height:20px; padding:0 6px; border-radius:999px; background:var(--da-danger); color:#fff; font:700 11px/20px system-ui, sans-serif; text-align:center; box-shadow:0 0 0 2px #fff } :host([open]) .lbadge { display:none }
@media (max-width:520px) {
  :host([mode="launcher"]) .panel { left:0; right:0; top:var(--da-vv-top, 0px); bottom:auto; width:100%; height:100vh; height:var(--da-vvh, 100dvh); border-radius:0; box-shadow:none; transform:translateY(24px); transform-origin:bottom center }
  :host([mode="launcher"][open]) .launcher { display:none }
  header { padding-top:calc(10px + env(safe-area-inset-top)) !important }
  textarea.q, .inp, .msearch, .fbpop input, .pop .search { font-size:16px !important }
}

/* ---------------------------------------------------------------- header */
header { flex:none; position:relative; z-index:10; display:flex; align-items:center; gap:10px; min-height:64px; padding:10px 8px 10px 16px; background:var(--da-head); color:var(--da-head-text) }
.hav { position:relative; flex:none; width:36px; height:36px; border-radius:12px; display:grid; place-items:center; background:var(--da-grad); color:#fff; box-shadow:inset 0 0 0 1px rgba(255,255,255,.16) } .hav svg { width:20px; height:20px }
.hav::after { content:""; position:absolute; inset:-3px; border-radius:14px; border:2px solid rgba(169,159,255,.0); transition:border-color .2s } .hav.work::after { border-color:rgba(169,159,255,.75); animation:da-blink 1.2s ease-in-out infinite }
.brand { flex:1; min-width:0 } .brand h1 { margin:0; font-size:15px; font-weight:650; line-height:1.25; letter-spacing:-.01em; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.brand p { margin:2px 0 0; display:flex; align-items:center; gap:6px; font-size:12px; line-height:1.3; color:var(--da-head-muted); white-space:nowrap; overflow:hidden } .brand .sub { overflow:hidden; text-overflow:ellipsis } .brand .sep { opacity:.6 }
.st { display:inline-flex; align-items:center; gap:5px; flex:none } .st i { width:7px; height:7px; border-radius:50%; background:var(--da-success); box-shadow:0 0 0 3px rgba(25,184,135,.22) }
.st.off i { background:#8C93AB; box-shadow:none } .st.work i { background:#A99FFF; box-shadow:0 0 0 3px rgba(169,159,255,.25); animation:da-blink 1s ease-in-out infinite } .st.call i { background:#FF6B8A; box-shadow:0 0 0 3px rgba(255,107,138,.25); animation:da-blink 1.4s ease-in-out infinite }
.vtitle { flex:1; min-width:0; margin:0; font-size:15px; font-weight:650; letter-spacing:-.01em; color:#fff }
.hbtn { position:relative; flex:none; width:34px; height:34px; display:inline-grid; place-items:center; padding:0; border:0; border-radius:10px; background:transparent; color:rgba(255,255,255,.78); cursor:pointer; transition:background .15s, color .15s }
.hbtn:hover { background:rgba(255,255,255,.10); color:#fff } .hbtn svg { width:18px; height:18px } .hbtn:focus-visible { outline-color:#fff; outline-offset:0 } .hbtn[aria-expanded="true"] { background:rgba(255,255,255,.14); color:#fff }
.hbadge { position:absolute; top:3px; right:3px; min-width:16px; height:16px; padding:0 4px; border-radius:999px; background:#FF5C7A; color:#fff; font:700 10px/16px system-ui, sans-serif; text-align:center; box-shadow:0 0 0 2px var(--da-head) }
.vpill { display:none; align-items:center; gap:6px; height:28px; padding:0 10px; border:1px solid rgba(255,255,255,.2); border-radius:999px; background:rgba(255,255,255,.08); color:#fff; font-size:12px; font-weight:600; cursor:pointer; flex:none } .vpill.show { display:inline-flex } .vpill i { width:6px; height:6px; border-radius:50%; background:#FF6B8A; animation:da-blink 1s infinite }
.menu { position:absolute; right:8px; top:calc(100% - 4px); z-index:30; min-width:224px; padding:6px; background:var(--da-surface); color:var(--da-text); border:1px solid var(--da-line); border-radius:14px; box-shadow:var(--da-shadow-md); display:none }
.menu.open { display:block; animation:da-pop .14s var(--da-ease) both; transform-origin:top right }
.menu button { display:flex; align-items:center; gap:10px; width:100%; padding:9px 10px; border:0; border-radius:9px; background:transparent; text-align:left; font-size:13.5px; cursor:pointer } .menu button:hover, .menu button:focus-visible { background:var(--da-subtle); outline:none } .menu svg { width:17px; height:17px; color:var(--da-muted); flex:none }
.menu hr { border:0; border-top:1px solid var(--da-line); margin:6px 4px }

/* ---------------------------------------------------------------- views + conversation */
.views { flex:1; min-height:0; min-width:0; display:flex } .view { flex:1; min-height:0; min-width:0; display:flex; flex-direction:column; position:relative }
.log { flex:1; min-height:0; overflow-y:auto; overflow-x:hidden; padding:20px 16px 12px; display:flex; flex-direction:column; gap:16px }
.welcome { display:flex; flex-direction:column; gap:14px; padding:4px 2px 0; animation:da-in .3s var(--da-ease) both }
.wav { width:44px; height:44px; border-radius:14px; display:grid; place-items:center; background:var(--da-grad); color:#fff; box-shadow:0 10px 24px -10px rgba(85,70,247,.6) } .wav svg { width:24px; height:24px }
.welcome h2 { margin:4px 0 0; font-size:20px; font-weight:700; line-height:1.25; letter-spacing:-.02em; color:var(--da-text) }
.welcome p { margin:-4px 0 0; font-size:14px; line-height:1.55; color:var(--da-muted) }
.acts-label { margin:6px 2px -4px; font-size:12px; font-weight:600; color:var(--da-muted) }
.acts { display:flex; flex-direction:column; gap:8px }
.act { display:flex; align-items:center; gap:12px; width:100%; min-height:52px; padding:10px 12px; border:1px solid var(--da-line); border-radius:14px; background:var(--da-surface); color:var(--da-text); font-size:14px; font-weight:550; text-align:left; text-decoration:none; cursor:pointer; box-shadow:var(--da-shadow-sm); transition:border-color .15s, box-shadow .15s, transform .15s }
.act .ai { flex:none; width:32px; height:32px; border-radius:10px; display:grid; place-items:center; background:var(--da-lavender); color:var(--da-ink) } .act .ai svg { width:17px; height:17px }
.act .al { flex:1; min-width:0 } .act .al small { display:block; margin-top:1px; font-size:12px; font-weight:400; color:var(--da-muted) }
.act > svg { flex:none; width:16px; height:16px; color:var(--da-muted); transition:transform .15s, color .15s }
.act:hover { border-color:rgba(85,70,247,.45); box-shadow:var(--da-shadow-md) } .act:hover > svg { transform:translateX(2px); color:var(--da-ink) } .act:active { transform:scale(.99) }
.act.book .ai { background:var(--da-primary); color:#fff }
.row { display:flex; gap:8px; max-width:100%; min-width:0; animation:da-in .22s var(--da-ease) both } .row.user { justify-content:flex-end }
.bav { flex:none; width:28px; height:28px; margin-top:2px; border-radius:9px; display:grid; place-items:center; background:var(--da-grad); color:#fff } .bav svg { width:16px; height:16px }
.col { display:flex; flex-direction:column; align-items:flex-start; min-width:0; max-width:calc(100% - 36px) } .row.user .col { align-items:flex-end; max-width:85% } .row.wide .col { flex:1 }
.msg { position:relative; min-width:0; max-width:100%; padding:10px 14px; border-radius:16px; font-size:14.5px; line-height:1.55; white-space:pre-wrap; overflow-wrap:anywhere }
.bot .msg { background:var(--da-surface); color:var(--da-text); border:1px solid var(--da-line); border-top-left-radius:6px; box-shadow:var(--da-shadow-sm) }
.user .msg { background:var(--da-user); color:var(--da-user-text); border-top-right-radius:6px }
.msg.hascard { width:100%; padding:14px } .msg.err { background:var(--da-danger-soft); border-color:rgba(214,52,91,.28); color:var(--da-danger-text) }
.msg b { font-weight:650 } .msg .h { display:block; font-weight:650; margin:2px 0 } .msg code { font:12.5px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; padding:1px 5px; border-radius:5px; background:var(--da-subtle) }
.msg a:not(.btn):not(.cite) { color:var(--da-ink); text-decoration:underline; text-decoration-color:rgba(85,70,247,.35); text-underline-offset:3px; overflow-wrap:anywhere } .user .msg a:not(.btn) { color:inherit }
.msg img.gif { display:block; max-width:240px; max-height:220px; border-radius:12px; margin:2px 0 }
.li { display:block; position:relative; padding-left:16px; margin:2px 0 } .li::before { content:""; position:absolute; left:4px; top:.68em; width:5px; height:5px; border-radius:50%; background:var(--da-primary); opacity:.75 }
.li.num { padding-left:22px } .li.num::before { content:attr(data-n) "."; top:0; left:0; width:auto; height:auto; border-radius:0; background:none; opacity:1; color:var(--da-muted); font-weight:600; font-size:13px }
.meta { margin:5px 4px 0; font-size:11.5px; line-height:1.3; color:var(--da-muted) }
.cite { display:inline-block; vertical-align:super; margin-left:2px; padding:1px 5px; border-radius:999px; background:var(--da-lavender); color:var(--da-ink); font:650 9.5px/1.2 system-ui, sans-serif; text-decoration:none } a.cite:hover { background:var(--da-primary); color:#fff }
.activity { display:inline-flex; align-items:center; gap:8px; margin:0 0 6px; padding:6px 12px; border-radius:999px; background:var(--da-surface); border:1px solid var(--da-line); font-size:12.5px; color:var(--da-muted); max-width:100%; animation:da-in .2s ease-out both }
.activity .spin { width:12px; height:12px; flex:none; border-radius:50%; border:2px solid var(--da-lavender); border-top-color:var(--da-ink); animation:da-spin .8s linear infinite }
.activity .lbl { white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.msg.skel { min-width:200px; max-width:260px; padding:14px } .skel .ln { height:9px; margin:6px 0; border-radius:6px; background:linear-gradient(90deg, var(--da-subtle) 25%, var(--da-line) 50%, var(--da-subtle) 75%); background-size:200% 100%; animation:da-shimmer 1.4s linear infinite } .skel .ln:nth-child(2) { width:85% } .skel .ln:nth-child(3) { width:55% }
.msg.streaming::after { content:""; display:inline-block; width:2px; height:1em; margin-left:2px; vertical-align:-2px; background:var(--da-primary); animation:da-blink .9s steps(2, start) infinite }
.worked { display:inline-flex; align-items:center; gap:4px; margin:0 0 6px; padding:0; border:0; background:transparent; color:var(--da-muted); font-size:12px; cursor:pointer } .worked:hover { color:var(--da-text) } .worked svg { width:12px; height:12px; transition:transform .2s } .worked.open svg { transform:rotate(90deg) }
.steps { display:none; margin:-2px 0 8px 4px; font-size:12px; line-height:1.55; color:var(--da-muted) } .steps.open { display:block } .steps div { display:flex; gap:10px } .steps b { min-width:40px; text-align:right; font-weight:500; font-variant-numeric:tabular-nums; opacity:.8 }
.sources { display:flex; align-items:center; gap:8px; margin:8px 0 0; max-width:100%; min-width:0 } .sources .lbl { flex:none; font-size:11.5px; font-weight:600; color:var(--da-muted) }
.srcs { display:flex; gap:6px; min-width:0; overflow-x:auto; scrollbar-width:none } .srcs::-webkit-scrollbar { display:none }
.srcs a { flex:none; display:inline-flex; align-items:center; gap:6px; height:26px; max-width:240px; padding:0 10px 0 4px; border:1px solid var(--da-line); border-radius:999px; background:var(--da-surface); color:var(--da-text); font-size:12px; line-height:1; text-decoration:none; transition:border-color .15s }
.srcs a b { min-width:18px; height:18px; padding:0 4px; border-radius:999px; background:var(--da-lavender); color:var(--da-ink); font:650 10.5px/18px system-ui, sans-serif; text-align:center } .srcs a .t { white-space:nowrap; overflow:hidden; text-overflow:ellipsis } .srcs a .hh { color:var(--da-muted); white-space:nowrap } .srcs a:hover { border-color:var(--da-ink) }
.tools { display:flex; gap:2px; margin:4px 0 0; opacity:0; transition:opacity .15s } .row:hover .tools, .row:focus-within .tools, .row.last .tools, .tools.keep { opacity:1 } @media (hover:none) { .tools { opacity:1 } }
.tool { position:relative; width:28px; height:28px; display:inline-grid; place-items:center; padding:0; border:0; border-radius:8px; background:transparent; color:var(--da-muted); cursor:pointer } .tool:hover { background:var(--da-subtle); color:var(--da-text) } .tool svg { width:15px; height:15px } .tool.on { color:var(--da-ink) }
.tool .tip { position:absolute; bottom:calc(100% + 4px); left:50%; transform:translateX(-50%); padding:3px 7px; border-radius:6px; background:var(--da-navy); color:#fff; font-size:11px; white-space:nowrap; pointer-events:none }
.followups { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; animation:da-in .25s .05s var(--da-ease) both }
.fu { display:inline-flex; align-items:center; gap:6px; min-height:32px; padding:4px 12px; border:1px solid rgba(85,70,247,.3); border-radius:999px; background:var(--da-surface); color:var(--da-ink); font-size:13px; font-weight:550; cursor:pointer; text-align:left; transition:background .15s, border-color .15s }
.fu:hover { background:var(--da-lavender); border-color:var(--da-ink) } .fu svg { width:14px; height:14px; flex:none }
.jump { position:absolute; left:50%; bottom:calc(100% + 8px); transform:translateX(-50%); z-index:4; display:inline-flex; align-items:center; gap:6px; height:30px; padding:0 12px; border:1px solid var(--da-line); border-radius:999px; background:var(--da-surface); color:var(--da-text); box-shadow:var(--da-shadow-md); font-size:12px; font-weight:600; cursor:pointer; animation:da-in .18s var(--da-ease) both } .jump svg { width:14px; height:14px }
.toastmsg { position:absolute; left:50%; bottom:128px; z-index:40; transform:translate(-50%, 8px); padding:8px 14px; border-radius:999px; background:var(--da-navy); color:#fff; font-size:13px; box-shadow:var(--da-shadow-md); opacity:0; pointer-events:none; transition:opacity .2s, transform .2s } .toastmsg.show { opacity:1; transform:translate(-50%, 0) }
.fbpop { display:flex; flex-direction:column; gap:8px; width:min(300px, 100%); margin:6px 0 0; padding:12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-surface); box-shadow:var(--da-shadow-md); animation:da-pop .16s var(--da-ease) both }
.fbpop .reasons { display:flex; flex-wrap:wrap; gap:4px } .reason { height:28px; padding:0 10px; border:1px solid var(--da-line); border-radius:999px; background:transparent; font-size:12px; cursor:pointer } .reason:hover { border-color:var(--da-ink) } .reason.on { background:var(--da-primary); border-color:var(--da-ink); color:#fff }
.fbpop input { height:34px; padding:0 10px; border:1px solid var(--da-line); border-radius:8px; background:var(--da-surface); font-size:13px } .fbpop input:focus { border-color:var(--da-ink); box-shadow:0 0 0 3px var(--da-primary-soft) }
.fbpop .fbrow { display:flex; justify-content:flex-end; gap:6px }

/* ---------------------------------------------------------------- buttons, cards, forms */
.btn { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:38px; padding:8px 14px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-surface); color:var(--da-text); font-size:13.5px; font-weight:600; line-height:1.2; text-align:center; text-decoration:none; cursor:pointer; transition:background .15s, border-color .15s, color .15s, box-shadow .15s }
.btn:hover { border-color:var(--da-line-strong); background:var(--da-subtle) } .btn svg { width:16px; height:16px; flex:none }
.btn.primary { background:var(--da-primary); border-color:var(--da-ink); color:#fff; box-shadow:0 6px 16px -8px rgba(85,70,247,.7) } .btn.primary:hover { background:var(--da-primary-hover); border-color:var(--da-primary-hover) }
.btn.ghost { border-color:transparent; background:transparent; color:var(--da-muted) } .btn.ghost:hover { color:var(--da-text); background:var(--da-subtle) }
.btn.block { width:100% } .btn.sm { min-height:32px; padding:4px 10px; font-size:12.5px } .btn:disabled { opacity:.55; cursor:not-allowed }
.btn.loading::before { content:""; width:14px; height:14px; border-radius:50%; border:2px solid rgba(255,255,255,.4); border-top-color:#fff; animation:da-spin .8s linear infinite }
.hrow { display:flex; flex-wrap:wrap; align-items:center; gap:8px }
.note { margin:0; font-size:12px; line-height:1.45; color:var(--da-muted) } .note.warn { color:var(--da-danger-text) } .note.ok { color:var(--da-ok-text) }
.banner { display:flex; gap:8px; align-items:flex-start; padding:10px 12px; border-radius:10px; background:var(--da-danger-soft); color:var(--da-danger-text); font-size:13px; line-height:1.45 } .banner svg { width:16px; height:16px; flex:none; margin-top:1px } .banner.info { background:var(--da-lavender); color:var(--da-text) }
.card { white-space:normal; min-width:0; max-width:100% }
.field { display:flex; flex-direction:column; gap:4px } .field > label { font-size:12px; font-weight:600; color:var(--da-text) } .field > label span { font-weight:400; color:var(--da-muted) }
.inp { width:100%; height:40px; padding:0 12px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-surface); color:var(--da-text); font-size:14px; transition:border-color .15s, box-shadow .15s }
textarea.inp { height:auto; min-height:68px; padding:9px 12px; resize:vertical; line-height:1.45 } .inp::placeholder { color:var(--da-muted); opacity:.8 }
.inp:focus { border-color:var(--da-ink); box-shadow:0 0 0 3px var(--da-primary-soft) } .inp[aria-invalid="true"] { border-color:var(--da-danger) } .ferr { font-size:12px; color:var(--da-danger-text) }

/* booking card (docs/BOOKING.md) */
.bk { display:flex; flex-direction:column; gap:12px } .msg > .bk.card, .msg > .hform { margin-top:12px }
.bk-head { display:flex; align-items:center; gap:8px } .bk-back { flex:none; width:30px; height:30px; display:inline-grid; place-items:center; margin-left:-4px; padding:0; border:0; border-radius:8px; background:transparent; color:var(--da-muted); cursor:pointer } .bk-back:hover { background:var(--da-subtle); color:var(--da-text) } .bk-back svg { width:18px; height:18px }
.bk-t { flex:1; min-width:0; display:flex; align-items:baseline; justify-content:space-between; gap:8px } .bk-t b { font-size:14.5px; font-weight:650; letter-spacing:-.01em } .bk-t span { flex:none; font-size:11.5px; color:var(--da-muted) }
.bk-prog { display:grid; grid-template-columns:repeat(4, 1fr); gap:4px; margin-top:-4px } .bk-prog i { height:3px; border-radius:2px; background:var(--da-line); transition:background .2s } .bk-prog i.on { background:var(--da-primary) }
.ctypes { display:flex; flex-direction:column; gap:8px }
.ctype { position:relative; display:flex; align-items:flex-start; gap:12px; width:100%; padding:12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-surface); color:var(--da-text); text-align:left; cursor:pointer; transition:border-color .15s, box-shadow .15s }
.ctype:hover { border-color:rgba(85,70,247,.5) } .ctype.on { border-color:var(--da-ink); box-shadow:0 0 0 3px var(--da-primary-soft) }
.ctype .ci { flex:none; width:32px; height:32px; border-radius:10px; display:grid; place-items:center; background:var(--da-lavender); color:var(--da-ink) } .ctype .ci svg { width:17px; height:17px }
.ctype .cx { flex:1; min-width:0 } .ctype b { display:block; font-size:13.5px; font-weight:650; line-height:1.35 } .ctype .cd { display:block; margin-top:2px; font-size:12.5px; line-height:1.45; color:var(--da-muted) }
.ctype .cm { display:inline-flex; align-items:center; gap:4px; margin-top:6px; font-size:12px; font-weight:600; color:var(--da-ink) } .ctype .cm svg { width:13px; height:13px }
.tag { display:inline-block; margin-left:6px; padding:1px 7px; border-radius:999px; background:var(--da-lavender); color:var(--da-ink); font-size:10.5px; font-weight:650; vertical-align:1px }
.ahead { display:flex; flex-direction:column; gap:2px; padding:10px 12px; border-radius:12px; background:var(--da-subtle) } .ahead b { font-size:13.5px; font-weight:650 } .ahead span { font-size:12px; color:var(--da-muted); line-height:1.45 }
.dates { display:flex; gap:6px; overflow-x:auto; padding:2px 2px 6px; margin:0 -2px; scroll-snap-type:x proximity; scrollbar-width:thin }
.date { flex:none; min-width:64px; display:flex; flex-direction:column; align-items:center; gap:2px; padding:8px 10px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-surface); color:var(--da-text); cursor:pointer; scroll-snap-align:start; transition:border-color .15s, background .15s }
.date b { font-size:12px; font-weight:650; white-space:nowrap } .date small { font-size:10.5px; color:var(--da-muted); white-space:nowrap } .date:not(.off):hover { border-color:var(--da-ink) }
.date.on { border-color:var(--da-ink); background:var(--da-lavender) } .date.on small { color:var(--da-ink) } .date.off { opacity:.45; cursor:not-allowed }
.times { display:grid; grid-template-columns:repeat(auto-fill, minmax(82px, 1fr)); gap:6px }
.time { min-height:38px; padding:4px 6px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-surface); color:var(--da-text); font-size:13px; font-weight:600; cursor:pointer; transition:border-color .15s, color .15s, background .15s }
.time:hover { border-color:var(--da-ink); color:var(--da-ink) } .time.on { background:var(--da-primary); border-color:var(--da-ink); color:#fff }
.sumbox { border:1px solid var(--da-line); border-radius:12px; overflow:hidden } .sumrow { display:flex; justify-content:space-between; gap:12px; padding:9px 12px; border-bottom:1px solid var(--da-line); font-size:13px } .sumrow:last-child { border-bottom:0 }
.sumrow span { flex:none; color:var(--da-muted) } .sumrow b { min-width:0; font-weight:600; text-align:right; overflow-wrap:anywhere }
.pickd { display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:12px; background:var(--da-lavender); font-size:13px } .pickd svg { width:16px; height:16px; color:var(--da-ink); flex:none } .pickd span { flex:1; min-width:0 } .pickd b { font-weight:650 }
.linkbtn { padding:0; border:0; background:none; color:var(--da-ink); font-size:12.5px; font-weight:600; cursor:pointer; text-decoration:underline; text-underline-offset:2px }
.bform, .hform { display:flex; flex-direction:column; gap:10px }
.booked { display:flex; flex-direction:column; gap:6px } .bk-ok { display:flex; align-items:center; gap:10px; font-size:16px; font-weight:700; letter-spacing:-.01em }
.chk { width:30px; height:30px; flex:none } .chk circle { fill:rgba(25,184,135,.12); stroke:var(--da-success); stroke-width:2; stroke-dasharray:80; stroke-dashoffset:80; animation:da-draw .5s ease-out forwards } .chk path { fill:none; stroke:var(--da-success); stroke-width:2.4; stroke-linecap:round; stroke-linejoin:round; stroke-dasharray:30; stroke-dashoffset:30; animation:da-draw .35s .35s ease-out forwards } @keyframes da-draw { to { stroke-dashoffset:0 } }
.pend { width:30px; height:30px; flex:none; border-radius:50%; display:grid; place-items:center; background:var(--da-lavender); color:var(--da-ink) } .pend svg { width:17px; height:17px }
.bk-when { font-size:15px; font-weight:650 } .bk-sub { font-size:12.5px; color:var(--da-muted) }
.nexts { list-style:none; display:flex; flex-direction:column; gap:7px; margin:6px 0 0; padding:12px 0 0; border-top:1px solid var(--da-line); font-size:13px; color:var(--da-text) } .nexts li { display:flex; gap:8px; align-items:flex-start } .nexts svg { width:15px; height:15px; flex:none; margin-top:2px; color:var(--da-success) } .nexts .nx { color:var(--da-ink) }
.callcard { padding:12px 14px; border:1px solid var(--da-line); border-radius:14px; background:var(--da-surface) } .callcard .cc-t { display:flex; align-items:center; gap:8px; font-size:13.5px; font-weight:650 } .callcard .cc-t svg { width:16px; height:16px; color:var(--da-ink) } .callcard .cc-s { margin-top:2px; font-size:12px; color:var(--da-muted) }

/* ---------------------------------------------------------------- composer */
.composer { flex:none; position:relative; padding:8px 12px 0; background:var(--da-bg) }
.cbox { padding:5px; border:1px solid var(--da-line); border-radius:22px; background:var(--da-surface); box-shadow:var(--da-shadow-sm); transition:border-color .15s, box-shadow .15s }
.cbox.focus { border-color:rgba(85,70,247,.6); box-shadow:0 0 0 4px var(--da-primary-soft) } .cbox.drop { border-color:var(--da-ink); background:var(--da-lavender) }
textarea.q { display:block; flex:1; min-width:0; width:auto; min-height:34px; max-height:120px; padding:6px 4px; border:0; background:transparent; color:var(--da-text); font-size:14.5px; line-height:22px; resize:none; outline:none; caret-color:var(--da-ink) } textarea.q::placeholder { color:var(--da-muted) }
.crow { display:flex; align-items:flex-end; gap:2px }
.plus-wrap { position:relative; flex:none }
.pmenu { position:absolute; left:-1px; bottom:calc(100% + 10px); z-index:7; min-width:184px; padding:6px; border:1px solid var(--da-line); border-radius:14px; background:var(--da-surface); box-shadow:var(--da-shadow-md); display:none } .pmenu.open { display:block; animation:da-pop .14s var(--da-ease) both; transform-origin:bottom left }
.pmenu button { display:flex; align-items:center; gap:10px; width:100%; padding:8px 10px; border:0; border-radius:9px; background:transparent; color:var(--da-text); font-size:13.5px; text-align:left; cursor:pointer } .pmenu button:hover, .pmenu button:focus-visible { background:var(--da-subtle); outline:none } .pmenu svg { width:17px; height:17px; color:var(--da-muted); flex:none } .pmenu .on svg { color:var(--da-ink) }
.cicon { width:34px; height:34px; display:inline-grid; place-items:center; padding:0; border:0; border-radius:50%; background:transparent; color:var(--da-muted); cursor:pointer; flex:none } .cicon:hover { background:var(--da-subtle); color:var(--da-text) } .cicon svg { width:18px; height:18px } .cicon.on { color:var(--da-ink); background:var(--da-lavender) }
.cicon.speak { color:var(--da-ink) } .cicon.speak:hover { background:var(--da-lavender); color:var(--da-ink) } .b-plus[aria-expanded="true"] { background:var(--da-lavender); color:var(--da-ink) } .b-plus svg { transition:transform .18s var(--da-ease) } .b-plus[aria-expanded="true"] svg { transform:rotate(45deg) }
.send { width:34px; height:34px; margin-left:2px; display:inline-grid; place-items:center; padding:0; border:0; border-radius:50%; background:var(--da-primary); color:#fff; cursor:pointer; flex:none; transition:background .15s, color .15s } .send svg { width:18px; height:18px }
.send:hover { background:var(--da-primary-hover) } .send:disabled { background:var(--da-subtle); color:var(--da-muted); cursor:not-allowed } .send.stop { background:var(--da-navy); color:#fff }
.attach { display:flex; flex-wrap:wrap; gap:6px; padding:4px 4px 6px } .achip { position:relative; display:inline-flex; align-items:center; gap:6px; max-width:100%; padding:4px 4px 4px 8px; border-radius:10px; background:var(--da-subtle); font-size:12px; overflow:hidden }
.achip img { width:28px; height:28px; border-radius:6px; object-fit:cover } .achip .nm { max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap } .achip .sz { color:var(--da-muted); font-size:11px }
.achip .x { width:22px; height:22px; border:0; border-radius:6px; background:transparent; color:var(--da-muted); cursor:pointer } .achip .x:hover { background:var(--da-line); color:var(--da-text) }
.achip .bar { position:absolute; left:0; bottom:0; height:2px; width:0; background:var(--da-primary); transition:width .2s } .achip.err { outline:1px solid var(--da-danger) }
.rec { display:none; align-items:center; gap:8px; padding:2px 8px 4px; font-size:12px; color:var(--da-danger-text) } .rec.on { display:flex } .rec i { width:8px; height:8px; border-radius:50%; background:var(--da-danger); animation:da-blink 1s steps(2, start) infinite } .rec .cicon { width:26px; height:26px }
.foot { flex:none; padding:6px 12px calc(8px + env(safe-area-inset-bottom)); text-align:center; font-size:11px; line-height:1.4; color:var(--da-muted) } .foot a { color:inherit; text-underline-offset:2px }
.pop { position:absolute; left:12px; right:12px; bottom:calc(100% - 4px); z-index:6; padding:12px; border:1px solid var(--da-line); border-radius:14px; background:var(--da-surface); box-shadow:var(--da-shadow-md); display:none } .pop.open { display:block; animation:da-pop .14s var(--da-ease) both }
.pop .search { width:100%; height:36px; margin-bottom:8px; padding:0 10px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-surface); font-size:14px } .pop .search:focus { border-color:var(--da-ink) }
.egrid { display:grid; grid-template-columns:repeat(8, 1fr); gap:2px; max-height:190px; overflow-y:auto } .egrid button { height:36px; border:0; border-radius:8px; background:transparent; font-size:20px; cursor:pointer } .egrid button:hover { background:var(--da-subtle) }
.ggrid { display:grid; grid-template-columns:repeat(3, 1fr); gap:6px; max-height:230px; overflow-y:auto } .ggrid button { padding:0; border:0; border-radius:10px; overflow:hidden; background:var(--da-subtle); cursor:pointer; aspect-ratio:4/3 } .ggrid img { width:100%; height:100%; object-fit:cover; display:block }
.pop .empty { padding:12px 4px; font-size:12px; color:var(--da-muted); text-align:center }

/* ---------------------------------------------------------------- history + help */
.hist, .help { flex:1; min-height:0; overflow-y:auto; overflow-x:hidden; padding:14px 12px 20px }
.htop { display:flex; flex-direction:column; gap:10px; margin:0 4px 6px } .searchbox { position:relative } .searchbox svg { position:absolute; left:11px; top:50%; width:16px; height:16px; transform:translateY(-50%); color:var(--da-muted); pointer-events:none }
.msearch { width:100%; height:38px; padding:0 12px 0 34px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-surface); color:var(--da-text); font-size:14px } .msearch:focus { border-color:var(--da-ink); box-shadow:0 0 0 3px var(--da-primary-soft) } .msearch::placeholder { color:var(--da-muted) }
.mgroup { margin:14px 10px 4px; font-size:11px; font-weight:650; letter-spacing:.06em; text-transform:uppercase; color:var(--da-muted) }
.convo { position:relative; display:flex; align-items:center; gap:12px; width:100%; min-width:0; padding:10px; border:0; border-radius:12px; background:transparent; color:var(--da-text); text-align:left; cursor:pointer; overflow:hidden; transition:background .15s, box-shadow .15s }
.convo:hover, .convo:focus-visible { background:var(--da-surface); box-shadow:var(--da-shadow-sm) } .convo.cur { background:var(--da-surface); box-shadow:inset 0 0 0 1px var(--da-line) }
.avatar { flex:none; width:34px; height:34px; border-radius:11px; display:grid; place-items:center; background:var(--da-lavender); color:var(--da-ink); font-weight:700; font-size:13px } .avatar svg { width:17px; height:17px }
.convo .c { flex:1 1 auto; min-width:0 } .convo .n { display:block; font-size:13.5px; font-weight:600; line-height:1.35; white-space:nowrap; overflow:hidden; text-overflow:ellipsis } .convo.unread .n { font-weight:750 }
.convo .p { display:block; margin-top:2px; font-size:12.5px; line-height:1.35; color:var(--da-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.convo .r { flex:none; align-self:flex-start; display:flex; flex-direction:column; align-items:flex-end; gap:6px; min-width:32px; padding-top:2px } .convo .ctime { font-size:11.5px; color:var(--da-muted); white-space:nowrap } .dot { width:8px; height:8px; border-radius:50%; background:var(--da-primary) }
.cur-tag { padding:1px 7px; border-radius:999px; background:var(--da-lavender); color:var(--da-ink); font-size:10.5px; font-weight:650 }
.more2 { position:absolute; right:8px; top:50%; transform:translateY(-50%); width:28px; height:28px; border-radius:8px; background:var(--da-surface); color:var(--da-muted); display:none; align-items:center; justify-content:center; cursor:pointer } .more2 svg { width:16px; height:16px }
.convo:hover .more2, .convo:focus-within .more2 { display:inline-flex } .more2:hover { background:var(--da-subtle); color:var(--da-text) } @media (hover:none) { .more2 { display:none !important } }
.rename { display:flex; gap:6px; align-items:center; padding:6px 10px 10px 56px } .rename .inp { flex:1; min-width:0; height:34px }
.empty { display:flex; flex-direction:column; align-items:center; gap:6px; padding:40px 20px 20px; text-align:center; color:var(--da-muted); font-size:13.5px; line-height:1.5 }
.empty .ei { width:48px; height:48px; margin-bottom:6px; border-radius:16px; display:grid; place-items:center; background:var(--da-lavender); color:var(--da-ink) } .empty .ei svg { width:22px; height:22px } .empty b { color:var(--da-text); font-size:15px } .empty .btn { margin-top:10px }
.sk { display:flex; align-items:center; gap:12px; padding:10px } .sk .a { width:34px; height:34px; border-radius:11px } .sk .l { flex:1 } .sk .a, .sk .l i { background:linear-gradient(90deg, var(--da-subtle) 25%, var(--da-line) 50%, var(--da-subtle) 75%); background-size:200% 100%; animation:da-shimmer 1.4s linear infinite }
.sk .l i { display:block; height:9px; border-radius:5px; margin:5px 0 } .sk .l i:last-child { width:65% }
.help h3 { margin:20px 4px 8px; font-size:11px; font-weight:650; letter-spacing:.06em; text-transform:uppercase; color:var(--da-muted) } .help h3:first-child { margin-top:4px }
.caplist { list-style:none; display:flex; flex-direction:column; gap:10px; margin:0; padding:12px 14px; border:1px solid var(--da-line); border-radius:14px; background:var(--da-surface); font-size:13px; line-height:1.45 } .caplist li { display:flex; gap:10px } .caplist svg { width:16px; height:16px; flex:none; margin-top:1px; color:var(--da-success) }
.chips { display:flex; flex-wrap:wrap; gap:6px } .chip { min-height:32px; padding:5px 12px; border:1px solid var(--da-line); border-radius:999px; background:var(--da-surface); color:var(--da-text); font-size:13px; text-align:left; cursor:pointer; transition:border-color .15s, color .15s } .chip:hover { border-color:var(--da-ink); color:var(--da-ink) }
.hfoot { margin:20px 4px 0; font-size:12px; color:var(--da-muted) } .hfoot a { color:inherit }

/* ---------------------------------------------------------------- voice call view */
.voice { position:absolute; inset:0; z-index:20; display:none; flex-direction:column; align-items:center; overflow:hidden; text-align:center; color:#fff; background:radial-gradient(120% 80% at 50% 0%, #232A4E 0%, var(--da-navy) 55%, #0C1023 100%) } .voice.open { display:flex }
.vhead { flex:none; width:100%; height:56px; display:flex; align-items:center; gap:8px; padding:0 8px 0 16px; padding-top:env(safe-area-inset-top); font-size:14px } .vhead b { font-weight:650 }
.vhead .live { width:8px; height:8px; border-radius:50%; background:var(--da-success); animation:da-live 1.6s ease-out infinite } @keyframes da-live { 0% { box-shadow:0 0 0 0 rgba(25,184,135,.55) } 100% { box-shadow:0 0 0 8px rgba(25,184,135,0) } }
.vhead .vtimer { margin-left:auto; font:500 13px/1 ui-monospace, monospace; color:rgba(255,255,255,.66); font-variant-numeric:tabular-nums }
.vbody { position:relative; flex:1; min-height:0; width:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:14px; padding:12px 16px }
.vglow { position:absolute; inset:0; pointer-events:none; background:radial-gradient(circle at 50% 44%, var(--vglow, rgba(85,70,247,.32)) 0%, transparent 52%); opacity:var(--vglow-o, .6); transition:opacity .4s }
.vorb { position:relative; width:220px; height:220px; display:flex; align-items:center; justify-content:center } .vorb canvas { width:220px; height:220px; display:block }
.vorb.static { width:160px; height:160px; border-radius:50%; background:radial-gradient(circle at 35% 32%, #DCD7FF 0%, #7C6FFF 32%, #5546F7 62%, #3A2FC9 100%); transition:opacity .4s, filter .4s } .voice.muted .vorb.static { filter:grayscale(1); opacity:.6 }
.vmute-badge { position:absolute; bottom:6px; left:50%; z-index:1; transform:translateX(-50%); display:none; padding:2px 8px; border-radius:999px; background:rgba(255,255,255,.14); color:#fff; font-size:11px } .voice.muted .vmute-badge { display:block }
.vstatus { min-height:20px; font-size:15px; color:rgba(255,255,255,.75); transition:opacity .25s, transform .25s } .vstatus.sw { opacity:0; transform:translateY(3px) }
.vcap { width:min(360px, 100%); min-height:46px; max-height:46px; overflow:hidden; display:flex; flex-direction:column; justify-content:flex-end; gap:3px; font-size:14px; line-height:1.45 }
.vcap .cu { color:rgba(255,255,255,.6); font-style:italic; white-space:nowrap; overflow:hidden; text-overflow:ellipsis } .vcap .ca .w { opacity:.3; transition:opacity .12s } .vcap .ca .w.on { opacity:1 } .vcap.off { visibility:hidden }
.vctl { flex:none; display:flex; justify-content:center; align-items:center; gap:16px; padding:12px 16px calc(24px + env(safe-area-inset-bottom)) }
.vbtn { position:relative; flex:none; width:56px; height:56px; display:inline-grid; place-items:center; padding:0; border:0; border-radius:50%; background:rgba(255,255,255,.12); color:#fff; cursor:pointer; transition:background .2s, color .2s, transform .15s }
.vbtn svg { width:24px; height:24px } .vbtn:hover { background:rgba(255,255,255,.2) } .vbtn:active { transform:scale(.96) } .vbtn.on { background:#fff; color:var(--da-navy) } .vbtn.end { background:#E5484D } .vbtn.end:hover { background:#F05A5F } .vbtn.cc.off { color:rgba(255,255,255,.5) } .vbtn:focus-visible { outline-color:#fff }
.vbtn .tip { position:absolute; bottom:calc(100% + 8px); left:50%; transform:translateX(-50%); padding:3px 7px; border-radius:6px; background:#fff; color:var(--da-navy); font-size:11px; white-space:nowrap; opacity:0; pointer-events:none; transition:opacity .15s } .vbtn:hover .tip, .vbtn:focus-visible .tip { opacity:1 }
.voice .hbtn { margin-left:4px }
.voice.closing .vorb { animation:da-collapse .35s ease-in forwards } @keyframes da-collapse { to { transform:scale(.15); opacity:0 } }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration:.001ms !important; animation-iteration-count:1 !important; animation-delay:0s !important; transition-duration:.001ms !important; transition-delay:0s !important }
  .chk circle, .chk path { stroke-dashoffset:0 }
}
`;

const I = (d, w = 1.8) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const SVG = {
  mark: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3.5c4.97 0 9 3.36 9 7.5s-4.03 7.5-9 7.5c-.9 0-1.77-.11-2.6-.32L5 20l.95-3.4C4.13 15.24 3 13.22 3 11c0-4.14 4.03-7.5 9-7.5z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M12 7.2l.95 2.65 2.65.95-2.65.95L12 14.4l-.95-2.65-2.65-.95 2.65-.95z" fill="currentColor"/></svg>',
  more: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>',
  close: I('<path d="M6 6l12 12M18 6L6 18"/>', 2),
  minus: I('<path d="M6 12h12"/>', 2),
  chevdown: I('<path d="M6 9l6 6 6-6"/>', 2.2),
  back: I('<path d="M15 5l-7 7 7 7"/>', 2),
  send: I('<path d="M12 19V5M6 11l6-6 6 6"/>', 2.2),
  stop: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>',
  copy: I('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>'),
  up: I('<path d="M7 11v9H4v-9h3zm3 9h7.5a2 2 0 0 0 2-1.6l1.2-6A2 2 0 0 0 18.7 10H14V6a2 2 0 0 0-2-2l-2 7v9z"/>'),
  down: I('<path d="M17 13V4h3v9h-3zm-3-9H6.5a2 2 0 0 0-2 1.6l-1.2 6A2 2 0 0 0 5.3 14H10v4a2 2 0 0 0 2 2l2-7V4z"/>'),
  history: I('<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6"/><path d="M3 4v4h4"/><path d="M12 8v4.5l3 2"/>'),
  help: I('<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01"/>'),
  ext: I('<path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>'),
  theme: I('<path d="M12 3a9 9 0 1 0 9 9c-5 0-9-4-9-9z"/>'),
  sun: I('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  dl: I('<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>'),
  reset: I('<path d="M4 12a8 8 0 1 1 2.3 5.7M4 20v-5h5"/>'),
  plus: I('<path d="M12 5v14M5 12h14"/>', 2),
  clip: I('<path d="M21 11.5l-8.5 8.5a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8"/>'),
  emoji: I('<circle cx="12" cy="12" r="9"/><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01"/>'),
  gif: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3"/><text x="12" y="15.5" text-anchor="middle" font-size="7.5" font-weight="700" fill="currentColor" stroke="none" font-family="system-ui, sans-serif">GIF</text></svg>',
  mic: I('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/>'),
  wave: I('<path d="M4 11.5v1"/><path d="M8 8v8"/><path d="M12 5v14"/><path d="M16 8v8"/><path d="M20 11v2"/>', 2.2),
  hangup: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 9c-2.6 0-5 .5-7.2 1.5-.6.3-.9.9-.8 1.5l.5 2.6c.1.6.7 1 1.3.9l2.8-.6c.5-.1.9-.5 1-1l.3-1.6c.7-.2 1.4-.3 2.1-.3s1.4.1 2.1.3l.3 1.6c.1.5.5.9 1 1l2.8.6c.6.1 1.2-.3 1.3-.9l.5-2.6c.1-.6-.2-1.2-.8-1.5C17 9.5 14.6 9 12 9z"/></svg>',
  micoff: I('<path d="M9 9v5a3 3 0 0 0 5.1 2.1M15 11V6a3 3 0 0 0-6 0M5 11a7 7 0 0 0 11 5.7M19 11a7 7 0 0 1-.6 2.8M12 18v3M9 21h6M4 4l16 16"/>'),
  cc: I('<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10.5 10.5a2 2 0 1 0 0 3M17 10.5a2 2 0 1 0 0 3"/>'),
  chev: I('<path d="M9 6l6 6-6 6"/>', 2.2),
  cal: I('<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>'),
  mail: I('<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 8l9 6 9-6"/>'),
  search: I('<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>'),
  spark: I('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>'),
  check: I('<path d="M5 12.5l4.5 4.5L19 7"/>', 2.2),
  checkc: I('<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.8 2.8L16 10"/>'),
  phone: I('<path d="M5 4h3.5l1.5 4-2 1.5a12 12 0 0 0 6.5 6.5L16 14l4 1.5V19a1 1 0 0 1-1 1A15 15 0 0 1 4 5a1 1 0 0 1 1-1z"/>'),
  layers: I('<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>'),
  compass: I('<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5 5-2z"/>'),
  building: I('<path d="M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16M15 9h4a1 1 0 0 1 1 1v11M3 21h18M8 8h3M8 12h3M8 16h3"/>'),
  target: I('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>'),
  play: I('<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10 9.5v5l4.5-2.5z"/>'),
  user: I('<circle cx="12" cy="8" r="4"/><path d="M4 20c1.5-3.5 4.5-5 8-5s6.5 1.5 8 5"/>'),
  chat: I('<path d="M4 5h16v11H8l-4 4z"/>'),
  clock: I('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  alert: I('<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/>', 2),
  arrowdown: I('<path d="M12 5v14M6 13l6 6 6-6"/>', 2),
  video: I('<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3"/>'),
};

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clean = (t) => String(t || '').replace(/【[^】]*】/g, '').replace(/^\s*\(?sources?\s*:.*$/gim, '').replace(/\n{3,}/g, '\n\n').trim();
const plain = (t) => clean(t).replace(/\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g, '').replace(/\[GIF\]\(\S+\)/g, 'GIF').replace(/\[attached: ([^\]]+)\]\(\S+\)/g, '$1').replace(/\*\*/g, '').replace(/\s+/g, ' ').trim();
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : 'x' + Date.now().toString(16) + Math.random().toString(16).slice(2));
const trunc = (s, n) => (s = String(s || ''), s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s);
function md(text, srcs, api) {
  let t = esc(clean(text));
  t = t.replace(/\[GIF\]\((https?:\/\/[^\s)]+)\)/g, (m, u) => `<img class="gif" src="${u}" alt="GIF">`);
  t = t.replace(/\[attached: ([^\]]+)\]\((\/uploads\/[^\s)]+)\)/g, (m, n, u) => `📎 <a href="${esc(api || '') + u}" target="_blank" rel="noopener">${n}</a>`);
  t = t.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
  t = t.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  t = t.replace(/(^|[^"=])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  t = t.replace(/^#{1,4}\s+(.*)$\n?/gm, '<span class="h">$1</span>');
  t = t.replace(/^(?:[-*•]\s+)(.*)$\n?/gm, '<span class="li">$1</span>');
  t = t.replace(/^(\d{1,2})[.)]\s+(.*)$\n?/gm, '<span class="li num" data-n="$1">$2</span>');
  t = t.replace(/\s?\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g, (m, ids) => ids.split(',').map((x) => { const n = parseInt(x, 10), s = (srcs || []).find((y) => y.n === n);
    return s ? `<a class="cite" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.title || s.url)}">${n}</a>` : `<sup class="cite">${n}</sup>`; }).join(''));
  return t;
}
const citedNumbers = (text) => { const out = new Set(); (String(text).match(/\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g) || []).forEach((m) => m.slice(1, -1).split(',').forEach((x) => out.add(parseInt(x, 10)))); return out; };
const usedSources = (text, items) => { const n = citedNumbers(text); const used = (items || []).filter((s) => n.has(s.n)); return used.length ? used : (items || []).slice(0, 3); };
const relShort = (ts) => { const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000); return s < 60 ? 'just now' : s < 3600 ? Math.floor(s / 60) + 'm' : s < 86400 ? Math.floor(s / 3600) + 'h' : Math.floor(s / 86400) + 'd'; };
const fmtSize = (b) => b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(0) + ' KB' : (b / 1048576).toFixed(1) + ' MB';
const store = { get(k) { try { return sessionStorage.getItem(k); } catch { return null; } }, set(k, v) { try { sessionStorage.setItem(k, v); } catch {} } };
const local = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };
const typeIcon = (s) => { const h = `${s.slug} ${s.name}`.toLowerCase(); return /walkthrough|demo/.test(h) ? SVG.play : /gtm|strategy/.test(h) ? SVG.target : SVG.chat; };
const BK_STEPS = ['type', 'time', 'details', 'review'];
const BK_TITLES = { type: 'Choose a meeting', time: 'Pick a time', details: 'Your details', review: 'Review and confirm' };

class DeepAssistant extends HTMLElement {
  static get observedAttributes() { return ['api', 'token', 'theme', 'mode', 'open', 'title', 'subtitle', 'suggestions', 'user-name', 'user-email', 'tabs', 'shortcut', 'privacy-url', 'greeting', 'page-context']; }
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._history = []; this._transcript = []; this._busy = false; this._controller = null; this._me = null; this._rendered = false; this._wasOpen = false;
    this._view = 'chat'; this._unread = 0; this._attachments = []; this._cfg = { gif: false, stt: 'browser', tts: 'browser', upload_max_mb: 10, upload_types: [] };
    this._voice = null; this._rec = null; this._online = undefined; this._nudged = false;
    this.tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const rm = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null; this._reduced = !!(rm && rm.matches); if (rm && rm.addEventListener) rm.addEventListener('change', (e) => { this._reduced = e.matches; });
    this._coarse = !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
  }
  // ---------------------------------------------------------------- public API
  get api() { return (this.getAttribute('api') || '').replace(/\/+$/, ''); }
  get busy() { return this._busy; }
  get sessionId() { return this._sid; }
  get view() { return this._view; }
  get botName() { return this.getAttribute('title') || 'Deep'; }
  ask(text) { this.showView('chat'); return this._send(text); }
  book(callType) { return this.startBooking(callType || null); }
  open() { this.setAttribute('open', ''); }
  close() { this.removeAttribute('open'); }
  toggle() { this.hasAttribute('open') ? this.close() : this.open(); }
  setToken(token) { if (token) this.setAttribute('token', token); else this.removeAttribute('token'); }
  reset() { this.newChat(); }
  newChat() {
    if (this._busy) this._stop(); this.stopVoice();
    this._sid = uuid(); store.set(this._key('sid'), this._sid);
    this._transcript = []; this._history = []; this._attachments = []; this._nudged = false; this._renderAttachments();
    this._restore(); this._track(); this.showView('chat');
  }
  download() {
    const lines = this._transcript.map((m) => `[${new Date(m.ts).toLocaleString()}] ${m.role === 'user' ? 'You' : this.botName}: ${plain(m.text)}${m.sources && m.sources.length ? '\n  sources: ' + m.sources.map((s) => s.url).join(', ') : ''}`);
    const blob = new Blob([`${this.botName} transcript · ${new Date().toLocaleString()} · conversation ${this._sid}\n\n` + lines.join('\n\n')], { type: 'text/plain' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `deep-chat-${new Date().toISOString().slice(0, 10)}.txt`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  switchTheme() { const next = this._isDark() ? 'light' : 'dark'; this.setAttribute('theme', next); local.set('da_theme', next); this._syncThemeItem(); }
  showView(name) {
    if (name === 'history') name = 'messages';
    if (!['chat', 'messages', 'help'].includes(name) || (name === 'help' && !this._tabs().includes('help'))) return;
    const sh = this.shadowRoot, sub = name !== 'chat', changed = name !== this._view;
    this._view = name; this.$panel.dataset.view = name;
    sh.querySelector('.view-chat').hidden = name !== 'chat'; sh.querySelector('.view-messages').hidden = name !== 'messages'; sh.querySelector('.view-help').hidden = name !== 'help';
    ['.hav', '.brand', '.b-history', '.more'].forEach((s) => { sh.querySelector(s).hidden = sub; });
    this.$back.hidden = !sub; const vt = sh.querySelector('.vtitle'); vt.hidden = !sub; vt.textContent = name === 'messages' ? 'History' : 'Help';
    this._closePops();
    if (name === 'messages') this._renderConversations();
    if (name === 'help') this._renderHelp();
    if (name === 'chat') setTimeout(() => { if (!this._voice) this._focusInput(); }, 30); else if (changed) setTimeout(() => this.$back.focus({ preventScroll: true }), 30);
    this._emit('view', { view: name });
  }
  async openConversation(sid) {
    if (!sid) return;
    if (sid !== this._sid) {
      if (this._busy) this._stop();
      let h = null;
      try { const r = await fetch(this._url('/conversations/' + encodeURIComponent(sid)), { headers: this._headers(false) }); if (r.ok) h = await r.json(); } catch {}
      if (!h) { this._toast("Couldn't open that conversation"); return; }
      this._sid = sid; store.set(this._key('sid'), sid); this._nudged = false;
      this.$log.innerHTML = ''; this._transcript = []; this._history = [];
      (h.messages || []).forEach((m) => {
        const el = this._add(m.role === 'user' ? 'user' : 'bot', '', m.ts);
        if (m.role === 'user') { this._setText(el, m.text); this._transcript.push({ role: 'user', text: m.text, ts: new Date(m.ts).getTime() }); }
        else { const srcs = usedSources(m.text, m.sources || []); this._setText(el, m.text, m.sources || []); this._addSources(el, srcs); this._addTools(el, () => plain(m.text), null, m.id, m.feedback);
          this._transcript.push({ role: 'bot', text: m.text, sources: srcs, ts: new Date(m.ts).getTime(), mid: m.id, fb: m.feedback }); }
      });
      if (!this._transcript.length) this._renderWelcome();
      this._history = this._transcript.map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text })).slice(-12);
      this._persist(); this._markLast();
    }
    this.showView('chat'); this._scroll(true); this._markRead(sid).then(() => this._refreshBadge());
  }
  // ---------------------------------------------------------------- lifecycle
  connectedCallback() { if (!this._rendered) this._render(); }
  disconnectedCallback() { this._bindViewport(false); clearTimeout(this._hT); if (this._onVis) document.removeEventListener('visibilitychange', this._onVis); this._onVis = null; }
  attributeChangedCallback(name) {
    if (!this._rendered) return;
    if (name === 'open') this._applyOpen();
    else if (name === 'mode') { this._applyMode(); this._applyOpen(); }
    else if (name === 'token' || name === 'user-name' || name === 'user-email') this._loadMe().then(() => { this._refreshBadge(); this._refreshWelcome(); });
    else if (name === 'title' || name === 'subtitle') this._applyCopy();
    else if (name === 'api') { this._health(); this._loadConfig(); }
    else if (name === 'tabs') this._applyTabs();
    else if (name === 'privacy-url') this._applyFooter();
    else if (name === 'theme') this._syncThemeItem();
    else if (name === 'suggestions' || name === 'greeting' || name === 'page-context') this._refreshWelcome();
    else if (name === 'shortcut' && this._view === 'help') this._renderHelp();
  }
  _toast(text) { let el = this.shadowRoot.querySelector('.toastmsg'); if (!el) { el = document.createElement('div'); el.className = 'toastmsg'; el.setAttribute('role', 'status'); this.$panel.appendChild(el); } el.textContent = text; el.classList.add('show'); clearTimeout(this._toastT); this._toastT = setTimeout(() => el.classList.remove('show'), 1800); }
  _fbPopover(anchor, submit) {
    this.shadowRoot.querySelectorAll('.fbpop').forEach((p) => p.remove());
    const pop = document.createElement('form'); pop.className = 'fbpop'; pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', 'What was wrong?');
    pop.innerHTML = '<div class="reasons">' + ['Not accurate', 'Not helpful', 'Missing info', 'Other'].map((r) => '<button type="button" class="reason">' + r + '</button>').join('') + '</div><input maxlength="300" placeholder="Tell us more (optional)" aria-label="Details"><div class="fbrow"><button type="button" class="btn ghost sm cancel">Cancel</button><button type="submit" class="btn primary sm">Submit</button></div>';
    let reason = ''; pop.querySelectorAll('.reason').forEach((r) => r.onclick = () => { reason = r.textContent; pop.querySelectorAll('.reason').forEach((x) => x.classList.toggle('on', x === r)); });
    pop.querySelector('.cancel').onclick = () => pop.remove();
    pop.onsubmit = async (e) => { e.preventDefault(); const note = [reason, pop.querySelector('input').value.trim()].filter(Boolean).join(': '); pop.remove(); await submit(note); };
    anchor.closest('.col').appendChild(pop); pop.querySelector('.reason').focus(); this._scroll();
  }
  _emit(name, detail) { this.dispatchEvent(new CustomEvent('deep-assistant:' + name, { detail: detail || {}, bubbles: true, composed: true })); }
  _key(s) { return 'da:' + this.api + ':' + s; }
  _url(p) { return this.api + p; }
  _headers(json = true) { const h = { 'X-Session-Id': this._sid }; if (json) h['Content-Type'] = 'application/json'; if (this._vid) h['X-Visitor-Id'] = this._vid; const t = this.getAttribute('token'); if (t) h['X-Visitor-Token'] = t; return h; }
  _tabs() { const raw = (this.getAttribute('tabs') || ALL_TABS.join(',')).split(',').map((s) => s.trim().toLowerCase()).filter((s) => ALL_TABS.includes(s)); if (!raw.includes('messages')) raw.push('messages'); return ALL_TABS.filter((t) => raw.includes(t)); }
  _shortcut() { const a = this.getAttribute('shortcut'); if (a === '') return null; const [label, href] = (a || DEFAULT_SHORTCUT).split('|'); return href ? { label: label.trim(), href: href.trim() } : null; }
  _isDark() { const t = this.getAttribute('theme'); return t === 'dark' || (t === 'auto' && !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)); }
  _focusInput() { if (this._coarse || this._view !== 'chat') return; try { this.$q.focus({ preventScroll: true }); } catch {} }
  _canListen() { return !!this._speechApi() || (this._cfg.stt === 'server' && !!navigator.mediaDevices && typeof MediaRecorder !== 'undefined'); }
  _render() {
    this._rendered = true; const sh = this.shadowRoot;
    if (!this.hasAttribute('theme')) this.setAttribute('theme', local.get('da_theme') || 'light');
    sh.innerHTML = `<style>${CSS}</style>
<button class="launcher" part="launcher" type="button" aria-label="Open the Deep assistant" aria-expanded="false"><span class="lic lic-open">${SVG.mark}</span><span class="lic lic-close">${SVG.chevdown}</span><span class="ldot" hidden></span><span class="lbadge" hidden></span></button>
<section class="panel" part="panel" data-view="chat" role="dialog" aria-label="Deep assistant">
  <header>
    <button class="hbtn back" type="button" aria-label="Back to chat" title="Back to chat" hidden>${SVG.back}</button>
    <span class="hav" aria-hidden="true">${SVG.mark}</span>
    <div class="brand"><h1 class="ttl"></h1><p><span class="sub"></span><span class="sep" aria-hidden="true">·</span><span class="st"><i aria-hidden="true"></i><span class="stt">Connecting…</span></span></p></div>
    <h2 class="vtitle" hidden></h2>
    <button class="vpill" type="button" aria-label="Return to the voice call" title="Return to the call"><i></i><span>In a call</span></button>
    <button class="hbtn b-history" type="button" aria-label="Conversation history" title="History">${SVG.history}<span class="hbadge" hidden></span></button>
    <button class="hbtn more" type="button" aria-label="More options" title="More" aria-haspopup="menu" aria-expanded="false">${SVG.more}</button>
    <button class="hbtn min" type="button" aria-label="Minimize" title="Minimize">${SVG.minus}</button>
    <button class="hbtn close" type="button" aria-label="Close" title="Close">${SVG.close}</button>
    <div class="menu" role="menu" aria-label="More options">
      <button type="button" role="menuitem" data-act="new">${SVG.plus}<span>New conversation</span></button>
      <button type="button" role="menuitem" data-act="help">${SVG.help}<span>Help &amp; contact</span></button>
      <hr>
      <button type="button" role="menuitem" data-act="download">${SVG.dl}<span>Download transcript</span></button>
      <button type="button" role="menuitem" data-act="theme"><span class="ti"></span><span class="tl"></span></button>
    </div>
  </header>
  <div class="views">
    <section class="view view-chat" aria-label="Chat">
      <div class="log scroll" role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation"></div>
      <div class="composer">
        <button class="jump" type="button" hidden>${SVG.arrowdown}<span>Latest</span></button>
        <div class="pop pop-emoji" role="dialog" aria-label="Emoji"><input class="search" placeholder="Search emoji" aria-label="Search emoji"><div class="egrid"></div></div>
        <div class="pop pop-gif" role="dialog" aria-label="GIFs"><input class="search" placeholder="Search GIFs" aria-label="Search GIFs"><div class="ggrid"></div><div class="empty" hidden></div></div>
        <form class="cbox">
          <div class="attach" hidden></div>
          <div class="rec" aria-live="polite"><i></i><span class="rlabel">Listening…</span><span class="rtime">0:00</span><button type="button" class="cicon rstop" aria-label="Stop dictation" title="Stop">${SVG.stop}</button></div>
          <div class="crow">
            <input type="file" class="file" multiple hidden>
            <div class="plus-wrap">
              <button type="button" class="cicon b-plus" aria-label="Attach a file, emoji or dictation" title="Add" aria-haspopup="menu" aria-expanded="false">${SVG.plus}</button>
              <div class="pmenu" role="menu" aria-label="Add to your message">
                <button type="button" role="menuitem" class="b-clip">${SVG.clip}<span>Attach a file</span></button>
                <button type="button" role="menuitem" class="b-emoji" aria-haspopup="dialog">${SVG.emoji}<span>Emoji</span></button>
                <button type="button" role="menuitem" class="b-gif" aria-haspopup="dialog" hidden>${SVG.gif}<span>GIF</span></button>
                <button type="button" role="menuitem" class="b-mic">${SVG.mic}<span>Dictate</span></button>
              </div>
            </div>
            <label class="vh" for="q">Message Deep</label>
            <textarea id="q" class="q" rows="1" placeholder="Ask anything…" enterkeyhint="send"></textarea>
            <button type="button" class="cicon speak" aria-label="Start a voice conversation with Deep" title="Voice conversation">${SVG.wave}</button>
            <button type="submit" class="send" aria-label="Send" title="Send" disabled><span class="i-send">${SVG.send}</span><span class="i-stop" hidden>${SVG.stop}</span></button>
          </div>
        </form>
      </div>
      <div class="foot">By chatting, you agree to our <a class="privacy" href="#" target="_blank" rel="noopener">Privacy Policy</a></div>
    </section>
    <section class="view view-messages" aria-label="History" hidden>
      <div class="hist scroll">
        <div class="htop">
          <div class="searchbox">${SVG.search}<label class="vh" for="msearch">Search conversations</label><input id="msearch" class="msearch" type="search" placeholder="Search conversations" autocomplete="off"></div>
          <button class="btn primary block newconvo" type="button">${SVG.plus}<span>New conversation</span></button>
        </div>
        <div class="mrows" role="list" aria-label="Conversations"></div>
      </div>
    </section>
    <section class="view view-help" aria-label="Help" hidden><div class="help scroll"></div></section>
  </div>
  <div class="voice" role="dialog" aria-label="Voice conversation">
    <div class="vhead"><b>Deep · Voice</b><span class="live" aria-hidden="true"></span><span class="vtimer" aria-label="Call duration">00:00</span><button type="button" class="hbtn v-min" aria-label="Minimize the call view (the call continues)" title="Back to chat">${SVG.chevdown}</button></div>
    <div class="vbody"><div class="vglow" aria-hidden="true"></div>
      <div class="vorb"><canvas width="440" height="440" aria-hidden="true"></canvas><span class="vmute-badge">muted</span></div>
      <div class="vstatus" aria-live="off">Connecting…</div>
      <div class="vcap" aria-live="off"><div class="cu"></div><div class="ca"></div></div>
    </div>
    <div class="vctl"><button type="button" class="vbtn v-mute" aria-pressed="false" aria-label="Mute microphone"><span class="vi">${SVG.mic}</span><span class="tip">Mute</span></button><button type="button" class="vbtn end v-end" aria-label="End call">${SVG.hangup}<span class="tip">End call</span></button><button type="button" class="vbtn cc v-cc" aria-pressed="true" aria-label="Captions on"><span class="vi">${SVG.cc}</span><span class="tip">Captions</span></button></div>
  </div>
  <div class="vh sr" role="status" aria-live="polite"></div>
</section>`;
    this.$panel = sh.querySelector('.panel'); this.$log = sh.querySelector('.log'); this.$q = sh.querySelector('.q'); this.$send = sh.querySelector('.send'); this.$speak = sh.querySelector('.speak');
    this.$launcher = sh.querySelector('.launcher'); this.$close = sh.querySelector('.close'); this.$min = sh.querySelector('.min'); this.$back = sh.querySelector('.back'); this.$cbox = sh.querySelector('.cbox'); this.$menu = sh.querySelector('.menu'); this.$jump = sh.querySelector('.jump');
    this._sid = store.get(this._key('sid')) || uuid(); store.set(this._key('sid'), this._sid);
    this._vid = local.get('dh_vid') || (local.set('dh_vid', uuid()), local.get('dh_vid'));
    this._applyCopy(); this._applyMode(); this._applyOpen(); this._applyFooter(); this._applyTabs(); this._renderEmoji(''); this._syncThemeItem(); this._applyComposerCaps();
    // header
    this.$launcher.onclick = () => this.toggle(); this.$min.onclick = () => this.close();
    this.$close.onclick = () => { if (this.getAttribute('mode') === 'launcher') { this.stopVoice(); if (this._busy) this._stop(); this.close(); } else { this._emit('close'); this.newChat(); } };
    this.$back.onclick = () => this.showView('chat');
    sh.querySelector('.b-history').onclick = () => this.showView('messages');
    const more = sh.querySelector('.more'); more.onclick = (e) => { e.stopPropagation(); const o = !this.$menu.classList.contains('open'); this._closePops(); this.$menu.classList.toggle('open', o); more.setAttribute('aria-expanded', String(o)); if (o) this.$menu.querySelector('button').focus(); };
    this.$menu.querySelectorAll('button').forEach((b) => b.onclick = () => { this._closePops(); const a = b.dataset.act; if (a === 'theme') this.switchTheme(); else if (a === 'download') this.download(); else if (a === 'help') this.showView('help'); else this.newChat(); });
    this.$menu.addEventListener('keydown', (e) => { const items = [...this.$menu.querySelectorAll('button')]; const i = items.indexOf(sh.activeElement);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus(); }
      else if (e.key === 'Escape' || e.key === 'Tab') { this._closePops(); if (e.key === 'Escape') { e.stopPropagation(); more.focus(); } } });
    sh.addEventListener('click', (e) => { if (!e.composedPath().some((n) => n.classList && (n.classList.contains('menu') || n.classList.contains('more') || n.classList.contains('pop') || n.classList.contains('b-emoji') || n.classList.contains('b-gif') || n.classList.contains('plus-wrap')))) this._closePops(); });
    this.$panel.addEventListener('keydown', (e) => { if (e.key !== 'Escape' || e.defaultPrevented) return;
      if (this.$menu.classList.contains('open') || sh.querySelector('.pop.open, .pmenu.open')) { this._closePops(); return; }
      if (sh.querySelector('.voice.open')) { this._showVoice(false); return; }
      if (this._view !== 'chat') { this.showView('chat'); return; }
      if (this.getAttribute('mode') === 'launcher') this.close(); });
    // history
    sh.querySelector('.newconvo').onclick = () => this.newChat();
    sh.querySelector('.msearch').addEventListener('input', (e) => { this._mquery = e.target.value; this._paintConversations(); });
    // composer
    this.$cbox.addEventListener('submit', (e) => { e.preventDefault(); if (this._busy) this._stop(); else this._send(); });
    this.$q.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!this._busy) this._send(); } if (e.key === 'Escape' && (this._busy || this.shadowRoot.querySelector('.pop.open'))) { e.preventDefault(); if (this._busy) this._stop(); this._closePops(); } });
    this.$q.addEventListener('input', () => { this._autosize(); this._syncSend(); });
    this.$q.addEventListener('focus', () => this.$cbox.classList.add('focus'));
    this.$q.addEventListener('blur', () => this.$cbox.classList.remove('focus'));
    const plus = sh.querySelector('.b-plus'), pmenu = sh.querySelector('.pmenu');
    plus.onclick = (e) => { e.stopPropagation(); const o = !pmenu.classList.contains('open'); this._closePops(); pmenu.classList.toggle('open', o); plus.setAttribute('aria-expanded', String(o)); if (o) pmenu.querySelector('button:not([hidden])').focus(); };
    pmenu.addEventListener('keydown', (e) => { const items = [...pmenu.querySelectorAll('button:not([hidden])')]; const i = items.indexOf(sh.activeElement);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus(); }
      else if (e.key === 'Escape') { e.preventDefault(); this._closePops(); plus.focus(); } });
    this.$jump.onclick = () => this._scroll(true, true);
    this.$log.addEventListener('scroll', () => { if (this._atBottom()) this.$jump.hidden = true; }, { passive: true });
    sh.querySelectorAll('.scroll').forEach((s) => { let t = null; s.addEventListener('scroll', () => { s.classList.add('scrolling'); clearTimeout(t); t = setTimeout(() => s.classList.remove('scrolling'), 700); }, { passive: true }); });
    // attachments: picker + drag and drop
    const file = sh.querySelector('.file'); sh.querySelector('.b-clip').onclick = () => { this._closePops(); file.click(); }; file.onchange = () => { [...file.files].forEach((f) => this._upload(f)); file.value = ''; };
    ['dragenter', 'dragover'].forEach((ev) => this.$panel.addEventListener(ev, (e) => { if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); this.$cbox.classList.add('drop'); } }));
    ['dragleave', 'drop'].forEach((ev) => this.$panel.addEventListener(ev, (e) => { this.$cbox.classList.remove('drop'); if (ev === 'drop' && e.dataTransfer.files.length) { e.preventDefault(); this.showView('chat'); [...e.dataTransfer.files].forEach((f) => this._upload(f)); } }));
    // emoji + gif popovers
    sh.querySelector('.b-emoji').onclick = () => this._togglePop('emoji'); sh.querySelector('.b-gif').onclick = () => this._togglePop('gif');
    sh.querySelector('.pop-emoji .search').addEventListener('input', (e) => this._renderEmoji(e.target.value));
    let gt = null; sh.querySelector('.pop-gif .search').addEventListener('input', (e) => { clearTimeout(gt); gt = setTimeout(() => this._searchGifs(e.target.value), 350); });
    // dictation + voice
    sh.querySelector('.b-mic').onclick = () => { this._closePops(); this._toggleDictation(); this.$q.focus(); }; sh.querySelector('.rstop').onclick = () => this._stopDictation();
    this.$speak.onclick = () => this.startVoice(); sh.querySelector('.v-end').onclick = () => this.stopVoice(); sh.querySelector('.v-mute').onclick = () => this._toggleMute();
    sh.querySelector('.v-min').onclick = () => this._showVoice(false); sh.querySelector('.vpill').onclick = () => this.startVoice(); sh.querySelector('.v-cc').onclick = () => this._toggleCaptions();
    this._onVis = () => { const v = this._voice; if (v && v.orb) { if (document.visibilityState === 'hidden') v.orb.pause(); else if (this.hasAttribute('open') || this.getAttribute('mode') !== 'launcher') v.orb.resume(); } };
    document.addEventListener('visibilitychange', this._onVis);
    this._loadMe().then(() => { this._restore(); this._refreshBadge(); }); this._autosize(); this._syncSend(); this._track(); this._health(); this._loadConfig();
    console.info('deep-assistant v' + VERSION + ' ready (api ' + this.api + ')');
    this._emit('ready', { sessionId: this._sid, version: VERSION });
  }
  _closePops() { const sh = this.shadowRoot; this.$menu.classList.remove('open'); sh.querySelector('.more').setAttribute('aria-expanded', 'false'); sh.querySelectorAll('.pop').forEach((p) => p.classList.remove('open')); sh.querySelectorAll('.b-emoji, .b-gif').forEach((b) => b.classList.remove('on')); sh.querySelector('.pmenu').classList.remove('open'); sh.querySelector('.b-plus').setAttribute('aria-expanded', 'false'); }
  _togglePop(which) { const p = this.shadowRoot.querySelector('.pop-' + which); const o = !p.classList.contains('open'); this._closePops(); p.classList.toggle('open', o); this.shadowRoot.querySelector('.b-' + which).classList.toggle('on', o); if (o) { p.querySelector('.search').focus(); if (which === 'gif' && !p.querySelector('.ggrid').children.length) this._searchGifs(''); } }
  _applyCopy() { const sh = this.shadowRoot; sh.querySelector('.ttl').textContent = this.botName; sh.querySelector('.sub').textContent = this.getAttribute('subtitle') || 'AI assistant'; this.$panel.setAttribute('aria-label', this.botName + ' assistant'); }
  _applyMode() { const launcher = this.getAttribute('mode') === 'launcher'; this.$min.hidden = !launcher; this.$close.hidden = !launcher; this.$panel.setAttribute('role', launcher ? 'dialog' : 'region'); }
  _applyFooter() { const a = this.shadowRoot.querySelector('.privacy'); a.href = this.getAttribute('privacy-url') || this._cfg.privacy_url || 'https://deependhq.com/privacy'; this.shadowRoot.querySelector('.foot').title = 'deep-assistant v' + VERSION + (this._cfg.version ? ' · server ' + this._cfg.version : ''); }
  _applyTabs() { const help = this._tabs().includes('help'); this.$menu.querySelector('[data-act="help"]').hidden = !help; if (!help && this._view === 'help') this.showView('chat'); }
  _syncThemeItem() { const b = this.$menu && this.$menu.querySelector('[data-act="theme"]'); if (!b) return; const dark = this._isDark(); b.querySelector('.ti').outerHTML = `<span class="ti">${dark ? SVG.sun : SVG.theme}</span>`; b.querySelector('.tl').textContent = dark ? 'Light theme' : 'Dark theme'; }
  _applyComposerCaps() { const sh = this.shadowRoot; sh.querySelector('.b-gif').hidden = !this._cfg.gif; const listen = this._canListen(); sh.querySelector('.b-mic').hidden = !listen; this.$speak.dataset.off = listen ? '' : '1'; this._syncSend(); }
  _applyOpen() {
    const launcher = this.getAttribute('mode') === 'launcher', open = this.hasAttribute('open');
    this.$launcher.setAttribute('aria-expanded', String(open)); this.$launcher.setAttribute('aria-label', open ? 'Minimize the assistant' : 'Open the ' + this.botName + ' assistant');
    if (!launcher || open === this._wasOpen) return; this._wasOpen = open;
    this._emit(open ? 'open' : 'close');
    if (open) { this._bindViewport(true); this._health(); setTimeout(() => { if (!this._voice) this._focusInput(); }, 60); this._refreshBadge(); if (this._voice && this._voice.orb) this._voice.orb.resume(); }
    else { this._bindViewport(false); this._closePops(); if (this._voice && this._voice.orb) this._voice.orb.pause(); if (this.shadowRoot.activeElement && this.shadowRoot.activeElement !== this.$launcher) this.$launcher.focus({ preventScroll: true }); }
  }
  _bindViewport(on) {  // phones: size the full-screen panel to the visual viewport so the composer stays above the keyboard
    const vv = window.visualViewport; if (!vv) return;
    if (on && !this._vvH) { this._vvH = () => { this.$panel.style.setProperty('--da-vvh', Math.round(vv.height) + 'px'); this.$panel.style.setProperty('--da-vv-top', Math.round(vv.offsetTop) + 'px'); }; vv.addEventListener('resize', this._vvH); vv.addEventListener('scroll', this._vvH); this._vvH(); }
    else if (!on && this._vvH) { vv.removeEventListener('resize', this._vvH); vv.removeEventListener('scroll', this._vvH); this._vvH = null; }
  }
  async _loadConfig() { if (!this.api) return; try { const r = await fetch(this._url('/widget-config')); if (r.ok) { this._cfg = await r.json(); this._applyFooter(); this._applyComposerCaps(); if (this._view === 'help') this._renderHelp(); } } catch {} }
  _setBusy(on) { this._busy = on; this.shadowRoot.querySelector('.i-send').hidden = on; this.shadowRoot.querySelector('.i-stop').hidden = !on; this.$send.classList.toggle('stop', on); this.$send.setAttribute('aria-label', on ? 'Stop generating' : 'Send'); this.$send.title = on ? 'Stop' : 'Send'; this.$log.setAttribute('aria-busy', String(on)); this._setStatus(on ? 'work' : (this._voice ? 'call' : 'idle')); this._syncSend(); }
  _setStatus(mode) {
    const sh = this.shadowRoot, st = sh.querySelector('.st'); if (!st) return;
    const pending = mode === 'idle' && this._online === undefined, off = mode === 'idle' && this._online === false;
    st.classList.toggle('work', mode === 'work'); st.classList.toggle('call', mode === 'call'); st.classList.toggle('off', pending || off); sh.querySelector('.hav').classList.toggle('work', mode === 'work');
    const t = mode === 'work' ? 'Working…' : mode === 'call' ? 'In a call' : off ? 'Offline' : pending ? 'Connecting…' : 'Online';
    const el = st.querySelector('.stt'); if (el.textContent !== t) { el.textContent = t; if (mode !== 'idle' || off) this._announce('Deep is ' + t.replace('…', '').toLowerCase()); }
    const dot = sh.querySelector('.ldot'); if (dot) dot.hidden = this._online !== true;
  }
  _announce(text) { const sr = this.shadowRoot.querySelector('.sr'); if (!sr) return; clearTimeout(this._srT); this._srT = setTimeout(() => { sr.textContent = ''; sr.textContent = text; }, 60); }
  _syncSend() { const ready = (!!this.$q.value.trim() || this._attachments.some((a) => a.id)) && !this._attachments.some((a) => a.xhr); const typing = !!this.$q.value.trim() || this._attachments.length > 0;
    this.$send.disabled = !this._busy && !ready; this.$speak.hidden = typing || this._busy || this.$speak.dataset.off === '1'; }
  _autosize() { const q = this.$q; q.style.height = 'auto'; q.style.height = Math.max(22, Math.min(q.scrollHeight, 120)) + 'px'; }
  _scroll(force, smooth) { if (!force && !this._stick) { if (this._busy || force === false) this.$jump.hidden = false; return; } const l = this.$log; if (smooth && !this._reduced) l.scrollTo({ top: l.scrollHeight, behavior: 'smooth' }); else l.scrollTop = l.scrollHeight; this.$jump.hidden = true; }
  _reveal(el) {  // scroll the conversation (never the host page) so el is in view
    const l = this.$log, r = el.getBoundingClientRect(), lr = l.getBoundingClientRect(); let d = 0;
    if (r.height > lr.height - 24 || r.top < lr.top) d = r.top - lr.top - 12; else if (r.bottom > lr.bottom) d = r.bottom - lr.bottom + 12;
    if (d) l.scrollTo({ top: l.scrollTop + d, behavior: this._reduced ? 'auto' : 'smooth' });
  }
  _atBottom() { return this.$log.scrollHeight - this.$log.scrollTop - this.$log.clientHeight < 48; }
  async _health() {
    if (!this.api) return; clearTimeout(this._hT);
    try { const r = await fetch(this._url('/healthz'), { cache: 'no-store' }); this._online = r.ok; } catch { this._online = false; }
    this._setStatus(this._busy ? 'work' : (this._voice ? 'call' : 'idle'));
    if (!this._online && this.isConnected) this._hT = setTimeout(() => this._health(), 20000);
  }
  async _loadMe() {
    const hintName = this.getAttribute('user-name'), hintEmail = this.getAttribute('user-email');
    this._me = { signed_in: false, name: hintName, email: hintEmail, verified: false };
    if (this.getAttribute('token') && this.api) { try { const r = await fetch(this._url('/me'), { headers: this._headers(false) }); if (r.ok) this._me = await r.json(); } catch {} }
    if (!this._me.name && hintName) this._me.name = hintName; if (!this._me.email && hintEmail) this._me.email = hintEmail;
  }
  _firstName() { return (this._me && this._me.name) ? String(this._me.name).trim().split(/\s+/)[0] : ''; }
  _track() {
    if (!this.api || store.get(this._key('tracked')) === this._sid) return;
    const body = { session_id: this._sid, visitor_id: this._vid, page: location.href, referrer: document.referrer || null, timezone: this.tz, lang: navigator.language || null, screen: screen && screen.width ? `${screen.width}x${screen.height}` : null };
    fetch(this._url('/track'), { method: 'POST', headers: this._headers(), body: JSON.stringify(body), keepalive: true }).then(() => store.set(this._key('tracked'), this._sid)).catch(() => {});
  }
  // ---------------------------------------------------------------- welcome + page context
  _pageContext() {
    const forced = (this.getAttribute('page-context') || '').trim().toLowerCase(); if (CONTEXT_ACTIONS[forced]) return forced;
    const p = (location.pathname || '').toLowerCase();
    if (/contact|book|schedule|pricing|get-started|request-demo/.test(p)) return 'contact';
    if (/solution|service|use-case|usecase|industr/.test(p)) return 'solutions';
    if (/product|platform|feature/.test(p)) return 'product';
    return 'general';
  }
  _pageTitle() { const t = (document.title || '').split(/\s[|–—-]\s/)[0].trim(); return t && t.length <= 60 ? t : ''; }
  _actions() {
    const a = this.getAttribute('suggestions');
    if (a) return a.split('|').map((s) => s.trim()).filter(Boolean).slice(0, 4).map((label) => (BOOK_RE.test(label) ? { icon: 'cal', label, book: true } : { icon: 'spark', label, ask: label }));
    const title = this._pageTitle();
    return CONTEXT_ACTIONS[this._pageContext()].map((k) => { const x = ACTIONS[k]; return x.askPage ? { ...x, ask: x.askPage(title) } : x; });
  }
  _renderWelcome() {
    const w = document.createElement('div'); w.className = 'welcome'; const first = this._firstName(); const ctx = this.getAttribute('suggestions') ? 'custom' : this._pageContext();
    w.innerHTML = `<div class="wav" aria-hidden="true">${SVG.mark}</div><h2>${esc(first ? `Hi ${first}! I'm Deep 👋` : "Hi! I'm Deep 👋")}</h2><p>${esc(this.getAttribute('greeting') || INTRO)}</p>
      <div class="acts-label">${ctx === 'general' || ctx === 'custom' ? 'Popular ways to start' : 'Suggested for this page'}</div><div class="acts" role="group" aria-label="Suggested actions"></div>`;
    const acts = w.querySelector('.acts');
    this._actions().forEach((x) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'act' + (x.book ? ' book' : ''); b.innerHTML = `<span class="ai">${SVG[x.icon] || SVG.spark}</span><span class="al">${esc(x.label)}</span>${SVG.chev}`; b.onclick = () => this._runAction(x, 'suggestion'); acts.appendChild(b); });
    this.$log.appendChild(w);
  }
  _refreshWelcome() { if (!this._rendered || this._transcript.length) return; const w = this.$log.querySelector('.welcome'); if (w) { w.remove(); this._renderWelcome(); } }
  _runAction(x, source) {
    this._emit('action', { action: source, label: x.label, kind: x.book ? 'booking' : 'question' });
    if (x.book) return this.startBooking(typeof x.book === 'string' ? x.book : null, x.label);
    return this._send(x.ask || x.label);
  }
  // ---------------------------------------------------------------- history + help
  _setBadge(n) { this._unread = n; const b = this.shadowRoot.querySelector('.hbadge'); b.hidden = !n; b.textContent = String(n); this.shadowRoot.querySelector('.b-history').setAttribute('aria-label', n ? `Conversation history, ${n} unread` : 'Conversation history'); const lb = this.shadowRoot.querySelector('.lbadge'); lb.hidden = !n; lb.textContent = String(n); }
  async _conversations() {
    if (!this.api || (!this._vid && !this.getAttribute('token'))) return { items: [], unread_conversations: 0 };
    try { const r = await fetch(this._url('/conversations'), { headers: this._headers(false) }); return r.ok ? await r.json() : { items: [], unread_conversations: 0, error: true }; } catch { return { items: [], unread_conversations: 0, error: true }; }
  }
  async _refreshBadge() { const d = await this._conversations(); if (!d.error) this._setBadge(d.unread_conversations || 0); return d; }
  async _markRead(sid) { try { await fetch(this._url('/conversations/' + encodeURIComponent(sid) + '/read'), { method: 'POST', headers: this._headers() }); } catch {} }
  async _renderConversations() {
    const rows = this.shadowRoot.querySelector('.mrows'); rows.setAttribute('aria-busy', 'true');
    if (!this._convos) rows.innerHTML = '<div class="sk"><span class="a"></span><span class="l"><i></i><i></i></span></div>'.repeat(4);
    const d = await this._refreshBadge(); rows.setAttribute('aria-busy', 'false');
    this._convErr = !!d.error; if (!d.error || !this._convos) this._convos = d.items || []; this._paintConversations();
  }
  _group(ts) { const d = new Date(ts), now = new Date(); const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime(); const diff = Math.round((day(now) - day(d)) / 86400000);
    return diff <= 0 ? 'Today' : diff === 1 ? 'Yesterday' : diff <= 7 ? 'Previous 7 days' : 'Older'; }
  _paintConversations() {
    const sh = this.shadowRoot, rows = sh.querySelector('.mrows'); const q = (this._mquery || '').trim().toLowerCase(); const all = this._convos || [];
    const items = all.filter((c) => !q || (c.title || '').toLowerCase().includes(q) || plain(c.preview).toLowerCase().includes(q));
    sh.querySelector('.searchbox').hidden = !all.length;
    if (!all.length && this._convErr) { rows.innerHTML = `<div class="empty"><span class="ei">${SVG.alert}</span><b>Couldn't load your conversations</b>Check your connection and try again.<button class="btn" type="button">${SVG.reset}<span>Try again</span></button></div>`; rows.querySelector('.btn').onclick = () => this._renderConversations(); return; }
    if (!all.length) { rows.innerHTML = `<div class="empty"><span class="ei">${SVG.chat}</span><b>No conversations yet</b>Your chats with Deep will appear here, so you can pick them up later.</div>`; return; }
    if (!items.length) { rows.innerHTML = `<div class="empty"><span class="ei">${SVG.search}</span><b>No matches</b>No conversations match “${esc(this._mquery.trim())}”.</div>`; return; }
    let html = '', last = null;
    for (const c of items) {
      const g = this._group(c.last_ts); if (g !== last) { html += `<div class="mgroup" role="presentation">${g}</div>`; last = g; }
      const cur = c.session_id === this._sid;
      html += `<button class="convo${c.unread ? ' unread' : ''}${cur ? ' cur' : ''}" type="button" role="listitem" data-sid="${esc(c.session_id)}" aria-label="${esc(c.title)}${cur ? ', current conversation' : ''}${c.unread ? ', unread' : ''}">
        <span class="avatar" aria-hidden="true">${c.handovers ? SVG.user : SVG.mark}</span>
        <span class="c"><span class="n" title="${esc(c.title)}">${esc(c.title)}</span><span class="p">${esc(plain(c.preview) || '…')}</span></span>
        <span class="r">${cur ? '<span class="cur-tag">Current</span>' : `<span class="ctime">${relShort(c.last_ts).replace('just now', 'now')}</span>`}${c.unread ? '<span class="dot" aria-hidden="true"></span>' : ''}</span>
        <span class="more2" role="button" tabindex="0" aria-label="Rename conversation" title="Rename">${SVG.more}</span></button>`;
    }
    rows.innerHTML = html;
    rows.querySelectorAll('.convo').forEach((b) => {
      b.onclick = (e) => { if (e.target.closest('.more2')) { this._renameRow(b); return; } this.openConversation(b.dataset.sid); };
      b.querySelector('.more2').addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); this._renameRow(b); } });
      let t = null; b.addEventListener('pointerdown', (e) => { if (e.pointerType === 'touch') t = setTimeout(() => { t = null; this._renameRow(b); }, 600); });
      ['pointerup', 'pointerleave', 'pointercancel'].forEach((ev) => b.addEventListener(ev, () => { if (t) { clearTimeout(t); t = null; } }));
    });
  }
  _renameRow(btn) {
    const sid = btn.dataset.sid, c = (this._convos || []).find((x) => x.session_id === sid); if (!c || btn.nextElementSibling?.classList.contains('rename')) return;
    const f = document.createElement('form'); f.className = 'rename'; f.innerHTML = `<input class="inp" maxlength="80" aria-label="Conversation title"><button type="submit" class="btn primary sm">Save</button><button type="button" class="btn ghost sm cancel">Cancel</button>`;
    const input = f.querySelector('input'); input.value = c.title || ''; btn.insertAdjacentElement('afterend', f); input.focus(); input.select();
    f.querySelector('.cancel').onclick = () => { f.remove(); btn.focus(); }; input.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); f.remove(); btn.focus(); } });
    f.onsubmit = async (e) => { e.preventDefault(); const title = input.value.trim(); if (!title) return; let ok = false;
      try { const r = await fetch(this._url('/conversations/' + encodeURIComponent(sid)), { method: 'PATCH', headers: this._headers(), body: JSON.stringify({ title }) }); if (r.ok) { const d = await r.json(); c.title = d.title; c.title_source = 'user'; ok = true; } } catch {}
      this._toast(ok ? 'Renamed' : "Couldn't rename it. Try again."); f.remove(); this._paintConversations(); };
  }
  _renderHelp() {
    const h = this.shadowRoot.querySelector('.help'); const sc = this._shortcut(); const listen = this._canListen();
    const common = ((this._cfg && Array.isArray(this._cfg.suggestions)) ? this._cfg.suggestions : []).filter((s) => s && !BOOK_RE.test(s));
    const qs = (common.length ? common : [ACTIONS.explore.ask, ACTIONS.about.ask, ACTIONS.usecases.ask]).slice(0, 5);
    const item = (cls, icon, label, small, tail) => `<span class="ai">${icon}</span><span class="al">${label}<small>${small}</small></span>${tail || SVG.chev}`;
    h.innerHTML = `<h3>Get in touch</h3><div class="acts">
        <button class="act book h-book" type="button">${item('', SVG.cal, 'Book a meeting', 'Pick a time that suits you, right here')}</button>
        <button class="act h-human" type="button">${item('', SVG.user, 'Talk to a person', 'Leave a message, the team replies by email')}</button>
        ${listen ? `<button class="act h-voice" type="button">${item('', SVG.wave, 'Voice conversation', 'Talk with Deep hands-free')}</button>` : ''}
        ${sc ? `<a class="act" href="${esc(sc.href)}" target="_blank" rel="noopener">${item('', SVG.video, esc(sc.label), esc(host(sc.href)) + ' · opens in a new tab', SVG.ext)}</a>` : ''}
      </div>
      <h3>What Deep can do</h3><ul class="caplist">
        <li>${SVG.checkc}<span>Answer questions about LakeB2B, with links to the pages it used</span></li>
        <li>${SVG.checkc}<span>Book a meeting with live availability, without leaving this chat</span></li>
        <li>${SVG.checkc}<span>Pass your question to the team when it can't answer confidently</span></li>
        <li>${SVG.checkc}<span>Keep your conversations in History so you can pick them up later</span></li>
      </ul>
      <h3>Common questions</h3><div class="chips"></div>
      <p class="hfoot">Deep is an AI assistant and can make mistakes. <a href="${esc(this.shadowRoot.querySelector('.privacy').href)}" target="_blank" rel="noopener">Privacy policy</a></p>`;
    h.querySelector('.h-book').onclick = () => { this._emit('action', { action: 'help', label: 'Book a meeting', kind: 'booking' }); this.startBooking(); };
    h.querySelector('.h-human').onclick = () => { this._emit('action', { action: 'handover_requested', label: 'Talk to a person' }); this._send('Can I talk to a real person?'); };
    const hv = h.querySelector('.h-voice'); if (hv) hv.onclick = () => this.startVoice();
    const chips = h.querySelector('.chips'); qs.forEach((x) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'chip'; b.textContent = x; b.onclick = () => { this._emit('action', { action: 'help_question', label: x, kind: 'question' }); this._send(x); }; chips.appendChild(b); });
  }
  // ---------------------------------------------------------------- rendering
  _add(role, text, ts) {
    const stick = role === 'user' || this._atBottom();
    const w = this.$log.querySelector('.welcome'); if (w) w.remove();
    const row = document.createElement('div'); row.className = 'row ' + role; row.dataset.role = role; row.dataset.ts = String(ts || Date.now());
    if (role === 'bot') row.insertAdjacentHTML('beforeend', `<span class="bav" aria-hidden="true">${SVG.mark}</span>`);
    const col = document.createElement('div'); col.className = 'col';
    const d = document.createElement('div'); d.className = 'msg'; d.textContent = text; col.appendChild(d);
    const meta = document.createElement('div'); meta.className = 'meta'; const when = relShort(ts || Date.now());
    meta.innerHTML = role === 'bot' ? `<span class="vh">${esc(this.botName)} said, </span>${esc(this.botName)} · ${when}` : `<span class="vh">You said, </span>${when}`; col.appendChild(meta);
    row.appendChild(col); this.$log.appendChild(row); this._stick = stick; this._scroll(); return d;
  }
  _markLast() { this.$log.querySelectorAll('.row.last').forEach((r) => r.classList.remove('last')); const rows = this.$log.querySelectorAll('.row.bot'); if (rows.length) rows[rows.length - 1].classList.add('last'); }
  _activity(bot) {  // the agent at work: skeleton bubble + a status pill fed by real 'status' events; collapses into "Worked for …"
    const col = bot.parentElement; bot.classList.add('skel'); bot.innerHTML = '<div class="ln"></div><div class="ln"></div><div class="ln"></div>';
    const a = document.createElement('div'); a.className = 'activity'; a.setAttribute('aria-hidden', 'true'); a.innerHTML = '<span class="spin"></span><span class="lbl">Thinking…</span>'; col.insertBefore(a, bot);
    const act = { el: a, t0: performance.now(), steps: [], label: a.querySelector('.lbl'), last: 'Thinking…' };
    act.set = (step, label) => { act.label.textContent = label; act.last = label; act.steps.push({ step, label, at: performance.now() - act.t0 }); this._announce(label); };
    act.done = (sourcesN) => { const ms = performance.now() - act.t0; a.remove(); bot.classList.remove('skel');
      if (!act.steps.length || ms < 400) return;
      const w = document.createElement('button'); w.type = 'button'; w.className = 'worked'; const secs = ms < 950 ? (ms / 1000).toFixed(1) + 's' : Math.round(ms / 1000) + 's';
      w.innerHTML = `${SVG.chev}<span>Worked for ${secs}${sourcesN ? ' · ' + sourcesN + ' source' + (sourcesN === 1 ? '' : 's') : ''}</span>`; w.setAttribute('aria-expanded', 'false');
      const st = document.createElement('div'); st.className = 'steps'; st.innerHTML = act.steps.map((x) => `<div><b>${(x.at / 1000).toFixed(1)}s</b><span>${esc(x.label.replace(/…$/, ''))}</span></div>`).join('') + `<div><b>${secs}</b><span>Done</span></div>`;
      w.onclick = () => { const o = !st.classList.contains('open'); st.classList.toggle('open', o); w.classList.toggle('open', o); w.setAttribute('aria-expanded', String(o)); };
      col.insertBefore(w, bot); col.insertBefore(st, bot); };
    return act;
  }
  _setText(el, text, srcs) {
    el.classList.remove('skel'); const extras = Array.from(el.querySelectorAll(':scope > div:not(.ln), :scope > form'));
    el.innerHTML = md(text, srcs, this.api); extras.forEach((x) => el.appendChild(x)); el.dataset.raw = plain(text);
  }
  _addSources(el, items) {
    if (!items || !items.length) return; const s = document.createElement('div'); s.className = 'sources';
    s.innerHTML = '<span class="lbl">Sources</span><div class="srcs">' + items.map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener" title="${esc(x.title || x.url)}"><b>${x.n}</b><span class="t">${esc(trunc(x.title || x.url, 28))}</span><span class="hh">${esc(host(x.url))}</span></a>`).join('') + '</div>';
    el.parentElement.appendChild(s);
  }
  async _rate(mid, rating, note) { try { const r = await fetch(this._url('/feedback'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ message_id: mid, rating, note: note || null }) }); const ok = r.ok && (await r.json()).ok; if (ok) this._emit('feedback', { messageId: mid, rating, note: note || null }); else this._toast("Couldn't send feedback"); return ok; } catch { this._toast("Couldn't send feedback"); return false; } }
  _addTools(el, raw, retryText, mid, fb) {
    const col = el.parentElement, t = document.createElement('div'); t.className = 'tools';
    const tool = (label, icon, cls) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'tool ' + (cls || ''); b.setAttribute('aria-label', label); b.title = label; b.innerHTML = icon; return b; };
    if (mid) {
      const mark = (rating) => { t.querySelectorAll('.thumb').forEach((x) => { const on = x.classList.contains(rating === 1 ? 'up' : 'down'); x.classList.toggle('on', on); x.setAttribute('aria-pressed', String(on)); }); const tr = this._transcript.find((m) => m.mid === mid); if (tr) { tr.fb = rating; this._persist(); } this._toast('Thanks for the feedback'); };
      const mk = (rating, label, icon) => { const b = tool(label, icon, 'thumb ' + (rating === 1 ? 'up' : 'down') + (fb === rating ? ' on' : '')); b.setAttribute('aria-pressed', String(fb === rating));
        b.onclick = async () => { if (rating === 1) { if (await this._rate(mid, 1)) mark(1); return; } this._fbPopover(b, async (reason) => { if (await this._rate(mid, -1, reason)) mark(-1); }); };
        return b; };
      t.appendChild(mk(1, 'Helpful', SVG.up)); t.appendChild(mk(-1, 'Not helpful', SVG.down));
    }
    if (raw() && !retryText) {
      const copy = tool('Copy answer', SVG.copy);
      copy.onclick = async () => { let ok = true; try { await navigator.clipboard.writeText(raw()); } catch { ok = false; } const tip = document.createElement('span'); tip.className = 'tip'; tip.textContent = ok ? 'Copied' : 'Copy failed'; copy.appendChild(tip); t.classList.add('keep'); this._announce(tip.textContent); setTimeout(() => { tip.remove(); t.classList.remove('keep'); }, 1200); };
      t.appendChild(copy);
    }
    if (retryText) { const r = tool('Try again', SVG.reset); r.onclick = () => this._retry(el, retryText); t.appendChild(r); }
    if (t.children.length) col.appendChild(t);
  }
  _retry(bot, text) {
    const row = bot.closest('.row'); const u = row.previousElementSibling; row.remove(); if (u && u.dataset.role === 'user') u.remove();
    this._history = this._history.slice(0, -2); this._transcript = this._transcript.slice(0, -2); this._persist(); this._send(text);
  }
  _clearFollowups() { this.$log.querySelectorAll('.followups').forEach((f) => f.remove()); }
  _followups(bot, items) {  // contextual next steps under one answer; never generic, never more than two
    if (!items.length) return; const f = document.createElement('div'); f.className = 'followups'; f.setAttribute('role', 'group'); f.setAttribute('aria-label', 'Suggested next steps');
    items.slice(0, 2).forEach((x) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'fu'; b.innerHTML = `${SVG[x.icon] || SVG.spark}<span>${esc(x.label)}</span>`;
      b.onclick = () => { this._emit('action', { action: 'followup', label: x.label, kind: x.kind || 'question' }); f.remove(); x.fn(); }; f.appendChild(b); });
    bot.parentElement.appendChild(f); this._scroll();
  }
  _answerFollowups(bot, question, answer, nSources) {
    if (this._nudged || !answer || !nSources) return [];
    const t = (question + ' ' + answer).toLowerCase(); let item = null;
    if (/\b(pric(e|ing)|cost|quote|demo|trial|walkthrough|how (does|do) (it|this|that) work)\b/.test(t)) item = { icon: 'play', label: 'See it in a walkthrough', kind: 'booking', fn: () => this.startBooking('walkthrough', 'Book a product walkthrough') };
    else if (/\b(data|solution|platform|product|intent|leads?|campaigns?|gtm|go-to-market|abm|prospect)/.test(t) && this._transcript.filter((m) => m.role === 'user').length >= 2) item = { icon: 'user', label: 'Talk to an expert', kind: 'booking', fn: () => this.startBooking(null, 'Talk to an expert') };
    if (item) this._nudged = true;
    return item ? [item] : [];
  }
  _persist() { store.set(this._key('tx:' + this._sid), JSON.stringify(this._transcript.slice(-40))); }
  _restore() {
    try { this._transcript = JSON.parse(store.get(this._key('tx:' + this._sid)) || '[]'); } catch { this._transcript = []; }
    this.$log.innerHTML = '';
    if (!this._transcript.length) { this._history = []; this._renderWelcome(); this.$log.scrollTop = 0; return; }
    this._transcript.forEach((m) => { const el = this._add(m.role === 'user' ? 'user' : 'bot', '', m.ts); this._setText(el, m.text, m.sources); if (m.role === 'bot') { if (m.err) el.classList.add('err'); this._addSources(el, m.sources); this._addTools(el, () => plain(m.text), null, m.mid, m.fb); } });
    this._history = this._transcript.map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text })).slice(-12);
    this._markLast(); this._scroll(true);
  }
  // ---------------------------------------------------------------- in-chat booking (docs/BOOKING.md)
  // One card per bot message walks through type -> time -> details -> review -> done. The state lives on the card, so
  // going back keeps every choice; nothing is booked until POST /booking/confirm answers "confirmed" / "pending_zoom".
  async startBooking(prefer, label) {
    if (this._busy) return; this.showView('chat'); this._clearFollowups();
    const text = label || 'Book a meeting', intro = 'Happy to set that up. Pick the meeting that fits best and I\'ll show you the open times.';
    const user = this._add('user', '', Date.now()); this._setText(user, text);
    const bot = this._add('bot', '', Date.now()); this._setText(bot, intro);
    this._transcript.push({ role: 'user', text, ts: Date.now() }, { role: 'bot', text: intro, ts: Date.now() });
    this._history.push({ role: 'user', content: text }, { role: 'assistant', content: intro }); this._history = this._history.slice(-12); this._persist(); this._markLast();
    this._emit('booking', { status: 'started', schedule: prefer || null });
    const f = this._bkFlow(bot); f.prefer = prefer || null; this._bkRender(f); this._bkLoadTypes(f);
  }
  _bkFlow(el) {
    if (el._bk && el.contains(el._bk.card)) return el._bk;
    el.querySelectorAll(':scope > .ln').forEach((x) => x.remove()); el.classList.add('hascard'); el.closest('.row').classList.add('wide');
    const card = document.createElement('div'); card.className = 'bk card avail'; card.setAttribute('role', 'group'); card.setAttribute('aria-label', 'Book a meeting'); el.appendChild(card);
    const f = { el, card, step: 'type', types: null, schedule: null, avail: null, day: null, slot: null, who: null, prefill: {}, prefer: null, notice: null, alts: null };
    el._bk = f; return f;
  }
  _bkGo(f, step, focus = true) { f.step = step; this._bkRender(f, focus); }
  _bkRender(f, focus) {
    const c = f.card, i = BK_STEPS.indexOf(f.step); c.innerHTML = '';
    if (f.step !== 'done') {
      const head = document.createElement('div'); head.className = 'bk-head';
      head.innerHTML = `${i > 0 ? `<button type="button" class="bk-back" aria-label="Back to ${BK_TITLES[BK_STEPS[i - 1]].toLowerCase()}" title="Back">${SVG.back}</button>` : ''}<div class="bk-t"><b tabindex="-1">${BK_TITLES[f.step]}</b><span>Step ${i + 1} of 4</span></div>`;
      const back = head.querySelector('.bk-back'); if (back) back.onclick = () => { f.notice = null; this._bkGo(f, BK_STEPS[i - 1]); if (BK_STEPS[i - 1] === 'type' && !f.types) this._bkLoadTypes(f); if (BK_STEPS[i - 1] === 'time' && !f.avail) this._bkLoadAvail(f); };
      c.appendChild(head); c.insertAdjacentHTML('beforeend', `<div class="bk-prog" aria-hidden="true">${BK_STEPS.map((s, j) => `<i class="${j <= i ? 'on' : ''}"></i>`).join('')}</div>`);
    }
    if (f.notice) c.insertAdjacentHTML('beforeend', `<div class="banner" role="alert">${SVG.alert}<span>${esc(f.notice)}</span></div>`);
    const body = document.createElement('div'); body.className = 'bk'; c.appendChild(body);
    ({ type: () => this._bkType(f, body), time: () => this._bkTime(f, body), details: () => this._bkDetails(f, body), review: () => this._bkReview(f, body), done: () => this._bkDone(f, body) })[f.step]();
    if (focus) { const t = c.querySelector('.bk-t b, .bk-ok'); if (t) { t.setAttribute('tabindex', '-1'); t.focus({ preventScroll: true }); } }
    requestAnimationFrame(() => this._reveal(c));
  }
  async _bkLoadTypes(f) {
    if (f.loadingTypes) return; f.loadingTypes = true; let d = null;
    try { const r = await fetch(this._url(`/booking/availability?schedule=&tz=${encodeURIComponent(this.tz)}`), { headers: this._headers(false) }); if (r.ok) d = await r.json(); } catch {}
    f.loadingTypes = false;
    const choices = d && Array.isArray(d.choices) ? d.choices : null;
    if (choices && choices.length) { const by = Object.fromEntries(choices.map((x) => [x.slug, x])); f.types = f.types ? f.types.map((x) => ({ ...by[x.slug], ...x, description: x.description || (by[x.slug] || {}).description })) : choices; f.typesError = null; }
    else if (!f.types) { f.types = []; f.typesError = (d && d.message && d.error !== 'unknown_schedule') ? d.message : "Meeting types couldn't be loaded right now."; f.fallback = (d && d.fallback_link) || null; }
    if (f.step === 'type') this._bkRender(f, false);
  }
  _bkType(f, body) {
    if (!f.types) { body.innerHTML = '<div class="ctypes">' + '<div class="sk"><span class="a"></span><span class="l"><i></i><i></i></span></div>'.repeat(3) + '</div>'; return; }
    if (!f.types.length) {
      body.innerHTML = `<div class="banner">${SVG.alert}<span>${esc(f.typesError || 'No meeting types are available right now.')}</span></div><div class="hrow"><button type="button" class="btn retry">${SVG.reset}<span>Try again</span></button>${f.fallback ? `<a class="btn" href="${esc(f.fallback)}" target="_blank" rel="noopener">Open the scheduler ${SVG.ext}</a>` : ''}</div>`;
      body.querySelector('.retry').onclick = () => { f.types = null; this._bkRender(f, false); this._bkLoadTypes(f); }; return;
    }
    const list = document.createElement('div'); list.className = 'ctypes'; list.setAttribute('role', 'list');
    const pref = f.prefer ? f.types.find((x) => `${x.slug} ${x.name}`.toLowerCase().includes(f.prefer.toLowerCase())) : null;
    f.types.forEach((c) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'ctype' + (f.schedule && f.schedule.slug === c.slug ? ' on' : ''); b.setAttribute('role', 'listitem');
      b.innerHTML = `<span class="ci">${typeIcon(c)}</span><span class="cx"><b>${esc(c.name)}${pref === c ? '<span class="tag">Suggested</span>' : ''}</b>${c.description ? `<span class="cd">${esc(c.description)}</span>` : ''}<span class="cm">${SVG.clock}${c.duration_min} min · Zoom video call</span></span>`;
      b.onclick = () => { const same = f.schedule && f.schedule.slug === c.slug; f.schedule = { ...c }; if (!same) { f.avail = null; f.day = null; f.slot = null; f.alts = null; } f.notice = null; this._bkGo(f, 'time'); if (!f.avail) this._bkLoadAvail(f); this._emit('action', { action: 'booking_type', label: c.name, kind: 'booking' }); };
      list.appendChild(b); });
    body.appendChild(list);
  }
  async _bkLoadAvail(f, prefer) {
    if (!f.schedule || !f.schedule.slug) { this._bkGo(f, 'type', false); if (!f.types) this._bkLoadTypes(f); return; }
    const seq = (f.seq = (f.seq || 0) + 1); f.avail = null; if (f.step === 'time') this._bkRender(f, false);
    let d = { ok: false, message: "Availability couldn't be loaded right now." };
    try { const r = await fetch(this._url(`/booking/availability?schedule=${encodeURIComponent(f.schedule.slug)}&tz=${encodeURIComponent(this.tz)}`), { headers: this._headers(false) }); if (r.ok) d = await r.json(); else if (r.status === 429) d = { ok: false, message: 'Too many requests. Please wait a moment and try again.' }; } catch {}
    if (seq !== f.seq) return;
    this._bkSetAvail(f, d, prefer); if (f.step === 'time' || f.step === 'type') this._bkRender(f, false);
  }
  _bkSetAvail(f, d, prefer) {
    f.avail = d; if (d.ok && d.schedule) f.schedule = { ...(f.schedule || {}), ...d.schedule };
    if (!d.ok) { if (d.error === 'unknown_schedule' && d.choices) { f.types = d.choices; f.step = 'type'; } return; }
    const days = d.days || []; const want = prefer || (f.slot && f.slot.start_iso);
    const pre = want && days.find((x) => x.slots.some((s) => s.start_iso === want && s.available));
    if (pre) f.day = pre.date; else if (!f.day || !days.some((x) => x.date === f.day && x.open)) { const first = days.find((x) => x.open); f.day = first ? first.date : null; }
  }
  _bkTime(f, body) {
    const s = f.schedule || {};
    body.insertAdjacentHTML('beforeend', `<div class="ahead"><b>${esc(s.name || 'Meeting')}</b><span>${s.duration_min ? s.duration_min + ' min · ' : ''}Zoom video call${s.description ? ' · ' + esc(s.description) : ''}</span></div>`);
    const d = f.avail;
    if (!d) { body.insertAdjacentHTML('beforeend', '<div class="sk" style="padding:0"><span class="l"><i></i><i></i></span></div><p class="note" role="status">Loading open times…</p>'); return; }
    if (!d.ok) {
      body.insertAdjacentHTML('beforeend', `<div class="banner">${SVG.alert}<span>${esc(d.message || "Availability couldn't be loaded right now.")}</span></div><div class="hrow"><button type="button" class="btn retry">${SVG.reset}<span>Try again</span></button>${d.fallback_link ? `<a class="btn" href="${esc(d.fallback_link)}" target="_blank" rel="noopener">Open the scheduler ${SVG.ext}</a>` : ''}</div>`);
      body.querySelector('.retry').onclick = () => this._bkLoadAvail(f); return;
    }
    const pick = (sl) => { f.slot = sl; f.notice = null; this._bkGo(f, 'details'); this._emit('action', { action: 'booking_time', label: sl.label_visitor, kind: 'booking' }); };
    if (f.alts && f.alts.length) {
      const alt = document.createElement('div'); alt.innerHTML = `<p class="note" style="margin-bottom:6px">Nearest open times</p>`; const row = document.createElement('div'); row.className = 'hrow';
      f.alts.forEach((sl) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'btn sm'; b.textContent = sl.label_visitor; b.onclick = () => pick(sl); row.appendChild(b); }); alt.appendChild(row); body.appendChild(alt);
    }
    const days = d.days || []; const open = days.filter((x) => x.open);
    if (!open.length) {
      body.insertAdjacentHTML('beforeend', `<div class="banner info">${SVG.cal}<span>No open times in the next ${days.length || 14} days.</span></div>${d.fallback_link ? `<div class="hrow"><a class="btn" href="${esc(d.fallback_link)}" target="_blank" rel="noopener">Open the scheduler ${SVG.ext}</a></div>` : ''}`); return;
    }
    const dates = document.createElement('div'); dates.className = 'dates scroll'; dates.setAttribute('role', 'listbox'); dates.setAttribute('aria-label', 'Dates');
    const times = document.createElement('div'); times.className = 'times'; times.setAttribute('role', 'group'); times.setAttribute('aria-label', 'Open times');
    const show = (day, user) => { f.day = day.date; times.innerHTML = '';
      dates.querySelectorAll('.date').forEach((x) => { const on = x.dataset.date === day.date; x.classList.toggle('on', on); x.setAttribute('aria-selected', String(on)); });
      const avail = day.slots.filter((x) => x.available);
      avail.forEach((sl) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'time' + (f.slot && f.slot.start_iso === sl.start_iso ? ' on' : ''); b.dataset.start = sl.start_iso; b.textContent = sl.time; b.setAttribute('aria-label', `${day.label}, ${sl.time}`); b.onclick = () => pick(sl); times.appendChild(b); });
      if (!avail.length) times.innerHTML = '<p class="note">No open times on this day.</p>';
      if (user) this._announce(`${avail.length} open time${avail.length === 1 ? '' : 's'} on ${day.label}`); };
    days.forEach((day) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'date' + (day.open ? '' : ' off'); b.dataset.date = day.date; b.setAttribute('role', 'option');
      b.innerHTML = `<b>${esc(day.label)}</b><small>${day.open ? day.open + ' open' : 'Full'}</small>`;
      if (day.open) b.onclick = () => show(day, true); else { b.disabled = true; b.setAttribute('aria-label', day.label + ', no open times'); }
      dates.appendChild(b); });
    body.append(dates, times); body.insertAdjacentHTML('beforeend', `<p class="note">Times shown in ${esc(d.timezone || this.tz)}</p>`);
    show(days.find((x) => x.date === f.day && x.open) || open[0]);
    requestAnimationFrame(() => { const on = dates.querySelector('.date.on'); if (on) dates.scrollLeft = Math.max(0, on.offsetLeft - dates.offsetLeft - 8); });
  }
  _bkDetails(f, body) {
    const me = this._me || {}; const known = !!(me.signed_in && me.verified && me.email); const p = f.prefill || {}; const w = f.who || {};
    body.innerHTML = `<div class="pickd">${SVG.cal}<span><b>${esc(f.slot.label_visitor)}</b><br>${esc((f.schedule || {}).name || '')}</span><button type="button" class="linkbtn chg">Change</button></div>
      <form class="bform" novalidate>
        ${known ? `<p class="note">Booking as <b>${esc(me.name || me.email)}</b> · ${esc(me.email)}</p>` : `
        <div class="field"><label for="bk-name">Full name</label><input class="inp" id="bk-name" name="name" maxlength="120" required autocomplete="name"><span class="ferr" hidden></span></div>
        <div class="field"><label for="bk-email">Work email</label><input class="inp" id="bk-email" name="email" type="email" maxlength="200" required autocomplete="email" inputmode="email"><span class="ferr" hidden></span></div>`}
        <div class="field"><label for="bk-company">Company <span>(optional)</span></label><input class="inp" id="bk-company" name="company" maxlength="120" autocomplete="organization"></div>
        <div class="field"><label for="bk-notes">What would you like to discuss? <span>(optional)</span></label><textarea class="inp" id="bk-notes" name="notes" rows="2" maxlength="1000"></textarea></div>
        <button class="btn primary block" type="submit">Continue ${SVG.chev}</button>
      </form>`;
    const form = body.querySelector('form'), field = (n) => form.elements[n];
    if (!known) { field('name').value = w.name ?? p.name ?? me.name ?? ''; field('email').value = w.email ?? p.email ?? me.email ?? ''; }
    field('company').value = w.company ?? p.company ?? ''; field('notes').value = w.notes ?? p.reason ?? p.notes ?? '';
    const read = () => ({ name: known ? (me.name || '') : field('name').value.trim(), email: known ? me.email : field('email').value.trim(), company: field('company').value.trim(), notes: field('notes').value.trim() });
    form.addEventListener('input', () => { f.who = read(); });
    body.querySelector('.chg').onclick = () => { f.who = read(); this._bkGo(f, 'time'); if (!f.avail) this._bkLoadAvail(f); };
    form.onsubmit = (e) => { e.preventDefault(); const who = read(); f.who = who; let bad = null;
      const err = (n, msg) => { const el = field(n); if (!el) return; const fe = el.parentElement.querySelector('.ferr'); el.setAttribute('aria-invalid', String(!!msg)); fe.hidden = !msg; fe.textContent = msg || ''; if (msg) { fe.id = 'e-' + n; el.setAttribute('aria-describedby', fe.id); if (!bad) bad = el; } else el.removeAttribute('aria-describedby'); };
      if (!known) { err('name', who.name.length < 2 ? 'Please enter your name.' : null); err('email', !EMAIL_RE.test(who.email) ? 'Please enter a valid email address.' : null); }
      if (bad) { bad.focus(); return; }
      this._bkGo(f, 'review'); };
  }
  _bkReview(f, body) {
    const s = f.schedule || {}, w = f.who || {};
    const rows = [['Meeting', s.name], ['When', f.slot.label_visitor], ['Duration', s.duration_min ? `${s.duration_min} min · Zoom` : 'Zoom'], ['Name', w.name], ['Email', w.email], ['Company', w.company], ['Topic', w.notes && trunc(w.notes, 120)]].filter((r) => r[1]);
    body.innerHTML = `<div class="sumbox">${rows.map(([k, v]) => `<div class="sumrow"><span>${k}</span><b>${esc(v)}</b></div>`).join('')}</div>
      <button class="btn primary block confirm" type="button">Confirm booking</button><p class="note sstat" role="status">Nothing is booked until you confirm.</p>`;
    const btn = body.querySelector('.confirm'); btn.onclick = () => this._bkConfirm(f, btn, body.querySelector('.sstat'));
  }
  async _bkConfirm(f, btn, stat) {
    const back = f.card.querySelector('.bk-back'); const lock = (on) => { btn.disabled = on; btn.classList.toggle('loading', on); btn.textContent = on ? 'Booking…' : 'Confirm booking'; if (back) back.disabled = on; };
    lock(true); stat.className = 'note sstat'; stat.textContent = 'Checking the time with Zoom and booking…';
    const s = f.schedule, w = f.who || {}; let res = null, status = 0;
    try { const r = await fetch(this._url('/booking/confirm'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ schedule_slug: s.slug, start: f.slot.start_iso, name: w.name, email: w.email, company: w.company, notes: w.notes, timezone: this.tz }) }); status = r.status; res = r.ok ? await r.json() : null; } catch {}
    const fail = (msg) => { lock(false); stat.className = 'note sstat warn'; stat.textContent = msg; };
    if (status === 429) return fail('Too many booking attempts. Please wait a minute and try again. Nothing was booked.');
    if (!res) return fail("Couldn't reach the server. Nothing was booked. Please try again.");
    if (res.status === 'confirmed' || res.status === 'pending_zoom') { f.result = res; this._bkGo(f, 'done'); this._bkBooked(res); return; }
    if (res.status === 'slot_taken') { f.notice = res.message || 'That time was just taken. Please pick another.'; f.alts = res.alternatives || null; f.slot = null; this._bkGo(f, 'time'); this._bkLoadAvail(f); this._emit('booking', { status: 'slot_taken', schedule: s.slug }); return; }
    if (res.status === 'unavailable') { fail(res.message || "The scheduler isn't responding right now. Nothing was booked."); if (res.fallback_link) stat.insertAdjacentHTML('afterend', `<div class="hrow"><a class="btn" href="${esc(res.fallback_link)}" target="_blank" rel="noopener">Book directly on Zoom ${SVG.ext}</a></div>`); this._emit('booking', { status: 'unavailable', schedule: s.slug }); return; }
    if (res.status === 'invalid') { f.notice = res.message || 'Please check your details.'; this._bkGo(f, 'details'); return; }
    fail((res.message || "That didn't work.") + ' Nothing was booked; please try again.');
  }
  _bkDone(f, body) {
    const res = f.result, b = res.booking, pending = res.status !== 'confirmed';
    body.innerHTML = `<div class="booked">
      <div class="bk-ok" tabindex="-1">${pending ? `<span class="pend">${SVG.clock}</span><span>One last step on Zoom</span>` : `<svg class="chk" viewBox="0 0 30 30" aria-hidden="true"><circle cx="15" cy="15" r="13"/><path d="M9 15.5l4 4 8-8"/></svg><span>You're booked</span>`}</div>
      <div class="bk-when">${esc(b.label_visitor)}</div><div class="bk-sub">${esc(b.schedule_name)} · ${b.duration_min} min · ${esc(b.visitor_tz)}</div>
      ${pending ? `<p class="note">Your time is held. Confirm it on the Zoom scheduler (your details are prefilled) to make it final.</p>` : ''}
      <div class="hrow" style="margin-top:6px">${pending && b.handoff_url ? `<a class="btn primary" href="${esc(b.handoff_url)}" target="_blank" rel="noopener">Confirm on Zoom ${SVG.ext}</a>` : ''}${b.join_url ? `<a class="btn primary" href="${esc(b.join_url)}" target="_blank" rel="noopener">${SVG.video}Join Zoom</a>` : ''}${b.ics_url ? `<a class="btn" href="${esc(b.ics_url)}" download>${SVG.cal}Add to calendar</a>` : ''}</div>
      <ul class="nexts">
        ${res.emails_queued ? `<li>${SVG.checkc}<span>A confirmation${b.join_url ? ' with the Zoom link' : ''} is on its way to <b>${esc(b.email)}</b></span></li>` : ''}
        ${b.ics_url ? `<li>${SVG.checkc}<span>Add it to your calendar so it doesn't slip</span></li>` : ''}
        <li>${SVG.spark.replace('aria-hidden', 'class="nx" aria-hidden')}<span>Want to prepare? Ask me anything before the call.</span></li>
      </ul></div>`;
  }
  _bkBooked(res) {
    const b = res.booking, pending = res.status !== 'confirmed';
    const line = pending ? `Time held: ${b.schedule_name} on ${b.label_visitor}; confirm on Zoom to make it final.` : `Booking confirmed: ${b.schedule_name} on ${b.label_visitor}.`;
    this._history.push({ role: 'assistant', content: line }); this._history = this._history.slice(-12);
    this._transcript.push({ role: 'bot', text: line, ts: Date.now() }); this._persist(); this._announce(pending ? 'Time held. One last step on Zoom.' : 'Booking confirmed.');
    this._emit('booking', { status: res.status, bookingId: b.id, joinUrl: b.join_url || null, handoffUrl: b.handoff_url || null, slot: b.start_iso, schedule: b.schedule_slug, email: b.email });
  }
  _onSchedules(bot, items) { const f = this._bkFlow(bot); f.types = items; this._bkGo(f, 'type', false); if (items.some((x) => !x.description)) this._bkLoadTypes(f); }
  _onAvailability(bot, ev) {
    const f = this._bkFlow(bot); if (ev.schedule) f.schedule = { ...(f.schedule || {}), ...ev.schedule };
    if (!ev.ok && ev.error === 'unknown_schedule') { this._onSchedules(bot, ev.choices || []); return; }
    this._bkSetAvail(f, ev); f.step = 'time'; this._bkRender(f, false);
  }
  _onReview(bot, ev) {
    const f = this._bkFlow(bot); if (ev.schedule) f.schedule = { ...(f.schedule || {}), ...ev.schedule }; f.prefill = ev.prefill || {};
    if (ev.status === 'review' && ev.slot) { f.slot = ev.slot; f.notice = null; this._bkGo(f, 'details', false); return; }
    if (ev.status === 'unavailable' && ev.alternatives) { f.notice = (ev.wanted ? ev.wanted + ' is not open.' : 'That time is not open.') + ' Here are the nearest open times.'; f.alts = ev.alternatives; this._bkGo(f, 'time', false); if (!f.avail) this._bkLoadAvail(f); return; }
    f.avail = { ok: false, message: ev.message || 'Availability could not be loaded.', fallback_link: ev.fallback_link }; this._bkGo(f, 'time', false);
  }
  _onSlots(bot, ev) {  // legacy 3-slot event: only when the grid did not render
    if (bot._bk) return;
    if (!ev.ok && ev.error === 'unknown_schedule') { this._onSchedules(bot, ev.choices || []); return; }
    const f = this._bkFlow(bot); if (ev.schedule) f.schedule = ev.schedule;
    if (!ev.ok) { f.avail = { ok: false, message: ev.error === 'no_slots' ? 'No open times in that window.' : "The scheduler isn't responding right now.", fallback_link: ev.fallback_link }; this._bkGo(f, 'time', false); return; }
    this._bkGo(f, 'time', false); this._bkLoadAvail(f);
  }
  _renderBooking(el, ev) {  // legacy event, kept for older servers
    const box = document.createElement('div'); box.className = 'card hrow'; box.style.marginTop = '10px';
    if (ev.handoff_url) box.innerHTML = `<a class="btn primary" href="${esc(ev.handoff_url)}" target="_blank" rel="noopener">Confirm on Zoom ${SVG.ext}</a>`;
    if (ev.status === 'slot_taken') box.insertAdjacentHTML('beforeend', '<p class="note warn">That slot was just taken.</p>');
    el.appendChild(box); this._emit('booking', { status: ev.status, leadId: ev.lead_id || null, handoffUrl: ev.handoff_url || null, slot: ev.slot || null, schedule: ev.schedule || null });
  }
  _renderHandover(el, prefill) {
    if (el.querySelector('.hform')) return; const me = this._me || {}; const known = !!(me.signed_in && me.verified && me.email);
    el.classList.add('hascard'); el.closest('.row').classList.add('wide');
    const f = document.createElement('form'); f.className = 'hform card'; f.noValidate = true; f.style.marginTop = '12px'; const id = 'h' + Math.random().toString(36).slice(2, 7);
    f.innerHTML = `<div class="bk-t"><b>Message the team</b></div>
      ${known ? '' : `<div class="field"><label for="${id}n">Your name</label><input class="inp" id="${id}n" name="name" maxlength="120" required autocomplete="name"></div>
      <div class="field"><label for="${id}e">Email for the reply</label><input class="inp" id="${id}e" name="email" type="email" maxlength="200" required autocomplete="email" inputmode="email"></div>`}
      <div class="field"><label for="${id}m">Your message</label><textarea class="inp" id="${id}m" name="message" rows="3" maxlength="2000" required></textarea></div>
      <button class="btn primary block" type="submit">${SVG.mail}Send message</button><p class="note" role="status">${known ? 'Replies go to ' + esc(me.email) + '.' : 'A real person replies by email.'}</p>`;
    const field = (n) => f.elements[n]; field('message').value = prefill || ''; if (!known) { if (me.name) field('name').value = me.name; if (me.email) field('email').value = me.email; }
    const note = f.querySelector('.note');
    f.onsubmit = async (e) => { e.preventDefault(); const b = f.querySelector('button[type=submit]'); const name = known ? (me.name || '') : field('name').value.trim(); const email = known ? me.email : field('email').value.trim(); const message = field('message').value.trim();
      const bad = !known && name.length < 2 ? field('name') : !known && !EMAIL_RE.test(email) ? field('email') : message.length < 2 ? field('message') : null;
      f.querySelectorAll('.inp').forEach((x) => x.setAttribute('aria-invalid', String(x === bad)));
      if (bad) { note.className = 'note warn'; note.textContent = bad.name === 'email' ? 'Please enter a valid email address.' : bad.name === 'name' ? 'Please enter your name.' : 'Please write a short message.'; bad.focus(); return; }
      b.disabled = true; b.classList.add('loading'); note.className = 'note'; note.textContent = 'Sending…';
      try { const r = await fetch(this._url('/handover'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ session_id: this._sid, name, email, message }) });
        const d = r.ok ? await r.json() : null;
        if (d && d.ok) { f.innerHTML = `<div class="booked"><div class="bk-ok" tabindex="-1"><svg class="chk" viewBox="0 0 30 30" aria-hidden="true"><circle cx="15" cy="15" r="13"/><path d="M9 15.5l4 4 8-8"/></svg><span>Message sent</span></div><p class="note">The team will reply to <b>${esc(email)}</b>.${d.visitor_mailed ? ' A copy is in your inbox.' : ''}</p></div>`; f.querySelector('.bk-ok').focus({ preventScroll: true }); this._announce('Message sent'); this._emit('handover', { leadId: d.lead_id, email, briefSent: d.brief_sent }); }
        else { b.disabled = false; b.classList.remove('loading'); note.className = 'note warn'; note.textContent = r.status === 422 ? 'Please check the email address.' : "Couldn't send right now. Please try again."; } }
      catch { b.disabled = false; b.classList.remove('loading'); note.className = 'note warn'; note.textContent = 'Connection problem. Please try again.'; } };
    el.appendChild(f); this._emit('action', { action: 'handover_form' });
    requestAnimationFrame(() => { this._stick = true; this._scroll(); if (!this._coarse) (known ? field('message') : field('name')).focus({ preventScroll: true }); });
  }
  // ---------------------------------------------------------------- attachments
  _renderAttachments() {
    const box = this.shadowRoot.querySelector('.attach'); box.hidden = !this._attachments.length; box.innerHTML = '';
    this._attachments.forEach((a) => { const c = document.createElement('span'); c.className = 'achip' + (a.error ? ' err' : ''); c.title = a.error || a.name;
      c.innerHTML = `${a.image && a.preview ? `<img src="${a.preview}" alt="">` : '📎'}<span class="nm">${esc(a.name)}</span><span class="sz">${a.error ? esc(a.error) : a.id ? fmtSize(a.size) : 'uploading…'}</span><button type="button" class="x" aria-label="Remove ${esc(a.name)}">×</button><span class="bar" style="width:${a.id ? 100 : a.progress || 10}%"></span>`;
      c.querySelector('.x').onclick = () => { if (a.xhr) a.xhr.abort(); this._attachments = this._attachments.filter((x) => x !== a); this._renderAttachments(); this.$q.focus(); }; box.appendChild(c); });
    this._syncSend();
  }
  _upload(file) {
    if (!this.api) return; const max = (this._cfg.upload_max_mb || 10) * 1048576;
    const a = { name: file.name, size: file.size, image: /^image\//.test(file.type), preview: null, progress: 0, id: null, error: null, xhr: null };
    if (file.size > max) { a.error = `over ${this._cfg.upload_max_mb || 10} MB`; this._attachments.push(a); this._renderAttachments(); return; }
    if (a.image) { try { a.preview = URL.createObjectURL(file); } catch {} }
    this._attachments.push(a); this._renderAttachments();
    const fd = new FormData(); fd.append('file', file, file.name); const xhr = new XMLHttpRequest(); a.xhr = xhr;
    xhr.open('POST', this._url('/upload')); Object.entries(this._headers(false)).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) { a.progress = Math.round((e.loaded / e.total) * 100); this._renderAttachments(); } };
    xhr.onload = () => { a.xhr = null; if (xhr.status === 200) { const d = JSON.parse(xhr.responseText); a.id = d.id; a.name = d.name; a.size = d.size; this._emit('upload', d); } else { try { a.error = JSON.parse(xhr.responseText).detail || 'upload failed'; } catch { a.error = 'upload failed'; } } this._renderAttachments(); };
    xhr.onerror = () => { a.xhr = null; a.error = 'upload failed'; this._renderAttachments(); };
    xhr.send(fd);
  }
  // ---------------------------------------------------------------- emoji + gifs
  _renderEmoji(q) { const g = this.shadowRoot.querySelector('.egrid'); q = (q || '').trim().toLowerCase(); g.innerHTML = EMOJI.filter(([e, k]) => !q || k.includes(q)).map(([e, k]) => `<button type="button" title="${k}" aria-label="${k}">${e}</button>`).join('') || '<div class="empty">No match</div>';
    g.querySelectorAll('button').forEach((b) => b.onclick = () => { this._insert(b.textContent); }); }
  _insert(text) { const q = this.$q, s = q.selectionStart ?? q.value.length, e = q.selectionEnd ?? s; q.value = q.value.slice(0, s) + text + q.value.slice(e); q.selectionStart = q.selectionEnd = s + text.length; q.focus(); this._autosize(); this._syncSend(); }
  async _searchGifs(q) {
    const grid = this.shadowRoot.querySelector('.ggrid'), empty = this.shadowRoot.querySelector('.pop-gif .empty'); grid.innerHTML = ''; empty.hidden = true;
    try { const r = await fetch(this._url('/gifs?q=' + encodeURIComponent(q || ''))); const d = r.ok ? await r.json() : { items: [] };
      if (!d.items.length) { empty.hidden = false; empty.textContent = d.error === 'not configured' ? 'GIFs are not enabled on this assistant.' : 'No GIFs found.'; return; }
      d.items.forEach((g) => { const b = document.createElement('button'); b.type = 'button'; b.title = g.title || 'GIF'; b.setAttribute('aria-label', 'Send GIF ' + (g.title || '')); b.innerHTML = `<img src="${esc(g.preview)}" alt="${esc(g.title || 'GIF')}" loading="lazy">`; b.onclick = () => { this._closePops(); this._send(`[GIF](${g.url})`); }; grid.appendChild(b); });
    } catch { empty.hidden = false; empty.textContent = 'Could not load GIFs.'; }
  }
  // ---------------------------------------------------------------- dictation (microphone -> text in the input)
  _speechApi() { return window.SpeechRecognition || window.webkitSpeechRecognition || null; }
  _toggleDictation() { if (this._rec) this._stopDictation(); else this._startDictation(); }
  async _startDictation() {
    const sh = this.shadowRoot, rec = sh.querySelector('.rec'), label = rec.querySelector('.rlabel'), time = rec.querySelector('.rtime'), mic = sh.querySelector('.b-mic');
    const t0 = Date.now(); const tick = setInterval(() => { const s = Math.floor((Date.now() - t0) / 1000); time.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }, 500);
    const show = (msg) => { label.textContent = msg; rec.classList.add('on'); mic.classList.add('on'); mic.setAttribute('aria-pressed', 'true'); }; const done = () => { clearInterval(tick); rec.classList.remove('on'); mic.classList.remove('on'); mic.setAttribute('aria-pressed', 'false'); time.textContent = '0:00'; this._rec = null; };
    const Api = this._speechApi();
    if (Api && this._cfg.stt !== 'server') {
      const r = new Api(); r.lang = navigator.language || 'en-US'; r.interimResults = true; r.continuous = true; let finalText = '';
      r.onresult = (e) => { let interim = ''; for (let i = e.resultIndex; i < e.results.length; i++) { const t = e.results[i][0].transcript; if (e.results[i].isFinal) finalText += t + ' '; else interim += t; } label.textContent = interim ? 'Listening… ' + interim.slice(-40) : 'Listening…'; };
      r.onerror = (e) => { show(e.error === 'not-allowed' ? 'Microphone access was denied. Allow it in your browser settings and try again.' : 'Dictation error: ' + e.error); setTimeout(done, 2500); };
      r.onend = () => { if (finalText.trim()) this._insert((this.$q.value && !/\s$/.test(this.$q.value) ? ' ' : '') + finalText.trim()); done(); };
      this._rec = { stop: () => r.stop() }; show('Listening…'); try { r.start(); } catch (e) { show('Could not start dictation.'); setTimeout(done, 2000); }
      return;
    }
    if (this._cfg.stt !== 'server' || !navigator.mediaDevices) { show('Dictation is not available in this browser.'); setTimeout(done, 2500); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); const mr = new MediaRecorder(stream); const chunks = [];
      mr.ondataavailable = (e) => chunks.push(e.data);
      mr.onstop = async () => { stream.getTracks().forEach((t) => t.stop()); show('Transcribing…'); try { const fd = new FormData(); fd.append('file', new Blob(chunks, { type: mr.mimeType || 'audio/webm' }), 'audio.webm'); fd.append('language', (navigator.language || 'en').slice(0, 2));
          const r = await fetch(this._url('/stt'), { method: 'POST', headers: this._headers(false), body: fd }); const d = r.ok ? await r.json() : null; if (d && d.text) this._insert((this.$q.value && !/\s$/.test(this.$q.value) ? ' ' : '') + d.text); else show('Could not transcribe that.'); } catch { show('Could not transcribe that.'); } setTimeout(done, 600); };
      this._rec = { stop: () => mr.stop() }; show('Recording…'); mr.start();
    } catch (e) { show(e && e.name === 'NotAllowedError' ? 'Microphone access was denied. Allow it in your browser settings and try again.' : 'Could not access the microphone.'); setTimeout(done, 2500); }
  }
  _stopDictation() { if (this._rec) this._rec.stop(); }
  // ---------------------------------------------------------------- voice conversation: living orb + audio analysers (docs/AGENT_UI.md)
  async startVoice() {
    const sh = this.shadowRoot;
    if (this._voice) { this._showVoice(true); return; }
    const v = { muted: false, ended: false, rec: null, audio: null, t0: Date.now(), timer: null, orb: null, meter: null, lines: [], cc: true, state: 'idle', mic: null };
    this._voice = v; this.showView('chat'); this._showVoice(true); this._emit('voice', { state: 'start' });
    this.$q.blur();  // no text caret while the call view is up (Windows draws its text-cursor indicator at any caret)
    const timer = sh.querySelector('.vtimer'); v.timer = setInterval(() => { const sec = Math.floor((Date.now() - v.t0) / 1000); timer.textContent = `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`; }, 1000);
    sh.querySelector('.voice').classList.remove('muted'); const mb = sh.querySelector('.v-mute'); mb.classList.remove('on'); mb.setAttribute('aria-pressed', 'false'); mb.querySelector('.vi').innerHTML = SVG.mic; mb.querySelector('.tip').textContent = 'Mute';
    sh.querySelector('.vcap .cu').textContent = ''; sh.querySelector('.vcap .ca').innerHTML = ''; sh.querySelector('.vcap').classList.toggle('off', !v.cc);
    this._setStatus('call');
    const canvas = sh.querySelector('.vorb canvas'), orbWrap = sh.querySelector('.vorb');
    try {
      const m = await import('./deep-orb.js?v=' + VERSION); if (v.ended) return;
      v.meter = new m.AudioMeter(); v.orb = new m.Orb(canvas, { reduced: this._reduced, onGlow: (b, grey) => { const body = sh.querySelector('.vbody'); body.style.setProperty('--vglow-o', String(Math.min(1, b * 0.7))); body.style.setProperty('--vglow', grey > 0.5 ? 'rgba(150,150,160,.18)' : 'rgba(85,70,247,.34)'); } });
      v.orb.setMeter(v.meter); v.orb.setState('idle'); v.orb.start(); orbWrap.classList.remove('static');
    } catch (e) { orbWrap.classList.add('static'); canvas.hidden = true; console.warn('deep-assistant: orb unavailable', e); }
    if (!this._canListen()) { this._vstate('Voice is not available in this browser.', 'idle'); return; }
    if (v.meter && navigator.mediaDevices) v.meter.listenMic().then((ok) => { v.mic = ok; });  // levels for the orb while you speak
    this._vstate('Listening…', 'listen'); this._vListen();
  }
  _showVoice(open) {
    const sh = this.shadowRoot, el = sh.querySelector('.voice'), pill = sh.querySelector('.vpill'); const v = this._voice;
    el.classList.toggle('open', open); pill.classList.toggle('show', !open && !!v);
    if (v && v.orb) { if (open) v.orb.resume(); else v.orb.pause(); }
    if (!open) { this._setStatus(this._busy ? 'work' : (v ? 'call' : 'idle')); this._focusInput(); } else { this.$q.blur(); setTimeout(() => sh.querySelector('.v-end').focus({ preventScroll: true }), 50); }
  }
  stopVoice() {
    const v = this._voice; if (!v) return; v.ended = true; const sh = this.shadowRoot, el = sh.querySelector('.voice');
    if (v.rec) { try { v.rec.stop(); } catch {} } if (v.audio) { try { v.audio.pause(); } catch {} } try { speechSynthesis.cancel(); } catch {}
    clearInterval(v.timer); const secs = Math.round((Date.now() - v.t0) / 1000);
    if (v.orb) v.orb.collapse(350);
    const finish = () => { if (v.orb) v.orb.stop(); if (v.meter) v.meter.close(); el.classList.remove('open'); el.classList.remove('closing'); sh.querySelector('.vpill').classList.remove('show'); };
    if (el.classList.contains('open') && !this._reduced) { el.classList.add('closing'); setTimeout(finish, 360); } else finish();
    this._voice = null; this._setStatus(this._busy ? 'work' : 'idle'); this._emit('voice', { state: 'end', seconds: secs, turns: v.lines.length });
    if (v.lines.length || secs >= 1) this._callSummary(secs, v.lines);
    this._focusInput();
  }
  _callSummary(secs, lines) {
    const w = this.$log.querySelector('.welcome'); if (w) w.remove();
    const row = document.createElement('div'); row.className = 'row bot'; row.innerHTML = `<span class="bav" aria-hidden="true">${SVG.mark}</span>`; const col = document.createElement('div'); col.className = 'col'; const c = document.createElement('div'); c.className = 'card callcard';
    const dur = secs >= 60 ? `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, '0')}s` : `${secs}s`;
    c.innerHTML = `<div class="cc-t">${SVG.phone}<span>Voice call · ${dur}</span></div><div class="cc-s">${lines.length ? lines.length + ' exchange' + (lines.length === 1 ? '' : 's') : 'No exchanges'}</div>`;
    if (lines.length) { const wb = document.createElement('button'); wb.type = 'button'; wb.className = 'worked'; wb.style.marginTop = '6px'; wb.innerHTML = `${SVG.chev}<span>Transcript</span>`; wb.setAttribute('aria-expanded', 'false'); const st = document.createElement('div'); st.className = 'steps';
      st.innerHTML = lines.map((l) => `<div><b>${l.who === 'you' ? 'You' : 'Deep'}</b><span>${esc(l.text)}</span></div>`).join(''); wb.onclick = () => { const o = !st.classList.contains('open'); st.classList.toggle('open', o); wb.classList.toggle('open', o); wb.setAttribute('aria-expanded', String(o)); }; c.append(wb, st); }
    col.appendChild(c); row.appendChild(col); this.$log.appendChild(row); this._stick = true; this._scroll();
  }
  _toggleMute() {
    const v = this._voice; if (!v) return; v.muted = !v.muted; const sh = this.shadowRoot, b = sh.querySelector('.v-mute');
    b.setAttribute('aria-pressed', String(v.muted)); b.classList.toggle('on', v.muted); b.querySelector('.vi').innerHTML = v.muted ? SVG.micoff : SVG.mic; b.querySelector('.tip').textContent = v.muted ? 'Unmute' : 'Mute'; b.setAttribute('aria-label', v.muted ? 'Unmute microphone' : 'Mute microphone');
    sh.querySelector('.voice').classList.toggle('muted', v.muted); if (v.meter) v.meter.mute(v.muted);
    if (v.muted) { if (v.rec) { v.discard = true; try { v.rec.stop(); } catch {} } this._vstate('Muted', 'muted'); } else if (!this._busy) this._vListen();
  }
  _toggleCaptions() { const v = this._voice; const sh = this.shadowRoot, b = sh.querySelector('.v-cc'); const on = v ? (v.cc = !v.cc) : true; b.classList.toggle('off', !on); b.setAttribute('aria-pressed', String(on)); b.setAttribute('aria-label', on ? 'Captions on' : 'Captions off'); sh.querySelector('.vcap').classList.toggle('off', !on); }
  _vstate(text, mode) {
    const sh = this.shadowRoot, st = sh.querySelector('.vstatus'); const v = this._voice;
    if (st.textContent !== text) { if (this._reduced) st.textContent = text; else { st.classList.add('sw'); setTimeout(() => { st.textContent = text; st.classList.remove('sw'); }, 160); } this._announce(text); }
    if (v) { v.state = mode; if (v.orb) v.orb.setState(mode === 'listen' ? 'listen' : mode === 'think' ? 'think' : mode === 'speak' ? 'speak' : mode === 'muted' ? 'muted' : 'idle'); }
  }
  _caption(who, text, words) {
    const sh = this.shadowRoot, cap = sh.querySelector('.vcap'); if (who === 'you') { cap.querySelector('.cu').textContent = text; return; }
    const ca = cap.querySelector('.ca'); if (words) ca.innerHTML = words.map((w) => `<span class="w">${esc(w)}</span>`).join(' '); else ca.textContent = text;
  }
  _captionProgress(i) { const ws = this.shadowRoot.querySelectorAll('.vcap .ca .w'); ws.forEach((w, j) => w.classList.toggle('on', j <= i)); }
  _vListen() {
    const v = this._voice; if (!v || v.ended || v.muted) return; this._vstate('Listening…', 'listen'); const Api = this._speechApi();
    const onText = async (text) => { if (!text || v.ended) return; v.lines.push({ who: 'you', text }); this._caption('you', text); this._vstate('Thinking…', 'think');
      await this._send(text); if (v.ended) return; const last = this._transcript[this._transcript.length - 1]; const reply = last && last.role === 'bot' ? plain(last.text) : '';
      if (reply) { v.lines.push({ who: 'deep', text: reply }); this._vstate('Speaking…', 'speak'); const say = trunc(reply, 600); this._caption('deep', say, say.split(/\s+/)); await this._vSpeak(say); this._captionProgress(1e9); } if (!v.ended) this._vListen(); };
    if (Api && this._cfg.stt !== 'server') {
      const r = new Api(); r.lang = navigator.language || 'en-US'; r.interimResults = true; r.continuous = false; let got = '';
      r.onresult = (e) => { let interim = ''; for (let i = e.resultIndex; i < e.results.length; i++) { const t = e.results[i][0].transcript; if (e.results[i].isFinal) got += t; else interim += t; } this._caption('you', (got || interim).trim()); };
      r.onerror = (e) => { if (e.error === 'not-allowed') this._vstate('Microphone access was denied.', 'idle'); };
      r.onend = () => { v.rec = null; if (v.discard) { v.discard = false; return; } if (got) onText(got.trim()); else if (!v.ended && !v.muted && !this._busy) setTimeout(() => this._vListen(), 300); };
      v.rec = r; try { r.start(); } catch { this._vstate('Could not start listening.', 'idle'); }
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => { const mr = new MediaRecorder(stream); const chunks = []; mr.ondataavailable = (e) => chunks.push(e.data);
      mr.onstop = async () => { stream.getTracks().forEach((t) => t.stop()); v.rec = null; if (v.ended || v.discard) { v.discard = false; return; } this._vstate('Thinking…', 'think'); const fd = new FormData(); fd.append('file', new Blob(chunks, { type: mr.mimeType || 'audio/webm' }), 'audio.webm');
        try { const r = await fetch(this._url('/stt'), { method: 'POST', headers: this._headers(false), body: fd }); const d = r.ok ? await r.json() : null; if (d && d.text) onText(d.text.trim()); else if (!v.muted) setTimeout(() => this._vListen(), 300); } catch { this._vstate('Transcription failed.', 'idle'); } };
      v.rec = mr; mr.start(); setTimeout(() => { if (mr.state === 'recording') mr.stop(); }, 6000); }).catch(() => this._vstate('Microphone access was denied.', 'idle'));
  }
  _vSpeak(text) {
    return new Promise(async (resolve) => {
      const v = this._voice; if (!v) return resolve(); const words = text.split(/\s+/);
      if (this._cfg.tts === 'server') {
        try { const r = await fetch(this._url('/tts'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ text }) });
          if (r.ok) { const a = new Audio(URL.createObjectURL(await r.blob())); a.crossOrigin = 'anonymous'; v.audio = a; if (v.meter) v.meter.listenElement(a);  // TTS output -> AnalyserNode
            a.ontimeupdate = () => { if (a.duration) this._captionProgress(Math.floor((a.currentTime / a.duration) * words.length)); };
            a.onended = () => resolve(); a.onerror = () => resolve(); a.play().catch(() => resolve()); return; } } catch {}
      }
      if (!('speechSynthesis' in window)) return resolve();
      const u = new SpeechSynthesisUtterance(text); u.lang = navigator.language || 'en-US';
      // SpeechSynthesis exposes no audio stream: word boundaries drive the captions and a synthetic pulse on the orb
      u.onboundary = (e) => { if (e.name && e.name !== 'word') return; const i = text.slice(0, e.charIndex).split(/\s+/).length - 1; this._captionProgress(i); if (v.meter) v.meter.pulse(0.55 + Math.min(0.45, ((e.charLength || 4) / 10))); };
      u.onend = () => resolve(); u.onerror = () => resolve(); speechSynthesis.cancel(); speechSynthesis.speak(u);
    });
  }
  // ---------------------------------------------------------------- send / stop
  _stop() { if (this._controller) this._controller.abort(); }
  _errorText(status) {
    if (status === 429) return "You're sending messages quickly. Please wait a moment, then try again.";
    if (status === 403) return "This site isn't allowed to use the assistant yet.";
    if (status >= 500) return "Deep couldn't answer just now. Please try again in a moment.";
    return `Something went wrong (error ${status}). Please try again.`;
  }
  async _send(text) {
    text = (text || this.$q.value).trim(); const files = this._attachments.filter((a) => a.id);
    if ((!text && !files.length) || this._busy) return; if (this._attachments.some((a) => a.xhr)) return;
    if (!this.api) { this._add('bot', 'This assistant has no api attribute set.'); return; }
    if (this._view !== 'chat') this.showView('chat');
    this.$q.value = ''; this._autosize(); this._closePops(); this._clearFollowups(); this._setBusy(true);
    const shown = (text || (files.length > 1 ? 'Please look at the attached files.' : 'Please look at the attached file.')) + files.map((a) => `\n[attached: ${a.name}](/uploads/${a.id})`).join('');
    const user = this._add('user', '', Date.now()); this._setText(user, shown); this._transcript.push({ role: 'user', text: shown, ts: Date.now() }); this._persist(); this._emit('question', { text, attachments: files.map((a) => a.id) });
    this._attachments = []; this._renderAttachments();
    const bot = this._add('bot', ''); const act = this._activity(bot); this._markLast();
    let answer = '', sources = [], all = [], failed = false, mid = null, offer = false, booking = false; const sid = this._sid;
    this._controller = new AbortController(); const me = this._me || {};
    const fail = (msg) => { failed = true; this._setText(bot, msg); bot.classList.add('err'); };
    try {
      const r = await fetch(this._url('/chat'), { method: 'POST', signal: this._controller.signal, headers: this._headers(),
        body: JSON.stringify({ message: text || 'Please look at the attached file.', history: this._history, timezone: this.tz, attachments: files.map((a) => a.id), user_name: me.signed_in ? undefined : (me.name || undefined), user_email: me.signed_in ? undefined : (me.email || undefined) }) });
      if (!r.ok) { fail(this._errorText(r.status)); this._emit('error', { error: 'http_' + r.status }); return; }
      if (!this._online) { this._online = true; }
      const reader = r.body.getReader(), dec = new TextDecoder(); let buf = '';
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i; while ((i = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, i).trim(); buf = buf.slice(i + 2); if (!line.startsWith('data:')) continue;
          let ev; try { ev = JSON.parse(line.slice(5)); } catch { continue; }
          this._stick = this._atBottom();
          if (ev.type === 'token') { if (!answer) { bot.classList.add('streaming'); if (act.last !== 'Writing…') act.set('writing', 'Writing…'); } answer += ev.text; this._setText(bot, answer, all); }
          else if (ev.type === 'status') { act.set(ev.step, ev.label); }
          else if (ev.type === 'availability') { booking = true; bot.classList.remove('skel'); this._onAvailability(bot, ev); }
          else if (ev.type === 'booking_review') { booking = true; bot.classList.remove('skel'); this._onReview(bot, ev); }
          else if (ev.type === 'schedules') { booking = true; bot.classList.remove('skel'); if (!answer) bot.innerHTML = ''; this._onSchedules(bot, ev.items || []); }
          else if (ev.type === 'slots') { booking = true; bot.classList.remove('skel'); this._onSlots(bot, ev); }
          else if (ev.type === 'booking') { booking = true; this._renderBooking(bot, ev); }
          else if (ev.type === 'sources') { all = ev.items || []; this._emit('sources', { items: all }); }
          else if (ev.type === 'meta') { mid = ev.message_id || null; }
          else if (ev.type === 'handover') { bot.classList.remove('skel'); this._renderHandover(bot, ev.prefill || ''); this._emit('action', { action: 'handover_requested' }); }
          else if (ev.type === 'handover_offer') { offer = true; this._emit('action', { action: 'unanswered', label: text }); }
          else if (ev.type === 'error') { fail('Something went wrong on our side. ' + (answer ? '' : 'Please try again.')); this._emit('error', { error: ev.error }); }
          this._scroll();
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') { this._setText(bot, answer || 'Stopped.'); if (answer) bot.insertAdjacentHTML('beforeend', '<div class="note">Stopped.</div>'); }
      else { fail("Couldn't reach Deep. Check your connection, then try again."); this._online = false; this._health(); this._emit('error', { error: String(e) }); }
    } finally {
      // _stick still holds "was the reader at the bottom before the last change", so the tail below follows the same rule
      bot.classList.remove('streaming'); if (bot.classList.contains('skel')) this._setText(bot, answer || '…', all);
      if (answer && all.length && !failed) { sources = usedSources(answer, all); this._addSources(bot, sources); }
      act.done(sources.length);
      const raw = bot.dataset.raw || answer; this._addTools(bot, () => raw, failed ? text : null, mid);
      if (failed) this._followups(bot, [{ icon: 'reset', label: 'Try again', fn: () => this._retry(bot, text) }]);
      else if (offer) this._followups(bot, [{ icon: 'mail', label: 'Ask the team directly', kind: 'handover', fn: () => this._renderHandover(bot, text) }, { icon: 'cal', label: 'Book a meeting', kind: 'booking', fn: () => this.startBooking() }]);
      else if (!booking) this._followups(bot, this._answerFollowups(bot, text, answer, sources.length));
      this._history.push({ role: 'user', content: shown }, { role: 'assistant', content: answer }); this._history = this._history.slice(-12);
      this._transcript.push({ role: 'bot', text: failed ? bot.dataset.raw : answer, sources, ts: Date.now(), mid, err: failed || undefined }); this._persist();
      this._controller = null; this._setBusy(false); if (!this._voice) this._focusInput(); this._scroll();
      this._emit('answer', { question: text, answer: raw, sources, messageId: mid, failed });
      if (this._view === 'chat' && this._sid === sid) await this._markRead(sid);
      this._refreshBadge(); if (this._view === 'messages') this._renderConversations();
      clearTimeout(this._titleT); this._titleT = setTimeout(() => { if (this._view === 'messages') this._renderConversations(); else this._convos = null; }, 6000);
    }
  }
}
if (!customElements.get('deep-assistant')) customElements.define('deep-assistant', DeepAssistant);
export { DeepAssistant };
