/* <deep-assistant> : the Ask Deep assistant as a framework-agnostic web component (no build step, no dependencies).
 *
 *   <script type="module" src="https://assistant.example.com/static/deep-assistant.js"></script>
 *   <deep-assistant api="https://assistant.example.com" mode="launcher" theme="dark"></deep-assistant>
 *
 * Attributes
 *   api          base URL of the assistant server (required)
 *   mode         "panel" (fills its container; default) | "launcher" (round floating button + pop-over panel)
 *   theme        "dark" (default) | "light" | "auto" (follow the OS)
 *   open         present = pop-over open (launcher mode)
 *   token        signed-in visitor token minted by YOUR backend (HMAC) or a Clerk session JWT; see docs/WIDGET.md
 *   user-name / user-email   unverified prefill hints when no token is available
 *   title / subtitle / suggestions ("|"-separated) / greeting   copy
 *   tabs         bottom navigation, comma-separated from home,messages,help (default all; "messages" always kept)
 *   shortcut     "Label|https://…" card at the top of Messages (default: the Zoom booking page); "" hides it
 *   privacy-url  footer link (default: the server's PRIVACY_URL)
 * Methods      ask(text), open(), close(), toggle(), newChat() / reset(), openConversation(id), showView(name),
 *              setToken(token), download(), startVoice(), stopVoice()
 * Events       deep-assistant:ready | :open | :close | :question | :answer | :sources | :booking | :handover
 *              | :feedback | :error | :view | :upload | :voice   (CustomEvent, bubbles + composed)
 * Theming      --da-bg --da-panel --da-bubble --da-user --da-user-text --da-text --da-muted --da-line --da-accent
 *              --da-mint --da-sky --da-font --da-radius (set on the element)
 */
const VERSION = '2026.10.07.2';
const DEFAULT_SUGGESTIONS = ['Book a call with Deep', 'What is Deep working on?', 'Tell me about the companies'];
const DEFAULT_SHORTCUT = 'Book a call with Deep|https://scheduler.zoom.us/sreedeep';
const ALL_TABS = ['home', 'messages', 'help'];
const EMOJI = [['😀', 'grin smile happy'], ['😂', 'laugh joy tears'], ['🙂', 'smile'], ['😉', 'wink'], ['😍', 'love heart eyes'], ['🤔', 'thinking hmm'], ['😅', 'sweat smile'], ['😎', 'cool sunglasses'], ['🥳', 'party celebrate'], ['😢', 'sad cry'], ['😡', 'angry'], ['🙏', 'thanks please pray'],
  ['👋', 'wave hello hi'], ['👍', 'thumbs up yes'], ['👎', 'thumbs down no'], ['👏', 'clap'], ['🙌', 'hands raised'], ['🤝', 'handshake deal'], ['💪', 'strong muscle'], ['✌️', 'peace'], ['🤞', 'fingers crossed'], ['👀', 'eyes look'],
  ['❤️', 'heart love'], ['🔥', 'fire hot'], ['✨', 'sparkles'], ['⭐', 'star'], ['🎉', 'tada party'], ['🚀', 'rocket launch ship'], ['💡', 'idea bulb'], ['✅', 'check done yes'], ['❌', 'cross no'], ['⚡', 'bolt fast'], ['💯', 'hundred'], ['🎯', 'target goal'],
  ['📅', 'calendar date'], ['📞', 'phone call'], ['📧', 'email mail'], ['💼', 'briefcase work'], ['📈', 'chart growth'], ['📊', 'bar chart data'], ['🧠', 'brain'], ['🤖', 'robot bot ai'], ['💬', 'chat message'], ['📝', 'note memo'], ['🔗', 'link'], ['🕒', 'clock time'],
  ['☕', 'coffee'], ['🍕', 'pizza'], ['🌍', 'world globe'], ['🏢', 'office building'], ['🏆', 'trophy win'], ['🎓', 'graduate'], ['🙈', 'monkey see no'], ['🤷', 'shrug'], ['🫡', 'salute'], ['😴', 'sleep tired'], ['🤩', 'star struck wow'], ['😬', 'grimace awkward']];

const CSS = `
:host { display:block; box-sizing:border-box; font-family: var(--da-font, inherit); font-size:15px; line-height:1.5; color:var(--da-text);
  --da-bg:#000000; --da-panel:#0F0F10; --da-bubble:#1C1C1E; --da-bubble-2:#27272A; --da-user:#F28C28; --da-user-text:#1A1208; --da-text:#F2F3F5; --da-muted:#8A8D93;
  --da-line:#1F1F22; --da-accent:#F28C28; --da-mint:#9FE8C8; --da-sky:#8EC9F5; --da-danger:#E5484D; --da-ok:#5CCB8A; --da-radius:16px; --da-shadow:0 18px 50px rgba(0,0,0,.5); --da-thumb:rgba(255,255,255,.22);
  --da-cbox:#121214; --da-cbox-line:rgba(255,255,255,.10); --voice-gradient-start:#F28C28; --voice-gradient-mid:#FF6A3D; --voice-gradient-end:#E9487A; --voice-glow:rgba(255,106,61,.30) }
:host([theme="light"]) { --da-bg:#FFFFFF; --da-panel:#F7F7F8; --da-bubble:#F1F2F4; --da-bubble-2:#E7E8EB; --da-user:#F28C28; --da-user-text:#FFFFFF; --da-text:#16171A; --da-muted:#6B7079; --da-line:#E3E5E8; --da-shadow:0 18px 50px rgba(20,20,30,.18); --da-thumb:rgba(0,0,0,.25); --da-cbox:#F7F7F8; --da-cbox-line:rgba(0,0,0,.08) }
@media (prefers-color-scheme: light) { :host([theme="auto"]) { --da-bg:#FFFFFF; --da-panel:#F7F7F8; --da-bubble:#F1F2F4; --da-bubble-2:#E7E8EB; --da-user-text:#FFFFFF; --da-text:#16171A; --da-muted:#6B7079; --da-line:#E3E5E8; --da-shadow:0 18px 50px rgba(20,20,30,.18); --da-thumb:rgba(0,0,0,.25); --da-cbox:#F7F7F8; --da-cbox-line:rgba(0,0,0,.08) } }
*, *::before, *::after { box-sizing:border-box } button { font:inherit; color:inherit } [hidden] { display:none !important }
:focus-visible { outline:2px solid var(--da-sky); outline-offset:2px }
/* thin scrollbars inside the panel only (no arrows, transparent track, thumb on hover/scroll) */
.scroll { scrollbar-width:thin; scrollbar-color:transparent transparent } .scroll:hover, .scroll.scrolling { scrollbar-color:var(--da-thumb) transparent }
.scroll::-webkit-scrollbar { width:6px; height:6px } .scroll::-webkit-scrollbar-track { background:transparent } .scroll::-webkit-scrollbar-button { display:none; height:0; width:0 }
.scroll::-webkit-scrollbar-thumb { background:transparent; border-radius:3px } .scroll:hover::-webkit-scrollbar-thumb, .scroll.scrolling::-webkit-scrollbar-thumb { background:var(--da-thumb) }
.panel { display:flex; flex-direction:column; height:100%; min-height:420px; background:var(--da-bg); color:var(--da-text); border-radius:var(--da-radius); overflow:hidden; position:relative }
:host([mode="launcher"]) { display:contents }
:host([mode="launcher"]) .panel { position:fixed; z-index:2147482999; right:20px; bottom:92px; width:400px; height:700px; max-height:calc(100vh - 40px); box-shadow:var(--da-shadow); display:none; border:1px solid var(--da-line) }
:host([mode="launcher"][open]) .panel { display:flex }
@media (max-width:480px) { :host([mode="launcher"]) .panel { inset:0; width:100vw; height:100dvh; max-height:none; border-radius:0; border:0 } }
.launcher { display:none; position:fixed; z-index:2147483000; right:max(20px, env(safe-area-inset-right)); bottom:max(20px, env(safe-area-inset-bottom)); width:56px; height:56px; border-radius:50%; border:0; background:var(--da-accent); color:#1A1208; cursor:pointer; box-shadow:0 10px 30px rgba(0,0,0,.4); align-items:center; justify-content:center }
.launcher svg { width:26px; height:26px } :host([mode="launcher"]) .launcher { display:flex } :host([mode="launcher"][open]) .launcher { display:none }
.lbadge { position:absolute; top:-4px; right:-4px; min-width:20px; height:20px; padding:0 6px; border-radius:999px; background:var(--da-danger); color:#fff; font:700 11px/20px system-ui,sans-serif; text-align:center; box-shadow:0 0 0 2px var(--da-bg) }
/* header: 64px, 16px side padding, 1px divider */
header { flex:none; display:flex; align-items:center; gap:8px; height:64px; padding:0 12px 0 16px; border-bottom:1px solid var(--da-line); background:var(--da-bg) }
.logo { width:36px; height:36px; border-radius:50%; background:var(--da-accent); color:#1A1208; display:flex; align-items:center; justify-content:center; flex:none } .logo svg { width:18px; height:18px }
.brand { flex:1; min-width:0; margin-left:4px } .brand h1 { margin:0; font-size:15px; font-weight:700; line-height:1.25; white-space:nowrap; overflow:hidden; text-overflow:ellipsis } .brand h1 span { font-family:"IBM Plex Mono", ui-monospace, monospace; font-weight:600 }
.brand p { margin:0; font-size:12px; color:var(--da-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.vtitle { position:absolute; left:50%; transform:translateX(-50%); font-size:16px; font-weight:700; margin:0; pointer-events:none } header { position:relative } header .spacer { flex:1 }
.icon { width:36px; height:36px; display:inline-flex; align-items:center; justify-content:center; border:0; background:transparent; border-radius:10px; cursor:pointer; color:var(--da-muted); flex:none }
.icon:hover { color:var(--da-text); background:var(--da-bubble) } .icon svg { width:18px; height:18px }
.menu { position:absolute; right:12px; top:60px; z-index:5; min-width:200px; background:var(--da-panel); border:1px solid var(--da-line); border-radius:12px; box-shadow:var(--da-shadow); padding:4px; display:none } .menu.open { display:block }
.menu button { display:flex; align-items:center; gap:10px; width:100%; padding:10px 12px; border:0; background:transparent; border-radius:8px; text-align:left; cursor:pointer; font-size:14px } .menu button:hover { background:var(--da-bubble) } .menu button svg { width:16px; height:16px; color:var(--da-muted) }
/* views: header + composer fixed, the conversation flexes and scrolls */
.views { flex:1; min-height:0; min-width:0; display:flex } .view { flex:1; min-height:0; min-width:0; display:flex; flex-direction:column; position:relative }
.log { flex:1; min-height:0; overflow-y:auto; overflow-x:hidden; padding:16px; display:flex; flex-direction:column; gap:20px; scroll-behavior:smooth }
.row { display:flex; flex-direction:column; max-width:85%; animation:da-rise .22s cubic-bezier(.16,1,.3,1) both; position:relative } .row.bot { align-self:flex-start } .row.user { align-self:flex-end; align-items:flex-end }
@keyframes da-rise { from { opacity:0; transform:translateY(4px) } to { opacity:1; transform:none } }
.msg { position:relative; padding:12px 16px; white-space:pre-wrap; overflow-wrap:anywhere; min-width:0; max-width:100%; border-radius:20px; background:var(--da-bubble); color:var(--da-text); font-size:15px; line-height:1.5 }
.bot .msg { border-bottom-left-radius:6px } .user .msg { background:var(--da-user); color:var(--da-user-text); border-bottom-right-radius:6px }
.msg a:not(.btn):not(.cite) { color:inherit; text-decoration:underline; text-underline-offset:3px }
.msg img.gif { display:block; max-width:240px; max-height:220px; border-radius:12px; margin:2px 0 }
.li { display:block; padding-left:14px; position:relative } .li::before { content:"•"; position:absolute; left:2px; color:var(--da-muted) }
.meta { margin:6px 4px 0; font-size:12px; line-height:1.3; color:var(--da-muted) } .user .meta { text-align:right }
.msg.thinking { padding:14px 16px; display:flex; gap:5px; align-items:center } .msg.thinking i { width:7px; height:7px; border-radius:50%; background:var(--da-muted); animation:da-dot 1.1s ease-in-out infinite } .msg.thinking i:nth-child(2) { animation-delay:.18s } .msg.thinking i:nth-child(3) { animation-delay:.36s }
@keyframes da-dot { 0%,80%,100% { transform:translateY(0); opacity:.5 } 40% { transform:translateY(-4px); opacity:1 } }
@media (prefers-reduced-motion: reduce) { .row, .fab, .wave i, .toastmsg { animation:none } .msg.thinking i { animation:none; opacity:.8 } .log { scroll-behavior:auto } }
.cite { display:inline-block; vertical-align:super; font:600 9.5px/1 system-ui, sans-serif; color:var(--da-muted); text-decoration:none; margin-left:2px; padding:1px 4px; border:1px solid var(--da-line); border-radius:999px } a.cite:hover { color:var(--da-text); border-color:var(--da-muted) }
/* order under a bot bubble: meta (6px) → sources row (6px) → action icons (6px) */
.sources { margin:6px 0 0 4px; display:flex; align-items:center; gap:8px; max-width:100%; min-width:0 } .sources .lbl { flex:none; font-size:12px; color:var(--da-muted) }
.srow { display:flex; gap:6px; overflow-x:auto; min-width:0; scrollbar-width:none } .srow::-webkit-scrollbar { display:none }
.srow a { flex:none; display:inline-flex; align-items:center; gap:6px; height:24px; font-size:12px; line-height:1; color:var(--da-text); text-decoration:none; border:1px solid var(--da-line); border-radius:999px; padding:0 10px 0 4px; max-width:260px; background:transparent }
.srow a b { font:600 10px/16px system-ui, sans-serif; min-width:16px; height:16px; padding:0 4px; border-radius:999px; background:var(--da-bubble-2); color:var(--da-text); text-align:center } .srow a .t { white-space:nowrap } .srow a .h { color:var(--da-muted); white-space:nowrap } .srow a:hover { border-color:var(--da-muted) }
.tools { display:flex; gap:4px; margin:6px 0 0 0; opacity:.55; transition:opacity .15s } .row:hover .tools, .row:focus-within .tools, .tools.keep { opacity:1 }
.tool { width:28px; height:28px; display:inline-flex; align-items:center; justify-content:center; border:0; background:transparent; border-radius:8px; color:var(--da-muted); cursor:pointer; position:relative } .tool:hover { color:var(--da-text); background:var(--da-bubble) } .tool svg { width:16px; height:16px } .tool.on { color:var(--da-accent) }
.tool .tip { position:absolute; bottom:calc(100% + 4px); left:50%; transform:translateX(-50%); background:var(--da-bubble-2); color:var(--da-text); font-size:11px; padding:3px 7px; border-radius:6px; white-space:nowrap; pointer-events:none }
/* thumbs-down popover (in flow under the icons so it never clips) + toast */
.fbpop { margin:6px 0 0; padding:12px; width:min(300px, 100%); background:var(--da-panel); border:1px solid var(--da-line); border-radius:12px; box-shadow:var(--da-shadow); display:flex; flex-direction:column; gap:8px }
.fbpop .reasons { display:flex; flex-wrap:wrap; gap:4px } .fbpop .reason { height:28px; padding:0 10px; border:1px solid var(--da-line); border-radius:999px; background:transparent; color:var(--da-text); font-size:12px; cursor:pointer } .fbpop .reason:hover { border-color:var(--da-muted) } .fbpop .reason.on { background:var(--da-accent); border-color:var(--da-accent); color:#1A1208 }
.fbpop input { height:32px; padding:0 10px; border:1px solid var(--da-line); border-radius:8px; background:var(--da-bg); color:var(--da-text); font:inherit; font-size:14px } .fbpop input:focus { outline:none; border-color:var(--da-accent) }
.fbpop .fbrow { display:flex; justify-content:flex-end; gap:12px } .textbtn { border:0; background:transparent; color:var(--da-muted); font-size:14px; cursor:pointer; padding:4px 2px } .textbtn.submit { color:var(--da-accent); font-weight:600 } .textbtn:hover { color:var(--da-text) }
.toastmsg { position:absolute; left:50%; bottom:140px; transform:translate(-50%, 8px); z-index:8; background:var(--da-bubble-2); color:var(--da-text); font-size:14px; padding:8px 14px; border-radius:999px; box-shadow:var(--da-shadow); opacity:0; pointer-events:none; transition:opacity .2s, transform .2s } .toastmsg.show { opacity:1; transform:translate(-50%, 0) }
.btn { display:inline-flex; align-items:center; gap:8px; min-height:40px; padding:8px 14px; border-radius:999px; border:1px solid var(--da-line); background:var(--da-bubble); color:var(--da-text); cursor:pointer; text-decoration:none; text-align:left; line-height:1.3; font-size:14px }
.btn:hover { border-color:var(--da-muted) } .btn.primary { background:var(--da-accent); border-color:var(--da-accent); color:#1A1208; font-weight:600 } .btn:disabled { opacity:.5; cursor:default }
.btn small { display:block; font-size:12px; color:var(--da-muted); font-weight:400 } .btn.primary small { color:#4a3214 }
.slots, .handoff { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 0; align-items:center } .note { font-size:12px; color:var(--da-muted); margin:8px 4px 0 } .note.warn { color:var(--da-danger) } .note.ok { color:var(--da-ok) }
.picker { display:grid; grid-template-rows:0fr; transition:grid-template-rows .3s cubic-bezier(.16,1,.3,1); min-width:0 } .picker.open { grid-template-rows:1fr } .picker > div { min-height:0; min-width:0; overflow:hidden }
.picker-in { display:flex; flex-direction:column; gap:8px; padding:12px 0 4px; min-width:0 } .picker label { font-size:12px; color:var(--da-muted) } .sel { position:relative; min-width:0 }
.sel select { width:100%; max-width:100%; height:40px; padding:0 38px 0 12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-panel); color:var(--da-text); font:inherit; font-size:14px; appearance:none; -webkit-appearance:none; cursor:pointer; text-overflow:ellipsis }
.sel::after { content:""; position:absolute; right:14px; top:50%; width:8px; height:8px; border-right:1.5px solid var(--da-muted); border-bottom:1.5px solid var(--da-muted); transform:translateY(-70%) rotate(45deg); pointer-events:none }
.picker .btn { align-self:flex-start } .picker.done select, .picker.done .btn { opacity:.5; pointer-events:none } .picker .hint { font-size:12px; color:var(--da-muted) }
  .card { margin:12px 0 0; padding:12px; border:1px solid var(--da-line); border-radius:14px; background:var(--da-panel); min-width:0; max-width:100% } .card .lbl { font-size:12px; color:var(--da-muted); margin-bottom:8px }
  .hrow { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:10px }
  .ctypes { display:flex; flex-direction:column; gap:8px } .ctype { display:flex; flex-direction:column; gap:2px; text-align:left; padding:10px 12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-bubble); color:var(--da-text); font:inherit; cursor:pointer } .ctype:hover { border-color:var(--da-muted) } .ctype.on { border-color:var(--da-accent) } .ctype b { font-size:14px; font-weight:600 } .ctype span, .ctype small { font-size:12px; color:var(--da-muted) } .picker.done .ctype:not(.on) { opacity:.5 }
  .ahead { display:flex; justify-content:space-between; align-items:baseline; gap:8px; font-size:14px; flex-wrap:wrap } .ahead span { font-size:12px; color:var(--da-muted) }
  .dates { display:flex; gap:6px; overflow-x:auto; padding:10px 0 6px; scrollbar-width:thin } .date { flex:none; width:66px; padding:8px 4px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-bubble); color:var(--da-text); font:inherit; cursor:pointer; display:flex; flex-direction:column; align-items:center; gap:2px } .date b { font-size:12px; font-weight:600; white-space:nowrap } .date small { font-size:10px; color:var(--da-muted); white-space:nowrap } .date:hover { border-color:var(--da-muted) } .date.on { border-color:var(--da-accent); background:rgba(242,140,40,.12) } .date.off { opacity:.45; cursor:default }
  .times { display:grid; grid-template-columns:repeat(auto-fill, minmax(84px, 1fr)); gap:6px; margin-top:6px } .time { min-height:38px; padding:4px 6px; border:1px solid var(--da-line); border-radius:999px; background:var(--da-bubble); color:var(--da-text); font:inherit; font-size:13px; cursor:pointer; display:flex; flex-direction:column; align-items:center; justify-content:center; line-height:1.15 } .time:hover { border-color:var(--da-accent) } .time.off { opacity:.45; cursor:default; border-style:dashed } .time.off s { color:var(--da-muted) } .time.off small { font-size:9px; text-transform:uppercase; letter-spacing:.03em; color:var(--da-muted) }
  .tzn { margin-top:8px }
  .bform { display:flex; flex-direction:column; gap:8px; margin-top:12px; padding-top:12px; border-top:1px solid var(--da-line) } .bform input, .bform textarea { min-height:40px; padding:8px 12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-bg); color:var(--da-text); font:inherit; font-size:14px; resize:vertical } .bform input:focus, .bform textarea:focus { outline:none; border-color:var(--da-accent) }
  .bsum { margin-top:12px; padding-top:12px; border-top:1px solid var(--da-line) } .srow { display:flex; justify-content:space-between; gap:12px; padding:6px 0; border-bottom:1px solid var(--da-line); font-size:14px } .srow span { color:var(--da-muted); flex:none } .srow b { font-weight:500; text-align:right; min-width:0; overflow-wrap:anywhere }
  .booked .bk-title { font-size:16px; font-weight:700 } .booked .bk-when { font-size:15px; margin-top:6px } .booked .bk-sub { font-size:12px; color:var(--da-muted); margin-top:2px }
.hform { display:flex; flex-direction:column; gap:8px; margin:12px 0 0; max-width:420px } .hform .lbl { font-size:12px; color:var(--da-muted) }
.hform input, .hform textarea { min-height:40px; padding:8px 12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-panel); color:var(--da-text); font:inherit; font-size:14px; resize:vertical } .hform .hrow { display:flex; gap:12px; align-items:center; flex-wrap:wrap }
.suggest { display:flex; flex-wrap:wrap; gap:8px } .chip { height:36px; padding:0 14px; border:1px solid var(--da-line); background:var(--da-bubble); border-radius:999px; color:var(--da-text); cursor:pointer; font-size:14px } .chip:hover { border-color:var(--da-muted) }
/* composer: 12px from the edges, 12px inside, 14px radius, accent border on focus */
.composer { flex:none; padding:8px 12px 0; background:var(--da-bg); position:relative }
.cbox { border:1px solid var(--da-cbox-line); border-radius:14px; background:var(--da-cbox); padding:12px; transition:border-color .15s, box-shadow .15s } .cbox.focus { border-color:rgba(242,140,40,.45); box-shadow:0 0 0 3px rgba(242,140,40,.12) } .cbox.drop { border-color:var(--da-mint); background:var(--da-bubble) }
.attach { display:flex; flex-wrap:wrap; gap:6px; padding:0 0 8px } .achip { display:inline-flex; align-items:center; gap:6px; max-width:100%; padding:4px 6px 4px 8px; border-radius:10px; background:var(--da-bubble); font-size:12px; position:relative; overflow:hidden }
.achip img { width:28px; height:28px; border-radius:6px; object-fit:cover } .achip .nm { max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap } .achip .sz { color:var(--da-muted); font-size:11px } .achip .x { width:22px; height:22px; border:0; background:transparent; color:var(--da-muted); cursor:pointer; border-radius:6px } .achip .x:hover { color:var(--da-text); background:var(--da-bubble-2) }
.achip .bar { position:absolute; left:0; bottom:0; height:2px; background:var(--da-mint); width:0; transition:width .2s } .achip.err { outline:1px solid var(--da-danger) }
textarea.q { display:block; width:100%; resize:none; min-height:30px; max-height:110px; padding:10px 0 0; border:0; background:transparent; color:var(--da-text); font:inherit; font-size:14px; line-height:20px; outline:none; caret-color:#F28C28 } textarea.q::placeholder { color:var(--da-muted) }
.crow { display:flex; align-items:center; gap:2px; margin-top:8px } .crow .sp { flex:1 } .crow .icon { width:30px; height:30px; border-radius:8px; color:#8A8D93 } .crow .icon:hover { color:#FFFFFF; background:var(--da-bubble) } .crow .icon svg { width:18px; height:18px }
.speak { display:inline-flex; align-items:center; gap:8px; height:34px; padding:0 14px; border:0; border-radius:999px; background:linear-gradient(135deg, var(--voice-gradient-start) 0%, var(--voice-gradient-mid) 55%, var(--voice-gradient-end) 100%); color:#FFFFFF; font-weight:600; font-size:13px; cursor:pointer; white-space:nowrap; box-shadow:0 4px 14px var(--voice-glow); transition:filter .15s, transform .15s } .speak svg { width:16px; height:16px }
.speak:hover { filter:brightness(1.08); transform:translateY(-1px) } .speak:active { transform:scale(.98) }
.speak svg path { transform-origin:center; transform-box:fill-box } .speak:hover svg path { animation:da-bars .9s ease-in-out infinite } .speak:hover svg path:nth-child(2) { animation-delay:.1s } .speak:hover svg path:nth-child(3) { animation-delay:.2s } .speak:hover svg path:nth-child(4) { animation-delay:.3s } .speak:hover svg path:nth-child(5) { animation-delay:.4s }
@keyframes da-bars { 0%,100% { transform:scaleY(1) } 50% { transform:scaleY(1.6) } }
@media (prefers-reduced-motion: reduce) { .speak:hover svg path { animation:none } .speak:hover { transform:none } }
.send { width:34px; height:34px; border-radius:50%; border:0; background:linear-gradient(135deg, var(--voice-gradient-start) 0%, var(--voice-gradient-mid) 55%, var(--voice-gradient-end) 100%); color:#FFFFFF; display:inline-flex; align-items:center; justify-content:center; cursor:pointer; flex:none; box-shadow:0 4px 14px var(--voice-glow) } .send svg { width:18px; height:18px } .send.stop { background:var(--da-bubble-2); color:var(--da-danger); box-shadow:none }
.rec { display:none; align-items:center; gap:8px; padding:4px 0 0; font-size:12px; color:var(--da-danger) } .rec.on { display:flex } .rec i { width:8px; height:8px; border-radius:50%; background:var(--da-danger); animation:da-blink 1s steps(2,start) infinite } @keyframes da-blink { to { visibility:hidden } }
.khint { height:0; overflow:hidden; margin:0 12px; font-size:11px; line-height:16px; color:var(--da-muted); opacity:0; transition:opacity .15s, height .15s } .khint.show { height:16px; opacity:1; margin-top:6px }
.foot { flex:none; text-align:center; font-size:11px; line-height:1.4; color:var(--da-muted); padding:8px 12px } .foot a { color:var(--da-muted) }
.pop { position:absolute; left:12px; right:12px; bottom:calc(100% - 4px); z-index:6; background:var(--da-panel); border:1px solid var(--da-line); border-radius:14px; box-shadow:var(--da-shadow); padding:12px; display:none } .pop.open { display:block }
.pop .search { width:100%; height:36px; padding:0 10px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-bg); color:var(--da-text); font:inherit; font-size:14px; margin-bottom:8px }
.egrid { display:grid; grid-template-columns:repeat(8, 1fr); gap:2px; max-height:190px; overflow-y:auto } .egrid button { height:36px; border:0; background:transparent; border-radius:8px; font-size:20px; cursor:pointer } .egrid button:hover { background:var(--da-bubble) }
.ggrid { display:grid; grid-template-columns:repeat(3, 1fr); gap:6px; max-height:230px; overflow-y:auto } .ggrid button { padding:0; border:0; background:var(--da-bubble); border-radius:10px; overflow:hidden; cursor:pointer; aspect-ratio:4/3 } .ggrid img { width:100%; height:100%; object-fit:cover; display:block } .pop .empty { font-size:12px; color:var(--da-muted); padding:12px 4px; text-align:center }
/* voice */
.voice { position:absolute; inset:0; z-index:7; background:var(--da-bg); display:none; flex-direction:column; align-items:center; padding:0; text-align:center; overflow:hidden } .voice.open { display:flex }
.voice .logo { width:72px; height:72px } .voice .logo svg { width:34px; height:34px }
.wave { display:flex; align-items:center; gap:4px; height:40px } .wave i { width:5px; height:10px; border-radius:3px; background:linear-gradient(180deg, var(--da-mint), var(--da-sky)); animation:da-wave 1s ease-in-out infinite } .wave i:nth-child(2n) { animation-delay:.15s } .wave i:nth-child(3n) { animation-delay:.3s } .wave.idle i { animation-play-state:paused; height:6px; opacity:.5 }
@keyframes da-wave { 0%,100% { height:8px } 50% { height:34px } }
.vstatus { font-size:15px; color:var(--da-muted) } .vtext { font-size:14px; color:var(--da-text); max-width:320px; min-height:20px } .vbtns { display:flex; gap:12px } .vbtns .btn { min-width:110px; justify-content:center }
/* Messages */
.mlist { flex:1; min-height:0; overflow-y:auto; overflow-x:hidden; padding:12px 0 64px }
.msearch { display:block; width:calc(100% - 32px); margin:0 16px 12px; height:36px; padding:0 12px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-panel); color:var(--da-text); font:inherit; font-size:14px } .msearch:focus { outline:none; border-color:var(--da-accent) } .msearch::placeholder { color:var(--da-muted) }
.mgroup { margin:8px 16px 4px; font-size:11px; font-weight:600; letter-spacing:.05em; text-transform:uppercase; color:var(--da-muted) } .mgroup:first-of-type { margin-top:0 }
.mempty { padding:24px 16px; font-size:13px; color:var(--da-muted); text-align:center }
.shortcut { display:flex; align-items:center; gap:12px; padding:12px 16px; margin:0 16px 12px; border:1px solid var(--da-line); border-radius:14px; background:var(--da-panel); color:var(--da-text); text-decoration:none; min-width:0 } .shortcut:hover { border-color:var(--da-muted) } .shortcut .t { flex:1; min-width:0 } .shortcut .t b { display:block; font-size:14px } .shortcut .t span { font-size:12px; color:var(--da-muted) } .shortcut svg { width:18px; height:18px; color:var(--da-muted); flex:none }
.convo { position:relative; display:flex; align-items:center; gap:12px; width:100%; min-width:0; padding:12px 16px; border:0; border-bottom:1px solid var(--da-line); background:transparent; color:var(--da-text); cursor:pointer; text-align:left; overflow:hidden } .convo:hover { background:var(--da-panel) } .convo:last-child { border-bottom:0 }
.avatar { flex:none; width:32px; height:32px; border-radius:50%; background:var(--da-accent); color:#1A1208; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px } .avatar svg { width:16px; height:16px } .shortcut .avatar { width:36px; height:36px } .shortcut .avatar svg { width:18px; height:18px }
.convo .c { flex:1 1 auto; min-width:0; overflow:hidden } .convo .n { display:block; font-weight:600; font-size:14px; line-height:1.35; color:var(--da-text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.convo .p { display:block; color:var(--da-muted); font-size:12px; line-height:1.35; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px } .convo.unread .n { color:var(--da-text) }
.convo .r { flex:none; display:flex; flex-direction:column; align-items:flex-end; gap:6px; min-width:32px; align-self:flex-start; padding-top:2px } .convo .time { font-size:12px; color:var(--da-muted); white-space:nowrap } .dot { width:8px; height:8px; border-radius:50%; background:var(--da-accent) }
.convo .more2 { position:absolute; right:40px; top:50%; transform:translateY(-50%); width:28px; height:28px; border:0; border-radius:8px; background:transparent; color:var(--da-muted); display:none; align-items:center; justify-content:center; cursor:pointer } .convo .more2 svg { width:16px; height:16px } .convo:hover .more2, .convo:focus-within .more2 { display:inline-flex } .convo .more2:hover { background:var(--da-bubble); color:var(--da-text) } .convo:hover .r, .convo:focus-within .r { visibility:hidden }
.rename { display:flex; gap:8px; align-items:center; padding:8px 16px 8px 60px; border-bottom:1px solid var(--da-line) } .rename input { flex:1; min-width:0; height:34px; padding:0 10px; border:1px solid var(--da-accent); border-radius:8px; background:var(--da-bg); color:var(--da-text); font:inherit; font-size:14px; outline:none }
.empty { padding:48px 16px 20px; text-align:center; color:var(--da-muted); font-size:14px } .empty b { display:block; color:var(--da-text); font-size:16px; margin-bottom:6px }
.fab { position:absolute; left:50%; bottom:16px; transform:translateX(-50%); display:inline-flex; align-items:center; gap:8px; height:40px; padding:0 16px; border-radius:999px; border:0; background:var(--da-accent); color:#1A1208; font-weight:600; font-size:14px; cursor:pointer; box-shadow:0 10px 30px rgba(0,0,0,.35); white-space:nowrap } .fab svg { width:18px; height:18px }
.help { flex:1; min-height:0; overflow-y:auto; padding:16px } .help h2 { margin:16px 0 8px; font-size:11px; color:var(--da-muted); font-weight:500; text-transform:uppercase; letter-spacing:.05em } .help h2:first-child { margin-top:0 } .help .stack { display:flex; flex-direction:column; gap:8px } .help .btn { justify-content:space-between } .help .btn svg { width:16px; height:16px; color:var(--da-muted) }
/* bottom tabs: 56px, Home and Messages screens only */
.tabs { flex:none; display:flex; height:56px; border-top:1px solid var(--da-line); background:var(--da-bg); padding-bottom:env(safe-area-inset-bottom) }
.tab { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:4px; padding:0 4px; border:0; background:transparent; color:var(--da-muted); cursor:pointer; font-size:11px; line-height:1; position:relative } .tab svg { width:20px; height:20px } .tab.on { color:var(--da-text) } .tab:hover { color:var(--da-text) }
.tab .badge { position:absolute; top:6px; left:calc(50% + 6px); min-width:17px; height:17px; padding:0 5px; border-radius:999px; background:var(--da-danger); color:#fff; font:700 10.5px/17px system-ui, sans-serif; text-align:center }
.vh { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap }
/* ---- agent UI (docs/AGENT_UI.md) */
.orb-mini { width:36px; height:36px; border-radius:50%; flex:none; position:relative; background:radial-gradient(circle at 35% 32%, #FFD9B0 0%, #F28C28 32%, #FF6A3D 62%, #E9487A 100%); box-shadow:0 0 0 0 rgba(242,140,40,.0), 0 4px 14px rgba(255,106,61,.25); animation:da-breathe 3.6s ease-in-out infinite }
.orb-mini.work { animation:da-pulse 1.1s ease-in-out infinite } .orb-mini.call { animation:da-pulse 1.8s ease-in-out infinite; background:radial-gradient(circle at 35% 32%, #FFF3E3 0%, #FFB45E 32%, #FF7A3D 62%, #FF5F8E 100%) }
@keyframes da-breathe { 0%,100% { transform:scale(1); box-shadow:0 0 0 0 rgba(242,140,40,0), 0 4px 14px rgba(255,106,61,.22) } 50% { transform:scale(1.04); box-shadow:0 0 0 4px rgba(242,140,40,.10), 0 6px 18px rgba(255,106,61,.32) } }
@keyframes da-pulse { 0%,100% { transform:scale(1); box-shadow:0 0 0 0 rgba(242,140,40,.0) } 50% { transform:scale(1.09); box-shadow:0 0 0 6px rgba(242,140,40,.16) } }
.st { display:inline-flex; align-items:center; gap:5px; margin-left:8px; font:500 11px/1 system-ui, sans-serif; color:var(--da-muted); vertical-align:middle; white-space:nowrap } .st i { width:6px; height:6px; border-radius:50%; background:var(--da-ok) } .st.work i { background:var(--da-accent); animation:da-blink2 1s ease-in-out infinite } .st.call i { background:var(--da-danger); animation:da-blink2 1.4s ease-in-out infinite }
@keyframes da-blink2 { 50% { opacity:.3 } }
.vpill { display:none; align-items:center; gap:6px; height:28px; padding:0 10px; border-radius:999px; border:1px solid var(--da-line); background:var(--da-bubble); color:var(--da-text); font-size:12px; cursor:pointer; flex:none } .vpill.show { display:inline-flex } .vpill i { width:6px; height:6px; border-radius:50%; background:var(--da-danger); animation:da-blink2 1s infinite } .vpill:hover { border-color:var(--da-muted) }
.activity { display:inline-flex; align-items:center; gap:10px; margin:0 0 6px; padding:8px 14px; border-radius:16px; background:var(--da-bubble); font-size:13px; color:var(--da-muted); max-width:100%; animation:da-in .2s ease-out both } .activity .orb { width:14px; height:14px; border-radius:50%; flex:none; background:radial-gradient(circle at 35% 32%, #FFD9B0 0%, #F28C28 40%, #E9487A 100%); animation:da-pulse 1.1s ease-in-out infinite }
.activity .lbl { background:linear-gradient(90deg, var(--da-muted) 0%, var(--da-text) 50%, var(--da-muted) 100%); background-size:200% 100%; -webkit-background-clip:text; background-clip:text; color:transparent; animation:da-shimmer 1.6s linear infinite; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
@keyframes da-shimmer { from { background-position:200% 0 } to { background-position:-200% 0 } }
.worked { display:inline-flex; align-items:center; gap:6px; margin:0 0 6px; padding:0; border:0; background:transparent; color:var(--da-muted); font:inherit; font-size:12px; cursor:pointer; animation:da-in .25s ease-out both } .worked:hover { color:var(--da-text) } .worked svg { width:12px; height:12px; transition:transform .2s } .worked.open svg { transform:rotate(90deg) }
.steps { display:none; margin:-2px 0 8px 4px; font-size:12px; color:var(--da-muted); line-height:1.5 } .steps.open { display:block } .steps div { display:flex; gap:10px } .steps b { font-weight:500; min-width:40px; text-align:right; font-variant-numeric:tabular-nums; color:var(--da-muted); opacity:.8 }
.msg.skel { padding:14px 16px; min-width:200px; max-width:260px } .skel .ln { height:10px; border-radius:6px; margin:7px 0; background:linear-gradient(90deg, var(--da-bubble-2) 25%, var(--da-line) 50%, var(--da-bubble-2) 75%); background-size:200% 100%; animation:da-shimmer 1.4s linear infinite } .skel .ln:nth-child(2) { width:85% } .skel .ln:nth-child(3) { width:60% }
.tok { animation:da-tok .15s ease-out both } @keyframes da-tok { from { opacity:0; filter:blur(2px) } to { opacity:1; filter:blur(0) } }
.msg.streaming::after { content:""; display:inline-block; width:2px; height:1em; margin-left:2px; vertical-align:-2px; background:var(--da-accent); animation:da-caret 1s steps(2, start) infinite } @keyframes da-caret { to { visibility:hidden } }
@keyframes da-in { from { opacity:0; transform:translateY(4px) } to { opacity:1; transform:none } }
.sources.in { animation:da-in .25s .06s ease-out both } .tools.in { animation:da-in .25s .12s ease-out both } .meta.in { animation:da-in .25s ease-out both } .ctx.in { animation:da-in .25s ease-out both }
.card, .slots, .handoff, .picker, .hform, .booked, .actcard, .avail { animation:da-pop .25s cubic-bezier(.16,1,.3,1) both } @keyframes da-pop { from { opacity:0; transform:scale(.96) } to { opacity:1; transform:none } }
.chk { width:26px; height:26px; flex:none } .chk circle { stroke:var(--da-ok); stroke-width:2; fill:none; stroke-dasharray:80; stroke-dashoffset:80; animation:da-draw .5s ease-out forwards } .chk path { stroke:var(--da-ok); stroke-width:2.4; fill:none; stroke-linecap:round; stroke-linejoin:round; stroke-dasharray:30; stroke-dashoffset:30; animation:da-draw .35s .35s ease-out forwards } @keyframes da-draw { to { stroke-dashoffset:0 } }
.booked .bk-title { display:flex; align-items:center; gap:8px }
.actcard { display:flex; align-items:center; gap:10px; margin:10px 0 0; padding:8px 12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-panel); font-size:13px; max-width:100% } .actcard .ai { width:28px; height:28px; border-radius:8px; background:var(--da-bubble); display:flex; align-items:center; justify-content:center; flex:none; color:var(--da-muted) } .actcard .ai svg { width:16px; height:16px }
.actcard .at { flex:1; min-width:0 } .actcard .at b { display:block; font-weight:600; font-size:13px } .actcard .at span { display:block; font-size:12px; color:var(--da-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.actcard .as { flex:none; display:inline-flex; align-items:center; gap:5px; font-size:12px; color:var(--da-muted) } .actcard.run .as i { width:8px; height:8px; border-radius:50%; background:var(--da-accent); animation:da-blink2 1s infinite } .actcard.ok .as { color:var(--da-ok) } .actcard.ok .ai { color:var(--da-ok) } .actcard.fail .as { color:var(--da-danger) } .actcard.fail .ai { color:var(--da-danger) }
.ctx { display:inline-flex; align-items:center; gap:6px; margin:0 0 6px 4px; height:24px; padding:0 10px; border:1px solid var(--da-line); border-radius:999px; background:transparent; color:var(--da-muted); font:inherit; font-size:12px; cursor:pointer; align-self:flex-start } .ctx:hover { color:var(--da-text); border-color:var(--da-muted) } .ctx svg { width:12px; height:12px; transition:transform .2s } .ctx.open svg { transform:rotate(90deg) } .sources.hide { display:none }
.caps-row { max-width:100%; width:100% } .caps { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:8px } .cap { display:flex; flex-direction:column; gap:6px; padding:10px 12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-panel); color:var(--da-text); text-align:left; cursor:pointer; font:inherit; font-size:13px; line-height:1.3; min-width:0 } .cap svg { width:18px; height:18px; color:var(--da-accent) } .cap span { overflow-wrap:anywhere }
.btn, .chip, .time, .date, .ctype, .cap, .vbtn, .tab, .worked, .ctx { position:relative; overflow:hidden } .btn, .chip, .card, .ctype, .date, .time, .cap { transition:transform .15s, border-color .15s, box-shadow .15s }
.chip:hover, .ctype:hover, .cap:hover, .date:not(.off):hover, .time:not(.off):hover, .btn:not(:disabled):hover { transform:translateY(-1px); box-shadow:0 4px 14px rgba(0,0,0,.22) }
.rip { position:absolute; border-radius:50%; transform:scale(0); background:currentColor; opacity:.18; pointer-events:none; animation:da-ripple .5s ease-out forwards } @keyframes da-ripple { to { transform:scale(2.6); opacity:0 } }
textarea.q { transition:height .15s ease } .cbox.busy { border-color:rgba(242,140,40,.35); animation:da-glow 1.6s ease-in-out infinite } @keyframes da-glow { 0%,100% { box-shadow:0 0 0 3px rgba(242,140,40,.08), 0 0 18px rgba(242,140,40,.12) } 50% { box-shadow:0 0 0 3px rgba(242,140,40,.16), 0 0 30px rgba(242,140,40,.26) } }
/* voice call view */
.vhead { flex:none; width:100%; height:52px; display:flex; align-items:center; gap:8px; padding:0 8px 0 16px; border-bottom:1px solid var(--da-line); font-size:14px } .vhead b { font-family:"IBM Plex Mono", ui-monospace, monospace; font-weight:600 } .vhead .live { width:8px; height:8px; border-radius:50%; background:var(--da-ok); animation:da-live 1.6s ease-out infinite } .vhead .vtimer { margin-left:auto; font:500 13px/1 ui-monospace, monospace; color:var(--da-muted); font-variant-numeric:tabular-nums }
@keyframes da-live { 0% { box-shadow:0 0 0 0 rgba(92,203,138,.55) } 100% { box-shadow:0 0 0 8px rgba(92,203,138,0) } }
.vbody { flex:1; min-height:0; width:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:14px; padding:12px 16px; position:relative } .vglow { position:absolute; inset:0; pointer-events:none; background:radial-gradient(circle at 50% 44%, var(--vglow, rgba(242,140,40,.26)) 0%, transparent 52%); opacity:var(--vglow-o, .6); transition:opacity .4s }
.vorb { position:relative; width:220px; height:220px; display:flex; align-items:center; justify-content:center } .vorb canvas { width:220px; height:220px; display:block } .vorb.static { width:160px; height:160px; border-radius:50%; background:radial-gradient(circle at 35% 32%, #FFD9B0 0%, #F28C28 32%, #FF6A3D 62%, #E9487A 100%); transition:opacity .4s, filter .4s } .voice.muted .vorb.static { filter:grayscale(1); opacity:.6 }
.vmute-badge { position:absolute; bottom:6px; left:50%; transform:translateX(-50%); font-size:11px; padding:2px 8px; border-radius:999px; background:var(--da-bubble-2); color:var(--da-muted); display:none; z-index:1 } .voice.muted .vmute-badge { display:block }
.voice .vstatus { font-size:15px; color:var(--da-muted); min-height:20px; transition:opacity .25s, transform .25s } .voice .vstatus.sw { opacity:0; transform:translateY(3px) }
.vcap { width:min(360px, 100%); min-height:46px; max-height:46px; overflow:hidden; display:flex; flex-direction:column; justify-content:flex-end; gap:3px; font-size:14px; line-height:1.45; text-align:center } .vcap .cu { color:var(--da-muted); font-style:italic; white-space:nowrap; overflow:hidden; text-overflow:ellipsis } .vcap .ca { color:var(--da-text) } .vcap .ca .w { opacity:.28; transition:opacity .12s } .vcap .ca .w.on { opacity:1 } .vcap.off { visibility:hidden } .vcap:empty { display:none }
.vctl { flex:none; display:flex; justify-content:center; align-items:center; gap:16px; padding:12px 16px calc(24px + env(safe-area-inset-bottom)) }
.vbtn { width:56px; height:56px; border-radius:50%; border:0; background:var(--da-bubble-2); color:var(--da-text); display:inline-flex; align-items:center; justify-content:center; cursor:pointer; flex:none; transition:background .2s, color .2s, transform .15s } .vbtn svg { width:24px; height:24px } .vbtn:hover { transform:translateY(-1px) } .vbtn:active { transform:scale(.96) } .vbtn.on { background:#FFFFFF; color:#1A1208 } .vbtn.end { background:var(--da-danger); color:#FFFFFF } .vbtn.end:hover { background:#F05A5F } .vbtn.cc.off { color:var(--da-muted) }
.vbtn .tip { position:absolute; bottom:calc(100% + 8px); left:50%; transform:translateX(-50%); background:var(--da-bubble-2); color:var(--da-text); font-size:11px; padding:3px 7px; border-radius:6px; white-space:nowrap; opacity:0; pointer-events:none; transition:opacity .15s } .vbtn:hover .tip, .vbtn:focus-visible .tip { opacity:1 }
.voice.closing .vorb { animation:da-collapse .35s ease-in forwards } @keyframes da-collapse { to { transform:scale(.15); opacity:0 } }
.callcard .cc-t { display:flex; align-items:center; gap:8px; font-size:14px; font-weight:600 } .callcard .cc-t svg { width:16px; height:16px; color:var(--da-accent) } .callcard .cc-s { font-size:12px; color:var(--da-muted); margin-top:2px }
@media (prefers-reduced-motion: reduce) {
  .orb-mini, .activity .orb, .activity .lbl, .skel .ln, .tok, .msg.streaming::after, .card, .slots, .handoff, .picker, .hform, .booked, .actcard, .avail, .sources.in, .tools.in, .meta.in, .ctx.in, .activity, .worked, .cbox.busy, .vhead .live, .chk circle, .chk path, .rip, .actcard.run .as i, .vpill i, .st.work i, .st.call i, .voice.closing .vorb { animation:none }
  .tok { opacity:1; filter:none } .chk circle, .chk path { stroke-dashoffset:0 } .activity .lbl { color:var(--da-muted); background:none; -webkit-text-fill-color:var(--da-muted) } .msg.streaming::after { visibility:visible }
  .cap:hover, .chip:hover, .ctype:hover, .date:hover, .time:hover, .vbtn:hover, .btn:hover { transform:none; box-shadow:none } textarea.q, .vstatus, .vglow, .vbtn { transition:none } .cbox.busy { box-shadow:0 0 0 3px rgba(242,140,40,.12) }
}

`;

const SVG = {
  mark: '<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M1 7V1h6M15 1h6v6M21 15v6h-6M7 21H1v-6"/><circle cx="11" cy="11" r="3"/><path d="M11 4v3M11 15v3M4 11h3M15 11h3"/></svg>',
  more: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/></svg>',
  up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M7 11v9H4v-9h3zm3 9h7.5a2 2 0 0 0 2-1.6l1.2-6A2 2 0 0 0 18.7 10H14V6a2 2 0 0 0-2-2l-2 7v9z"/></svg>',
  down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M17 13V4h3v9h-3zm-3-9H6.5a2 2 0 0 0-2 1.6l-1.2 6A2 2 0 0 0 5.3 14H10v4a2 2 0 0 0 2 2l2-7V4z"/></svg>',
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/></svg>',
  messages: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 5h16v11H8l-4 4z"/></svg>',
  help: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01"/></svg>',
  ext: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>',
  theme: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9c-5 0-9-4-9-9z"/></svg>',
  dl: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M4 20h16"/></svg>',
  reset: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 12a8 8 0 1 1 2.3 5.7M4 20v-5h5"/></svg>',
  clip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M21 11.5l-8.5 8.5a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8"/></svg>',
  emoji: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01"/></svg>',
  gif: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3"/><text x="12" y="15.5" text-anchor="middle" font-size="7.5" font-weight="700" fill="currentColor" stroke="none" font-family="system-ui, sans-serif">GIF</text></svg>',
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/></svg>',
  wave: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M4 11.5v1"/><path d="M8 8v8"/><path d="M12 5v14"/><path d="M16 8v8"/><path d="M20 11v2"/></svg>',
  question: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01"/></svg>',
  mute: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M4 4l16 16"/></svg>',
  end: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 14c4-3 12-3 16 0l-2 3c-3-2-9-2-12 0z"/></svg>',
  hangup: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 9c-2.6 0-5 .5-7.2 1.5-.6.3-.9.9-.8 1.5l.5 2.6c.1.6.7 1 1.3.9l2.8-.6c.5-.1.9-.5 1-1l.3-1.6c.7-.2 1.4-.3 2.1-.3s1.4.1 2.1.3l.3 1.6c.1.5.5.9 1 1l2.8.6c.6.1 1.2-.3 1.3-.9l.5-2.6c.1-.6-.2-1.2-.8-1.5C17 9.5 14.6 9 12 9z"/></svg>',
  micoff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M9 9v5a3 3 0 0 0 5.1 2.1M15 11V6a3 3 0 0 0-6 0M5 11a7 7 0 0 0 11 5.7M19 11a7 7 0 0 1-.6 2.8M12 18v3M9 21h6M4 4l16 16"/></svg>',
  cc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10.5 10.5a2 2 0 1 0 0 3M17 10.5a2 2 0 1 0 0 3"/></svg>',
  min: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 10l6 6 6-6"/></svg>',
  chev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>',
  cal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
  mail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 8l9 6 9-6"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>',
  spark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M5 4h3.5l1.5 4-2 1.5a12 12 0 0 0 6.5 6.5L16 14l4 1.5V19a1 1 0 0 1-1 1A15 15 0 0 1 4 5a1 1 0 0 1 1-1z"/></svg>',
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
  t = t.replace(/(^|[^"=])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  t = t.replace(/^(?:[-*•]\s+)(.*)$/gm, '<span class="li">$1</span>');
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

class DeepAssistant extends HTMLElement {
  static get observedAttributes() { return ['api', 'token', 'theme', 'mode', 'open', 'title', 'subtitle', 'suggestions', 'user-name', 'user-email', 'tabs', 'shortcut', 'privacy-url', 'greeting']; }
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._history = []; this._transcript = []; this._busy = false; this._controller = null; this._me = null; this._rendered = false; this._pickerSeq = 0;
    this._view = 'chat'; this._fromMessages = false; this._unread = 0; this._attachments = []; this._cfg = { gif: false, stt: 'browser', tts: 'browser', upload_max_mb: 10, upload_types: [] };
    this._voice = null; this._rec = null;
    this.tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const rm = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null; this._reduced = !!(rm && rm.matches); if (rm && rm.addEventListener) rm.addEventListener('change', (e) => { this._reduced = e.matches; });
  }
  // ---------------------------------------------------------------- public API
  get api() { return (this.getAttribute('api') || '').replace(/\/+$/, ''); }
  get busy() { return this._busy; }
  get sessionId() { return this._sid; }
  get view() { return this._view; }
  get botName() { return this.getAttribute('title') || 'deep >_'; }
  ask(text) { this.showView('chat'); return this._send(text); }
  open() { this.setAttribute('open', ''); }
  close() { this.removeAttribute('open'); }
  toggle() { this.hasAttribute('open') ? this.close() : this.open(); }
  setToken(token) { if (token) this.setAttribute('token', token); else this.removeAttribute('token'); }
  reset() { this.newChat(); }
  newChat() {
    if (this._busy) this._stop(); this.stopVoice();
    this._sid = uuid(); store.set(this._key('sid'), this._sid);
    this._transcript = []; this._history = []; this._fromMessages = false; this._attachments = []; this._renderAttachments();
    this.$log.innerHTML = ''; this._restore(); this._track(); this.showView('chat'); this.$q.focus();
  }
  download() {
    const lines = this._transcript.map((m) => `[${new Date(m.ts).toLocaleString()}] ${m.role === 'user' ? 'You' : this.botName}: ${plain(m.text)}${m.sources && m.sources.length ? '\n  sources: ' + m.sources.map((s) => s.url).join(', ') : ''}`);
    const blob = new Blob([`${this.botName} transcript · ${new Date().toLocaleString()} · conversation ${this._sid}\n\n` + lines.join('\n\n')], { type: 'text/plain' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `deep-chat-${new Date().toISOString().slice(0, 10)}.txt`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  switchTheme() { const cur = this.getAttribute('theme') || 'dark'; const next = cur === 'light' ? 'dark' : 'light'; this.setAttribute('theme', next); local.set('da_theme', next); }
  showView(name) {
    if (!['chat', 'messages', 'help'].includes(name)) return;
    this._view = name; this.$panel.dataset.view = name; const sh = this.shadowRoot;
    sh.querySelector('.view-chat').hidden = name !== 'chat'; sh.querySelector('.view-messages').hidden = name !== 'messages'; sh.querySelector('.view-help').hidden = name !== 'help';
    sh.querySelector('.orb-mini.hl').hidden = name !== 'chat'; sh.querySelector('.brand').hidden = name !== 'chat'; sh.querySelector('.more').hidden = name !== 'chat'; sh.querySelector('.spacer').hidden = name === 'chat';
    this._updateChrome();
    const vt = sh.querySelector('.vtitle'); vt.hidden = name === 'chat'; vt.textContent = name === 'messages' ? 'Messages' : 'Help';
    sh.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', (t.dataset.tab === 'home' && name === 'chat') || t.dataset.tab === name));
    this._closePops();
    if (name === 'messages') this._renderConversations();
    if (name === 'chat') setTimeout(() => this.$q.focus(), 30);
    this._emit('view', { view: name });
  }
  async openConversation(sid) {
    if (!sid) return;
    if (sid !== this._sid) {
      if (this._busy) this._stop();
      let h = null;
      try { const r = await fetch(this._url('/conversations/' + encodeURIComponent(sid)), { headers: this._headers(false) }); if (r.ok) h = await r.json(); } catch {}
      if (!h) return;
      this._sid = sid; store.set(this._key('sid'), sid);
      this.$log.innerHTML = ''; this._transcript = []; this._history = [];
      h.messages.forEach((m) => {
        const el = this._add(m.role === 'user' ? 'user' : 'bot', '', m.ts);
        if (m.role === 'user') { this._setText(el, m.text); this._transcript.push({ role: 'user', text: m.text, ts: new Date(m.ts).getTime() }); }
        else { const srcs = usedSources(m.text, m.sources || []); this._setText(el, m.text, m.sources || []); this._addSources(el, srcs); this._addTools(el, () => plain(m.text), null, m.id, m.feedback);
          this._transcript.push({ role: 'bot', text: m.text, sources: srcs, ts: new Date(m.ts).getTime(), mid: m.id, fb: m.feedback }); }
      });
      this._history = this._transcript.map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text })).slice(-12);
      this._persist();
    }
    this._fromMessages = true; this.showView('chat'); this._markRead(sid).then(() => this._refreshBadge());
  }
  // ---------------------------------------------------------------- lifecycle
  connectedCallback() { if (!this._rendered) this._render(); }
  attributeChangedCallback(name) {
    if (!this._rendered) return;
    if (name === 'open') this._applyOpen();
    else if (name === 'token' || name === 'user-name' || name === 'user-email') this._loadMe().then(() => this._refreshBadge());
    else if (name === 'title' || name === 'subtitle') this._applyCopy();
    else if (name === 'api') { this._health(); this._loadConfig(); }
    else if (name === 'tabs') this._renderTabs();
    else if (name === 'privacy-url') this._applyFooter();
    else if (name === 'shortcut' && this._view === 'messages') this._renderConversations();
  }
  _updateChrome() {
    const inConvo = this._view === 'chat' && this._transcript.some((m) => m.role === 'user');
    this.$back.hidden = !inConvo;
    const nav = this.shadowRoot.querySelector('.tabs'); nav.hidden = this._tabs().length < 2 || inConvo;
  }
  _toast(text) { let el = this.shadowRoot.querySelector('.toastmsg'); if (!el) { el = document.createElement('div'); el.className = 'toastmsg'; el.setAttribute('role', 'status'); this.$panel.appendChild(el); } el.textContent = text; el.classList.add('show'); clearTimeout(this._toastT); this._toastT = setTimeout(() => el.classList.remove('show'), 1800); }
  _fbPopover(anchor, submit) {
    this.shadowRoot.querySelectorAll('.fbpop').forEach((p) => p.remove());
    const pop = document.createElement('form'); pop.className = 'fbpop'; pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', 'What was wrong?');
    pop.innerHTML = '<div class="reasons">' + ['Not accurate', 'Not helpful', 'Missing info', 'Other'].map((r) => '<button type="button" class="reason">' + r + '</button>').join('') + '</div><input maxlength="300" placeholder="Tell us more (optional)" aria-label="Details"><div class="fbrow"><button type="button" class="textbtn cancel">Cancel</button><button type="submit" class="textbtn submit">Submit</button></div>';
    let reason = ''; pop.querySelectorAll('.reason').forEach((r) => r.onclick = () => { reason = r.textContent; pop.querySelectorAll('.reason').forEach((x) => x.classList.toggle('on', x === r)); });
    pop.querySelector('.cancel').onclick = () => pop.remove();
    pop.onsubmit = async (e) => { e.preventDefault(); const note = [reason, pop.querySelector('input').value.trim()].filter(Boolean).join(': '); pop.remove(); await submit(note); };
    anchor.closest('.row').appendChild(pop); pop.querySelector('.reason').focus(); this._scroll();
  }
  _emit(name, detail) { this.dispatchEvent(new CustomEvent('deep-assistant:' + name, { detail: detail || {}, bubbles: true, composed: true })); }
  _key(s) { return 'da:' + this.api + ':' + s; }
  _url(p) { return this.api + p; }
  _headers(json = true) { const h = { 'X-Session-Id': this._sid }; if (json) h['Content-Type'] = 'application/json'; if (this._vid) h['X-Visitor-Id'] = this._vid; const t = this.getAttribute('token'); if (t) h['X-Visitor-Token'] = t; return h; }
  _tabs() { const raw = (this.getAttribute('tabs') || ALL_TABS.join(',')).split(',').map((s) => s.trim().toLowerCase()).filter((s) => ALL_TABS.includes(s)); if (!raw.includes('messages')) raw.push('messages'); return ALL_TABS.filter((t) => raw.includes(t)); }
  _shortcut() { const a = this.getAttribute('shortcut'); if (a === '') return null; const [label, href] = (a || DEFAULT_SHORTCUT).split('|'); return href ? { label: label.trim(), href: href.trim() } : null; }
  _render() {
    this._rendered = true; const sh = this.shadowRoot;
    if (!this.hasAttribute('theme')) this.setAttribute('theme', local.get('da_theme') || 'dark');
    sh.innerHTML = `<style>${CSS}</style>
<button class="launcher" part="launcher" type="button" aria-label="Open the assistant" aria-expanded="false">${SVG.mark}<span class="lbadge" hidden></span></button>
<section class="panel" part="panel" data-view="chat">
  <header>
    <button class="icon back" type="button" aria-label="Back to messages" title="Back" hidden>${SVG.back}</button>
    <span class="orb-mini hl" aria-hidden="true"></span>
    <div class="brand"><h1><span class="ttl"></span><span class="st"><i></i><span class="stt">Online</span></span></h1><p class="sub">Deep can also help directly</p></div>
    <button class="vpill" type="button" aria-label="Return to the voice call" title="Return to the call"><i></i><span>In a call</span></button>
    <h2 class="vtitle" hidden>Messages</h2><span class="spacer" hidden></span>
    <button class="icon more" type="button" aria-label="More options" title="More" aria-haspopup="menu" aria-expanded="false">${SVG.more}</button>
    <button class="icon close" type="button" aria-label="Close" title="Close">${SVG.close}</button>
    <div class="menu" role="menu">
      <button type="button" role="menuitem" data-act="theme">${SVG.theme}<span>Switch theme</span></button>
      <button type="button" role="menuitem" data-act="download">${SVG.dl}<span>Download transcript</span></button>
      <button type="button" role="menuitem" data-act="new">${SVG.reset}<span>New chat</span></button>
    </div>
  </header>
  <div class="views">
    <section class="view view-chat">
      <div class="log scroll" role="log" aria-live="polite" aria-label="Conversation"></div>
      <div class="composer">
        <div class="pop pop-emoji" role="dialog" aria-label="Emoji"><input class="search" placeholder="Search emoji" aria-label="Search emoji"><div class="egrid"></div></div>
        <div class="pop pop-gif" role="dialog" aria-label="GIFs"><input class="search" placeholder="Search GIFs" aria-label="Search GIFs"><div class="ggrid"></div><div class="empty" hidden></div></div>
        <form class="cbox">
          <div class="attach" hidden></div>
          <label class="vh" for="q">Your message</label>
          <textarea id="q" class="q" rows="1" placeholder="Ask about Deep, or say “book a call”"></textarea>
          <div class="rec" aria-live="polite"><i></i><span class="rlabel">Listening…</span><span class="rtime">0:00</span><button type="button" class="icon rstop" aria-label="Stop dictation" title="Stop">${SVG.stop}</button></div>
          <div class="crow">
            <input type="file" class="file" multiple hidden>
            <button type="button" class="icon b-clip" aria-label="Attach a file" title="Attach a file">${SVG.clip}</button>
            <button type="button" class="icon b-emoji" aria-label="Insert emoji" title="Emoji" aria-haspopup="dialog">${SVG.emoji}</button>
            <button type="button" class="icon b-gif" aria-label="Send a GIF" title="GIF" aria-haspopup="dialog">${SVG.gif}</button>
            <button type="button" class="icon b-mic" aria-label="Dictate with your microphone" title="Dictate">${SVG.mic}</button>
            <span class="sp"></span>
            <button type="button" class="speak" aria-label="Speak to Deep: start a voice conversation" title="Speak to Deep">${SVG.wave}<span>Speak to Deep</span></button>
            <button type="submit" class="send" aria-label="Send" title="Send" hidden><span class="i-send">${SVG.send}</span><span class="i-stop" hidden>${SVG.stop}</span></button>
          </div>
        </form>
        <div class="khint" aria-hidden="true">Enter to send · Shift+Enter for a new line · Esc to stop</div>
      </div>
      <div class="foot">By chatting with us, you agree to our <a class="privacy" href="#" target="_blank" rel="noopener">Privacy Policy</a></div>
    </section>
    <section class="view view-messages" hidden><div class="mlist scroll"><label class="vh" for="msearch">Search conversations</label><input id="msearch" class="msearch" type="search" placeholder="Search conversations" autocomplete="off"><div class="mhead"></div><div class="mrows" role="list" aria-label="Conversations"></div></div><button class="fab" type="button">${SVG.question}<span>Ask a question</span></button></section>
    <section class="view view-help" hidden><div class="help scroll"></div></section>
  </div>
  <nav class="tabs" aria-label="Assistant sections"></nav>
  <div class="voice" role="dialog" aria-label="Voice conversation">
    <div class="vhead"><b>ask deep &gt;_</b><span class="live" aria-hidden="true"></span><span class="vtimer" aria-label="Call duration">00:00</span><button type="button" class="icon v-min" aria-label="Minimize the call view (the call continues)" title="Minimize">${SVG.min}</button></div>
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
    this.$launcher = sh.querySelector('.launcher'); this.$close = sh.querySelector('.close'); this.$back = sh.querySelector('.back'); this.$cbox = sh.querySelector('.cbox'); this.$menu = sh.querySelector('.menu');
    this._sid = store.get(this._key('sid')) || uuid(); store.set(this._key('sid'), this._sid);
    this._vid = local.get('dh_vid') || (local.set('dh_vid', uuid()), local.get('dh_vid'));
    this._applyCopy(); this._applyOpen(); this._applyFooter(); this._renderTabs(); this._renderHelp(); this._renderEmoji('');
    this.$launcher.onclick = () => this.toggle(); this.$close.onclick = () => { if (this.getAttribute('mode') === 'launcher') this.close(); else { this._emit('close'); this.newChat(); } }; this.$back.onclick = () => this.showView('messages');
    const more = sh.querySelector('.more'); more.onclick = (e) => { e.stopPropagation(); const o = !this.$menu.classList.contains('open'); this._closePops(); this.$menu.classList.toggle('open', o); more.setAttribute('aria-expanded', String(o)); };
    this.$menu.querySelectorAll('button').forEach((b) => b.onclick = () => { this._closePops(); if (b.dataset.act === 'theme') this.switchTheme(); else if (b.dataset.act === 'download') this.download(); else this.newChat(); });
    sh.addEventListener('click', (e) => { if (!e.composedPath().some((n) => n.classList && (n.classList.contains('menu') || n.classList.contains('more') || n.classList.contains('pop') || n.classList.contains('b-emoji') || n.classList.contains('b-gif')))) this._closePops(); });
    sh.querySelector('.fab').onclick = () => this.newChat();
    sh.querySelector('.msearch').addEventListener('input', (e) => { this._mquery = e.target.value; this._paintConversations(); });
    this.$cbox.addEventListener('submit', (e) => { e.preventDefault(); if (this._busy) this._stop(); else this._send(); });
    this.$send.addEventListener('click', (e) => { if (this._busy) { e.preventDefault(); this._stop(); } });
    this.$q.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!this._busy) this._send(); } if (e.key === 'Escape') { if (this._busy) this._stop(); this._closePops(); } });
    this.$q.addEventListener('input', () => { this._autosize(); this._syncSend(); });
    sh.querySelectorAll('.scroll').forEach((s) => { let t = null; s.addEventListener('scroll', () => { s.classList.add('scrolling'); clearTimeout(t); t = setTimeout(() => s.classList.remove('scrolling'), 700); }, { passive: true }); });
    this.$q.addEventListener('focus', () => { this.$cbox.classList.add('focus'); sh.querySelector('.khint').classList.add('show'); });
    this.$q.addEventListener('blur', () => { this.$cbox.classList.remove('focus'); sh.querySelector('.khint').classList.remove('show'); });
    // attachments: picker + drag and drop
    const file = sh.querySelector('.file'); sh.querySelector('.b-clip').onclick = () => file.click(); file.onchange = () => { [...file.files].forEach((f) => this._upload(f)); file.value = ''; };
    ['dragenter', 'dragover'].forEach((ev) => this.$panel.addEventListener(ev, (e) => { if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); this.$cbox.classList.add('drop'); } }));
    ['dragleave', 'drop'].forEach((ev) => this.$panel.addEventListener(ev, (e) => { this.$cbox.classList.remove('drop'); if (ev === 'drop' && e.dataTransfer.files.length) { e.preventDefault(); this.showView('chat'); [...e.dataTransfer.files].forEach((f) => this._upload(f)); } }));
    // emoji + gif popovers
    sh.querySelector('.b-emoji').onclick = () => this._togglePop('emoji'); sh.querySelector('.b-gif').onclick = () => this._togglePop('gif');
    sh.querySelector('.pop-emoji .search').addEventListener('input', (e) => this._renderEmoji(e.target.value));
    let gt = null; sh.querySelector('.pop-gif .search').addEventListener('input', (e) => { clearTimeout(gt); gt = setTimeout(() => this._searchGifs(e.target.value), 350); });
    // dictation + voice
    sh.querySelector('.b-mic').onclick = () => this._toggleDictation(); sh.querySelector('.rstop').onclick = () => this._stopDictation();
    this.$speak.onclick = () => this.startVoice(); sh.querySelector('.v-end').onclick = () => this.stopVoice(); sh.querySelector('.v-mute').onclick = () => this._toggleMute();
    sh.querySelector('.v-min').onclick = () => this._showVoice(false); sh.querySelector('.vpill').onclick = () => this.startVoice(); sh.querySelector('.v-cc').onclick = () => this._toggleCaptions();
    sh.addEventListener('pointerdown', (e) => this._ripple(e), { passive: true });
    document.addEventListener('visibilitychange', () => { const v = this._voice; if (v && v.orb) { if (document.visibilityState === 'hidden') v.orb.pause(); else if (this.hasAttribute('open') || this.getAttribute('mode') !== 'launcher') v.orb.resume(); } });
    this._loadMe().then(() => { this._restore(); this._refreshBadge(); }); this._autosize(); this._syncSend(); this._track(); this._health(); this._loadConfig();
    console.info('deep-assistant v' + VERSION + ' ready (api ' + this.api + ')');
    this._emit('ready', { sessionId: this._sid, version: VERSION });
  }
  _closePops() { const sh = this.shadowRoot; this.$menu.classList.remove('open'); sh.querySelector('.more').setAttribute('aria-expanded', 'false'); sh.querySelectorAll('.pop').forEach((p) => p.classList.remove('open')); }
  _togglePop(which) { const p = this.shadowRoot.querySelector('.pop-' + which); const o = !p.classList.contains('open'); this._closePops(); p.classList.toggle('open', o); if (o) { p.querySelector('.search').focus(); if (which === 'gif' && !p.querySelector('.ggrid').children.length) this._searchGifs(''); } }
  _applyCopy() { this.shadowRoot.querySelector('.ttl').innerHTML = this.getAttribute('title') ? esc(this.getAttribute('title')) : 'ask <span>deep &gt;_</span>'; this.shadowRoot.querySelector('.sub').textContent = this.getAttribute('subtitle') || 'Deep can also help directly'; }
  _applyFooter() { const a = this.shadowRoot.querySelector('.privacy'); a.href = this.getAttribute('privacy-url') || this._cfg.privacy_url || 'https://deependhq.com/privacy'; this.shadowRoot.querySelector('.foot').title = 'deep-assistant v' + VERSION + (this._cfg.version ? ' · server ' + this._cfg.version : ''); }
  _applyOpen() {
    const launcher = this.getAttribute('mode') === 'launcher', open = this.hasAttribute('open');
    this.$launcher.setAttribute('aria-expanded', String(open));
    if (launcher) { this._emit(open ? 'open' : 'close'); if (open) { setTimeout(() => { if (!this._voice) this.$q.focus(); }, 50); this._refreshBadge(); if (this._voice && this._voice.orb) this._voice.orb.resume(); } else if (this._voice && this._voice.orb) this._voice.orb.pause(); }
  }
  async _loadConfig() { if (!this.api) return; try { const r = await fetch(this._url('/widget-config')); if (r.ok) { this._cfg = await r.json(); this._applyFooter(); this._refreshSuggestions(); } } catch {} }
  _setBusy(on) { this._busy = on; this.shadowRoot.querySelector('.i-send').hidden = on; this.shadowRoot.querySelector('.i-stop').hidden = !on; this.$send.classList.toggle('stop', on); this.$send.setAttribute('aria-label', on ? 'Stop' : 'Send'); this.$cbox.classList.toggle('busy', on); this._setStatus(on ? 'work' : (this._voice ? 'call' : 'idle')); this._syncSend(); }
  _setStatus(mode) { const sh = this.shadowRoot, orb = sh.querySelector('.orb-mini'), st = sh.querySelector('.st'); if (!orb || !st) return; orb.classList.toggle('work', mode === 'work'); orb.classList.toggle('call', mode === 'call'); st.classList.toggle('work', mode === 'work'); st.classList.toggle('call', mode === 'call'); const t = mode === 'work' ? 'Working…' : mode === 'call' ? 'In a call' : 'Online'; const el = st.querySelector('.stt'); if (el.textContent !== t) { el.textContent = t; this._announce('Deep is ' + (mode === 'work' ? 'working' : mode === 'call' ? 'in a call' : 'online')); } }
  _announce(text) { const sr = this.shadowRoot.querySelector('.sr'); if (!sr) return; clearTimeout(this._srT); this._srT = setTimeout(() => { sr.textContent = ''; sr.textContent = text; }, 60); }
  _ripple(e) { if (this._reduced || e.button) return; const t = e.composedPath().find((n) => n.classList && (n.classList.contains('btn') || n.classList.contains('chip') || n.classList.contains('time') || n.classList.contains('date') || n.classList.contains('ctype') || n.classList.contains('cap') || n.classList.contains('vbtn') || n.classList.contains('tab'))); if (!t || t.disabled) return; const r = t.getBoundingClientRect(); const d = Math.max(r.width, r.height); const sp = document.createElement('span'); sp.className = 'rip'; sp.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX - r.left - d / 2}px;top:${e.clientY - r.top - d / 2}px`; t.appendChild(sp); setTimeout(() => sp.remove(), 520); }
  _syncSend() { const has = !!this.$q.value.trim() || this._attachments.length > 0 || this._busy; this.$send.hidden = !has; this.$speak.hidden = has; }
  _autosize() { const q = this.$q, prev = q.style.height; q.style.height = 'auto'; const h = Math.max(30, Math.min(q.scrollHeight, 110)) + 'px'; if (this._reduced || !prev || prev === h) { q.style.height = h; return; } q.style.height = prev; requestAnimationFrame(() => { q.style.height = h; }); }
  _scroll() { this.$log.scrollTop = this.$log.scrollHeight; }
  _atBottom() { return this.$log.scrollHeight - this.$log.scrollTop - this.$log.clientHeight < 40; }
  async _health() { if (!this.api) return; try { const r = await fetch(this._url('/healthz'), { cache: 'no-store' }); this._online = r.ok; } catch { this._online = false; } }
  async _loadMe() {
    const hintName = this.getAttribute('user-name'), hintEmail = this.getAttribute('user-email');
    this._me = { signed_in: false, name: hintName, email: hintEmail, verified: false };
    if (this.getAttribute('token') && this.api) { try { const r = await fetch(this._url('/me'), { headers: this._headers(false) }); if (r.ok) this._me = await r.json(); } catch {} }
    if (!this._me.name && hintName) this._me.name = hintName; if (!this._me.email && hintEmail) this._me.email = hintEmail;
  }
  _greeting() {
    if (this.getAttribute('greeting')) return this.getAttribute('greeting');
    const first = (this._me && this._me.name) ? String(this._me.name).trim().split(/\s+/)[0] : '';
    return first ? `👋 Hey ${first}, you're speaking with Deep's AI assistant. Share as much detail as you can so I can give you the best answer.`
                 : `👋 Hi, you're speaking with Deep's AI assistant. Share as much detail as you can so I can give you the best answer.`;
  }
  _track() {
    if (!this.api || store.get(this._key('tracked')) === this._sid) return;
    const body = { session_id: this._sid, visitor_id: this._vid, page: location.href, referrer: document.referrer || null, timezone: this.tz, lang: navigator.language || null, screen: screen && screen.width ? `${screen.width}x${screen.height}` : null };
    fetch(this._url('/track'), { method: 'POST', headers: this._headers(), body: JSON.stringify(body), keepalive: true }).then(() => store.set(this._key('tracked'), this._sid)).catch(() => {});
  }
  // ---------------------------------------------------------------- tabs, messages, help
  _renderTabs() {
    const nav = this.shadowRoot.querySelector('.tabs'); const tabs = this._tabs();
    nav.innerHTML = tabs.map((t) => `<button class="tab" type="button" data-tab="${t}" aria-label="${t === 'home' ? 'Home' : t === 'messages' ? 'Messages' : 'Help'}">${SVG[t]}<span>${t === 'home' ? 'Home' : t === 'messages' ? 'Messages' : 'Help'}</span>${t === 'messages' ? '<span class="badge" hidden></span>' : ''}</button>`).join('');
    nav.querySelectorAll('.tab').forEach((b) => b.onclick = () => this.showView(b.dataset.tab === 'home' ? 'chat' : b.dataset.tab));
    nav.hidden = tabs.length < 2; this.showView(this._view); this._setBadge(this._unread);
  }
  _renderHelp() {
    const h = this.shadowRoot.querySelector('.help'); const sc = this._shortcut();
    h.innerHTML = `<h2>Things I can do</h2><div class="stack">
      <button class="btn" type="button" data-ask="I want to book a call with Deep"><span>Book a call with Deep</span>${SVG.ext}</button>
      <button class="btn" type="button" data-ask="Can I talk to a real person?"><span>Ask Deep directly (reply by email)</span>${SVG.ext}</button>
      ${sc ? `<a class="btn" href="${esc(sc.href)}" target="_blank" rel="noopener"><span>${esc(sc.label)}</span>${SVG.ext}</a>` : ''}
    </div><h2>Common questions</h2><div class="suggest"></div>`;
    h.querySelectorAll('button[data-ask]').forEach((b) => b.onclick = () => { this.newChat(); this._send(b.dataset.ask); });
    const s = h.querySelector('.suggest'); this._suggestions().forEach((x) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'chip'; b.textContent = x; b.onclick = () => { this.newChat(); this._send(x); }; s.appendChild(b); });
  }
  _setBadge(n) { this._unread = n; const b = this.shadowRoot.querySelector('.tab[data-tab="messages"] .badge'); if (b) { b.hidden = !n; b.textContent = String(n); } const lb = this.shadowRoot.querySelector('.lbadge'); lb.hidden = !n; lb.textContent = String(n); }
  async _conversations() { if (!this.api || (!this._vid && !this.getAttribute('token'))) return { items: [], unread_conversations: 0 }; try { const r = await fetch(this._url('/conversations'), { headers: this._headers(false) }); return r.ok ? await r.json() : { items: [], unread_conversations: 0 }; } catch { return { items: [], unread_conversations: 0 }; } }
  async _refreshBadge() { const d = await this._conversations(); this._setBadge(d.unread_conversations || 0); return d; }
  async _markRead(sid) { try { await fetch(this._url('/conversations/' + encodeURIComponent(sid) + '/read'), { method: 'POST', headers: this._headers() }); } catch {} }
  async _renderConversations() {
    const sh = this.shadowRoot; const sc = this._shortcut();
    sh.querySelector('.mhead').innerHTML = sc ? `<a class="shortcut" href="${esc(sc.href)}" target="_blank" rel="noopener"><span class="avatar" aria-hidden="true">${SVG.mark}</span><span class="t"><b>${esc(sc.label)}</b><span>${esc(host(sc.href))}</span></span>${SVG.ext}</a>` : '';
    sh.querySelector('.mrows').innerHTML = '<div class="mempty">Loading…</div>';
    const d = await this._refreshBadge(); this._convos = d.items || []; this._paintConversations();
  }
  _group(ts) { const d = new Date(ts), now = new Date(); const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime(); const diff = Math.round((day(now) - day(d)) / 86400000);
    return diff <= 0 ? 'Today' : diff === 1 ? 'Yesterday' : diff <= 7 ? 'Previous 7 days' : 'Older'; }
  _paintConversations() {
    const sh = this.shadowRoot, rows = sh.querySelector('.mrows'); const q = (this._mquery || '').trim().toLowerCase();
    const items = (this._convos || []).filter((c) => !q || (c.title || '').toLowerCase().includes(q) || plain(c.preview).toLowerCase().includes(q));
    sh.querySelector('.msearch').hidden = !(this._convos || []).length;
    if (!(this._convos || []).length) { rows.innerHTML = `<div class="empty"><b>No conversations yet</b>Ask anything about deependhq.com, or book a call with Deep.</div>`; return; }
    if (!items.length) { rows.innerHTML = '<div class="mempty">No conversations match your search.</div>'; return; }
    let html = '', last = null;
    for (const c of items) {
      const g = this._group(c.last_ts); if (g !== last) { html += `<div class="mgroup">${g}</div>`; last = g; }
      html += `<button class="convo ${c.unread ? 'unread' : ''}" type="button" role="listitem" data-sid="${esc(c.session_id)}" aria-label="${esc(c.title)}">
        <span class="avatar" aria-hidden="true">${c.handovers ? 'D' : SVG.mark}</span>
        <span class="c"><span class="n" title="${esc(c.title)}">${esc(c.title)}</span><span class="p">${esc(plain(c.preview) || '…')}</span></span>
        <span class="r"><span class="time">${relShort(c.last_ts).replace('just now', 'now')}</span>${c.unread ? '<span class="dot" aria-label="unread"></span>' : ''}</span>
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
    const f = document.createElement('form'); f.className = 'rename'; f.innerHTML = `<input maxlength="80" aria-label="Conversation title"><button type="submit" class="textbtn submit">Save</button><button type="button" class="textbtn cancel">Cancel</button>`;
    const input = f.querySelector('input'); input.value = c.title || ''; btn.insertAdjacentElement('afterend', f); input.focus(); input.select();
    f.querySelector('.cancel').onclick = () => f.remove(); input.addEventListener('keydown', (e) => { if (e.key === 'Escape') f.remove(); });
    f.onsubmit = async (e) => { e.preventDefault(); const title = input.value.trim(); if (!title) return;
      try { const r = await fetch(this._url('/conversations/' + encodeURIComponent(sid)), { method: 'PATCH', headers: this._headers(), body: JSON.stringify({ title }) }); if (r.ok) { const d = await r.json(); c.title = d.title; c.title_source = 'user'; this._toast('Renamed'); } } catch {}
      f.remove(); this._paintConversations(); };
  }
  // ---------------------------------------------------------------- rendering
  _add(role, text, ts) {
    const row = document.createElement('div'); row.className = 'row ' + role; row.dataset.role = role; row.dataset.ts = String(ts || Date.now());
    const d = document.createElement('div'); d.className = 'msg'; d.textContent = text; row.appendChild(d);
    const meta = document.createElement('div'); meta.className = 'meta'; meta.textContent = role === 'bot' ? `Deep • AI Agent • ${relShort(ts || Date.now())}` : relShort(ts || Date.now()); row.appendChild(meta);
    this.$log.appendChild(row); this._scroll(); return d;
  }
  _thinking(el) { el.classList.add('thinking'); el.innerHTML = '<i></i><i></i><i></i>'; }
  _activity(bot) {  // the agent at work: skeleton bubble + activity row fed by real 'status' events; collapses into "Worked for …"
    const row = bot.parentElement; bot.classList.add('skel'); bot.innerHTML = '<div class="ln"></div><div class="ln"></div><div class="ln"></div>';
    const a = document.createElement('div'); a.className = 'activity'; a.setAttribute('aria-hidden', 'true'); a.innerHTML = '<span class="orb"></span><span class="lbl">Thinking…</span>'; row.insertBefore(a, bot);
    const act = { el: a, t0: performance.now(), steps: [], label: a.querySelector('.lbl'), last: 'Thinking…' };
    act.set = (step, label) => { act.label.textContent = label; act.last = label; act.steps.push({ step, label, at: performance.now() - act.t0 }); this._announce(label); };
    act.done = (sourcesN) => { const ms = performance.now() - act.t0; a.remove(); bot.classList.remove('skel');
      if (!act.steps.length || ms < 400) return;
      const w = document.createElement('button'); w.type = 'button'; w.className = 'worked'; const secs = ms < 950 ? (ms / 1000).toFixed(1) + 's' : Math.round(ms / 1000) + 's';
      w.innerHTML = `${SVG.chev}<span>Worked for ${secs}${sourcesN ? ' · ' + sourcesN + ' source' + (sourcesN === 1 ? '' : 's') : ''}</span>`; w.setAttribute('aria-expanded', 'false');
      const st = document.createElement('div'); st.className = 'steps'; st.innerHTML = act.steps.map((x) => `<div><b>${(x.at / 1000).toFixed(1)}s</b><span>${esc(x.label.replace(/…$/, ''))}</span></div>`).join('') + `<div><b>${secs}</b><span>Done</span></div>`;
      w.onclick = () => { const o = !st.classList.contains('open'); st.classList.toggle('open', o); w.classList.toggle('open', o); w.setAttribute('aria-expanded', String(o)); };
      row.insertBefore(w, bot); row.insertBefore(st, bot); };
    return act;
  }
  _setText(el, text, srcs, tail) {
    el.classList.remove('thinking'); el.classList.remove('skel'); const extras = Array.from(el.querySelectorAll(':scope > div, :scope > form'));
    el.innerHTML = md(text, srcs, this.api); if (tail) this._wrapTail(el, tail); extras.forEach((x) => el.appendChild(x)); el.dataset.raw = plain(text);
  }
  _wrapTail(el, n) {  // the newest streamed chunk fades in (opacity + 2px blur → sharp): wrap the last n characters of the last text node
    if (this._reduced || !n) return; let node = el; while (node && node.lastChild) node = node.lastChild; if (!node || node.nodeType !== 3) return;
    const len = node.data.length, k = Math.min(n, len); if (k <= 0) return; const tail = node.splitText(len - k); const sp = document.createElement('span'); sp.className = 'tok'; tail.parentNode.insertBefore(sp, tail); sp.appendChild(tail);
  }
  _contextChip(row, items) {  // "Using 3 sources from deependhq.com", above the answer; toggles the source list below it
    if (!items || !items.length || row.querySelector('.ctx')) return; const hosts = [...new Set(items.map((x) => host(x.url)).filter(Boolean))];
    const b = document.createElement('button'); b.type = 'button'; b.className = 'ctx in'; b.setAttribute('aria-expanded', 'true');
    b.innerHTML = `${SVG.chev}<span>Using ${items.length} source${items.length === 1 ? '' : 's'}${hosts.length === 1 ? ' from ' + esc(hosts[0]) : ''}</span>`; b.classList.add('open');
    b.onclick = () => { const src = row.querySelector('.sources'); const o = !b.classList.contains('open'); b.classList.toggle('open', o); b.setAttribute('aria-expanded', String(o)); if (src) src.classList.toggle('hide', !o); };
    row.insertBefore(b, row.querySelector('.msg'));
  }
  _actionCard(el, key, icon, title, detail, state) {  // the agent acting, not just talking: calendar checked, slot booked, email sent
    let c = el.querySelector(`.actcard[data-key="${key}"]`); if (!c) { c = document.createElement('div'); c.className = 'actcard'; c.dataset.key = key; c.innerHTML = `<span class="ai"></span><span class="at"><b></b><span></span></span><span class="as"></span>`; el.appendChild(c); }
    c.className = 'actcard ' + (state || 'run'); c.querySelector('.ai').innerHTML = icon; c.querySelector('.at b').textContent = title; c.querySelector('.at span').textContent = detail || '';
    c.querySelector('.as').innerHTML = state === 'ok' ? `${SVG.check}<span>done</span>` : state === 'fail' ? `${SVG.x}<span>failed</span>` : '<i></i><span>in progress</span>';
    c.setAttribute('role', 'status'); this._announce(title + (state === 'ok' ? ' done' : state === 'fail' ? ' failed' : '')); this._scroll(); return c;
  }
  _renderCaps() {
    const row = document.createElement('div'); row.className = 'row bot caps-row'; const g = document.createElement('div'); g.className = 'caps';
    const caps = [
      [SVG.search, 'Answers from Deep\'s work', () => this._send('What is Deep working on?')],
      [SVG.cal, 'Books calls on Deep\'s calendar', () => this._send('I want to book a call with Deep')],
      [SVG.mail, 'Sends Zoom invites by email', () => this._send('Book a call with Deep and send me the Zoom invite')],
      [SVG.phone, 'Voice conversation', () => this.startVoice()],
    ];
    caps.forEach(([icon, label, fn]) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'cap'; b.innerHTML = `${icon}<span>${esc(label)}</span>`; b.onclick = fn; g.appendChild(b); });
    row.appendChild(g); this.$log.appendChild(row);
  }
  _addSources(el, items) {
    if (!items || !items.length) return; const s = document.createElement('div'); s.className = 'sources';
    s.innerHTML = '<span class="lbl">Sources</span><div class="srow">' + items.map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener" title="${esc(x.title || x.url)}"><b>${x.n}</b><span class="t">${esc(trunc(x.title || x.url, 28))}</span><span class="h">${esc(host(x.url))}</span></a>`).join('') + '</div>';
    el.parentElement.appendChild(s);
  }
  async _rate(mid, rating, note) { try { const r = await fetch(this._url('/feedback'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ message_id: mid, rating, note: note || null }) }); const ok = r.ok && (await r.json()).ok; if (ok) this._emit('feedback', { messageId: mid, rating, note: note || null }); return ok; } catch { return false; } }
  _addTools(el, raw, retryText, mid, fb) {
    const row = el.parentElement, t = document.createElement('div'); t.className = 'tools';
    const tool = (label, icon, cls) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'tool ' + (cls || ''); b.setAttribute('aria-label', label); b.title = label; b.innerHTML = icon; return b; };
    if (mid) {
      const mark = (rating) => { t.querySelectorAll('.thumb').forEach((x) => x.classList.toggle('on', x.classList.contains(rating === 1 ? 'up' : 'down'))); const tr = this._transcript.find((m) => m.mid === mid); if (tr) { tr.fb = rating; this._persist(); } this._toast('Thanks for the feedback'); };
      const mk = (rating, label, icon) => { const b = tool(label, icon, 'thumb ' + (rating === 1 ? 'up' : 'down') + (fb === rating ? ' on' : ''));
        b.onclick = async () => { if (rating === 1) { if (await this._rate(mid, 1)) mark(1); return; } this._fbPopover(b, async (reason) => { if (await this._rate(mid, -1, reason)) mark(-1); }); };
        return b; };
      t.appendChild(mk(1, 'Helpful', SVG.up)); t.appendChild(mk(-1, 'Not helpful', SVG.down));
    }
    const copy = tool('Copy answer', SVG.copy);
    copy.onclick = async () => { try { await navigator.clipboard.writeText(raw()); } catch {} const tip = document.createElement('span'); tip.className = 'tip'; tip.textContent = 'Copied'; copy.appendChild(tip); t.classList.add('keep'); setTimeout(() => { tip.remove(); t.classList.remove('keep'); }, 1200); };
    t.appendChild(copy);
    if (retryText) { const r = tool('Retry', SVG.reset); r.onclick = () => { row.remove(); const u = this.$log.lastElementChild; if (u && u.dataset.role === 'user') u.remove(); this._history = this._history.slice(0, -2); this._transcript = this._transcript.slice(0, -2); this._persist(); this._send(retryText); }; t.appendChild(r); }
    row.appendChild(t);
  }
  _suggestions() { const a = this.getAttribute('suggestions'); if (a) return a.split('|').map((s) => s.trim()).filter(Boolean); const c = this._cfg && Array.isArray(this._cfg.suggestions) ? this._cfg.suggestions.filter(Boolean) : []; return c.length ? c : DEFAULT_SUGGESTIONS; }
  _refreshSuggestions() { /* the server's smart suggestions (most asked questions) arrive after first paint: swap the chips while nothing has been asked yet */
    const s = this.shadowRoot.querySelector('.suggest-row .suggest'); if (s && !this._transcript.length) { s.innerHTML = ''; this._suggestions().forEach((x) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'chip'; b.textContent = x; b.onclick = () => this._send(x); s.appendChild(b); }); }
    if (typeof this._renderHelp === 'function') this._renderHelp();
  }
  _renderSuggestions() { const row = document.createElement('div'); row.className = 'row bot suggest-row'; const s = document.createElement('div'); s.className = 'suggest'; this._suggestions().forEach((x) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'chip'; b.textContent = x; b.onclick = () => this._send(x); s.appendChild(b); }); row.appendChild(s); this.$log.appendChild(row); }
  _persist() { store.set(this._key('tx:' + this._sid), JSON.stringify(this._transcript.slice(-40))); }
  _restore() {
    try { this._transcript = JSON.parse(store.get(this._key('tx:' + this._sid)) || '[]'); } catch { this._transcript = []; }
    this.$log.innerHTML = '';
    if (!this._transcript.length) { this._add('bot', this._greeting()); this._renderCaps(); this._renderSuggestions(); this._updateChrome(); return; }
    this._transcript.forEach((m) => { const el = this._add(m.role === 'user' ? 'user' : 'bot', '', m.ts); this._setText(el, m.text, m.sources); if (m.role === 'bot') { this._addSources(el, m.sources); this._addTools(el, () => plain(m.text), null, m.mid, m.fb); } });
    this._history = this._transcript.map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text })).slice(-12);
    this._updateChrome();
  }
  // ---------------------------------------------------------------- in-chat booking (docs/BOOKING.md)
  _renderPicker(el, items) {
    if (el.querySelector('.picker')) return;
    const wrap = document.createElement('div'); wrap.className = 'picker card';
    const lbl = document.createElement('div'); lbl.className = 'lbl'; lbl.textContent = items.length > 1 ? 'Which call suits you?' : 'Call type';
    const list = document.createElement('div'); list.className = 'ctypes';
    items.forEach((c) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'ctype';
      b.innerHTML = `<b>${esc(c.name)}</b><span>${c.duration_min} min · with Deep</span>${c.description ? `<small>${esc(c.description)}</small>` : ''}`;
      b.onclick = () => { list.querySelectorAll('.ctype').forEach((x) => x.classList.toggle('on', x === b)); this._openAvailability(el, c.slug); }; list.appendChild(b); });
    wrap.append(lbl, list); el.appendChild(wrap);
    if (items.length === 1) this._openAvailability(el, items[0].slug);
    requestAnimationFrame(() => requestAnimationFrame(() => { wrap.classList.add('open'); this._scroll(); }));
  }
  _availBox(el) { let box = el.querySelector('.avail'); if (!box) { box = document.createElement('div'); box.className = 'avail card'; el.appendChild(box); } return box; }
  async _openAvailability(el, slug, prefer) {
    const box = this._availBox(el); box.dataset.slug = slug; box.innerHTML = '<div class="note">Loading Deep\'s availability…</div>'; this._scroll();
    let d = { ok: false, message: "Deep's availability couldn't be loaded right now." };
    try { const r = await fetch(this._url(`/booking/availability?schedule=${encodeURIComponent(slug)}&tz=${encodeURIComponent(this.tz)}`), { headers: this._headers(false) }); if (r.ok) d = await r.json(); } catch {}
    this._renderAvailability(box, d, prefer);
  }
  _renderAvailability(box, d, prefer) {
    box.innerHTML = '';
    if (!d.ok) {
      box.innerHTML = `<div class="note warn">${esc(d.message || "Deep's availability couldn't be loaded right now.")}</div><div class="hrow">` +
        `<button type="button" class="btn retry">Try again</button>${d.fallback_link ? `<a class="btn" href="${esc(d.fallback_link)}" target="_blank" rel="noopener">Open Deep's scheduler</a>` : ''}</div>`;
      box.querySelector('.retry').onclick = () => this._openAvailability(box.parentElement, box.dataset.slug || (d.schedule && d.schedule.slug) || ''); this._scroll(); return;
    }
    box.dataset.slug = d.schedule.slug;
    const head = document.createElement('div'); head.className = 'ahead'; head.innerHTML = `<b>${esc(d.schedule.name)}</b><span>${d.schedule.duration_min} min · with Deep</span>`;
    const dates = document.createElement('div'); dates.className = 'dates'; const times = document.createElement('div'); times.className = 'times';
    const tzn = document.createElement('div'); tzn.className = 'note tzn'; tzn.textContent = `Times shown in ${d.timezone}`;
    const show = (day) => { times.innerHTML = ''; dates.querySelectorAll('.date').forEach((x) => x.classList.toggle('on', x.dataset.date === day.date));
      day.slots.forEach((sl) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'time' + (sl.available ? '' : ' off'); b.dataset.start = sl.start_iso;
        if (sl.available) { b.textContent = sl.time; b.onclick = () => this._renderDetails(box, d, sl); }
        else { b.disabled = true; b.innerHTML = `<s>${esc(sl.time)}</s><small>Not available</small>`; b.title = sl.reason === 'booked' ? 'Already booked' : sl.reason === 'past' ? 'Already passed' : 'Not available on Deep\'s scheduler'; }
        times.appendChild(b); });
      if (!day.slots.length) times.innerHTML = '<div class="note">No times on this day.</div>'; };
    let first = null;
    d.days.forEach((day) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'date' + (day.open ? '' : ' off'); b.dataset.date = day.date;
      b.innerHTML = `<b>${esc(day.label)}</b><small>${day.open ? day.open + ' open' : 'Not available'}</small>`;
      if (day.open) { b.onclick = () => show(day); if (!first) first = day; } else { b.disabled = true; b.setAttribute('aria-label', day.label + ', not available'); }
      dates.appendChild(b); });
    box.append(head, dates, times, tzn);
    const pre = prefer && d.days.find((dd) => dd.slots.some((x) => x.start_iso === prefer));
    if (pre) show(pre); else if (first) show(first);
    else { times.innerHTML = '<div class="note warn">No open times in the next two weeks.</div>'; if (d.fallback_link) times.insertAdjacentHTML('beforeend', `<div class="hrow"><a class="btn" href="${esc(d.fallback_link)}" target="_blank" rel="noopener">Open Deep's scheduler</a></div>`); }
    if (d.alternatives && d.alternatives.length) { const alt = document.createElement('div'); alt.className = 'note'; alt.textContent = 'Nearest open times:'; const row = document.createElement('div'); row.className = 'hrow';
      d.alternatives.forEach((sl) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'btn'; b.textContent = sl.label_visitor; b.onclick = () => this._renderDetails(box, d, sl); row.appendChild(b); }); box.append(alt, row); }
    this._scroll();
  }
  _renderDetails(box, d, sl, prefill) {
    const me = this._me || {}; const known = !!(me.signed_in && me.verified && me.email); prefill = prefill || {};
    box.querySelectorAll('.bform, .bsum').forEach((x) => x.remove());
    const f = document.createElement('form'); f.className = 'bform';
    f.innerHTML = `<div class="lbl">Your details · ${esc(sl.label_visitor)}</div>
      <input name="name" placeholder="Full name" maxlength="120" required autocomplete="name" ${known ? 'hidden' : ''}>
      <input name="email" type="email" placeholder="Email" maxlength="200" required autocomplete="email" ${known ? 'hidden' : ''}>
      <input name="company" placeholder="Company (optional)" maxlength="120" autocomplete="organization">
      <textarea name="notes" rows="2" placeholder="What would you like to discuss? (optional)" maxlength="1000"></textarea>
      <div class="hrow"><button class="btn primary" type="submit">Continue</button><button class="btn" type="button" data-back>Change time</button>${known ? `<span class="note">Booking as ${esc(me.email)}</span>` : ''}</div>`;
    const field = (n) => f.elements[n];
    field('name').value = prefill.name || me.name || ''; field('email').value = prefill.email || me.email || ''; field('notes').value = prefill.reason || prefill.notes || ''; if (prefill.company) field('company').value = prefill.company;
    f.querySelector('[data-back]').onclick = () => { f.remove(); if (!box.querySelector('.dates')) this._openAvailability(box.parentElement, d.schedule.slug, sl.start_iso); };
    f.onsubmit = (e) => { e.preventDefault(); this._renderSummary(box, d, sl, { name: field('name').value.trim(), email: field('email').value.trim(), company: field('company').value.trim(), notes: field('notes').value.trim() }); };
    box.appendChild(f); requestAnimationFrame(() => { this._scroll(); (known ? field('notes') : field('name')).focus(); });
  }
  _renderSummary(box, d, sl, who) {
    box.querySelectorAll('.bsum').forEach((x) => x.remove());
    const c = document.createElement('div'); c.className = 'bsum';
    c.innerHTML = `<div class="lbl">Confirm your booking</div>
      <div class="srow"><span>Call</span><b>${esc(d.schedule.name)}</b></div>
      <div class="srow"><span>When</span><b>${esc(sl.label_visitor)}</b></div>
      <div class="srow"><span>Duration</span><b>${d.schedule.duration_min} min · with Deep</b></div>
      <div class="srow"><span>You</span><b>${esc(who.name)} · ${esc(who.email)}${who.company ? ' · ' + esc(who.company) : ''}</b></div>
      <div class="hrow"><button class="btn primary" type="button" data-confirm>Confirm booking</button><button class="btn" type="button" data-change>Change slot</button></div><div class="note sstat">Nothing is booked until you confirm.</div>`;
    c.querySelector('[data-change]').onclick = () => { box.querySelectorAll('.bform, .bsum').forEach((x) => x.remove()); if (!box.querySelector('.dates')) this._openAvailability(box.parentElement, d.schedule.slug); };
    c.querySelector('[data-confirm]').onclick = () => this._confirmBooking(box, d, sl, who, c);
    box.appendChild(c); this._scroll();
  }
  async _confirmBooking(box, d, sl, who, sum) {
    const btns = sum.querySelectorAll('button'); btns.forEach((b) => b.disabled = true); const stat = sum.querySelector('.sstat'); stat.className = 'note sstat'; stat.textContent = 'Checking the time with Zoom and booking…';
    const host = box.parentElement; const card = this._actionCard(host, 'book', SVG.cal, 'Booking your slot', `${d.schedule.name} · ${sl.label_visitor}`, 'run');
    let res = null, status = 0;
    try { const r = await fetch(this._url('/booking/confirm'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ schedule_slug: d.schedule.slug, start: sl.start_iso, name: who.name, email: who.email, company: who.company, notes: who.notes, timezone: this.tz }) }); status = r.status; res = r.ok ? await r.json() : null; } catch {}
    if (status === 429) { this._actionCard(host, 'book', SVG.cal, 'Booking your slot', 'Too many attempts', 'fail'); stat.classList.add('warn'); stat.textContent = 'Too many booking attempts. Please wait a minute and try again.'; btns.forEach((b) => b.disabled = false); return; }
    if (!res) { this._actionCard(host, 'book', SVG.cal, 'Booking your slot', 'Server not reachable', 'fail'); stat.classList.add('warn'); stat.textContent = 'Could not reach the server. Please try again.'; btns.forEach((b) => b.disabled = false); return; }
    if (res.status === 'confirmed' || res.status === 'pending_zoom') { this._actionCard(host, 'book', SVG.cal, res.status === 'confirmed' ? 'Booked on Deep\'s calendar' : 'Time held, finish on Zoom', `${d.schedule.name} · ${sl.label_visitor}`, 'ok'); if (res.emails_queued) this._actionCard(host, 'mail', SVG.mail, 'Sending confirmation', `Invite emailed to ${who.email}`, 'ok'); this._renderBooked(box, res); return; }
    this._actionCard(host, 'book', SVG.cal, 'Booking your slot', res.message || 'That did not work.', 'fail');
    btns.forEach((b) => b.disabled = false); stat.classList.add('warn'); stat.textContent = res.message || 'That did not work.';
    if (res.status === 'slot_taken') { sum.remove(); box.querySelectorAll('.bform').forEach((x) => x.remove()); const el = box.parentElement; this._openAvailability(el, d.schedule.slug).then(() => { const b2 = el.querySelector('.avail'); if (b2) { const n = document.createElement('div'); n.className = 'note warn'; n.textContent = res.message; b2.prepend(n); if (res.alternatives && res.alternatives.length) this._renderAvailability(b2, Object.assign({}, { ok: true, schedule: d.schedule, timezone: this.tz, days: [] }, JSON.parse(b2.dataset.last || 'null') || {}, { alternatives: res.alternatives })); } }); }
    else if (res.status === 'unavailable' && res.fallback_link) { stat.insertAdjacentHTML('afterend', `<div class="hrow"><a class="btn" href="${esc(res.fallback_link)}" target="_blank" rel="noopener">Book directly on Zoom</a></div>`); }
    else if (res.status === 'error' || res.retry) { stat.textContent = (res.message || 'Zoom did not respond.') + ' Use the button to try again.'; }
  }
  _renderBooked(box, res) {
    const b = res.booking; const pending = res.status !== 'confirmed'; box.innerHTML = '';
    const c = document.createElement('div'); c.className = 'booked' + (pending ? ' pending' : '');
    c.innerHTML = `<div class="bk-title">${pending ? '⏳ One last step on Zoom' : '<svg class="chk" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="12"/><path d="M8 14.5l4 4 8-8"/></svg>You\'re booked with Deep'}</div>
      <div class="bk-when">${esc(b.label_visitor)}</div><div class="bk-sub">${esc(b.schedule_name)} · ${b.duration_min} min · ${esc(b.visitor_tz)}</div>
      ${pending ? `<div class="note">Your time is held in this chat. Confirm it on Deep's scheduler (your details are prefilled) to make it final.</div>` : ''}
      <div class="hrow">${pending && b.handoff_url ? `<a class="btn primary" href="${esc(b.handoff_url)}" target="_blank" rel="noopener">Confirm on Zoom</a>` : ''}${b.join_url ? `<a class="btn primary" href="${esc(b.join_url)}" target="_blank" rel="noopener">Join Zoom</a>` : ''}${b.ics_url ? `<a class="btn" href="${esc(b.ics_url)}" download>Add to calendar</a>` : ''}</div>
      <div class="note ok">A confirmation email${b.join_url ? ' with the Zoom link and invite' : ' with the invite'} is on its way to ${esc(b.email)}.</div>`;
    box.appendChild(c); this._scroll();
    const line = pending ? `Time held: ${b.schedule_name} on ${b.label_visitor}; confirm on Zoom to make it final.` : `Booking confirmed: ${b.schedule_name} on ${b.label_visitor}.`;
    this._history.push({ role: 'assistant', content: line }); this._history = this._history.slice(-12);
    this._transcript.push({ role: 'bot', text: line, ts: Date.now() }); this._persist();
    this._emit('booking', { status: res.status, bookingId: b.id, joinUrl: b.join_url || null, handoffUrl: b.handoff_url || null, slot: b.start_iso, schedule: b.schedule_slug, email: b.email });
  }
  _renderReview(el, ev) {
    const box = this._availBox(el); const d = { ok: true, schedule: ev.schedule || {}, timezone: ev.timezone || this.tz, days: [] };
    if (ev.status === 'review' && ev.slot) { box.innerHTML = ''; box.dataset.slug = d.schedule.slug || ''; this._renderDetails(box, d, ev.slot, ev.prefill || {}); return; }
    if (ev.status === 'unavailable' && ev.alternatives) { box.innerHTML = `<div class="note warn">${esc(ev.wanted ? ev.wanted + ' is not open on Deep\'s scheduler.' : 'That time is not open.')}</div>`; const row = document.createElement('div'); row.className = 'hrow';
      ev.alternatives.forEach((sl) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'btn'; b.textContent = sl.label_visitor; b.onclick = () => this._renderDetails(box, d, sl, ev.prefill || {}); row.appendChild(b); });
      const all = document.createElement('button'); all.type = 'button'; all.className = 'btn'; all.textContent = 'See all times'; all.onclick = () => this._openAvailability(el, d.schedule.slug); row.appendChild(all); box.appendChild(row); this._scroll(); return; }
    if (ev.fallback_link) box.innerHTML = `<div class="note warn">${esc(ev.message || 'Availability could not be loaded.')}</div><div class="hrow"><a class="btn" href="${esc(ev.fallback_link)}" target="_blank" rel="noopener">Open Deep's scheduler</a></div>`;
  }
  _renderSlots(el, ev) {  // legacy 3-slot buttons: only when the grid did not render (e.g. no_slots / unavailable without a schedule)
    if (el.querySelector('.avail')) return;
    if (!ev.ok && ev.error === 'unknown_schedule') { this._renderPicker(el, ev.choices || []); return; }
    const box = this._availBox(el);
    if (!ev.ok) { this._renderAvailability(box, { ok: false, message: ev.error === 'no_slots' ? 'No open times in that window.' : "Zoom's scheduler isn't responding right now.", fallback_link: ev.fallback_link, schedule: ev.schedule }); return; }
    this._openAvailability(el, ev.schedule ? ev.schedule.slug : '');
  }
  _renderBooking(el, ev) {  // legacy event, kept for older servers
    const box = document.createElement('div'); box.className = 'handoff';
    if (ev.handoff_url) box.innerHTML = `<a class="btn primary" href="${esc(ev.handoff_url)}" target="_blank" rel="noopener">Confirm on Zoom</a>`;
    if (ev.status === 'slot_taken') { const p = document.createElement('div'); p.className = 'note warn'; p.textContent = 'That slot was just taken.'; box.appendChild(p); }
    el.appendChild(box); this._emit('booking', { status: ev.status, leadId: ev.lead_id || null, handoffUrl: ev.handoff_url || null, slot: ev.slot || null, schedule: ev.schedule || null });
  }
  _renderHandover(el, prefill) {
    if (el.querySelector('.hform')) return; const me = this._me || {}; const known = !!(me.signed_in && me.verified && me.email);
    const f = document.createElement('form'); f.className = 'hform';
    f.innerHTML = `<div class="lbl">Message for Deep</div>
      <input name="name" placeholder="Your name" maxlength="120" required autocomplete="name" ${known ? 'hidden' : ''}>
      <input name="email" type="email" placeholder="Your email" maxlength="200" required autocomplete="email" ${known ? 'hidden' : ''}>
      <textarea name="message" rows="3" placeholder="What would you like to ask?" maxlength="2000" required></textarea>
      <div class="hrow"><button class="btn primary" type="submit">Send to Deep</button><span class="note">${known ? 'Replies go to ' + esc(me.email) + '.' : 'Replies come by email.'}</span></div>`;
    const field = (n) => f.elements[n]; field('message').value = prefill || ''; if (me.name) field('name').value = me.name; if (me.email) field('email').value = me.email;
    f.onsubmit = async (e) => { e.preventDefault(); const b = f.querySelector('button'); b.disabled = true; const email = field('email').value.trim();
      try { const r = await fetch(this._url('/handover'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ session_id: this._sid, name: field('name').value.trim(), email, message: field('message').value.trim() }) });
        const d = r.ok ? await r.json() : null;
        if (d && d.ok) { f.innerHTML = `<div class="note ok">Sent. Deep will reply to ${esc(email)}.${d.visitor_mailed ? ' A copy is in your inbox.' : ''}</div>`; this._actionCard(el, 'handover', SVG.mail, 'Sent to Deep', `Reply comes to ${email}`, 'ok'); this._emit('handover', { leadId: d.lead_id, email, briefSent: d.brief_sent }); }
        else { b.disabled = false; f.querySelector('.note').textContent = r.status === 422 ? 'Please check the email address.' : 'Could not send right now. Please try again.'; } }
      catch { b.disabled = false; f.querySelector('.note').textContent = 'Connection problem. Please try again.'; } };
    el.appendChild(f); requestAnimationFrame(() => { this._scroll(); (known ? field('message') : field('name')).focus(); });
  }
  _renderHandoverOffer(el, question) { const d = document.createElement('div'); d.className = 'handoff'; const b = document.createElement('button'); b.type = 'button'; b.className = 'btn'; b.textContent = 'Ask Deep directly'; b.onclick = () => { d.remove(); this._renderHandover(el, question); }; d.appendChild(b); el.appendChild(d); }
  // ---------------------------------------------------------------- attachments
  _renderAttachments() {
    const box = this.shadowRoot.querySelector('.attach'); box.hidden = !this._attachments.length; box.innerHTML = '';
    this._attachments.forEach((a) => { const c = document.createElement('span'); c.className = 'achip' + (a.error ? ' err' : ''); c.title = a.error || a.name;
      c.innerHTML = `${a.image && a.preview ? `<img src="${a.preview}" alt="">` : '📎'}<span class="nm">${esc(a.name)}</span><span class="sz">${a.error ? esc(a.error) : a.id ? fmtSize(a.size) : 'uploading…'}</span><button type="button" class="x" aria-label="Remove ${esc(a.name)}">×</button><span class="bar" style="width:${a.id ? 100 : a.progress || 10}%"></span>`;
      c.querySelector('.x').onclick = () => { if (a.xhr) a.xhr.abort(); this._attachments = this._attachments.filter((x) => x !== a); this._renderAttachments(); this._syncSend(); }; box.appendChild(c); });
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
    const sh = this.shadowRoot, rec = sh.querySelector('.rec'), label = rec.querySelector('.rlabel'), time = rec.querySelector('.rtime');
    const t0 = Date.now(); const tick = setInterval(() => { const s = Math.floor((Date.now() - t0) / 1000); time.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }, 500);
    const show = (msg) => { label.textContent = msg; rec.classList.add('on'); }; const done = () => { clearInterval(tick); rec.classList.remove('on'); time.textContent = '0:00'; this._rec = null; };
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
  // ---------------------------------------------------------------- voice conversation ("Speak to Deep"): living orb + audio analysers (docs/AGENT_UI.md)
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
      v.meter = new m.AudioMeter(); v.orb = new m.Orb(canvas, { reduced: this._reduced, onGlow: (b, grey) => { const body = sh.querySelector('.vbody'); body.style.setProperty('--vglow-o', String(Math.min(1, b * 0.7))); body.style.setProperty('--vglow', grey > 0.5 ? 'rgba(150,150,160,.18)' : 'rgba(242,140,40,.28)'); } });
      v.orb.setMeter(v.meter); v.orb.setState('idle'); v.orb.start(); orbWrap.classList.remove('static');
    } catch (e) { orbWrap.classList.add('static'); canvas.hidden = true; console.warn('deep-assistant: orb unavailable', e); }
    const Api = this._speechApi(); const canListen = !!Api || (this._cfg.stt === 'server' && !!navigator.mediaDevices);
    if (!canListen) { this._vstate('Voice is not available in this browser.', 'idle'); return; }
    if (v.meter && navigator.mediaDevices) v.meter.listenMic().then((ok) => { v.mic = ok; });  // levels for the orb while you speak
    this._vstate('Listening…', 'listen'); this._vListen();
  }
  _showVoice(open) {
    const sh = this.shadowRoot, el = sh.querySelector('.voice'), pill = sh.querySelector('.vpill'); const v = this._voice;
    el.classList.toggle('open', open); pill.classList.toggle('show', !open && !!v);
    if (v && v.orb) { if (open) v.orb.resume(); else v.orb.pause(); }
    if (!open) { this._setStatus(this._busy ? 'work' : (v ? 'call' : 'idle')); this.$q.focus(); } else this.$q.blur();
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
    this.$q.focus();
  }
  _callSummary(secs, lines) {
    const row = document.createElement('div'); row.className = 'row bot'; const c = document.createElement('div'); c.className = 'card callcard';
    const dur = secs >= 60 ? `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, '0')}s` : `${secs}s`;
    c.innerHTML = `<div class="cc-t">${SVG.phone}<span>Voice call · ${dur}</span></div><div class="cc-s">${lines.length ? lines.length + ' exchange' + (lines.length === 1 ? '' : 's') : 'No exchanges'}</div>`;
    if (lines.length) { const w = document.createElement('button'); w.type = 'button'; w.className = 'worked'; w.innerHTML = `${SVG.chev}<span>Transcript</span>`; w.setAttribute('aria-expanded', 'false'); const st = document.createElement('div'); st.className = 'steps';
      st.innerHTML = lines.map((l) => `<div><b>${l.who === 'you' ? 'You' : 'Deep'}</b><span>${esc(l.text)}</span></div>`).join(''); w.onclick = () => { const o = !st.classList.contains('open'); st.classList.toggle('open', o); w.classList.toggle('open', o); w.setAttribute('aria-expanded', String(o)); }; c.append(w, st); }
    row.appendChild(c); this.$log.appendChild(row); this._scroll();
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
  async _send(text) {
    text = (text || this.$q.value).trim(); const files = this._attachments.filter((a) => a.id);
    if ((!text && !files.length) || this._busy) return; if (this._attachments.some((a) => a.xhr)) return;
    if (!this.api) { this._add('bot', 'This assistant has no api attribute set.'); return; }
    if (this._view !== 'chat') this.showView('chat');
    this.$q.value = ''; this._autosize(); this._closePops(); const sr = this.$log.querySelector('.suggest-row'); if (sr) sr.remove(); const cr = this.$log.querySelector('.caps-row'); if (cr) cr.remove(); this._setBusy(true);
    const shown = (text || (files.length > 1 ? 'Please look at the attached files.' : 'Please look at the attached file.')) + files.map((a) => `\n[attached: ${a.name}](/uploads/${a.id})`).join('');
    const user = this._add('user', '', Date.now()); this._setText(user, shown); this._transcript.push({ role: 'user', text: shown, ts: Date.now() }); this._persist(); this._emit('question', { text, attachments: files.map((a) => a.id) });
    this._attachments = []; this._renderAttachments();
    const bot = this._add('bot', ''); const act = this._activity(bot);
    let answer = '', sources = [], all = [], failed = false, mid = null; const sid = this._sid;
    this._controller = new AbortController(); const me = this._me || {};
    try {
      const r = await fetch(this._url('/chat'), { method: 'POST', signal: this._controller.signal, headers: this._headers(),
        body: JSON.stringify({ message: text || 'Please look at the attached file.', history: this._history, timezone: this.tz, attachments: files.map((a) => a.id), user_name: me.signed_in ? undefined : (me.name || undefined), user_email: me.signed_in ? undefined : (me.email || undefined) }) });
      if (!r.ok) { failed = true; this._setText(bot, r.status === 429 ? 'Slow down a little. Try again in a minute.' : `The assistant returned an error (${r.status}).`); return; }
      const reader = r.body.getReader(), dec = new TextDecoder(); let buf = '';
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i; while ((i = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, i).trim(); buf = buf.slice(i + 2); if (!line.startsWith('data:')) continue;
          const ev = JSON.parse(line.slice(5));
          if (ev.type === 'token') { if (!answer) { bot.classList.add('streaming'); if (act.last !== 'Writing…') act.set('writing', 'Writing…'); } answer += ev.text; this._setText(bot, answer, all, ev.text.length); }
          else if (ev.type === 'status') { act.set(ev.step, ev.label); }
          else if (ev.type === 'availability') { bot.classList.remove('thinking'); bot.classList.remove('skel'); const p = bot.querySelector('.picker'); if (p) p.classList.add('done'); const bx = this._availBox(bot); bx.dataset.slug = ev.schedule ? ev.schedule.slug : ''; this._renderAvailability(bx, ev); if (ev.ok) this._actionCard(bot, 'cal', SVG.cal, 'Checked Deep\'s calendar', `${ev.open_total || 0} open times in the next ${ev.days ? ev.days.length : 14} days`, 'ok'); else this._actionCard(bot, 'cal', SVG.cal, 'Checked Deep\'s calendar', ev.message || 'unavailable', 'fail'); }
          else if (ev.type === 'booking_review') { bot.classList.remove('thinking'); bot.classList.remove('skel'); this._renderReview(bot, ev); this._actionCard(bot, 'slot', SVG.cal, 'Checked that time', ev.status === 'review' ? (ev.slot ? ev.slot.label_visitor + ' is open' : 'open') : ev.status === 'unavailable' ? (ev.wanted || 'That time') + ' is not open' : (ev.message || ''), ev.status === 'review' ? 'ok' : 'fail'); }
          else if (ev.type === 'schedules') { bot.classList.remove('thinking'); bot.classList.remove('skel'); if (!answer) bot.innerHTML = ''; this._renderPicker(bot, ev.items); }
          else if (ev.type === 'slots') { bot.classList.remove('thinking'); this._renderSlots(bot, ev); }
          else if (ev.type === 'booking') { bot.classList.remove('thinking'); this._renderBooking(bot, ev); }
          else if (ev.type === 'sources') { all = ev.items || []; this._emit('sources', { items: all }); }
          else if (ev.type === 'meta') { mid = ev.message_id || null; }
          else if (ev.type === 'handover') { bot.classList.remove('thinking'); this._renderHandover(bot, ev.prefill || ''); }
          else if (ev.type === 'handover_offer') { this._renderHandoverOffer(bot, text); }
          else if (ev.type === 'error') { failed = true; this._setText(bot, 'Something went wrong on the assistant side. ' + (answer ? '' : 'Please try again.')); this._emit('error', { error: ev.error }); }
          if (this._atBottom()) this._scroll();
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') { this._setText(bot, answer || '(stopped)'); if (answer) bot.insertAdjacentHTML('beforeend', '<div class="note">Stopped.</div>'); }
      else { failed = true; this._setText(bot, 'Connection problem. Check that the assistant is reachable, then retry.'); this._emit('error', { error: String(e) }); }
    } finally {
      bot.classList.remove('streaming'); if (bot.classList.contains('thinking') || bot.classList.contains('skel')) this._setText(bot, answer || '…', all);
      if (answer && all.length) { sources = usedSources(answer, all); this._addSources(bot, sources); const sEl = bot.parentElement.querySelector('.sources'); if (sEl) sEl.classList.add('in'); this._contextChip(bot.parentElement, sources); }
      act.done(sources.length); const metaEl = bot.parentElement.querySelector(':scope > .meta'); if (metaEl) metaEl.classList.add('in');
      const raw = bot.dataset.raw || answer; this._addTools(bot, () => raw, failed ? text : null, mid); const tEl = bot.parentElement.querySelector('.tools'); if (tEl) tEl.classList.add('in');
      this._history.push({ role: 'user', content: shown }, { role: 'assistant', content: answer }); this._history = this._history.slice(-12);
      this._transcript.push({ role: 'bot', text: answer, sources, ts: Date.now(), mid }); this._persist();
      this._controller = null; this._setBusy(false); if (!this._voice) this.$q.focus();
      this._emit('answer', { question: text, answer: raw, sources, messageId: mid, failed }); this._updateChrome();
      if (this._view === 'chat' && this._sid === sid) await this._markRead(sid);
      this._refreshBadge(); if (this._view === 'messages') this._renderConversations();
      clearTimeout(this._titleT); this._titleT = setTimeout(() => { if (this._view === 'messages') this._renderConversations(); else this._convos = null; }, 6000);
    }
  }
}
if (!customElements.get('deep-assistant')) customElements.define('deep-assistant', DeepAssistant);
export { DeepAssistant };
