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
 *   tabs         sections, comma-separated from home,messages,help,news (default all; "messages" is always kept)
 *   news-tenant  whose News to show (default: the server's NEWS_TENANT, e.g. lakeb2b; app/news.py)
 *   news-popup   "off": no pop-up above the closed launcher when there is a new news item
 *   intro        "off": no opening animation when the launcher opens (lands on Home; skipped for reduced motion)
 *   shortcut     "Label|https://…" external scheduler link in Help (default: the Zoom booking page); "" hides it
 *   privacy-url  footer link (default: the server's PRIVACY_URL)
 * Methods      ask(text), book(callType?), open(), close(), toggle(), newChat() / reset(), openConversation(id),
 *              showView('home'|'chat'|'messages'|'help'|'news'), openHelp(focusSearch?), openArticle(slug), openCollection(slug),
 *              openNews(feed?), openNewsItem(id),
 *              setToken(token), download(), startVoice(), stopVoice()
 * Layout       like Intercom's messenger: Home / Messages / Help tabs with a bottom bar (tabs attribute), the chat on top
 *              (docs/ROADMAP.md); the help center comes from GET /help* (app/help.py)
 * Events       deep-assistant:ready | :open | :close | :question | :answer | :sources | :booking | :handover
 *              | :feedback | :error | :view | :upload | :voice | :action | :ui   (CustomEvent, bubbles + composed)
 * Theming      Indigo Dream tokens, override on the element: --da-primary --da-primary-hover --da-navy --da-lavender --da-dot
 *              --da-bg --da-surface --da-success --da-text --da-muted --da-line --da-font --da-radius
 */
const VERSION = '2026.11.02.9';
// Ask Deep links from booking emails: the Send test copy carries only a question key (prefilled, never sent)
const ASK_SAMPLE = { prep: 'How should I prepare for this call?', agenda: 'What will we cover on the call?', join: 'How do I join the call?',
  confirm_how: 'How do I confirm my time on Zoom?', after_confirm: 'What happens after I confirm on Zoom?', about: 'What can Deep help me with?',
  when_now: 'When is my call now?' };
const EMAIL_STATUS = { confirmed: 'confirmed', pending_zoom: 'waiting for you to confirm on Zoom', cancelled: 'cancelled' };
const DEFAULT_SHORTCUT = 'Open the Zoom scheduler|https://scheduler.zoom.us/sreedeep';
const ALL_TABS = ['home', 'messages', 'help', 'news'];
const TAB_LABEL = { home: 'Home', messages: 'Messages', help: 'Help', news: 'News' };
const INTRO = "I can help you explore LakeB2B's solutions, answer questions about our services, or connect you with the right expert.";
// voice languages: code -> BCP-47 tag for speech recognition / synthesis, native name, and the call-view labels
const VOICE_LANGS = { auto: ['', 'Auto'], en: ['en-US', 'English'], hi: ['hi-IN', 'हिन्दी'], te: ['te-IN', 'తెలుగు'], ta: ['ta-IN', 'தமிழ்'], es: ['es-ES', 'Español'], fr: ['fr-FR', 'Français'], de: ['de-DE', 'Deutsch'], pt: ['pt-BR', 'Português'], it: ['it-IT', 'Italiano'], nl: ['nl-NL', 'Nederlands'], ar: ['ar-SA', 'العربية'], zh: ['zh-CN', '中文'], ja: ['ja-JP', '日本語'], ko: ['ko-KR', '한국어'], ru: ['ru-RU', 'Русский'], bn: ['bn-IN', 'বাংলা'] };
const VOICE_LABELS = { en: { listen: 'Listening…', think: 'Thinking…', speak: 'Speaking…', muted: 'Muted' }, hi: { listen: 'सुन रहा हूँ…', think: 'सोच रहा हूँ…', speak: 'बोल रहा हूँ…', muted: 'म्यूट' }, te: { listen: 'వింటున్నాను…', think: 'ఆలోచిస్తున్నాను…', speak: 'మాట్లాడుతున్నాను…', muted: 'మ్యూట్' }, ta: { listen: 'கேட்கிறேன்…', think: 'யோசிக்கிறேன்…', speak: 'பேசுகிறேன்…', muted: 'ஒலியடக்கம்' }, es: { listen: 'Escuchando…', think: 'Pensando…', speak: 'Hablando…', muted: 'Silenciado' }, fr: { listen: 'À l’écoute…', think: 'Réflexion…', speak: 'Je parle…', muted: 'Muet' }, de: { listen: 'Ich höre zu…', think: 'Ich denke nach…', speak: 'Ich spreche…', muted: 'Stumm' }, pt: { listen: 'Ouvindo…', think: 'Pensando…', speak: 'Falando…', muted: 'Mudo' } };
// microphone settings for server speech-to-text (docs/MEMORY_VOICE.md "Accuracy")
const STT_AUDIO = { echoCancellation: true, noiseSuppression: false, autoGainControl: true, channelCount: 1 };
const BOOK_RE = /\b(book|schedule|meeting|appointment|demo call|call with)\b/i;
const CMP_RE = /\b(compare|comparison|vs\.?|versus|difference(s)? between)\b/i;
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
// wording when the console switched every company website off (app/knowledge.py widget_scope): Deep's companies in general
const NO_BRAND = { [INTRO]: "I can help you explore Deep's companies, answer questions about their services, or connect you with the right expert.",
  'What data solutions does LakeB2B offer?': "What do Deep's companies offer?", 'Help me find the right LakeB2B solution for my business.': 'Help me find the right solution for my business.',
  'Learn about LakeB2B': 'Learn about Deep', 'What is LakeB2B and what does it do?': 'What does Deep do?',
  'What are some real use cases for LakeB2B data?': 'What are some real customer use cases?',
  'Answer questions about LakeB2B, with links to the pages it used': "Answer questions about Deep's companies, with links to the pages it used" };
const CONTEXT_ACTIONS = { general: ['explore', 'fit', 'about', 'book'], product: ['product', 'usecases', 'demo', 'about'], solutions: ['fit', 'explore', 'usecases', 'book'], contact: ['book', 'human', 'fit', 'about'] };

const DARK = `--da-ink:#ADA4FF; --da-bg:#0F1324; --da-dot:rgba(255,255,255,.075); --da-surface:#171C33; --da-subtle:#1E2441; --da-line:#2A3152; --da-line-strong:#3A4268; --da-text:#ECEEF8; --da-muted:#9BA3C0;
  --da-lavender:#26234F; --da-user:#5546F7; --da-user-text:#FFFFFF; --da-head:#171C33; --da-head-text:#ECEEF8; --da-head-muted:#9BA3C0; --da-bot:#1E2441; --da-hero:#0A0D1C; --da-primary-soft:rgba(124,112,255,.16); --da-danger-soft:rgba(232,72,108,.14); --da-danger-text:#FF9DB2; --da-ok-text:#5BE0B5;
  --da-thumb:rgba(255,255,255,.18); --da-shadow-sm:0 1px 2px rgba(0,0,0,.3); --da-shadow-md:0 10px 28px -10px rgba(0,0,0,.6); --da-shadow-lg:0 28px 64px -16px rgba(0,0,0,.7), 0 0 0 1px rgba(255,255,255,.06)`;

const CSS = `
:host {
  /* Indigo Dream design tokens */
  --da-primary:#5546F7; --da-primary-hover:#4537E8; --da-ink:var(--da-primary); --da-navy:#151B32; --da-lavender:#EEECFF; --da-bg:#FFFFFF; --da-dot:rgba(21,27,50,.12); --da-surface:#FFFFFF;
  --da-success:#19B887; --da-text:#151B32; --da-muted:#68718A; --da-line:#E4E7F2; --da-line-strong:#CDD2E3; --da-subtle:#F0F2F9;
  --da-user:var(--da-primary); --da-user-text:#FFFFFF; --da-head:var(--da-surface); --da-head-text:var(--da-text); --da-head-muted:var(--da-muted);
  --da-bot:#F5F5F5; --da-hero:#0B1328; --da-card-shadow:0 4px 28px rgba(9,14,21,.06), 0 1px 4px rgba(9,14,21,.06);
  --da-danger:#D6345B; --da-danger-soft:#FDEEF2; --da-danger-text:#A61E43; --da-ok-text:#0E8A64;
  --da-primary-soft:rgba(85,70,247,.10); --da-primary-ring:rgba(85,70,247,.35); --da-thumb:rgba(21,27,50,.20);
  --da-radius:24px; --da-r-lg:14px; --da-r-md:10px; --da-r-sm:7px;
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
header { flex:none; position:relative; z-index:10; display:flex; align-items:center; gap:10px; min-height:58px; padding:9px 8px 9px 16px; background:var(--da-head); color:var(--da-head-text) }
.hav { position:relative; flex:none; width:34px; height:34px; border-radius:10px; display:grid; place-items:center; background:var(--da-grad); color:#fff; box-shadow:inset 0 0 0 1px rgba(255,255,255,.16) } .hav svg { width:19px; height:19px }
.hav::after { content:""; position:absolute; inset:-3px; border-radius:10px; border:2px solid rgba(169,159,255,.0); transition:border-color .2s } .hav.work::after { border-color:rgba(169,159,255,.75); animation:da-blink 1.2s ease-in-out infinite }
.brand { flex:1; min-width:0 } .brand h1 { margin:0; font-size:14.5px; font-weight:650; line-height:1.25; letter-spacing:-.01em; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.brand p { margin:1px 0 0; display:flex; align-items:center; gap:6px; font-size:11.5px; line-height:1.3; color:var(--da-head-muted); white-space:nowrap; overflow:hidden } .brand .sub { overflow:hidden; text-overflow:ellipsis } .brand .sep { opacity:.6 }
.st { display:inline-flex; align-items:center; gap:5px; flex:none } .st i { width:7px; height:7px; border-radius:50%; background:var(--da-success); box-shadow:0 0 0 3px rgba(25,184,135,.22) }
.st.off i { background:#8C93AB; box-shadow:none } .st.work i { background:#A99FFF; box-shadow:0 0 0 3px rgba(169,159,255,.25); animation:da-blink 1s ease-in-out infinite } .st.call i { background:#FF6B8A; box-shadow:0 0 0 3px rgba(255,107,138,.25); animation:da-blink 1.4s ease-in-out infinite }
header:has(.home:not([hidden])) { padding-left:8px; gap:8px }
.vtitle { flex:1; min-width:0; margin:0; font-size:14px; font-weight:650; letter-spacing:-.01em; color:#fff }
.hbtn { position:relative; flex:none; width:32px; height:32px; display:inline-grid; place-items:center; padding:0; border:0; border-radius:8px; background:transparent; color:rgba(255,255,255,.75); cursor:pointer; transition:background .15s, color .15s }
.hbtn:hover { background:rgba(255,255,255,.10); color:#fff } .hbtn svg { width:17px; height:17px } .hbtn:focus-visible { outline-color:#fff; outline-offset:0 } .hbtn[aria-expanded="true"] { background:rgba(255,255,255,.14); color:#fff }
.hbadge { position:absolute; top:3px; right:3px; min-width:16px; height:16px; padding:0 4px; border-radius:999px; background:#FF5C7A; color:#fff; font:700 10px/16px system-ui, sans-serif; text-align:center; box-shadow:0 0 0 2px var(--da-head) }
.vpill { display:none; align-items:center; gap:6px; height:28px; padding:0 10px; border:1px solid rgba(255,255,255,.2); border-radius:999px; background:rgba(255,255,255,.08); color:#fff; font-size:12px; font-weight:600; cursor:pointer; flex:none } .vpill.show { display:inline-flex } .vpill i { width:6px; height:6px; border-radius:50%; background:#FF6B8A; animation:da-blink 1s infinite }
.menu { position:absolute; right:8px; top:calc(100% - 4px); z-index:30; min-width:208px; padding:4px; background:var(--da-surface); color:var(--da-text); border:1px solid var(--da-line); border-radius:10px; box-shadow:var(--da-shadow-md); display:none }
.menu.open { display:block; animation:da-pop .14s var(--da-ease) both; transform-origin:top right }
.menu button { display:flex; align-items:center; gap:10px; width:100%; padding:7px 10px; border:0; border-radius:6px; background:transparent; text-align:left; font-size:13px; cursor:pointer } .menu button:hover, .menu button:focus-visible { background:var(--da-subtle); outline:none } .menu svg { width:15px; height:15px; color:var(--da-muted); flex:none }
.menu hr { border:0; border-top:1px solid var(--da-line); margin:6px 4px }

/* ---------------------------------------------------------------- views + conversation */
.views { flex:1; min-height:0; min-width:0; display:flex } .view { flex:1; min-height:0; min-width:0; display:flex; flex-direction:column; position:relative }
.log { flex:1; min-height:0; overflow-y:auto; overflow-x:hidden; padding:18px 16px 12px; display:flex; flex-direction:column; gap:14px }
.welcome { display:flex; flex-direction:column; gap:12px; padding:4px 2px 0; animation:da-in .3s var(--da-ease) both }
.wav { width:40px; height:40px; border-radius:12px; display:grid; place-items:center; background:var(--da-grad); color:#fff; box-shadow:0 8px 18px -8px rgba(85,70,247,.6) } .wav svg { width:22px; height:22px }
.welcome h2 { margin:0; font-size:18.5px; font-weight:700; line-height:1.25; letter-spacing:-.02em; color:var(--da-text) }
.welcome p { margin:-4px 0 0; font-size:13.5px; line-height:1.55; color:var(--da-muted) }
.emailctx { margin:0 0 2px; padding:8px 10px; border-radius:10px; background:var(--da-soft, rgba(85,70,247,.08)); font-size:12.5px; line-height:1.45; color:var(--da-text) }
.emailctx b { font-weight:650 }
.acts-label { margin:8px 2px -2px; font-size:11px; font-weight:650; letter-spacing:.06em; text-transform:uppercase; color:var(--da-muted) }
.acts { display:flex; flex-direction:column; gap:8px }
.act { display:flex; align-items:center; gap:12px; width:100%; min-height:46px; padding:8px 12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-surface); color:var(--da-text); font-size:13.5px; font-weight:550; text-align:left; text-decoration:none; cursor:pointer; box-shadow:var(--da-shadow-sm); transition:border-color .15s, box-shadow .15s, transform .15s }
.act .ai { flex:none; width:30px; height:30px; border-radius:9px; display:grid; place-items:center; background:var(--da-lavender); color:var(--da-ink) } .act .ai svg { width:16px; height:16px }
.act .al { flex:1; min-width:0 } .act .al small { display:block; margin-top:1px; font-size:12px; font-weight:400; color:var(--da-muted) }
.act > svg { flex:none; width:15px; height:15px; color:var(--da-muted); transition:transform .15s, color .15s }
.act:hover { border-color:rgba(85,70,247,.45); background:var(--da-subtle) } .act:hover > svg { transform:translateX(2px); color:var(--da-ink) } .act:active { transform:scale(.99) }
.act.book .ai { background:var(--da-primary); color:#fff }
.row { display:flex; gap:8px; max-width:100%; min-width:0; animation:da-in .22s var(--da-ease) both } .row.user { justify-content:flex-end }
.bav { flex:none; width:26px; height:26px; margin-top:2px; border-radius:8px; display:grid; place-items:center; background:var(--da-grad); color:#fff } .bav svg { width:15px; height:15px }
.col { display:flex; flex-direction:column; align-items:flex-start; min-width:0; max-width:calc(100% - 34px) } .row.user .col { align-items:flex-end; max-width:85% } .row.wide .col { flex:1 }
.msg { position:relative; min-width:0; max-width:100%; padding:9px 13px; border-radius:14px; font-size:14px; line-height:1.55; white-space:pre-wrap; overflow-wrap:anywhere }
.bot .msg { background:var(--da-surface); color:var(--da-text); border:1px solid var(--da-line); border-top-left-radius:5px; box-shadow:var(--da-shadow-sm) }
.user .msg { background:var(--da-user); color:var(--da-user-text); border-top-right-radius:5px }
.msg.hascard { width:100%; padding:12px } .msg.err { background:var(--da-danger-soft); border-color:rgba(214,52,91,.28); color:var(--da-danger-text) }
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
.followups { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; animation:da-in .25s .05s var(--da-ease) both }
.fu { display:inline-flex; align-items:center; gap:6px; min-height:30px; padding:4px 11px; border:1px solid rgba(85,70,247,.3); border-radius:999px; background:var(--da-surface); color:var(--da-ink); font-size:12.5px; font-weight:550; cursor:pointer; text-align:left; transition:background .15s, border-color .15s }
.fu:hover { background:var(--da-lavender); border-color:var(--da-ink) } .fu svg { width:14px; height:14px; flex:none }
.jump { position:absolute; left:50%; bottom:calc(100% + 8px); transform:translateX(-50%); z-index:4; display:inline-flex; align-items:center; gap:6px; height:30px; padding:0 12px; border:1px solid var(--da-line); border-radius:999px; background:var(--da-surface); color:var(--da-text); box-shadow:var(--da-shadow-md); font-size:12px; font-weight:600; cursor:pointer; animation:da-in .18s var(--da-ease) both } .jump svg { width:14px; height:14px }
.toastmsg { position:absolute; left:50%; bottom:128px; z-index:40; transform:translate(-50%, 8px); padding:8px 14px; border-radius:999px; background:var(--da-navy); color:#fff; font-size:13px; box-shadow:var(--da-shadow-md); opacity:0; pointer-events:none; transition:opacity .2s, transform .2s } .toastmsg.show { opacity:1; transform:translate(-50%, 0) }
.fbpop { display:flex; flex-direction:column; gap:8px; width:min(300px, 100%); margin:6px 0 0; padding:12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-surface); box-shadow:var(--da-shadow-md); animation:da-pop .16s var(--da-ease) both }
.fbpop .reasons { display:flex; flex-wrap:wrap; gap:4px } .reason { height:28px; padding:0 10px; border:1px solid var(--da-line); border-radius:999px; background:transparent; font-size:12px; cursor:pointer } .reason:hover { border-color:var(--da-ink) } .reason.on { background:var(--da-primary); border-color:var(--da-ink); color:#fff }
.fbpop input { height:34px; padding:0 10px; border:1px solid var(--da-line); border-radius:8px; background:var(--da-surface); font-size:13px } .fbpop input:focus { border-color:var(--da-ink); box-shadow:0 0 0 3px var(--da-primary-soft) }
.fbpop .fbrow { display:flex; justify-content:flex-end; gap:6px }

/* ---------------------------------------------------------------- buttons, cards, forms */
.btn { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:36px; padding:7px 13px; border:1px solid var(--da-line); border-radius:9px; background:var(--da-surface); color:var(--da-text); font-size:13.5px; font-weight:600; line-height:1.2; text-align:center; text-decoration:none; cursor:pointer; transition:background .15s, border-color .15s, color .15s, box-shadow .15s }
.btn:hover { border-color:var(--da-line-strong); background:var(--da-subtle) } .btn svg { width:16px; height:16px; flex:none }
.btn.primary { background:var(--da-primary); border-color:var(--da-ink); color:#fff; box-shadow:0 6px 16px -8px rgba(85,70,247,.7) } .btn.primary:hover { background:var(--da-primary-hover); border-color:var(--da-primary-hover) }
.btn.danger { background:#D6345B; border-color:#B52A4C; color:#fff } .btn.danger:hover { background:#B52A4C }
.btn.ghost { border-color:transparent; background:transparent; color:var(--da-muted) } .btn.ghost:hover { color:var(--da-text); background:var(--da-subtle) }
.btn.block { width:100% } .btn.sm { min-height:32px; padding:4px 10px; font-size:12.5px } .btn:disabled { opacity:.55; cursor:not-allowed }
.btn.loading::before { content:""; width:14px; height:14px; border-radius:50%; border:2px solid rgba(255,255,255,.4); border-top-color:#fff; animation:da-spin .8s linear infinite }
.hrow { display:flex; flex-wrap:wrap; align-items:center; gap:8px }
.note { margin:0; font-size:12px; line-height:1.45; color:var(--da-muted) } .note.warn { color:var(--da-danger-text) } .note.ok { color:var(--da-ok-text) }
.banner { display:flex; gap:8px; align-items:flex-start; padding:10px 12px; border-radius:10px; background:var(--da-danger-soft); color:var(--da-danger-text); font-size:13px; line-height:1.45 } .banner svg { width:16px; height:16px; flex:none; margin-top:1px } .banner.info { background:var(--da-lavender); color:var(--da-text) }
.card { white-space:normal; min-width:0; max-width:100% }
.field { display:flex; flex-direction:column; gap:4px } .field > label { font-size:12px; font-weight:600; color:var(--da-text) } .field > label span { font-weight:400; color:var(--da-muted) }
.inp { width:100%; height:38px; padding:0 11px; border:1px solid var(--da-line); border-radius:9px; background:var(--da-surface); color:var(--da-text); font-size:14px; transition:border-color .15s, box-shadow .15s }
textarea.inp { height:auto; min-height:68px; padding:9px 12px; resize:vertical; line-height:1.45 } .inp::placeholder { color:var(--da-muted); opacity:.8 }
.inp:focus { border-color:var(--da-ink); box-shadow:0 0 0 3px var(--da-primary-soft) } .inp[aria-invalid="true"] { border-color:var(--da-danger) } .ferr { font-size:12px; color:var(--da-danger-text) }

/* booking card (docs/BOOKING.md) */
.bk { display:flex; flex-direction:column; gap:12px } .msg > .bk.card, .msg > .hform { margin-top:12px }
.bk-head { display:flex; align-items:center; gap:8px } .bk-back { flex:none; width:30px; height:30px; display:inline-grid; place-items:center; margin-left:-4px; padding:0; border:0; border-radius:8px; background:transparent; color:var(--da-muted); cursor:pointer } .bk-back:hover { background:var(--da-subtle); color:var(--da-text) } .bk-back svg { width:18px; height:18px }
.bk-t { flex:1; min-width:0; display:flex; align-items:baseline; justify-content:space-between; gap:8px } .bk-t b { font-size:14.5px; font-weight:650; letter-spacing:-.01em } .bk-t span { flex:none; font-size:11.5px; color:var(--da-muted) }
.bk-prog { display:grid; grid-template-columns:repeat(4, 1fr); gap:4px; margin-top:-4px } .bk-prog i { height:3px; border-radius:2px; background:var(--da-line); transition:background .2s } .bk-prog i.on { background:var(--da-primary) }
.ctypes { display:flex; flex-direction:column; gap:8px }
.ctype { position:relative; display:flex; align-items:flex-start; gap:12px; width:100%; padding:10px; border:1px solid var(--da-line); border-radius:9px; background:var(--da-surface); color:var(--da-text); text-align:left; cursor:pointer; transition:border-color .15s, box-shadow .15s }
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
.time { min-height:34px; padding:4px 6px; border:1px solid var(--da-line); border-radius:8px; background:var(--da-surface); color:var(--da-text); font-size:13px; font-weight:600; cursor:pointer; transition:border-color .15s, color .15s, background .15s }
.time:hover { border-color:var(--da-ink); color:var(--da-ink) } .time.on { background:var(--da-primary); border-color:var(--da-ink); color:#fff }
.sumbox { border:1px solid var(--da-line); border-radius:12px; overflow:hidden } .sumrow { display:flex; justify-content:space-between; gap:12px; padding:9px 12px; border-bottom:1px solid var(--da-line); font-size:13px } .sumrow:last-child { border-bottom:0 }
.sumrow span { flex:none; color:var(--da-muted) } .sumrow b { min-width:0; font-weight:600; text-align:right; overflow-wrap:anywhere }
.pickd { display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:12px; background:var(--da-lavender); font-size:13px } .pickd svg { width:16px; height:16px; color:var(--da-ink); flex:none } .pickd span { flex:1; min-width:0 } .pickd b { font-weight:650 }
.linkbtn { padding:0; border:0; background:none; color:var(--da-ink); font-size:12.5px; font-weight:600; cursor:pointer; text-decoration:underline; text-underline-offset:2px }
.bform, .hform { display:flex; flex-direction:column; gap:10px }
.frus { display:flex; flex-direction:column; gap:10px; margin:10px 0 0; padding:12px 14px; border:1px solid var(--da-line); border-radius:14px; background:var(--da-surface); box-shadow:inset 3px 0 0 var(--da-primary); font-size:13.5px; line-height:1.45; animation:da-in .3s var(--da-ease) }
.frus p { margin:0 } .frus b { font-weight:650 } .frus .frow { display:flex; gap:8px; flex-wrap:wrap } .frus .btn svg { width:15px; height:15px; margin-right:6px; vertical-align:-3px }
@media (prefers-reduced-motion: reduce) { .frus { animation:none } }
.cmp, .cmail { margin-top:4px } .cmp .bk-t, .cmail .bk-t { display:block } .cmp .bk-t small, .cmail .bk-t small { display:block; color:var(--da-muted); font-weight:400; font-size:12.5px; margin-top:2px }
.cmp-l { font-size:12px; font-weight:600; color:var(--da-muted); margin:12px 0 6px } .cmp-chips { display:flex; flex-wrap:wrap; gap:6px }
.cmp-chips .chip { border:1px solid var(--da-line); background:var(--da-surface); color:var(--da-text); border-radius:999px; padding:6px 11px; font:inherit; font-size:13px; cursor:pointer }
.cmp-chips .chip:hover { border-color:var(--da-line-strong) } .cmp-chips .chip[aria-pressed="true"] { background:var(--da-primary-soft); border-color:var(--da-primary); color:var(--da-text); font-weight:600 }
.cmp .inp { width:100%; box-sizing:border-box } .cmp .btn.block, .cmail .btn.block { margin-top:14px } .cmail .note a { color:inherit }
.frus.buy { box-shadow:inset 3px 0 0 var(--da-ok-text, #15803D) } .followups.fit a.fu { text-decoration:none }
.hwrite { display:flex; align-items:center; gap:6px; margin:-2px 0 6px; color:var(--da-muted); font-size:12px } .hwrite svg { width:13px; height:13px; flex:none }
.hwrite.busy span { background:linear-gradient(90deg, var(--da-muted) 30%, var(--da-ink) 50%, var(--da-muted) 70%); background-size:200% 100%; -webkit-background-clip:text; background-clip:text; color:transparent; animation:da-shimmer 1.6s linear infinite }
.hform .btn.nudge { animation:da-nudge 1.2s var(--da-ease) 2 } @keyframes da-nudge { 0%, 100% { box-shadow:0 0 0 0 rgba(108,92,231,0) } 50% { box-shadow:0 0 0 6px rgba(108,92,231,.22) } }
.edr { display:flex; align-items:center; gap:4px; margin:0 0 8px; padding:4px 4px 4px 10px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-lavender); animation:da-in .25s var(--da-ease) } .edr[hidden] { display:none }
.edr-go { flex:1; min-width:0; display:flex; align-items:center; gap:8px; padding:4px 0; border:0; background:none; color:var(--da-text); font:inherit; font-size:12.5px; text-align:left; cursor:pointer }
.edr-go svg { width:15px; height:15px; flex:none; color:var(--da-ink) } .edr-go .edr-t { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap } .edr-go b { flex:none; font-weight:650; color:var(--da-ink) }
.edr-x { flex:none; width:26px; height:26px; border:0; border-radius:8px; background:none; color:var(--da-muted); font-size:16px; line-height:1; cursor:pointer } .edr-x:hover { background:rgba(0,0,0,.06) }
.edpop small { display:flex; align-items:center; gap:6px } .edpop small svg { width:13px; height:13px }
@media (prefers-reduced-motion: reduce) { .hwrite.busy span, .hform .btn.nudge, .edr { animation:none } .hwrite.busy span { color:var(--da-muted) } }
.row.agent .msg { box-shadow:inset 3px 0 0 var(--da-ink) } .row.agent .meta b { font-weight:650; color:var(--da-text) }
.row.rate { justify-content:center } .row.rate .col { width:100%; max-width:420px } .rcard { display:flex; flex-direction:column; gap:10px; margin-top:4px } .faces { display:flex; gap:6px; flex-wrap:wrap }
.face { width:42px; height:42px; border-radius:12px; border:1px solid var(--da-line, rgba(0,0,0,.12)); background:transparent; font-size:22px; line-height:1; cursor:pointer }
.face:hover, .face:focus-visible { background:var(--da-lavender) } .face.on { background:var(--da-lavender); border-color:var(--da-ink) }
.rcard .rrow { display:flex; gap:6px } .rcard .rrow .inp { flex:1 }
.guests { display:flex; flex-direction:column; gap:6px } .glabel { font-size:12px; font-weight:600; color:var(--da-text) } .glabel span { font-weight:400; color:var(--da-muted) }
.glist { display:flex; flex-direction:column; gap:6px } .grow { display:grid; grid-template-columns:1fr 1.25fr 30px; gap:6px; align-items:center } .grow .gerr { grid-column:1 / -1 }
.gx { width:30px; height:30px; padding:0; border:0; border-radius:8px; background:transparent; color:var(--da-muted); cursor:pointer; display:grid; place-items:center } .gx:hover, .gx:focus-visible { background:var(--da-surface); color:var(--da-text) } .gx svg { width:14px; height:14px }
.addg { align-self:flex-start }
.booked { display:flex; flex-direction:column; gap:6px } .bk-ok { display:flex; align-items:center; gap:10px; font-size:16px; font-weight:700; letter-spacing:-.01em }
.chk { width:30px; height:30px; flex:none } .chk circle { fill:rgba(25,184,135,.12); stroke:var(--da-success); stroke-width:2; stroke-dasharray:80; stroke-dashoffset:80; animation:da-draw .5s ease-out forwards } .chk path { fill:none; stroke:var(--da-success); stroke-width:2.4; stroke-linecap:round; stroke-linejoin:round; stroke-dasharray:30; stroke-dashoffset:30; animation:da-draw .35s .35s ease-out forwards } @keyframes da-draw { to { stroke-dashoffset:0 } }
.pend { width:30px; height:30px; flex:none; border-radius:50%; display:grid; place-items:center; background:var(--da-lavender); color:var(--da-ink) } .pend svg { width:17px; height:17px }
.bk-when { font-size:15px; font-weight:650 } .bk-sub { font-size:12.5px; color:var(--da-muted) }
.nexts { list-style:none; display:flex; flex-direction:column; gap:7px; margin:6px 0 0; padding:12px 0 0; border-top:1px solid var(--da-line); font-size:13px; color:var(--da-text) } .nexts li { display:flex; gap:8px; align-items:flex-start } .nexts svg { width:15px; height:15px; flex:none; margin-top:2px; color:var(--da-success) } .nexts .nx { color:var(--da-ink) }
.callcard { padding:12px 14px; border:1px solid var(--da-line); border-radius:14px; background:var(--da-surface) } .callcard .cc-t { display:flex; align-items:center; gap:8px; font-size:13.5px; font-weight:650 } .callcard .cc-t svg { width:16px; height:16px; color:var(--da-ink) } .callcard .cc-s { margin-top:2px; font-size:12px; color:var(--da-muted) }

/* ---------------------------------------------------------------- composer */
.composer { flex:none; position:relative; padding:8px 12px 0; background:var(--da-bg) }
.cbox { padding:5px; border:1px solid var(--da-line); border-radius:16px; background:var(--da-surface); box-shadow:var(--da-shadow-sm); transition:border-color .15s, box-shadow .15s }
.cbox.focus { border-color:rgba(85,70,247,.6); box-shadow:0 0 0 3px var(--da-primary-soft) } .cbox.drop { border-color:var(--da-ink); background:var(--da-lavender) }
textarea.q { display:block; flex:1; min-width:0; width:auto; min-height:32px; max-height:120px; padding:5px 4px; border:0; background:transparent; color:var(--da-text); font-size:14px; line-height:22px; resize:none; outline:none; caret-color:var(--da-ink) } textarea.q::placeholder { color:var(--da-muted) }
.crow { display:flex; align-items:flex-end; gap:2px }
.plus-wrap { position:relative; flex:none }
.pmenu { position:absolute; left:-1px; bottom:calc(100% + 10px); z-index:7; min-width:184px; padding:4px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-surface); box-shadow:var(--da-shadow-md); display:none } .pmenu.open { display:block; animation:da-pop .14s var(--da-ease) both; transform-origin:bottom left }
.pmenu button { display:flex; align-items:center; gap:10px; width:100%; padding:8px 10px; border:0; border-radius:9px; background:transparent; color:var(--da-text); font-size:13.5px; text-align:left; cursor:pointer } .pmenu button:hover, .pmenu button:focus-visible { background:var(--da-subtle); outline:none } .pmenu svg { width:17px; height:17px; color:var(--da-muted); flex:none } .pmenu .on svg { color:var(--da-ink) }
.cicon { width:32px; height:32px; display:inline-grid; place-items:center; padding:0; border:0; border-radius:10px; background:transparent; color:var(--da-muted); cursor:pointer; flex:none } .cicon:hover { background:var(--da-subtle); color:var(--da-text) } .cicon svg { width:17px; height:17px } .cicon.on { color:var(--da-ink); background:var(--da-lavender) }
.cicon.speak { color:var(--da-ink) } .cicon.speak:hover { background:var(--da-lavender); color:var(--da-ink) } .b-plus[aria-expanded="true"] { background:var(--da-lavender); color:var(--da-ink) } .b-plus svg { transition:transform .18s var(--da-ease) } .b-plus[aria-expanded="true"] svg { transform:rotate(45deg) }
.send { width:32px; height:32px; margin-left:2px; display:inline-grid; place-items:center; padding:0; border:0; border-radius:10px; background:var(--da-primary); color:#fff; cursor:pointer; flex:none; transition:background .15s, color .15s } .send svg { width:17px; height:17px }
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
.msearch { width:100%; height:34px; padding:0 12px 0 34px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-surface); color:var(--da-text); font-size:14px } .msearch:focus { border-color:var(--da-ink); box-shadow:0 0 0 3px var(--da-primary-soft) } .msearch::placeholder { color:var(--da-muted) }
.mgroup { margin:14px 10px 4px; font-size:11px; font-weight:650; letter-spacing:.06em; text-transform:uppercase; color:var(--da-muted) }
.convo { position:relative; display:flex; align-items:center; gap:12px; width:100%; min-width:0; padding:9px; border:0; border-radius:10px; background:transparent; color:var(--da-text); text-align:left; cursor:pointer; overflow:hidden; transition:background .15s, box-shadow .15s }
.convo:hover, .convo:focus-visible { background:var(--da-surface); box-shadow:var(--da-shadow-sm) } .convo.cur { background:var(--da-surface); box-shadow:inset 0 0 0 1px var(--da-line) }
.avatar { flex:none; width:32px; height:32px; border-radius:10px; display:grid; place-items:center; background:var(--da-lavender); color:var(--da-ink); font-weight:700; font-size:13px } .avatar svg { width:17px; height:17px }
.convo .c { flex:1 1 auto; min-width:0 } .convo .n { display:block; font-size:13.5px; font-weight:600; line-height:1.35; white-space:nowrap; overflow:hidden; text-overflow:ellipsis } .convo.unread .n { font-weight:750 }
.convo .p { display:block; margin-top:2px; font-size:12.5px; line-height:1.35; color:var(--da-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.convo .r { flex:none; align-self:flex-start; display:flex; flex-direction:column; align-items:flex-end; gap:6px; min-width:32px; padding-top:2px } .convo .ctime { font-size:11.5px; color:var(--da-muted); white-space:nowrap } .dot { width:8px; height:8px; border-radius:50%; background:var(--da-primary) }
.cur-tag { padding:1px 7px; border-radius:999px; background:var(--da-lavender); color:var(--da-ink); font-size:10.5px; font-weight:650 }
.brow { position:relative; display:flex; align-items:center; gap:12px; width:100%; min-width:0; padding:10px; border:0; border-radius:12px; background:transparent; color:var(--da-text); text-align:left; cursor:pointer; transition:background .15s, box-shadow .15s }
.brow:hover, .brow:focus-visible { background:var(--da-surface); box-shadow:var(--da-shadow-sm) } .brow .c { flex:1 1 auto; min-width:0 } .brow .n { display:block; font-size:13.5px; font-weight:600; line-height:1.35; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.brow .p { display:block; font-size:12.5px; color:var(--da-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis } .brow.cancelled .n, .brow.past .n { color:var(--da-muted); font-weight:500 }
.bstate { flex:none; padding:2px 8px; border-radius:999px; font-size:10.5px; font-weight:650; background:var(--da-lavender); color:var(--da-ink) } .bstate.ok { background:#E6F6EE; color:#15733F } .bstate.off { background:var(--da-surface); color:var(--da-muted); box-shadow:inset 0 0 0 1px var(--da-line) } .bstate.hold { background:#FFF2E0; color:#8A4B00 }
.bookings { margin-bottom:6px; padding-bottom:6px; border-bottom:1px solid var(--da-line) }
.more2 { position:absolute; right:8px; top:50%; transform:translateY(-50%); width:28px; height:28px; border-radius:8px; background:var(--da-surface); color:var(--da-muted); display:none; align-items:center; justify-content:center; cursor:pointer } .more2 svg { width:16px; height:16px }
.convo:hover .more2, .convo:focus-within .more2 { display:inline-flex } .more2:hover { background:var(--da-subtle); color:var(--da-text) } @media (hover:none) { .more2 { display:none !important } }
.rename { display:flex; gap:6px; align-items:center; padding:6px 10px 10px 56px } .rename .inp { flex:1; min-width:0; height:34px }
.empty { display:flex; flex-direction:column; align-items:center; gap:6px; padding:40px 20px 20px; text-align:center; color:var(--da-muted); font-size:13.5px; line-height:1.5 }
.empty .ei { width:48px; height:48px; margin-bottom:6px; border-radius:16px; display:grid; place-items:center; background:var(--da-lavender); color:var(--da-ink) } .empty .ei svg { width:22px; height:22px } .empty b { color:var(--da-text); font-size:15px } .empty .btn { margin-top:10px }
.sk { display:flex; align-items:center; gap:12px; padding:10px } .sk .a { width:34px; height:34px; border-radius:11px } .sk .l { flex:1 } .sk .a, .sk .l i { background:linear-gradient(90deg, var(--da-subtle) 25%, var(--da-line) 50%, var(--da-subtle) 75%); background-size:200% 100%; animation:da-shimmer 1.4s linear infinite }
.sk .l i { display:block; height:9px; border-radius:5px; margin:5px 0 } .sk .l i:last-child { width:65% }
.help h3 { margin:20px 4px 8px; font-size:11px; font-weight:650; letter-spacing:.06em; text-transform:uppercase; color:var(--da-muted) } .help h3:first-child { margin-top:4px }
.caplist { list-style:none; display:flex; flex-direction:column; gap:10px; margin:0; padding:10px 12px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-surface); font-size:13px; line-height:1.45 } .caplist li { display:flex; gap:10px } .caplist svg { width:16px; height:16px; flex:none; margin-top:1px; color:var(--da-success) }
.chips { display:flex; flex-wrap:wrap; gap:6px } .chip { min-height:28px; padding:4px 10px; border:1px solid var(--da-line); border-radius:999px; background:var(--da-surface); color:var(--da-text); font-size:13px; text-align:left; cursor:pointer; transition:border-color .15s, color .15s } .chip:hover { border-color:var(--da-ink); color:var(--da-ink) }
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
.vbtn.lang .vl { font-size:12px; font-weight:700; letter-spacing:.04em } .welcome.back h2 { color:var(--da-ink) }
.vbtn { position:relative; flex:none; width:56px; height:56px; display:inline-grid; place-items:center; padding:0; border:0; border-radius:50%; background:rgba(255,255,255,.12); color:#fff; cursor:pointer; transition:background .2s, color .2s, transform .15s }
.vbtn svg { width:24px; height:24px } .vbtn:hover { background:rgba(255,255,255,.2) } .vbtn:active { transform:scale(.96) } .vbtn.on { background:#fff; color:var(--da-navy) } .vbtn.end { background:#E5484D } .vbtn.end:hover { background:#F05A5F } .vbtn.cc.off { color:rgba(255,255,255,.5) } .vbtn:focus-visible { outline-color:#fff }
.vbtn .tip { position:absolute; bottom:calc(100% + 8px); left:50%; transform:translateX(-50%); padding:3px 7px; border-radius:6px; background:#fff; color:var(--da-navy); font-size:11px; white-space:nowrap; opacity:0; pointer-events:none; transition:opacity .15s } .vbtn:hover .tip, .vbtn:focus-visible .tip { opacity:1 }
.voice .hbtn { margin-left:4px }
.voice.closing .vorb { animation:da-collapse .35s ease-in forwards } @keyframes da-collapse { to { transform:scale(.15); opacity:0 } }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration:.001ms !important; animation-iteration-count:1 !important; animation-delay:0s !important; transition-duration:.001ms !important; transition-delay:0s !important }
  .chk circle, .chk path { stroke-dashoffset:0 }
}
/* ---------------------------------------------------------------- Intercom-style messenger (2026-10-29) */
@media (min-width:521px) {
  :host([mode="launcher"]) .panel { width:min(400px, calc(100vw - 40px)); height:min(704px, calc(100vh - 104px)); height:min(704px, calc(100dvh - 104px)); bottom:calc(max(20px, env(safe-area-inset-bottom)) + 64px);
    box-shadow:0 5px 40px rgba(9,14,21,.16); transition:opacity .2s var(--da-ease), transform .26s var(--da-ease), width .25s var(--da-ease), visibility 0s linear .26s }
  :host([mode="launcher"][open]) .panel { transition:opacity .2s var(--da-ease), transform .26s var(--da-ease), width .25s var(--da-ease), visibility 0s }
  :host([mode="launcher"]) .panel.wide { width:min(680px, calc(100vw - 40px)) }
}
.panel { background:var(--da-bg) }
.launcher { width:48px; height:48px; background:var(--da-primary); box-shadow:0 1px 6px rgba(0,0,0,.06), 0 2px 32px rgba(0,0,0,.16) } .launcher svg { width:24px; height:24px }
.launcher:hover { transform:scale(1.06); box-shadow:0 1px 6px rgba(0,0,0,.06), 0 2px 32px rgba(0,0,0,.2) }
/* header: white, title + subtitle (chat), centred title (tabs), back + title (help pages); hidden on Home */
header { min-height:64px; padding:12px 12px 12px 12px; background:var(--da-head); color:var(--da-head-text); border-bottom:1px solid #EDEDED; gap:8px }
:host([theme="dark"]) header { border-bottom-color:var(--da-line) }
.panel[data-view="home"] header { display:none }
.hav { width:32px; height:32px; border-radius:8px; box-shadow:none } .hav svg { width:18px; height:18px }
.brand h1 { font-size:14px; font-weight:600; color:var(--da-head-text) } .brand p { font-size:12.5px; color:var(--da-head-muted) }
.vtitle { text-align:center; font-size:18px; font-weight:600; color:var(--da-head-text) }
.hbtn { width:36px; height:36px; border-radius:10px; color:var(--da-head-muted) } .hbtn svg { width:18px; height:18px }
.hbtn:hover { background:var(--da-subtle); color:var(--da-head-text) } .hbtn:focus-visible { outline-color:var(--da-primary) } .hbtn[aria-expanded="true"] { background:var(--da-subtle); color:var(--da-head-text) }
.hbadge { box-shadow:0 0 0 2px var(--da-head) }
.vpill { border-color:var(--da-line); background:var(--da-subtle); color:var(--da-head-text) }
header .hspacer { flex:1 } header .hspacer.l { flex:none; width:36px }
/* conversation */
.log { padding:16px 16px 12px; gap:12px }
.bav { display:none } .col { max-width:88% } .row.user .col { max-width:80% } .row.wide .col { max-width:100% }
.msg { padding:12px 16px; border-radius:20px; font-size:14px; line-height:1.5 }
.bot .msg { background:var(--da-bot); border:0; box-shadow:none; border-top-left-radius:20px }
.bot .msg.hascard { background:var(--da-bot) }
.user .msg { background:var(--da-user); color:var(--da-user-text); border-top-right-radius:20px }
.user .msg a:not(.btn) { color:#fff }
.meta { margin:6px 16px 0; font-size:12px; color:var(--da-muted) } .row.user .meta { margin-right:4px }
.row.agent .msg { box-shadow:none; background:var(--da-lavender) }
/* composer: text on top, tools below, round send */
.composer { padding:8px 16px 0; background:var(--da-bg) }
.cbox { padding:12px 12px 8px 16px; border:1px solid #E5E5E5; border-radius:16px; box-shadow:none }
:host([theme="dark"]) .cbox { border-color:var(--da-line) }
.cbox.focus { border-color:var(--da-primary); box-shadow:0 0 0 1px var(--da-primary) }
textarea.q { width:100%; padding:0; min-height:24px; font-size:15px; line-height:24px }
.crow { align-items:center; gap:2px; margin-top:6px } .cfill { flex:1 }
.crow .cicon { width:30px; height:30px; border-radius:8px } .crow .cicon svg { width:18px; height:18px }
.send { width:32px; height:32px; border-radius:50% } .send:disabled { background:var(--da-subtle); color:#A0A4AB }
.foot { padding:8px 16px calc(10px + env(safe-area-inset-bottom)); font-size:12px }
/* bottom tab bar */
.tabbar { flex:none; display:flex; background:var(--da-surface); box-shadow:0 0 25px rgba(9,14,21,.06); position:relative; z-index:5 }
.tabbar[hidden] { display:none }
.tab { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:4px; height:72px; padding:12px 3px 10px; border:0; background:transparent; color:#6C6F74; font-size:14px; font-weight:400; cursor:pointer }
.tab .ti { position:relative; display:grid; place-items:center; width:26px; height:26px } .tab svg { width:24px; height:24px }
.tab.on { color:var(--da-primary); font-weight:600 } .tab:hover { color:var(--da-text) } .tab.on:hover { color:var(--da-primary) }
.tbadge { position:absolute; top:-4px; right:-8px; min-width:16px; height:16px; padding:0 4px; border-radius:9px; background:#DF2020; color:#fff; font:700 11px/16px system-ui, sans-serif; text-align:center }
/* Home */
.view-home { overflow:hidden } .homev { flex:1; min-height:0; overflow-y:auto; overflow-x:hidden; position:relative; background:var(--da-bg) }
.hero { position:relative; padding:24px 24px 120px; color:#FAFAFA;
  background:linear-gradient(180deg, var(--da-hero) 0%, var(--da-hero) 58%, rgba(11,19,40,0) 100%), radial-gradient(120% 70% at 85% 0%, rgba(85,70,247,.55) 0%, rgba(85,70,247,0) 60%), var(--da-hero) }
.hero::after { content:""; position:absolute; left:0; right:0; bottom:0; height:140px; background:linear-gradient(180deg, rgba(255,255,255,0) 0%, var(--da-bg) 100%) }
.htopbar { display:flex; align-items:center; gap:10px; height:40px; margin:8px 0 0 16px }
.hlogo { width:32px; height:32px; border-radius:8px; display:grid; place-items:center; background:var(--da-grad); color:#fff } .hlogo svg { width:18px; height:18px }
.havs { flex:1; display:flex; justify-content:flex-end } .havs img { width:40px; height:40px; border-radius:50%; object-fit:cover; border:2px solid var(--da-hero); margin-left:-8px; background:#2A3152 }
.hclose { width:36px; height:36px; display:grid; place-items:center; border:0; border-radius:10px; background:transparent; color:#FAFAFA; cursor:pointer } .hclose:hover { background:rgba(255,255,255,.12) } .hclose svg { width:16px; height:16px }
.hi { position:relative; z-index:1; margin:48px 0 0 16px; font-size:28px; line-height:34px; font-weight:600; letter-spacing:-.01em; color:#FAFAFA }
.hi span { display:block } .hi .hi2 { color:rgba(250,250,250,.86) }
.hcards { position:relative; z-index:2; display:flex; flex-direction:column; gap:10px; margin:-96px 20px 20px }
.hcard { display:flex; align-items:center; gap:12px; width:100%; padding:16px; border:0; border-radius:12px; background:var(--da-surface); color:var(--da-text); text-align:left; box-shadow:var(--da-card-shadow); cursor:pointer; font-size:14px }
.hcard:hover { box-shadow:0 4px 28px rgba(9,14,21,.1), 0 1px 4px rgba(9,14,21,.08) }
.hcard .ht { flex:1; min-width:0 } .hcard b { display:block; font-size:14px; font-weight:600; line-height:20px } .hcard small { display:block; font-size:14px; line-height:20px; color:var(--da-muted) }
.hcard > svg { flex:none; width:18px; height:18px; color:var(--da-primary) } .hcard .hci { flex:none; width:36px; height:36px; border-radius:10px; display:grid; place-items:center; background:var(--da-lavender); color:var(--da-primary) } .hcard .hci svg { width:18px; height:18px }
.hcard.recent { flex-direction:column; align-items:stretch; gap:10px } .hcard.recent .rl { font-size:14px; font-weight:600 }
.hcard.recent .rr { display:flex; align-items:center; gap:12px } .hcard.recent .ra { flex:none; width:32px; height:32px; border-radius:50%; overflow:hidden; display:grid; place-items:center; background:var(--da-grad); color:#fff } .hcard.recent .ra img { width:100%; height:100%; object-fit:cover } .hcard.recent .ra svg { width:16px; height:16px }
.hcard.recent .rp { flex:1; min-width:0 } .hcard.recent .rp span { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis } .hcard.recent .rp small { font-size:13px } .hcard.recent .rr > svg { flex:none; width:16px; height:16px; color:var(--da-primary) }
.hcard.searchc { display:block; padding:8px; cursor:default } .hcard.searchc:hover { box-shadow:var(--da-card-shadow) }
.hsearch { display:flex; align-items:center; justify-content:space-between; width:100%; padding:10px 12px; border:0; border-radius:8px; background:#F5F5F5; color:var(--da-text); font-size:14px; font-weight:600; cursor:pointer }
:host([theme="dark"]) .hsearch { background:var(--da-subtle) } .hsearch svg { width:16px; height:16px; color:var(--da-primary) }
.alist { display:flex; flex-direction:column } .arow { display:flex; align-items:center; gap:12px; width:100%; padding:8px 12px; border:0; border-radius:8px; background:transparent; color:var(--da-text); font-size:14px; line-height:21px; text-align:left; cursor:pointer }
.arow:hover { background:var(--da-subtle) } .arow span { flex:1; min-width:0 } .arow svg { flex:none; width:16px; height:16px; color:var(--da-primary) }
/* Messages */
.view-messages .hist { padding:8px 8px 96px } .newconvo.askq { position:absolute; left:50%; bottom:16px; transform:translateX(-50%); z-index:3; width:auto; min-height:40px; padding:0 18px; border-radius:20px; box-shadow:0 4px 14px rgba(85,70,247,.35) }
.convo { padding:12px; border-radius:12px } .avatar { width:40px; height:40px; border-radius:50%; overflow:hidden } .avatar img { width:100%; height:100%; object-fit:cover }
/* News (Intercom's News tab) */
.view-news { overflow:hidden } .newsv { flex:1; min-height:0; overflow-y:auto; padding:0 16px 20px }
.nhead { display:flex; align-items:center; justify-content:space-between; padding:20px 4px 12px } .nhead b { display:block; font-size:16px; font-weight:600 } .nhead small { display:block; font-size:14px; color:var(--da-muted) }
.nhead .havs img { border-color:var(--da-surface) }
.ncard, .hcard.newsc { position:relative; display:flex; flex-direction:column; width:100%; margin:0 0 12px; padding:0; border:0; border-radius:12px; overflow:hidden; background:var(--da-surface); color:var(--da-text); text-decoration:none; text-align:left; box-shadow:var(--da-card-shadow); cursor:pointer }
.hcard.newsc { margin:0; align-items:stretch; gap:0 }
.ncard:hover { box-shadow:0 4px 28px rgba(9,14,21,.1), 0 1px 4px rgba(9,14,21,.08) }
.nimg { display:block; aspect-ratio:16/8; background:var(--da-subtle); overflow:hidden } .nimg img { width:100%; height:100%; object-fit:cover; display:block }
.nbody { display:flex; flex-direction:column; gap:6px; padding:14px 40px 16px 16px } .nbody b { font-size:14.5px; font-weight:600; line-height:1.4 }
.nblurb { font-size:14px; line-height:1.45; color:var(--da-muted); display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden }
.nlabels { display:flex; align-items:center; gap:6px; flex-wrap:wrap } .nchip { padding:2px 9px; border-radius:999px; background:var(--da-lavender); color:var(--da-primary); font-size:12px; font-weight:600 }
.nchip.new { background:var(--da-primary); color:#fff } .nchip.upd { background:transparent; box-shadow:inset 0 0 0 1px var(--da-line); color:var(--da-muted) } .nwhen { font-size:12px; color:var(--da-muted) }
.ncard > svg { position:absolute; right:14px; bottom:18px; width:16px; height:16px; color:var(--da-primary) }
.ndot { position:absolute; top:-1px; right:-2px; width:9px; height:9px; border-radius:50%; background:#DF2020; box-shadow:0 0 0 2px var(--da-surface) }
/* News like Intercom / Snitcher: feeds, labels, the item read inside the messenger, reactions, the launcher pop-up */
.nfeeds { display:flex; gap:8px; overflow-x:auto; padding:0 2px 14px; scrollbar-width:none } .nfeeds::-webkit-scrollbar { display:none }
.nfeed { flex:none; padding:6px 12px; border:1px solid var(--da-line); border-radius:999px; background:var(--da-surface); color:var(--da-text); font:inherit; font-size:13px; font-weight:600; cursor:pointer }
.nfeed:hover { background:var(--da-subtle) } .nfeed.on { background:var(--da-ink); border-color:var(--da-ink); color:#fff }
:host([theme="dark"]) .nfeed.on { background:#fff; border-color:#fff; color:#111 }
.nchip.more { background:var(--da-subtle); color:var(--da-muted) }
.ncaught { display:flex; align-items:center; justify-content:center; gap:6px; padding:8px 0 4px; color:var(--da-muted); font-size:13px } .ncaught svg { width:14px; height:14px }
.ndot { min-width:16px; width:auto; height:16px; padding:0 4px; top:-6px; right:-9px; color:#fff; font-size:10px; font-weight:700; line-height:16px; text-align:center }
.nart { margin:0 -16px; padding:0 0 8px } .nart .nimg { aspect-ratio:16/8.4 } .nvideo { position:relative; aspect-ratio:16/9; background:#000 } .nvideo iframe { position:absolute; inset:0; width:100%; height:100%; border:0 }
.ninner { display:flex; flex-direction:column; gap:12px; padding:20px 20px 8px }
.ntitle { margin:0; font-size:20px; font-weight:700; line-height:1.3; letter-spacing:-.01em; color:var(--da-text) }
.nby { display:flex; align-items:center; gap:8px; font-size:13px; color:var(--da-muted) } .nby b { color:var(--da-text); font-weight:600 }
.nby .nav { display:inline-flex; align-items:center; justify-content:center; width:24px; height:24px; border-radius:50%; overflow:hidden; background:var(--da-lavender); color:var(--da-primary); font-size:12px; font-weight:700 } .nby .nav img { width:100%; height:100%; object-fit:cover }
.nhtml { font-size:15px; line-height:1.6; color:var(--da-text); overflow-wrap:anywhere } .nhtml > :first-child { margin-top:0 }
.nhtml p, .nhtml ul, .nhtml ol, .nhtml blockquote, .nhtml figure { margin:0 0 12px } .nhtml ul, .nhtml ol { padding-left:22px } .nhtml li { margin:4px 0 }
.nhtml h2 { margin:20px 0 8px; font-size:17px } .nhtml h3 { margin:18px 0 6px; font-size:16px } .nhtml h4 { margin:16px 0 6px; font-size:15px }
.nhtml img { display:block; max-width:100%; height:auto; border-radius:8px } .nhtml a { color:var(--da-primary) } .nhtml blockquote { padding-left:12px; border-left:3px solid var(--da-line); color:var(--da-muted) }
.nhtml figcaption { font-size:12px; color:var(--da-muted) } .nhtml hr { border:0; border-top:1px solid var(--da-line); margin:16px 0 }
.ncta { display:inline-flex; align-self:flex-start; align-items:center; gap:6px; padding:9px 14px; border-radius:8px; background:var(--da-primary); color:#fff; font-size:14px; font-weight:600; text-decoration:none }
.ncta:hover { filter:brightness(.95) } .ncta svg { width:14px; height:14px }
.nreact { margin:16px 20px 4px; padding:16px; border-radius:12px; background:var(--da-subtle); text-align:center } .nreact p { margin:0 0 10px; font-size:14px; font-weight:600; color:var(--da-text) }
.nemo { display:flex; justify-content:center; gap:10px } .nemoji { width:44px; height:44px; border:0; border-radius:50%; background:transparent; font-size:24px; line-height:1; cursor:pointer; transition:transform .15s var(--da-ease), background .15s }
.nemoji:hover { transform:scale(1.15) } .nemoji.on { background:var(--da-surface); box-shadow:0 0 0 2px var(--da-primary); transform:scale(1.1) }
.npop { display:none; position:fixed; z-index:2147483000; right:max(20px, env(safe-area-inset-right)); bottom:calc(max(20px, env(safe-area-inset-bottom)) + 64px); width:min(320px, calc(100vw - 40px)); border-radius:14px; background:var(--da-surface); box-shadow:0 8px 40px rgba(9,14,21,.18), 0 1px 4px rgba(9,14,21,.08); font-family:var(--da-font) }
:host([mode="launcher"]:not([open])) .npop:not([hidden]) { display:block; animation:da-pop .3s var(--da-ease) }
.npb { display:flex; flex-direction:column; width:100%; padding:0; border:0; border-radius:14px; overflow:hidden; background:transparent; color:var(--da-text); text-align:left; cursor:pointer; font:inherit }
.npi { display:block; aspect-ratio:16/7; overflow:hidden; background:var(--da-subtle) } .npi img { width:100%; height:100%; object-fit:cover; display:block }
.npt { display:flex; flex-direction:column; gap:4px; padding:12px 14px 14px } .npt small { font-size:12px; color:var(--da-muted) } .npt b { font-size:14px; font-weight:600; line-height:1.35 }
.npx { position:absolute; top:6px; right:6px; z-index:1; width:26px; height:26px; border:0; border-radius:50%; background:rgba(0,0,0,.45); color:#fff; font-size:16px; line-height:26px; cursor:pointer }
@keyframes da-pop { from { opacity:0; transform:translateY(8px) } to { opacity:1; transform:none } }
@media (prefers-reduced-motion: reduce) { :host([mode="launcher"]:not([open])) .npop:not([hidden]) { animation:none } .nemoji { transition:none } }
/* quick view: featured story, rows of small cards per feed, compact lists */
.nfeat { margin-bottom:18px } .nfeat .nimg { aspect-ratio:16/7 } .nfeat .nblurb { -webkit-line-clamp:1 } .nfeat .nbody { gap:5px; padding:12px 40px 13px 14px }
.nmi.none, .nth.none { background:linear-gradient(135deg, var(--da-lavender), var(--da-subtle)) } .nmi, .nth { position:relative } .nmi img, .nth img { position:absolute; inset:0 } .nmi:not(.none) em, .nth:not(.none) em { display:none } .nmi em, .nth em { font-style:normal; font-size:12px; font-weight:700; color:var(--da-primary); letter-spacing:.02em; padding:0 6px; text-align:center }
.nsec { margin:0 0 18px } .nsech { display:flex; align-items:center; justify-content:space-between; margin:0 2px 8px } .nsech b { font-size:14px; font-weight:700; color:var(--da-text) }
.nsee { display:inline-flex; align-items:center; gap:2px; padding:4px 6px; border:0; border-radius:6px; background:transparent; color:var(--da-primary); font:inherit; font-size:13px; font-weight:600; cursor:pointer }
.nsee:hover { background:var(--da-subtle) } .nsee svg { width:14px; height:14px }
.nrail { display:flex; gap:10px; overflow-x:auto; scroll-snap-type:x mandatory; scroll-padding:0 16px; margin:0 -16px; padding:2px 16px 8px; scrollbar-width:none } .nrail::-webkit-scrollbar { display:none }
.ncard.nmini { flex:none; width:158px; margin:0; scroll-snap-align:start; box-shadow:0 1px 3px rgba(9,14,21,.1), 0 0 0 1px rgba(9,14,21,.04) }
.nmi { display:flex; align-items:center; justify-content:center; aspect-ratio:16/9; overflow:hidden; background:var(--da-subtle); color:var(--da-muted) } .nmi img { width:100%; height:100%; object-fit:cover; display:block } .nmi svg, .nth svg { width:22px; height:22px; opacity:.6 }
.nmb { display:flex; flex-direction:column; gap:6px; padding:9px 10px 11px } .nmb b { font-size:13px; font-weight:600; line-height:1.35; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden }
.nmeta { display:flex; align-items:center; gap:6px; min-width:0 } .nmeta .nchip { padding:1px 7px; font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:110px } .nmeta .nwhen { font-size:11.5px; white-space:nowrap }
.nnew { flex:none; width:8px; height:8px; border-radius:50%; background:var(--da-primary) }
.nlist { display:flex; flex-direction:column; border-radius:12px; overflow:hidden; background:var(--da-surface); box-shadow:var(--da-card-shadow) }
.ncard.nrow { flex-direction:row; align-items:center; gap:12px; margin:0; padding:10px 12px; border-radius:0; box-shadow:none; border-bottom:1px solid var(--da-line) }
.ncard.nrow:last-child { border-bottom:0 } .ncard.nrow:hover { box-shadow:none; background:var(--da-subtle) }
.nth { flex:none; display:flex; align-items:center; justify-content:center; width:72px; height:52px; border-radius:8px; overflow:hidden; background:var(--da-subtle); color:var(--da-muted) } .nth img { width:100%; height:100%; object-fit:cover; display:block }
.nrb { flex:1; min-width:0; display:flex; flex-direction:column; gap:4px } .nrb b { font-size:13.5px; font-weight:600; line-height:1.35; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden }
/* Opening animation (launcher tap, ~2 s), in the chatbot's colours (indigo, its lighter and deeper shades, the navy
   header): colour wash 0–350 ms, the dot diamond forms 350–650, hold to 1100, the colour
   is lifted off the top 1100–1600 while white rises, then the chat's greeting and disclaimer arrive 1800–2100.
   Ease-out for what arrives, ease-in for what leaves. Off with intro="off" or prefers-reduced-motion. */
.intro { position:absolute; inset:0; z-index:60; display:none; overflow:hidden; border-radius:inherit; pointer-events:none;
  --ig-light:#7466FF; --ig-light:color-mix(in srgb, var(--da-primary) 72%, #fff); --ig-deep:#3E31D4; --ig-deep:color-mix(in srgb, var(--da-primary) 78%, #000);
  --ig-base:#F6F5FF; --ig-base:color-mix(in srgb, var(--da-primary) 6%, var(--da-bg)); --ig-end:var(--da-bg) }
.panel.intro-run .intro { display:block }
.panel.intro-run { background:transparent; box-shadow:none }
.panel.intro-run > :not(.intro) { visibility:hidden }
.panel.intro-out > :not(.intro) { visibility:visible } .panel.intro-run.intro-out { background:var(--da-bg) } .panel.intro-run .welcome, .panel.intro-run .foot, .panel.intro-run .hi, .panel.intro-run .hcards > *, .panel.intro-run .htopbar { animation:none; opacity:0 }
.panel.intro-out .intro { opacity:0; transition:opacity .2s cubic-bezier(.4,0,1,1) }
.ig-glass { position:absolute; inset:0; background:rgba(255,255,255,.22); -webkit-backdrop-filter:blur(16px) saturate(1.15); backdrop-filter:blur(16px) saturate(1.15); opacity:0; animation:ig-in .35s cubic-bezier(.2,.7,.2,1) forwards }
.ig-stage { position:absolute; inset:0; animation:ig-lift .5s cubic-bezier(.55,0,.8,.25) 1.1s forwards }
.ig-solid { position:absolute; inset:0; background:var(--ig-base); opacity:0; animation:ig-in .3s cubic-bezier(.2,.7,.2,1) .35s forwards }
.ig-blob { position:absolute; width:78%; aspect-ratio:1; border-radius:50%; filter:blur(56px); opacity:0; animation:ig-blob .35s cubic-bezier(.2,.7,.2,1) forwards, ig-drift 3.4s ease-in-out infinite alternate }
.ig-coral { left:-26%; top:4%; background:var(--ig-light) }
.ig-navy { left:10%; top:-46%; width:80%; background:var(--da-hero); filter:blur(64px); animation-delay:0s, -.9s }
.ig-violet { right:-26%; top:-4%; background:var(--ig-deep); animation-delay:0s, -1.7s }
.ig-melt { position:absolute; left:0; right:0; bottom:0; height:58%; background:linear-gradient(to bottom, transparent, color-mix(in srgb, var(--ig-end) 92%, transparent) 72%, var(--ig-end)) }
.ig-dots { position:absolute; inset:0; background-image:radial-gradient(rgba(255,255,255,.75) .9px, transparent 1.3px); background-size:15px 15px; opacity:0; animation:ig-dots .35s ease-out forwards }
.ig-logo { position:absolute; left:50%; top:44%; width:0; height:0; animation:ig-glow 1.1s ease-in-out .65s infinite alternate }
.ig-logo i { position:absolute; width:8px; height:8px; margin:-4px 0 0 -4px; border-radius:50%; background:#fff; opacity:0; transform:scale(.35); box-shadow:0 0 8px rgba(255,255,255,.75); animation:ig-dot .22s cubic-bezier(.2,.7,.2,1) forwards }
.ig-rise { position:absolute; inset:-140px 0 0; background:linear-gradient(to bottom, transparent, var(--ig-end) 140px); transform:translateY(100%); animation:ig-rise .5s cubic-bezier(.6,0,.4,1) 1.1s forwards }
@keyframes ig-in { to { opacity:1 } }
@keyframes ig-blob { to { opacity:.8 } }
.intro.to-home .ig-rise { background:linear-gradient(to bottom, transparent 0, var(--da-hero) 140px, var(--da-hero) calc(140px + 24%), var(--ig-end) calc(140px + 46%)),
  radial-gradient(120% 40% at 85% 140px, color-mix(in srgb, var(--da-primary) 55%, transparent), transparent 60%) }
@keyframes ig-dots { to { opacity:.5 } }
@keyframes ig-dot { to { opacity:1; transform:scale(1) } }
@keyframes ig-drift { from { transform:translate(0, 0) scale(1) } to { transform:translate(7%, 5%) scale(1.08) } }
@keyframes ig-glow { from { filter:drop-shadow(0 0 1px rgba(255,255,255,.4)) } to { filter:drop-shadow(0 0 10px rgba(255,255,255,.95)) } }
@keyframes ig-lift { to { transform:translateY(-24%); opacity:0 } }
@keyframes ig-rise { to { transform:none } }
@keyframes ig-up { from { opacity:0; transform:translateY(8px) } to { opacity:1; transform:none } }
.panel.intro-greet .welcome { animation:none }
.panel.intro-greet .welcome > * { animation:ig-up .3s cubic-bezier(.2,.7,.2,1) both }
.panel.intro-greet .welcome > p { animation-delay:.06s }
.panel.intro-greet .welcome > :not(h2):not(p) { animation-delay:.14s }
.panel.intro-greet .foot { animation:ig-up .35s cubic-bezier(.2,.7,.2,1) .1s both }
.panel.intro-greet .htopbar { animation:ig-fade-in .3s cubic-bezier(.2,.7,.2,1) both }
.panel.intro-greet .hi1 { display:block; animation:ig-up .32s cubic-bezier(.2,.7,.2,1) both }
.panel.intro-greet .hi2 { display:block; animation:ig-up .32s cubic-bezier(.2,.7,.2,1) .07s both }
.panel.intro-greet .hcards > * { animation:ig-up .34s cubic-bezier(.2,.7,.2,1) both }
.panel.intro-greet .hcards > :nth-child(1) { animation-delay:.12s } .panel.intro-greet .hcards > :nth-child(2) { animation-delay:.16s }
.panel.intro-greet .hcards > :nth-child(3) { animation-delay:.2s } .panel.intro-greet .hcards > :nth-child(4) { animation-delay:.24s }
.panel.intro-greet .hcards > :nth-child(5) { animation-delay:.28s }
@keyframes ig-fade-in { from { opacity:0 } to { opacity:1 } }
.foot .aidisc { white-space:nowrap }
@media (prefers-reduced-motion: reduce) { .panel.intro-run .intro { display:none } .panel.intro-run > :not(.intro) { visibility:visible } }
/* The conversation sits on a fine dot grid; it softens near the header and the composer so they stay clean.
   The grid stays put while messages scroll over it. --da-dot sets its colour (transparent turns it off). */
.view-chat .log { background-color:var(--da-bg);
  background-image:linear-gradient(to bottom, var(--da-bg) 0, transparent 48px, transparent calc(100% - 40px), var(--da-bg) 100%),
    radial-gradient(circle at 1px 1px, var(--da-dot) 1px, transparent 1.5px);
  background-size:100% 100%, 18px 18px; background-repeat:no-repeat, repeat; background-position:0 0, 8px 6px }
/* Design polish: bot replies as white cards that float on the dot grid, the visitor's messages in the brand
   gradient, a soft pill behind the active tab, a gentle focus glow on the composer, small lifts on hover. */
.view-chat .row.bot:not(.agent) .msg { background:var(--da-surface); border:1px solid var(--da-line); box-shadow:0 1px 2px rgba(21,27,50,.04), 0 8px 22px -12px rgba(21,27,50,.16) }
:host([theme="dark"]) .view-chat .row.bot:not(.agent) .msg { background:var(--da-bot); box-shadow:0 8px 22px -12px rgba(0,0,0,.5) }
.view-chat .row.user .msg { background:var(--da-grad); box-shadow:0 8px 20px -10px rgba(85,70,247,.55) }
.tab .ti { isolation:isolate }
.tab .ti::before { content:""; position:absolute; z-index:-1; inset:-4px -14px; border-radius:999px; background:var(--da-lavender); opacity:0; transform:scale(.6); transition:opacity .2s var(--da-ease), transform .3s var(--da-ease) }
.tab.on .ti::before { opacity:1; transform:none }
.tab { transition:color .15s }
.cbox:focus-within { border-color:#B9B2FB; border-color:color-mix(in srgb, var(--da-primary) 45%, var(--da-line)); box-shadow:0 0 0 4px rgba(85,70,247,.1); box-shadow:0 0 0 4px color-mix(in srgb, var(--da-primary) 12%, transparent) }
.view-messages .newconvo.askq { background:var(--da-grad) }
@media (hover:hover) {
  .hcard:not(.searchc) { transition:transform .18s var(--da-ease), box-shadow .18s var(--da-ease) }
  .hcard:not(.searchc):hover { transform:translateY(-1px); box-shadow:0 12px 30px -14px rgba(21,27,50,.28) }
  .convo { transition:background .15s } .convo:hover { background:var(--da-subtle) }
}
@media (prefers-reduced-motion: reduce) { .tab .ti::before, .hcard:not(.searchc) { transition:none } .hcard:not(.searchc):hover { transform:none } }
/* News, advanced: search, key takeaways, the actions under an article, more like this */
.nsearch { display:flex; align-items:center; gap:8px; margin:0 0 12px; padding:0 10px 0 12px; height:40px; border:1px solid var(--da-line); border-radius:10px; background:var(--da-surface); transition:border-color .15s, box-shadow .15s }
.nsearch:focus-within { border-color:color-mix(in srgb, var(--da-primary) 45%, var(--da-line)); box-shadow:0 0 0 4px color-mix(in srgb, var(--da-primary) 12%, transparent) }
.nsearch > svg { width:16px; height:16px; flex:none; color:var(--da-muted) } .nsearch input { flex:1; min-width:0; border:0; outline:0; background:transparent; color:var(--da-text); font:inherit; font-size:14px }
.nsearch input::-webkit-search-cancel-button { display:none } .nsx { display:grid; place-items:center; width:24px; height:24px; padding:0; border:0; border-radius:50%; background:var(--da-subtle); color:var(--da-muted); cursor:pointer } .nsx svg { width:12px; height:12px }
.nsres { margin:0 2px 10px; font-size:13px; color:var(--da-muted) } .nsres b { color:var(--da-text) }
.ntake { padding:14px 16px; border-radius:12px; background:linear-gradient(135deg, color-mix(in srgb, var(--da-primary) 9%, var(--da-surface)), var(--da-surface)); border:1px solid color-mix(in srgb, var(--da-primary) 22%, var(--da-line)) }
.ntake > b { display:flex; align-items:center; gap:7px; font-size:13px; font-weight:700; letter-spacing:.02em; color:var(--da-primary) } .ntake > b svg { width:15px; height:15px }
.ntake ul { margin:10px 0 6px; padding-left:18px; font-size:14px; line-height:1.55; color:var(--da-text) } .ntake li { margin:5px 0 } .ntake li::marker { color:var(--da-primary) }
.ntake small { font-size:11.5px; color:var(--da-muted) } .ntake .sk { display:block; margin-top:10px } .ntake .sk i { height:9px; margin:7px 0 }
.nnote { color:var(--da-muted) }
.nacts { display:flex; flex-wrap:wrap; align-items:center; gap:8px } .nacts .ncta { align-self:auto }
.nask, .nshare { display:inline-flex; align-items:center; gap:6px; padding:8px 12px; border:1px solid var(--da-line); border-radius:8px; background:var(--da-surface); color:var(--da-text); font:inherit; font-size:13.5px; font-weight:600; cursor:pointer; transition:background .15s, border-color .15s }
.nask:hover, .nshare:hover { background:var(--da-subtle) } .nask svg, .nshare svg { width:15px; height:15px; color:var(--da-primary) }
.nrel { margin:18px 20px 6px } .nrel > b { display:block; margin:0 2px 8px; font-size:14px; font-weight:700; color:var(--da-text) }
/* Help center */
.hsearchbar { flex:none; padding:0 12px 12px; background:var(--da-head); border-bottom:1px solid #EDEDED } :host([theme="dark"]) .hsearchbar { border-bottom-color:var(--da-line) }
.hsearchbar[hidden] { display:none } .hsearchbar .searchbox svg { left:auto; right:12px; color:var(--da-primary) }
.hq { width:100%; height:42px; padding:0 40px 0 12px; border:0; border-radius:10px; background:#F5F5F5; color:var(--da-text); font-size:14px } :host([theme="dark"]) .hq { background:var(--da-subtle) } .hq:focus { box-shadow:0 0 0 2px var(--da-primary) }
.help { padding:0 0 24px } .help .hc-h { margin:0; padding:16px 20px 12px; font-size:16px; font-weight:600; letter-spacing:0; text-transform:none; color:var(--da-text); border-bottom:1px solid #EDEDED } :host([theme="dark"]) .help .hc-h { border-bottom-color:var(--da-line) }
.crowl { display:flex; align-items:center; gap:12px; width:100%; padding:16px 20px; border:0; border-bottom:1px solid #EDEDED; background:transparent; color:var(--da-text); text-align:left; cursor:pointer }
:host([theme="dark"]) .crowl { border-bottom-color:var(--da-line) } .crowl:hover { background:var(--da-subtle) }
.crowl .ct { flex:1; min-width:0 } .crowl b { display:block; font-size:14px; font-weight:600; line-height:21px } .crowl .cdsc { display:block; font-size:14px; line-height:21px } .crowl small { display:block; font-size:14px; line-height:21px; color:var(--da-muted) }
.crowl > svg { flex:none; width:16px; height:16px; color:var(--da-primary) }
.cinfo { padding:16px 20px; border-bottom:1px solid #EDEDED } :host([theme="dark"]) .cinfo { border-bottom-color:var(--da-line) } .cinfo b { display:block; font-size:16px; font-weight:600 } .cinfo p { margin:4px 0 0; font-size:14px } .cinfo small { display:block; margin-top:8px; font-size:13px; color:var(--da-muted) }
.article { padding:24px 32px 32px; font-size:15px; line-height:1.6 } .article h1 { margin:0; font-size:24px; line-height:1.3; font-weight:700; letter-spacing:-.01em } .article .asum { margin:8px 0 0; color:var(--da-muted) }
.article .aby { display:flex; align-items:center; gap:10px; margin:16px 0 20px; font-size:13px; color:var(--da-muted) } .article .aby .ra { width:32px; height:32px; border-radius:50%; overflow:hidden; background:var(--da-grad); display:grid; place-items:center; color:#fff } .article .aby img { width:100%; height:100%; object-fit:cover }
.abody p { margin:0 0 14px } .abody h2 { margin:22px 0 8px; font-size:17px; font-weight:650 } .abody ul { margin:0 0 14px; padding-left:20px } .abody li { margin:4px 0 } .abody a { color:var(--da-primary) } .abody b { font-weight:650 }
.ahelp { margin-top:24px; padding:16px; border-radius:12px; background:var(--da-subtle); display:flex; align-items:center; gap:12px; font-size:14px } .ahelp span { flex:1 }
.arel { margin-top:24px } .arel h3 { margin:0 0 6px; font-size:13px; font-weight:650; color:var(--da-muted); text-transform:none; letter-spacing:0 }
.hcontact { padding:4px 16px 0 } .hcontact h3 { margin:20px 4px 8px }
.hempty { padding:32px 20px; text-align:center; color:var(--da-muted); font-size:14px }
@media (max-width:520px) { .article { padding:20px } }
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
  home: I('<path d="M4 10.5L12 4l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z"/>'),
  news: I('<path d="M3.5 10.5v3a1 1 0 0 0 1 1h2.2l5.3 4V5.5l-5.3 4H4.5a1 1 0 0 0-1 1z"/><path d="M15.5 9a3.5 3.5 0 0 1 0 6M18 6.5a7 7 0 0 1 0 11"/>'),
  askarrow: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M4.4 3.6l16.1 7.5a1 1 0 0 1 0 1.8L4.4 20.4a.7.7 0 0 1-1-.8L5.2 13l8.3-1-8.3-1L3.4 4.4a.7.7 0 0 1 1-.8z"/></svg>',
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
function articleMd(src) {
  const inline = (t) => esc(t).replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\[([^\]]+)\]\(((?:https?:\/\/|#dh-help=)[^\s)]+)\)/g, (m, label, url) => `<a href="${url}"${url.startsWith('#') ? '' : ' target="_blank" rel="noopener"'}>${label}</a>`);
  const out = []; let list = null;
  String(src || '').split(/\n/).forEach((line) => {
    const l = line.trim();
    if (/^[-*]\s+/.test(l)) { if (!list) { list = []; } list.push(`<li>${inline(l.replace(/^[-*]\s+/, ''))}</li>`); return; }
    if (list) { out.push(`<ul>${list.join('')}</ul>`); list = null; }
    if (!l) return;
    if (/^#{1,3}\s+/.test(l)) out.push(`<h2>${inline(l.replace(/^#{1,3}\s+/, ''))}</h2>`); else out.push(`<p>${inline(l)}</p>`);
  });
  if (list) out.push(`<ul>${list.join('')}</ul>`);
  return out.join('');
}
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
const relAge = (ts) => { const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000), d = s / 86400; return s < 3600 ? Math.max(1, Math.floor(s / 60)) + 'm' : s < 86400 ? Math.floor(s / 3600) + 'h' : d < 7 ? Math.floor(d) + 'd' : d < 35 ? Math.floor(d / 7) + 'w' : d < 365 ? Math.floor(d / 30.4) + 'mo' : Math.floor(d / 365) + 'y'; };
const relShort = (ts) => { const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000); return s < 60 ? 'just now' : s < 3600 ? Math.floor(s / 60) + 'm' : s < 86400 ? Math.floor(s / 3600) + 'h' : Math.floor(s / 86400) + 'd'; };
const fmtSize = (b) => b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(0) + ' KB' : (b / 1048576).toFixed(1) + ' MB';
const store = { get(k) { try { return sessionStorage.getItem(k); } catch { return null; } }, set(k, v) { try { sessionStorage.setItem(k, v); } catch {} } };
const local = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };
const typeIcon = (s) => { const h = `${s.slug} ${s.name}`.toLowerCase(); return /walkthrough|demo/.test(h) ? SVG.play : /gtm|strategy/.test(h) ? SVG.target : SVG.chat; };
const BK_STEPS = ['type', 'time', 'details', 'review'];
const RS_STEPS = ['time', 'review'];  // rescheduling an existing booking
const RS_TITLES = { time: 'Pick a new time', review: 'Confirm the change' };
const BK_TITLES = { type: 'Choose a meeting', time: 'Pick a time', details: 'Your details', review: 'Review and confirm' };
const RESCHED_RE = /\b(reschedule|re-schedule|move|change|shift|postpone|push)\b/i, CALL_RE = /\b(call|meeting|booking|appointment|slot|time|it)\b/i;
const CANCEL_RE = /\b(cancel|call off|drop|delete|remove)\b/i;

class DeepAssistant extends HTMLElement {
  static get observedAttributes() { return ['api', 'token', 'theme', 'mode', 'open', 'title', 'subtitle', 'suggestions', 'user-name', 'user-email', 'tabs', 'shortcut', 'privacy-url', 'greeting', 'page-context', 'outreach-event']; }
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._history = []; this._transcript = []; this._busy = false; this._controller = null; this._me = null; this._rendered = false; this._wasOpen = false;
    this._view = 'chat'; this._unread = 0; this._attachments = []; this._cfg = { gif: false, stt: 'browser', tts: 'browser', upload_max_mb: 10, upload_types: [] };
    this._voice = null; this._rec = null; this._online = undefined; this._nudged = false; this._lastLang = null;
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
  // Ask Deep from a booking email (docs/EMAILS.md): exchange the link's token, show which booking this chat is about, and
  // send the tapped question only once a person really has the page open (mail scanners open links too)
  async claimEmailLink(token, q) {
    if (!this.api) return;
    if (!token) { const t = q && ASK_SAMPLE[q]; if (t) { this.showView('chat'); this.$q.value = t; this._autosize(); } return; }  // Send test: prefill only
    if (this._transcript.length) this.newChat();
    let res = null, status = 0;
    try {
      const r = await fetch(this._url('/ask/claim'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ token, q: q || undefined, timezone: this.tz, gpc: !!(navigator.globalPrivacyControl || navigator.doNotTrack === '1') }) });
      status = r.status; if (r.ok) res = await r.json();
    } catch {}
    if (!res) { this._toast(status === 410 ? 'This link has expired. You can still ask anything here.' : "That link didn't open. You can still ask anything here."); return; }
    this._email = res; this._emit('email_link', { kind: res.kind, role: res.role, question: res.question && res.question.key });
    try { await this._loadMe(); } catch {}
    this.showView('chat'); this._renderWelcome();
    const x = res.question; if (!x) return;
    if (x.action === 'book') return this.startBooking(null, x.text);
    const up = this._me && this._me.memory && this._me.memory.upcoming;
    if (x.action === 'reschedule') { if (res.role === 'booker' && up && up.can_reschedule) return this.startReschedule(up, x.text); this.$q.value = x.text; this._autosize(); return; }
    if (res.autosend && await this._reallyOpen()) { this._askAuto = true; return this._send(x.text); }
    this.$q.value = x.text; this._autosize();
  }
  _reallyOpen() {  // a person, not a link checker: no automation flag, the page visible, a moment after it loaded
    if (navigator.webdriver) return Promise.resolve(false);
    return new Promise((done) => {
      const go = () => setTimeout(() => done(true), 400);
      if (document.visibilityState === 'visible') return go();
      const give = setTimeout(() => done(false), 600000);
      const f = () => { if (document.visibilityState === 'visible') { clearTimeout(give); document.removeEventListener('visibilitychange', f); go(); } };
      document.addEventListener('visibilitychange', f);
    });
  }
  book(callType) { return this.startBooking(callType || null); }
  open() { this.setAttribute('open', ''); }
  close() { this.removeAttribute('open'); }
  toggle() { this.hasAttribute('open') ? this.close() : this.open(); }
  setToken(token) { if (token) this.setAttribute('token', token); else this.removeAttribute('token'); }
  reset() { this.newChat(); }
  newChat() {
    this._email = null;
    if (this._busy) this._stop(); this.stopVoice();
    this._sid = uuid(); store.set(this._key('sid'), this._sid);
    this.removeAttribute('outreach-event'); this._outreachSent = false;  // a fresh conversation carries no pop-up context
    this._transcript = []; this._history = []; this._attachments = []; this._nudged = false; this._renderAttachments();
    clearTimeout(this._teamT); clearTimeout(this._rateT); this._teamStatus = null; this._rated = false;
    this._restore(); this._track(); this.showView('chat');
    if (this.api) this._loadMe().then(() => this._refreshWelcome());  // return-visitor memory for the new conversation
  }
  download() {
    const lines = this._transcript.map((m) => `[${new Date(m.ts).toLocaleString()}] ${m.role === 'user' ? 'You' : this.botName}: ${plain(m.text)}${m.sources && m.sources.length ? '\n  sources: ' + m.sources.map((s) => s.url).join(', ') : ''}`);
    const blob = new Blob([`${this.botName} transcript · ${new Date().toLocaleString()} · conversation ${this._sid}\n\n` + lines.join('\n\n')], { type: 'text/plain' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `deep-chat-${new Date().toISOString().slice(0, 10)}.txt`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  switchTheme() { const next = this._isDark() ? 'light' : 'dark'; this.setAttribute('theme', next); local.set('da_theme', next); this._syncThemeItem(); }
  // Views like Intercom's messenger: Home / Messages / Help are tabs (bottom bar), the chat and help pages sit on top
  showView(name) {
    if (name === 'history') name = 'messages';
    const tabs = this._tabs();
    if (!['chat', 'messages', 'help', 'home', 'news'].includes(name) || (['help', 'home', 'news'].includes(name) && !tabs.includes(name))) return;
    const sh = this.shadowRoot, changed = name !== this._view;
    if (name !== 'help') this._helpPage = null;
    if (name !== 'news') this._newsPage = null;
    this._view = name; this.$panel.dataset.view = name;
    ['home', 'chat', 'messages', 'help', 'news'].forEach((v) => { sh.querySelector('.view-' + v).hidden = v !== name; });
    this._paintHeader();
    const newsItem = name === 'news' && !!this._newsPage;
    this.$panel.classList.toggle('wide', (name === 'help' && !!this._helpPage && this._helpPage.page === 'article') || newsItem);
    sh.querySelector('.tabbar').hidden = name === 'chat' || (name === 'help' && !!this._helpPage && this._helpPage.page === 'article') || newsItem || tabs.length < 2;
    sh.querySelectorAll('.tab').forEach((t) => { const on = t.dataset.tab === name; t.classList.toggle('on', on); t.setAttribute('aria-current', on ? 'page' : 'false'); });
    this._closePops();
    if (name === 'messages') this._renderConversations();
    if (name === 'help' && !this._helpPage) this._renderHelp();
    if (name === 'home') this._renderHome();
    if (name === 'news' && !this._newsPage) this._renderNews();
    if (name === 'chat') setTimeout(() => { if (!this._voice) this._focusInput(); }, 30); else if (changed && name !== 'home') setTimeout(() => { const t = sh.querySelector(this.$back.hidden ? '.close' : '.back'); if (t && !t.hidden) t.focus({ preventScroll: true }); }, 30);
    this._syncHome(); this._emit('view', { view: name, page: this._helpPage ? this._helpPage.page : undefined });
  }
  _paintHeader() {
    const sh = this.shadowRoot, v = this._view, chat = v === 'chat', sub = (v === 'help' && !!this._helpPage) || (v === 'news' && !!this._newsPage), home = this._tabs().includes('home');
    ['.hav', '.brand', '.more'].forEach((s) => { sh.querySelector(s).hidden = !chat; });
    sh.querySelector('.b-history').hidden = true;
    this.$back.hidden = !(sub || (chat && (home || this._tabs().length > 1)));
    const vt = sh.querySelector('.vtitle'); vt.hidden = chat; vt.textContent = v === 'messages' ? 'Messages' : v === 'news' ? 'News' : 'Help';
    sh.querySelector('.hspacer.l').hidden = chat || sub; sh.querySelector('.hspacer.r').hidden = true;
    sh.querySelector('.hsearchbar').hidden = !(v === 'help' && (!this._helpPage || this._helpPage.page !== 'article'));
    this.$min.hidden = true;
  }
  _goBack() {
    if (this._view === 'news' && this._newsPage) { this._newsPage = null; this.showView('news'); return; }
    if (this._view === 'help' && this._helpPage) { const p = this._helpPage; this._helpPage = p.page === 'article' && p.from ? p.from : null; this.showView('help'); if (this._helpPage) this._paintHelpPage(); return; }
    this.showView(this._tabs().includes('home') ? 'home' : 'messages');
  }
  // back-to-start arrow: only in the chat view once the conversation has messages (it stays in History)
  _syncHome() { if (this.$home) this.$home.hidden = true; }
  async openConversation(sid) {
    if (!sid) return;
    if (sid !== this._sid) {
      if (this._busy) this._stop();
      let h = null;
      try { const r = await fetch(this._url('/conversations/' + encodeURIComponent(sid)), { headers: this._headers(false) }); if (r.ok) h = await r.json(); } catch {}
      if (!h) { this._toast("Couldn't open that conversation"); return; }
      this._sid = sid; store.set(this._key('sid'), sid); this._nudged = false;
      // cards exist only on the device that received them: carry the local copy over by message id
      let old = []; try { old = JSON.parse(store.get(this._key('tx:' + sid)) || '[]'); } catch {} const uiByMid = new Map(old.filter((m) => m.mid && m.ui).map((m) => [m.mid, m.ui]));
      this.$log.innerHTML = ''; this._transcript = []; this._history = [];
      (h.messages || []).forEach((m) => {
        if (m.agent) { this._addAgent(m); return; }
        const el = this._add(m.role === 'user' ? 'user' : 'bot', '', m.ts);
        if (m.role === 'user') { this._setText(el, m.text); this._transcript.push({ role: 'user', text: m.text, ts: new Date(m.ts).getTime() }); }
        else { const srcs = usedSources(m.text, m.sources || []); this._setText(el, m.text, m.sources || []); this._addSources(el, srcs); this._addTools(el, () => plain(m.text), null, m.id, m.feedback);
          const ui = uiByMid.get(m.id); this._transcript.push({ role: 'bot', text: m.text, sources: srcs, ts: new Date(m.ts).getTime(), mid: m.id, fb: m.feedback, ui }); if (ui) this._mountUi(el, ui, this._transcript[this._transcript.length - 1]); }
      });
      if (!this._transcript.length) this._renderWelcome();
      this._history = this._transcript.map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.agent ? `${m.author || 'Deep'} (from the team): ${m.text}` : m.text })).slice(-12);
      this._persist(); this._markLast(); this._teamStatus = h.team_status || null; this._rated = !!h.rating;
    }
    this._teamCheck();
    this.showView('chat'); this._scroll(true); this._markRead(sid).then(() => this._refreshBadge()); setTimeout(() => this._edCheck(), 300);
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
    else if (name === 'api') { this._adoptApi(); this._health(); this._loadConfig(); }
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
  _tabs() { const raw = (this.getAttribute('tabs') || ALL_TABS.join(',')).split(',').map((s) => s.trim().toLowerCase()).filter((s) => ALL_TABS.includes(s) && !(s === 'news' && this._cfg && this._cfg.news && this._cfg.news.enabled === false)); if (!raw.includes('messages')) raw.push('messages'); return ALL_TABS.filter((t) => raw.includes(t)); }
  _shortcut() { const a = this.getAttribute('shortcut'); if (a === '') return null; const [label, href] = (a || DEFAULT_SHORTCUT).split('|'); return href ? { label: label.trim(), href: href.trim() } : null; }
  _isDark() { const t = this.getAttribute('theme'); return t === 'dark' || (t === 'auto' && !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)); }
  _focusInput() { if (this._coarse || this._view !== 'chat') return; try { this.$q.focus({ preventScroll: true }); } catch {} }
  _canListen() { return !!this._speechApi() || (this._cfg.stt === 'server' && !!navigator.mediaDevices && typeof MediaRecorder !== 'undefined'); }
  _render() {
    this._rendered = true; const sh = this.shadowRoot;
    if (!this.hasAttribute('theme')) this.setAttribute('theme', local.get('da_theme') || 'light');
    sh.innerHTML = `<style>${CSS}</style>
<button class="launcher" part="launcher" type="button" aria-label="Open the Deep assistant" aria-expanded="false"><span class="lic lic-open">${SVG.mark}</span><span class="lic lic-close">${SVG.chevdown}</span><span class="ldot" hidden></span><span class="lbadge" hidden></span></button>
<div class="npop" role="status" aria-live="polite" hidden><button class="npx" type="button" aria-label="Dismiss">&times;</button><button class="npb" type="button"></button></div>
<section class="panel" part="panel" data-view="chat" role="dialog" aria-label="Deep assistant">
  <header>
    <button class="hbtn back" type="button" aria-label="Back to chat" title="Back to chat" hidden>${SVG.back}</button>
    <button class="hbtn home" type="button" aria-label="Back to start" title="Back to start" hidden>${SVG.back}</button>
    <span class="hav" aria-hidden="true">${SVG.mark}</span>
    <div class="brand"><h1 class="ttl"></h1><p><span class="sub"></span><span class="sep" aria-hidden="true">·</span><span class="st"><i aria-hidden="true"></i><span class="stt">Connecting…</span></span></p></div>
    <span class="hspacer l" hidden></span>
    <h2 class="vtitle" hidden></h2>
    <span class="hspacer r" hidden></span>
    <button class="vpill" type="button" aria-label="Return to the voice call" title="Return to the call"><i></i><span>In a call</span></button>
    <button class="hbtn b-history" type="button" aria-label="Conversation history" title="History">${SVG.history}<span class="hbadge" hidden></span></button>
    <button class="hbtn more" type="button" aria-label="More options" title="More" aria-haspopup="menu" aria-expanded="false">${SVG.more}</button>
    <button class="hbtn min" type="button" aria-label="Minimize" title="Minimize">${SVG.minus}</button>
    <button class="hbtn close" type="button" aria-label="Close" title="Close">${SVG.close}</button>
    <div class="menu" role="menu" aria-label="More options">
      <button type="button" role="menuitem" data-act="new">${SVG.plus}<span>New conversation</span></button>
      <button type="button" role="menuitem" data-act="help">${SVG.help}<span>Help &amp; contact</span></button>
      <hr>
      <button type="button" role="menuitem" data-act="compare">${SVG.layers}<span>Compare side by side</span></button>
      <button type="button" role="menuitem" data-act="email">${SVG.mail}<span>Email me this chat</span></button>
      <button type="button" role="menuitem" data-act="download">${SVG.dl}<span>Download transcript</span></button>
      <button type="button" role="menuitem" data-act="theme"><span class="ti"></span><span class="tl"></span></button>
    </div>
  </header>
  <div class="views">
    <section class="view view-home" aria-label="Home" hidden>
      <div class="homev scroll">
        <div class="hero"><div class="htopbar"><span class="hlogo" aria-hidden="true">${SVG.mark}</span><span class="havs"></span><button class="hclose" type="button" aria-label="Close" title="Close">${SVG.close}</button></div>
          <h2 class="hi"><span class="hi1">Hi there 👋</span><span class="hi2">How can we help?</span></h2></div>
        <div class="hcards">
          <button class="hcard recent" type="button" hidden></button>
          <button class="hcard askq" type="button"><span class="ht"><b>Ask a question</b><small>AI Agent and team can help</small></span>${SVG.askarrow}</button>
          <button class="hcard cmpc" type="button"><span class="hci">${SVG.layers}</span><span class="ht"><b>Compare side by side</b><small>Two or three of Deep's companies in one table</small></span>${SVG.chev}</button>
          <button class="hcard bookc" type="button"><span class="hci">${SVG.cal}</span><span class="ht"><b>Book a call with Deep</b><small>Pick a time that suits you, right here</small></span>${SVG.chev}</button>
          <div class="hcard searchc"><button class="hsearch" type="button"><span>Search for help</span>${SVG.search}</button><div class="alist harts"></div></div>
          <button class="hcard newsc" type="button" hidden></button>
        </div>
      </div>
    </section>
    <section class="view view-chat" aria-label="Chat">
      <div class="log scroll" role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation"></div>
      <div class="composer">
        <button class="jump" type="button" hidden>${SVG.arrowdown}<span>Latest</span></button>
        <div class="pop pop-emoji" role="dialog" aria-label="Emoji"><input class="search" placeholder="Search emoji" aria-label="Search emoji"><div class="egrid"></div></div>
        <div class="pop pop-gif" role="dialog" aria-label="GIFs"><input class="search" placeholder="Search GIFs" aria-label="Search GIFs"><div class="ggrid"></div><div class="empty" hidden></div></div>
        <div class="edr" role="status" hidden><button class="edr-go" type="button">${SVG.mail}<span class="edr-t">Your email isn't sent yet</span><b>Review &amp; send</b></button><button class="edr-x" type="button" aria-label="Dismiss the reminder">&times;</button></div>
        <form class="cbox">
          <div class="attach" hidden></div>
          <div class="rec" aria-live="polite"><i></i><span class="rlabel">Listening…</span><span class="rtime">0:00</span><button type="button" class="cicon rstop" aria-label="Stop dictation" title="Stop">${SVG.stop}</button></div>
          <label class="vh" for="q">Message Deep</label>
          <textarea id="q" class="q" rows="1" placeholder="Ask a question…" enterkeyhint="send"></textarea>
          <div class="crow">
            <input type="file" class="file" multiple hidden>
            <button type="button" class="cicon b-clip" aria-label="Attach a file" title="Attach a file">${SVG.clip}</button>
            <button type="button" class="cicon b-emoji" aria-label="Emoji" title="Emoji" aria-haspopup="dialog">${SVG.emoji}</button>
            <button type="button" class="cicon b-gif" aria-label="GIF" title="GIF" aria-haspopup="dialog" hidden>${SVG.gif}</button>
            <button type="button" class="cicon b-mic" aria-label="Dictate" title="Dictate">${SVG.mic}</button>
            <div class="plus-wrap" hidden><button type="button" class="cicon b-plus" aria-label="More" aria-haspopup="menu" aria-expanded="false" tabindex="-1">${SVG.plus}</button><div class="pmenu" role="menu" aria-label="Add to your message"></div></div>
            <span class="cfill"></span>
            <button type="button" class="cicon speak" aria-label="Start a voice conversation with Deep" title="Voice conversation">${SVG.wave}</button>
            <button type="submit" class="send" aria-label="Send" title="Send" disabled><span class="i-send">${SVG.send}</span><span class="i-stop" hidden>${SVG.stop}</span></button>
          </div>
        </form>
      </div>
      <div class="foot"><span class="aidisc">AI answers, with sources; they can be wrong.</span> By chatting, you agree to our <a class="privacy" href="#" target="_blank" rel="noopener">Privacy Policy</a></div>
    </section>
    <section class="view view-messages" aria-label="History" hidden>
      <div class="hist scroll">
        <div class="htop">
          <div class="searchbox">${SVG.search}<label class="vh" for="msearch">Search conversations</label><input id="msearch" class="msearch" type="search" placeholder="Search conversations" autocomplete="off"></div>
        </div>
        <div class="bookings" hidden><div class="mgroup" role="presentation">Your bookings</div><div class="brows" role="list" aria-label="Your bookings"></div></div>
        <div class="mrows" role="list" aria-label="Conversations"></div>
      </div>
      <button class="btn primary newconvo askq" type="button"><span>Ask a question</span>${SVG.help}</button>
    </section>
    <section class="view view-news" aria-label="News" hidden><div class="newsv scroll"></div></section>
    <section class="view view-help" aria-label="Help" hidden>
      <div class="hsearchbar"><div class="searchbox"><label class="vh" for="hq">Search for help</label><input id="hq" class="hq" type="search" placeholder="Search for help" autocomplete="off">${SVG.search}</div></div>
      <div class="help scroll"></div>
    </section>
  </div>
  <nav class="tabbar" aria-label="Sections">
    <button class="tab" type="button" data-tab="home"><span class="ti">${SVG.home}</span><span>Home</span></button>
    <button class="tab" type="button" data-tab="messages"><span class="ti">${SVG.chat}<span class="tbadge" hidden></span></span><span>Messages</span></button>
    <button class="tab" type="button" data-tab="help"><span class="ti">${SVG.help}</span><span>Help</span></button>
    <button class="tab" type="button" data-tab="news"><span class="ti">${SVG.news}<span class="ndot" hidden></span></span><span>News</span></button>
  </nav>
  <div class="voice" role="dialog" aria-label="Voice conversation">
    <div class="vhead"><b>Deep · Voice</b><span class="live" aria-hidden="true"></span><span class="vtimer" aria-label="Call duration">00:00</span><button type="button" class="hbtn v-min" aria-label="Minimize the call view (the call continues)" title="Back to chat">${SVG.chevdown}</button></div>
    <div class="vbody"><div class="vglow" aria-hidden="true"></div>
      <div class="vorb"><canvas width="440" height="440" aria-hidden="true"></canvas><span class="vmute-badge">muted</span></div>
      <div class="vstatus" aria-live="off">Connecting…</div>
      <div class="vcap" aria-live="off"><div class="cu"></div><div class="ca"></div></div>
    </div>
    <div class="vctl"><button type="button" class="vbtn v-mute" aria-pressed="false" aria-label="Mute microphone"><span class="vi">${SVG.mic}</span><span class="tip">Mute</span></button><button type="button" class="vbtn end v-end" aria-label="End call">${SVG.hangup}<span class="tip">End call</span></button><button type="button" class="vbtn cc v-cc" aria-pressed="true" aria-label="Captions on"><span class="vi">${SVG.cc}</span><span class="tip">Captions</span></button><button type="button" class="vbtn lang v-lang" aria-label="Voice language: automatic"><span class="vi vl">Auto</span><span class="tip">Language</span></button></div>
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
    this.$back.onclick = () => this._goBack();
    sh.querySelectorAll('.tab').forEach((t) => { t.onclick = () => { if (t.dataset.tab === 'help') this._helpPage = null; if (t.dataset.tab === 'news') this._newsPage = null; this.showView(t.dataset.tab); }; });
    sh.querySelector('.hclose').onclick = () => this.$close.click();
    sh.querySelector('.askq').onclick = () => { this._emit('action', { action: 'home', label: 'Ask a question', kind: 'question' }); if (this._transcript.length) this.newChat(); else this.showView('chat'); };
    sh.querySelector('.bookc').onclick = () => { this._emit('action', { action: 'home', label: 'Book a call', kind: 'booking' }); this.startBooking(); };
    sh.querySelector('.hsearch').onclick = () => this.openHelp(true);
    let hqT = null; sh.querySelector('.hq').addEventListener('input', (e) => { const v = e.target.value; clearTimeout(hqT); hqT = setTimeout(() => this._helpSearch(v), 300); });
    // links to help articles (#dh-help=<slug>) open inside the messenger, from answers and from articles
    sh.addEventListener('click', (e) => { const a = e.composedPath().find((n) => n.tagName === 'A' && n.getAttribute && /#dh-help=/.test(n.getAttribute('href') || '')); if (!a) return; e.preventDefault(); this.openArticle(decodeURIComponent(a.getAttribute('href').split('#dh-help=')[1] || '')); });
    this.$home = sh.querySelector('.home'); this.$home.onclick = () => this.newChat();
    sh.querySelector('.b-history').onclick = () => this.showView('messages');
    sh.querySelector('.cmpc').onclick = () => { this._emit('action', { action: 'home', label: 'Compare side by side', kind: 'compare' }); this.openCompare(); };
    const more = sh.querySelector('.more'); more.onclick = (e) => { e.stopPropagation(); const o = !this.$menu.classList.contains('open'); this._closePops(); this.$menu.classList.toggle('open', o); more.setAttribute('aria-expanded', String(o)); if (o) this.$menu.querySelector('button').focus(); };
    this.$menu.querySelectorAll('button').forEach((b) => b.onclick = () => { this._closePops(); const a = b.dataset.act; if (a === 'theme') this.switchTheme(); else if (a === 'download') this.download(); else if (a === 'email') this.emailChat(); else if (a === 'compare') this.openCompare(); else if (a === 'help') this.showView('help'); else this.newChat(); });
    this.$menu.addEventListener('keydown', (e) => { const items = [...this.$menu.querySelectorAll('button')]; const i = items.indexOf(sh.activeElement);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus(); }
      else if (e.key === 'Escape' || e.key === 'Tab') { this._closePops(); if (e.key === 'Escape') { e.stopPropagation(); more.focus(); } } });
    sh.addEventListener('click', (e) => { if (!e.composedPath().some((n) => n.classList && (n.classList.contains('menu') || n.classList.contains('more') || n.classList.contains('pop') || n.classList.contains('b-emoji') || n.classList.contains('b-gif') || n.classList.contains('plus-wrap')))) this._closePops(); });
    this.$panel.addEventListener('keydown', (e) => { if (e.key !== 'Escape' || e.defaultPrevented) return;
      if (this.$menu.classList.contains('open') || sh.querySelector('.pop.open, .pmenu.open')) { this._closePops(); return; }
      if (sh.querySelector('.voice.open')) { this._showVoice(false); return; }
      if ((this._view === 'help' && this._helpPage) || (this._view === 'news' && this._newsPage)) { this._goBack(); return; }
      if (this.getAttribute('mode') === 'launcher') this.close(); });
    // history
    sh.querySelector('.newconvo').onclick = () => this.newChat();
    sh.querySelector('.msearch').addEventListener('input', (e) => { this._mquery = e.target.value; this._paintConversations(); this._paintBookings(); });
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
    sh.querySelector('.v-lang').onclick = () => this._cycleVoiceLang(); this._paintVoiceLang();
    sh.querySelector('.v-min').onclick = () => this._showVoice(false); sh.querySelector('.vpill').onclick = () => this.startVoice(); sh.querySelector('.v-cc').onclick = () => this._toggleCaptions();
    this._onVis = () => { const v = this._voice; if (v && v.orb) { if (document.visibilityState === 'hidden') v.orb.pause(); else if (this.hasAttribute('open') || this.getAttribute('mode') !== 'launcher') v.orb.resume(); } };
    document.addEventListener('visibilitychange', this._onVis);
    this._me = { signed_in: false, name: this.getAttribute('user-name'), email: this.getAttribute('user-email'), verified: false }; this._restore();  // paint at once; /me then refreshes the welcome (memory) without touching a live conversation
    this.showView(this._tabs().includes('home') ? 'home' : 'chat');
    this._loadMe().then(() => { this._refreshWelcome(); this._refreshBadge(); if (this._view === 'home') this._renderHome(); }); this._autosize(); this._syncSend(); this._track(); this._health(); this._loadConfig();
    console.info('deep-assistant v' + VERSION + ' ready (api ' + this.api + ')');
    this._emit('ready', { sessionId: this._sid, version: VERSION });
  }
  _closePops() { const sh = this.shadowRoot; this.$menu.classList.remove('open'); sh.querySelector('.more').setAttribute('aria-expanded', 'false'); sh.querySelectorAll('.pop').forEach((p) => p.classList.remove('open')); sh.querySelectorAll('.b-emoji, .b-gif').forEach((b) => b.classList.remove('on')); sh.querySelector('.pmenu').classList.remove('open'); sh.querySelector('.b-plus').setAttribute('aria-expanded', 'false'); }
  _togglePop(which) { const p = this.shadowRoot.querySelector('.pop-' + which); const o = !p.classList.contains('open'); this._closePops(); p.classList.toggle('open', o); this.shadowRoot.querySelector('.b-' + which).classList.toggle('on', o); if (o) { p.querySelector('.search').focus(); if (which === 'gif' && !p.querySelector('.ggrid').children.length) this._searchGifs(''); } }
  _applyCopy() { const sh = this.shadowRoot; sh.querySelector('.ttl').textContent = this.botName; sh.querySelector('.sub').textContent = this.getAttribute('subtitle') || 'The team can also help'; this.$panel.setAttribute('aria-label', this.botName + ' assistant'); }
  _applyMode() { const launcher = this.getAttribute('mode') === 'launcher'; this.$min.hidden = !launcher; this.$close.hidden = !launcher; this.$panel.setAttribute('role', launcher ? 'dialog' : 'region'); }
  _applyFooter() { const a = this.shadowRoot.querySelector('.privacy'); a.href = this.getAttribute('privacy-url') || this._cfg.privacy_url || 'https://deependhq.com/privacy'; this.shadowRoot.querySelector('.foot').title = 'deep-assistant v' + VERSION + (this._cfg.version ? ' · server ' + this._cfg.version : ''); }
  _applyTabs() { const tabs = this._tabs(), help = tabs.includes('help'); this.$menu.querySelector('[data-act="help"]').hidden = !help;
    this.shadowRoot.querySelectorAll('.tab').forEach((t) => { t.hidden = !tabs.includes(t.dataset.tab); });
    if ((!help && this._view === 'help') || (!tabs.includes('home') && this._view === 'home')) this.showView('chat'); else if (this._view) this.showView(this._view); }
  _syncThemeItem() { const b = this.$menu && this.$menu.querySelector('[data-act="theme"]'); if (!b) return; const dark = this._isDark(); b.querySelector('.ti').outerHTML = `<span class="ti">${dark ? SVG.sun : SVG.theme}</span>`; b.querySelector('.tl').textContent = dark ? 'Light theme' : 'Dark theme'; }
  _applyComposerCaps() { const sh = this.shadowRoot; sh.querySelector('.b-gif').hidden = !this._cfg.gif; const listen = this._canListen(); sh.querySelector('.b-mic').hidden = !listen; this.$speak.dataset.off = listen ? '' : '1'; this._syncSend(); }
  _applyOpen() {
    const launcher = this.getAttribute('mode') === 'launcher', open = this.hasAttribute('open');
    this.$launcher.setAttribute('aria-expanded', String(open)); this.$launcher.setAttribute('aria-label', open ? 'Minimize the assistant' : 'Open the ' + this.botName + ' assistant');
    if (!launcher || open === this._wasOpen) return; this._wasOpen = open;
    this._emit(open ? 'open' : 'close');
    if (open) { if (this._introOn()) this._playIntro(); this._bindViewport(true); this._health(); setTimeout(() => { if (!this._voice) this._focusInput(); }, 60); this._refreshBadge(); this._teamCheck(); { const np = this.shadowRoot.querySelector('.npop'); if (np) np.hidden = true; clearTimeout(this._newsPopT); } this._newsLive(true); if (this._voice && this._voice.orb) this._voice.orb.resume(); clearTimeout(this._edPopT); setTimeout(() => this._edCheck(), 300); }
    else { this._stopIntro(); this._bindViewport(false); this._closePops(); this._edPop(1500); if (this._voice && this._voice.orb) this._voice.orb.pause(); if (this.shadowRoot.activeElement && this.shadowRoot.activeElement !== this.$launcher) this.$launcher.focus({ preventScroll: true }); }
  }
  // ---------------------------------------------------------------- opening animation (launcher tap)
  _introOn() { return this.getAttribute('mode') === 'launcher' && this.getAttribute('intro') !== 'off' && !this._reduced && !(this._cfg && this._cfg.intro === false); }
  _playIntro() {
    const p = this.$panel; this._stopIntro();
    const ov = document.createElement('div'); ov.className = 'intro'; ov.setAttribute('aria-hidden', 'true');
    // the logo: a diamond of dots in rows of 1, 3, 5, 7, 5, 3, 1, popping in from the centre outward
    const dots = []; [1, 3, 5, 7, 5, 3, 1].forEach((n, r) => { for (let k = 0; k < n; k++) { const c = k - (n - 1) / 2, d = Math.abs(r - 3) + Math.abs(c);
      dots.push(`<i style="left:${c * 15}px;top:${(r - 3) * 15}px;animation-delay:${350 + d * 55}ms"></i>`); } });
    ov.innerHTML = `<div class="ig-glass"></div><div class="ig-stage"><div class="ig-solid"></div><div class="ig-blob ig-navy"></div><div class="ig-blob ig-coral"></div><div class="ig-blob ig-violet"></div><div class="ig-melt"></div><div class="ig-dots"></div><div class="ig-logo">${dots.join('')}</div></div><div class="ig-rise"></div>`;
    if (this._view === 'home') ov.classList.add('to-home');   // it rises into Home's navy header
    p.prepend(ov); p.classList.add('intro-run'); this._introEl = ov;
    this._introT1 = setTimeout(() => {           // 1600 ms: white everywhere; the messenger (Home) shows as the overlay melts away
      p.classList.add('intro-out');
      this._introT2 = setTimeout(() => {         // 1800 ms: the greeting and the disclaimer arrive
        p.classList.remove('intro-run', 'intro-out'); ov.remove(); this._introEl = null;
        p.classList.add('intro-greet'); this._introT3 = setTimeout(() => p.classList.remove('intro-greet'), 1000);
      }, 200);
    }, 1600);
  }
  _stopIntro() { clearTimeout(this._introT1); clearTimeout(this._introT2); clearTimeout(this._introT3); if (this._introEl) { this._introEl.remove(); this._introEl = null; } if (this.$panel) this.$panel.classList.remove('intro-run', 'intro-out', 'intro-greet'); }
  _bindViewport(on) {  // phones: size the full-screen panel to the visual viewport so the composer stays above the keyboard
    const vv = window.visualViewport; if (!vv) return;
    if (on && !this._vvH) { this._vvH = () => { this.$panel.style.setProperty('--da-vvh', Math.round(vv.height) + 'px'); this.$panel.style.setProperty('--da-vv-top', Math.round(vv.offsetTop) + 'px'); }; vv.addEventListener('resize', this._vvH); vv.addEventListener('scroll', this._vvH); this._vvH(); }
    else if (!on && this._vvH) { vv.removeEventListener('resize', this._vvH); vv.removeEventListener('scroll', this._vvH); this._vvH = null; }
  }
  async _loadConfig() { if (!this.api) return; try { const r = await fetch(this._url('/widget-config')); if (r.ok) { this._cfg = await r.json(); if (this._brand() !== 'LakeB2B') this._refreshWelcome(); this._applyExtras(); this._applyFooter(); this._applyComposerCaps(); this._applyTabs(); this._loadNews().then(() => { this._paintNewsDot(); this._newsLive(); }); if (this._view === 'help' && !this._helpPage) this._renderHelp(); if (this._view === 'home') this._renderHome(); this._edPop(4000); } } catch {} }
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
    let next = this._me || { signed_in: false, name: hintName, email: hintEmail, verified: false };  // keep what we have until the server answers
    if (this.api) { try { const r = await fetch(this._url('/me'), { headers: this._headers(false) }); if (r.ok) { const d = await r.json(); next = { ...d, name: d.name || hintName, email: d.email || hintEmail }; } } catch {} }
    if (!next.name && hintName) next.name = hintName; if (!next.email && hintEmail) next.email = hintEmail;
    this._me = next;
  }
  _firstName() { return (this._me && this._me.name) ? String(this._me.name).trim().split(/\s+/)[0] : ''; }
  // A session counts as tracked only once the server stored the beacon (a 403/429/failed /track retries later; /chat and
  // /booking/confirm carry the same fields until then).
  _track() {
    if (!this.api || this._tracked()) return Promise.resolve();
    const sid = this._sid;
    return fetch(this._url('/track'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ session_id: sid, visitor_id: this._vid, timezone: this.tz, ...this._beaconData() }), keepalive: true })
      .then((r) => r.ok ? r.json() : null).then((d) => { if (d && d.ok) store.set(this._key('tracked'), sid); }).catch(() => {});
  }
  _tracked() { return store.get(this._key('tracked')) === this._sid; }
  // capped like the server's fields (it clips too): a long tracking URL must never cost the visitor a chat or a booking
  _beaconData() { return { page: String(location.href).slice(0, 2000), referrer: (document.referrer || '').slice(0, 2000) || null, lang: navigator.language || null, screen: screen && screen.width ? `${screen.width}x${screen.height}` : null }; }
  // The host set `api` after the element rendered (index.html, demo.html used to): key the sid under the real api and
  // start what an empty api skipped. A live conversation is never swapped.
  _adoptApi() {
    if (!this.api) return;
    const kept = store.get(this._key('sid'));
    if (kept && kept !== this._sid && !this._transcript.length && !this._busy) { this._sid = kept; this._restore(); }
    else { store.set(this._key('sid'), this._sid); if (this._transcript.length) this._persist(); }
    this._track(); this._loadMe().then(() => { this._refreshWelcome(); this._refreshBadge(); });
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
  _brand() { const k = this._cfg && this._cfg.knowledge; return k && 'brand' in k ? k.brand : 'LakeB2B'; }  // LakeB2B until the server says otherwise
  _b(text) {  // a LakeB2B line in the brand the Knowledge switches leave on; unchanged while LakeB2B is on
    const b = this._brand(); if (b === 'LakeB2B' || typeof text !== 'string') return text;
    if (!b) return NO_BRAND[text] || text.replace(/LakeB2B's /g, "Deep's companies' ").replace(/LakeB2B/g, "Deep's companies");
    return text.replace(/LakeB2B/g, b);
  }
  _pageTitle() { const t = (document.title || '').split(/\s[|–—-]\s/)[0].trim(); return t && t.length <= 60 ? t : ''; }
  _actions() {
    const a = this.getAttribute('suggestions');
    if (a) return a.split('|').map((s) => s.trim()).filter(Boolean).slice(0, 4).map((label) => (BOOK_RE.test(label) ? { icon: 'cal', label, book: true } : { icon: 'spark', label, ask: label }));
    const title = this._pageTitle();
    return CONTEXT_ACTIONS[this._pageContext()].map((k) => { const x = ACTIONS[k]; return x.askPage ? { ...x, ask: x.askPage(title) } : { ...x, label: this._b(x.label), ask: this._b(x.ask) }; });
  }
  _renderWelcome() {
    this.$log.querySelectorAll('.welcome').forEach((x) => x.remove());  // idempotent: open + restore + /me may each ask for it
    const w = document.createElement('div'); w.className = 'welcome'; const first = this._firstName(); const ctx = this.getAttribute('suggestions') ? 'custom' : this._pageContext();
    const mem = (this._me && this._me.memory && this._me.memory.returning) ? this._me.memory : null;  // return-visitor memory (docs/MEMORY_VOICE.md)
    const h2 = mem && mem.headline ? mem.headline : (first ? `Hi ${first}, I'm Deep` : "Hi, I'm Deep"); const p = this.getAttribute('greeting') || (mem && mem.line) || this._b(INTRO);
    if (mem) w.classList.add('back');
    w.innerHTML = `<h2>${esc(h2)}</h2><p>${esc(p)}</p>
      <div class="acts-label">${ctx === 'general' || ctx === 'custom' ? 'Popular ways to start' : 'Suggested for this page'}</div><div class="acts" role="group" aria-label="Suggested actions"></div>`;
    const acts = w.querySelector('.acts');
    const em = this._email;  // opened from a booking email: say which booking, and offer that email's questions
    if (em && em.booking) { const b = em.booking, n = document.createElement('div'); n.className = 'emailctx';
      n.innerHTML = `From your ${esc(em.opened_from || 'booking email')} · <b>${esc(b.schedule_name || 'your call')}</b>${b.label_visitor ? ' · ' + esc(b.label_visitor) : ''} · ${esc(EMAIL_STATUS[b.status] || '')}`;
      w.insertBefore(n, w.firstChild); }
    if (mem && mem.upcoming && (mem.upcoming.join_url || mem.upcoming.handoff_url)) { const u = mem.upcoming; const a = document.createElement('a'); a.className = 'act book'; a.href = u.join_url || u.handoff_url; a.target = '_blank'; a.rel = 'noopener';
      a.innerHTML = `<span class="ai">${SVG.cal}</span><span class="al">${esc(u.status === 'confirmed' ? 'Join your call' : 'Confirm your call on Zoom')}<small>${esc(u.schedule_name + ' · ' + u.label_visitor)}</small></span>${SVG.chev}`; acts.appendChild(a); }
    if (mem && mem.upcoming && mem.upcoming.can_reschedule) { const u = mem.upcoming; const b = document.createElement('button'); b.type = 'button'; b.className = 'act resched';
      b.innerHTML = `<span class="ai">${SVG.clock}</span><span class="al">Reschedule your call<small>Pick a new time for ${esc(u.schedule_name)}</small></span>${SVG.chev}`; b.onclick = () => this.startReschedule(u, 'Reschedule my call'); acts.appendChild(b); }
    if (mem && !mem.upcoming && mem.recent_change && mem.recent_change.kind === 'cancelled') { const r = mem.recent_change; const b = document.createElement('button'); b.type = 'button'; b.className = 'act book rebook';
      b.innerHTML = `<span class="ai">${SVG.cal}</span><span class="al">Book a new time<small>You cancelled ${esc(r.schedule_name + ' · ' + r.label_visitor)}</small></span>${SVG.chev}`; b.onclick = () => this.startBooking(null, 'Book a new time'); acts.appendChild(b); }
    if (mem && mem.upcoming && mem.upcoming.can_cancel) { const u = mem.upcoming; const b = document.createElement('button'); b.type = 'button'; b.className = 'act cancelcall';
      b.innerHTML = `<span class="ai">${SVG.x || SVG.close || SVG.alert}</span><span class="al">Cancel your call<small>${esc(u.schedule_name + ' · ' + u.label_visitor)}</small></span>${SVG.chev}`; b.onclick = () => this.startCancel(u, 'Cancel my call'); acts.appendChild(b); }
    (em && em.questions && em.questions.length ? em.questions.map((q) => (q.action === 'book' ? { icon: 'cal', label: q.text, book: true } : q.action === 'reschedule' ? { icon: 'clock', label: q.text, resched: true } : { icon: 'spark', label: q.text, ask: q.text })) : this._actions()).forEach((x) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'act' + (x.book ? ' book' : ''); b.innerHTML = `<span class="ai">${SVG[x.icon] || SVG.spark}</span><span class="al">${esc(x.label)}</span>${SVG.chev}`; b.onclick = () => this._runAction(x, 'suggestion'); acts.appendChild(b); });
    this.$log.appendChild(w);
  }
  _refreshWelcome() { if (!this._rendered || this._transcript.length) return; const w = this.$log.querySelector('.welcome'); if (w) { w.remove(); this._renderWelcome(); } }
  _runAction(x, source) {
    this._emit('action', { action: source, label: x.label, kind: x.book ? 'booking' : 'question' });
    if (x.resched) { const u = this._me && this._me.memory && this._me.memory.upcoming; if (u && u.can_reschedule) return this.startReschedule(u, x.label); return this._send(x.label); }
    if (x.book) return this.startBooking(typeof x.book === 'string' ? x.book : null, x.label);
    return this._send(x.ask || x.label);
  }
  // ---------------------------------------------------------------- News (Intercom's News tab, as on snitcher.com; app/news.py)
  // List: feeds (Latest, Newsletters, Case studies, Videos...), cards with "New", the first label and "+N labels";
  // an item opens inside the messenger with all its labels, "Shared by", the article and "How would you rate this?".
  _newsTenant() { return this.getAttribute('news-tenant') || (this._cfg && this._cfg.news && this._cfg.news.tenant) || ''; }
  async _loadNews(force, feed) {
    if (!this.api || !this._tabs().includes('news')) return null;
    feed = feed || 'latest'; this._newsByFeed = this._newsByFeed || {};
    const have = this._newsByFeed[feed];
    if (have && !force && Date.now() - have.at < 300000) return have;
    try { const t = this._newsTenant(), q = [t ? 'tenant=' + encodeURIComponent(t) : '', feed !== 'latest' ? 'feed=' + encodeURIComponent(feed) : ''].filter(Boolean).join('&');
      const r = await fetch(this._url('/news' + (q ? '?' + q : ''))); if (r.ok) { this._newsByFeed[feed] = { ...(await r.json()), at: Date.now() }; if (feed === 'latest') this._news = this._newsByFeed[feed]; } } catch {}
    return this._newsByFeed[feed] || null;
  }
  // while the panel is open the feed is re-asked every 2 minutes (a 304 when nothing changed, app/main.py) and the
  // open view repaints only when an item was added, edited or taken off on the site
  _newsSig() { const d = this._news; return d && d.items ? d.items.map((i) => `${i.id}:${i.published_at}:${i.title}:${i.image || ''}`).join('|') : ''; }
  _newsLive(now) {
    clearTimeout(this._newsT); const shown = this.getAttribute('mode') !== 'launcher' || this.hasAttribute('open');
    if (!this._tabs().includes('news')) return;
    if (!shown) { this._newsPopup(); return; }
    const step = async () => { if (!document.hidden) { const before = this._newsSig(); await this._loadNews(true);
      if (this._newsSig() !== before) { if (this._view === 'news' && !this._newsPage) this._renderNews(); else if (this._view === 'home') this._paintHomeNews(); else this._paintNewsDot(); } }
      this._newsLive(); };
    this._newsT = setTimeout(step, now && this._news && Date.now() - this._news.at > 60000 ? 0 : 120000);
  }
  // read state per item (Intercom marks an item seen once it was shown); items older than the old "seen up to" mark count as read
  _newsKey(k) { return this._key(k + ':' + this._newsTenant()); }
  _newsRead() { if (!this._newsReadSet) { let ids = []; try { ids = JSON.parse(localStorage.getItem(this._newsKey('news_read')) || '[]'); } catch {} this._newsReadSet = new Set(ids.map(String)); } return this._newsReadSet; }
  _newsSeen() { try { return localStorage.getItem(this._newsKey('news_seen')) || ''; } catch { return ''; } }
  _isNewsUnread(it) { const legacy = this._newsSeen(); return !this._newsRead().has(String(it.id)) && !(legacy && String(it.published_at) <= legacy); }
  _markNewsRead(items) { const s = this._newsRead(); let n = 0; items.forEach((it) => { if (!s.has(String(it.id))) { s.add(String(it.id)); n++; } });
    if (n) { try { localStorage.setItem(this._newsKey('news_read'), JSON.stringify([...s].slice(-300))); } catch {} } }
  _newsUnread() { const d = this._news; return d && d.items ? d.items.filter((it) => this._isNewsUnread(it)).length : 0; }
  _paintNewsDot() { const dot = this.shadowRoot.querySelector('.ndot'); if (!dot) return; const n = this._newsUnread(); dot.hidden = !n; dot.textContent = n > 9 ? '9+' : n ? String(n) : ''; }
  _newsLabels(it, unread, all) {
    const labels = (it.labels && it.labels.length ? it.labels : [it.label || it.kind]).filter(Boolean);
    const chips = (unread ? '<span class="nchip new">New</span>' : '') + (it.pinned ? '<span class="nchip">Pinned</span>' : '')
      + (all ? labels : labels.slice(0, 1)).map((l) => `<span class="nchip">${esc(l)}</span>`).join('')
      + (!all && labels.length > 1 ? `<span class="nchip more">+ ${labels.length - 1} label${labels.length > 2 ? 's' : ''}</span>` : '')
      + (it.updated ? '<span class="nchip upd">Updated</span>' : '');
    return `<span class="nlabels">${chips}</span>`;
  }
  _newsCard(it, isNew, cls) {
    return `<a class="${cls}" href="${esc(it.url)}" target="_blank" rel="noopener" data-id="${esc(String(it.id))}">${it.image ? `<span class="nimg"><img src="${esc(it.image)}" alt="" loading="lazy" onerror="this.parentNode.remove()"></span>` : ''}
      <span class="nbody">${this._newsLabels(it, isNew, false)}<b>${esc(it.title)}</b>${it.blurb ? `<span class="nblurb">${esc(it.blurb)}</span>` : ''}</span>${SVG.chev}</a>`;
  }
  _bindNewsCards(box) {
    box.querySelectorAll('a.ncard').forEach((a) => a.addEventListener('click', (e) => {
      this._emit('action', { action: 'news_open', label: (a.querySelector('b') || a).textContent, kind: 'news' });
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return;   // a new tab when asked for one
      e.preventDefault(); this.openNewsItem(a.dataset.id);
    }));
  }
  // quick view: Latest = one featured story, then a row of small cards per feed (swipe sideways, "See all");
  // a feed = a compact list (thumbnail, label, age, title), so a long feed is a short scroll
  _newsThumb(it, cls) { const l = esc(((it.labels && it.labels[0]) || it.label || it.kind || '').slice(0, 14));   // the label shows when there is no picture
    return `<span class="${cls}${it.image ? '' : ' none'}"><em>${l}</em>${it.image ? `<img src="${esc(it.image)}" alt="" loading="lazy" onerror="this.parentNode.classList.add('none');this.remove()">` : ''}</span>`; }
  _newsRow(it, isNew) {
    const first = (it.labels && it.labels[0]) || it.label || it.kind;
    return `<a class="ncard nrow" href="${esc(it.url)}" target="_blank" rel="noopener" data-id="${esc(String(it.id))}">${this._newsThumb(it, 'nth')}
      <span class="nrb"><span class="nmeta">${isNew ? '<i class="nnew" aria-label="New"></i>' : ''}<span class="nchip">${esc(first)}</span>${it.pinned ? '<span class="nchip">Pinned</span>' : ''}${it.published_at ? `<span class="nwhen">${esc(relAge(it.published_at))}${it.read_min ? ` · ${it.read_min} min` : ''}</span>` : ''}</span>
      <b>${esc(it.title)}</b></span></a>`;
  }
  _newsMini(it, isNew) {
    return `<a class="ncard nmini" href="${esc(it.url)}" target="_blank" rel="noopener" data-id="${esc(String(it.id))}">${this._newsThumb(it, 'nmi')}
      <span class="nmb"><span class="nmeta">${isNew ? '<i class="nnew" aria-label="New"></i>' : ''}<span class="nchip">${esc((it.labels && it.labels[0]) || it.label || it.kind)}</span>${it.published_at ? `<span class="nwhen">${esc(relAge(it.published_at))}</span>` : ''}</span><b>${esc(it.title)}</b></span></a>`;
  }
  _newsRail(key, label, items, count) {
    if (!items.length) return '';
    return `<section class="nsec" aria-label="${esc(label)}"><div class="nsech"><b>${esc(label)}</b>${key ? `<button class="nsee" type="button" data-feed="${esc(key)}">See all${count ? ` ${count}` : ''} ${SVG.chev}</button>` : ''}</div>
      <div class="nrail">${items.map((it) => this._newsMini(it, this._isNewsUnread(it))).join('')}</div></section>`;
  }
  async _renderNews() {
    const box = this.shadowRoot.querySelector('.newsv'); if (!box) return;
    if (this._newsPage) return this._paintNewsItem();
    const feed = this._newsFeed || 'latest';
    if (!this._newsByFeed || !this._newsByFeed[feed]) box.innerHTML = '<div class="sk"><span class="a"></span><span class="l"><i></i><i></i></span></div>'.repeat(3);
    const d = await this._loadNews(false, feed); if (this._view !== 'news' || this._newsPage || (this._newsFeed || 'latest') !== feed) return;
    const items = (d && d.items) || [], photo = this._hostPhoto(), feeds = ((this._news || d || {}).feeds || []).filter((f) => f.count || f.key === 'latest');
    const cur = feeds.find((f) => f.key === feed) || { label: 'Latest' }, count = (k) => (feeds.find((f) => f.key === k) || {}).count;
    let body = '';
    if (!items.length && !(d && d.sections && d.sections.length)) body = '<div class="hempty">No news yet. Check back soon.</div>';
    else if (feed === 'latest') {
      const top = items[0];   // the newest story large, then one row of small cards per feed (the story not twice)
      body = (top ? this._newsCard(top, this._isNewsUnread(top), 'ncard nfeat') : '')
        + ((d && d.sections) || []).map((s) => this._newsRail(s.key, s.label, s.items.filter((x) => !top || x.id !== top.id), count(s.key))).join('')
        + `<div class="ncaught">${SVG.check || ''}<span>You're all caught up!</span></div>`;
    } else {
      body = `<div class="nlist">${items.map((it) => this._newsRow(it, this._isNewsUnread(it))).join('')}</div><div class="ncaught">${SVG.check || ''}<span>You're all caught up!</span></div>`;
    }
    const q = this._newsQuery || '';
    box.innerHTML = `<div class="nhead"><span><b>${esc(cur.label)}</b><small>From Team ${esc((d && d.name) || this.botName)}</small></span>${photo ? `<span class="havs"><img src="${esc(photo)}" alt=""></span>` : ''}</div>`
      + `<label class="nsearch">${SVG.search}<input type="search" placeholder="Search news" aria-label="Search news" value="${esc(q)}" maxlength="80"><button type="button" class="nsx" aria-label="Clear search"${q ? '' : ' hidden'}>${SVG.close}</button></label>`
      + (feeds.length > 1 ? `<div class="nfeeds" role="tablist" aria-label="News feeds">${feeds.map((f) => `<button class="nfeed${f.key === feed ? ' on' : ''}" type="button" role="tab" aria-selected="${f.key === feed}" data-feed="${esc(f.key)}">${esc(f.label)}</button>`).join('')}</div>` : '')
      + `<div class="nbodyw">${body}</div>`;
    const inp = box.querySelector('.nsearch input'), clr = box.querySelector('.nsx');
    inp.addEventListener('input', () => { const v = inp.value; clr.hidden = !v; clearTimeout(this._newsQT); this._newsQT = setTimeout(() => this._newsSearch(v, body), 260); });
    clr.onclick = () => { inp.value = ''; clr.hidden = true; this._newsSearch('', body); inp.focus(); };
    if (q) this._newsSearch(q, body);
    const go = (k, label) => { this._newsFeed = k; this._newsQuery = ''; this._emit('action', { action: 'news_feed', label, kind: 'news' }); this._renderNews(); box.scrollTop = 0; };
    box.querySelectorAll('.nfeed').forEach((b) => { b.onclick = () => go(b.dataset.feed, b.textContent); });
    box.querySelectorAll('.nsee').forEach((b) => { b.onclick = () => go(b.dataset.feed, b.dataset.feed); });
    const on = box.querySelector('.nfeed.on'); if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    this._bindNewsCards(box);
    this._markNewsRead(items);   // shown: no longer new (the marks above keep saying "New" until the next visit)
    this._paintNewsDot();
  }
  async _newsSearch(q, feedBody) {
    const box = this.shadowRoot.querySelector('.newsv'), out = box && box.querySelector('.nbodyw'); if (!out) return;
    this._newsQuery = q = (q || '').trim();
    if (q.length < 2) { out.innerHTML = feedBody; this._bindNewsCards(out); this._bindNewsRails(out); return; }
    let d = null;
    try { const t = this._newsTenant(); const r = await fetch(this._url(`/news/search?q=${encodeURIComponent(q)}${t ? '&tenant=' + encodeURIComponent(t) : ''}`)); if (r.ok) d = await r.json(); } catch {}
    if ((this._newsQuery || '') !== q || !out.isConnected) return;
    const items = (d && d.items) || [];
    out.innerHTML = `<div class="nsres">${items.length ? `${items.length} result${items.length === 1 ? '' : 's'} for <b>${esc(q)}</b>` : `Nothing in the news for <b>${esc(q)}</b> yet`}</div>`
      + (items.length ? `<div class="nlist">${items.map((it) => this._newsRow(it, this._isNewsUnread(it))).join('')}</div>` : '');
    this._bindNewsCards(out);
    this._emit('action', { action: 'news_search', label: q, kind: 'news' });
  }
  _bindNewsRails(root) { root.querySelectorAll('.nsee').forEach((b) => { b.onclick = () => { this._newsFeed = b.dataset.feed; this._newsQuery = ''; this._renderNews(); }; }); }
  openNews(feed) { this._newsPage = null; if (feed) this._newsFeed = feed; this.showView('news'); }
  openNewsItem(id) { if (!id) return; this._newsPage = { id: String(id) }; this.showView('news'); this._paintNewsItem(); }
  async _paintNewsItem() {
    const p = this._newsPage, box = this.shadowRoot.querySelector('.newsv'); if (!p || !box) return;
    box.innerHTML = '<div class="sk"><span class="a"></span><span class="l"><i></i><i></i></span></div>';
    let it = null;
    try { const t = this._newsTenant(), q = ['visitor=' + encodeURIComponent(this._vid || this._sid || ''), t ? 'tenant=' + encodeURIComponent(t) : ''].filter(Boolean).join('&');
      const r = await fetch(this._url(`/news/items/${encodeURIComponent(p.id)}?${q}`)); if (r.ok) it = await r.json(); } catch {}
    if (this._newsPage !== p) return;
    if (!it) { box.innerHTML = '<div class="hempty">This news item is no longer available.</div>'; return; }
    this._markNewsRead([it]); this._paintNewsDot();
    const vid = it.kind === 'video' && (/[?&]v=([\w-]{6,20})/.exec(it.url) || [])[1];
    const host = (() => { try { return new URL(it.url).hostname.replace(/^www\./, ''); } catch { return ''; } })();
    const cta = it.source === 'manual' && /linkedin\./.test(host) ? 'See the post on LinkedIn' : it.cta || (host ? `Read on ${host}` : 'Open');
    const team = 'Team ' + (((this._news || {}).name) || this.botName), who = it.author || team, photo = this._hostPhoto();
    const av = (!it.author || it.author === team || (this._cfg && it.author === this._cfg.host_name)) && photo ? `<img src="${esc(photo)}" alt="">` : `<span>${esc((who.replace(/^Team /, '')[0] || '?').toUpperCase())}</span>`;
    const opts = (it.reactions && it.reactions.options) || (this._cfg && this._cfg.news && this._cfg.news.reactions) || ['💜', '😴', '👎', '🎉'];
    box.innerHTML = `<article class="nart" aria-label="${esc(it.title)}">
      ${vid ? `<div class="nvideo"><iframe src="https://www.youtube-nocookie.com/embed/${esc(vid)}" title="${esc(it.title)}" loading="lazy" allow="encrypted-media; picture-in-picture" allowfullscreen></iframe></div>`
        : it.image ? `<div class="nimg"><img src="${esc(it.image)}" alt="" onerror="this.parentNode.remove()"></div>` : ''}
      <div class="ninner">${this._newsLabels(it, false, true)}<h2 class="ntitle">${esc(it.title)}</h2>
      <div class="nby"><span class="nav">${av}</span><span>Shared by <b>${esc(who)}</b>${it.published_at ? ` • <time datetime="${esc(it.published_at)}">${esc(relAge(it.published_at))}</time>` : ''}${it.read_min ? ` • ${it.read_min} min read` : ''}</span></div>
      ${it.has_body && it.read_min >= 2 ? `<div class="ntake" aria-live="polite"><b>${SVG.spark}Key takeaways</b><span class="sk"><span class="l"><i></i><i></i><i></i></span></span></div>` : ''}
      <div class="nhtml">${it.body || (host ? `<p class="nnote">This ${esc((it.label || 'item').toLowerCase())} is on ${esc(host)}.</p>` : '')}</div>
      <div class="nacts"><a class="ncta" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(cta)}${SVG.ext || ''}</a>
        <button type="button" class="nask">${SVG.chat}<span>Ask Deep about this</span></button>
        <button type="button" class="nshare" aria-label="Copy a link to this story">${SVG.copy}<span>Copy link</span></button></div></div>
      <div class="nreact"><p>How would you rate this?</p><div class="nemo" role="group" aria-label="Rate this">${opts.map((e) => `<button type="button" class="nemoji${it.reactions && it.reactions.mine === e ? ' on' : ''}" data-e="${esc(e)}" aria-pressed="${!!(it.reactions && it.reactions.mine === e)}">${esc(e)}</button>`).join('')}</div></div>
      ${it.related && it.related.length ? `<section class="nrel" aria-label="More like this"><b>More like this</b><div class="nlist">${it.related.map((x) => this._newsRow(x, false)).join('')}</div></section>` : ''}
    </article>`;
    this._bindNewsCards(box);
    box.querySelector('.nask').onclick = () => { this._emit('action', { action: 'news_ask', label: it.title, kind: 'news' }); this.ask(`Tell me about "${it.title}"`); };
    box.querySelector('.nshare').onclick = async (e) => {
      const b = e.currentTarget, link = location.href.split('#')[0] + '#dh-news=' + it.id;
      try { await navigator.clipboard.writeText(link); b.querySelector('span').textContent = 'Link copied'; } catch { b.querySelector('span').textContent = link; }
      this._emit('action', { action: 'news_share', label: it.title, kind: 'news' });
      setTimeout(() => { if (b.isConnected) b.querySelector('span').textContent = 'Copy link'; }, 2200);
    };
    const take = box.querySelector('.ntake');
    if (take) { (async () => {
      let pts = [];
      try { const t = this._newsTenant(); const r = await fetch(this._url(`/news/items/${encodeURIComponent(it.id)}/takeaways${t ? '?tenant=' + encodeURIComponent(t) : ''}`)); if (r.ok) pts = (await r.json()).points || []; } catch {}
      if (!take.isConnected || this._newsPage !== p) return;
      if (!pts.length) { take.remove(); return; }
      take.innerHTML = `<b>${SVG.spark}Key takeaways</b><ul>${pts.map((x) => `<li>${esc(x)}</li>`).join('')}</ul><small>Summarised by AI from the article</small>`;
    })(); }
    box.scrollTop = 0;
    box.querySelector('.ncta').addEventListener('click', () => this._emit('action', { action: 'news_link', label: it.title, kind: 'news' }));
    box.querySelectorAll('.nemoji').forEach((b) => { b.onclick = async () => {
      const wasOn = b.classList.contains('on'); box.querySelectorAll('.nemoji').forEach((x) => { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false'); });
      if (!wasOn) { b.classList.add('on'); b.setAttribute('aria-pressed', 'true'); }
      this._emit('action', { action: 'news_react', label: b.dataset.e, kind: 'news' });
      try { const t = this._newsTenant(); await fetch(this._url(`/news/items/${encodeURIComponent(it.id)}/react${t ? '?tenant=' + encodeURIComponent(t) : ''}`),
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ visitor: this._vid || this._sid || 'anon', emoji: wasOn ? null : b.dataset.e }) }); } catch {}
    }; });
  }
  async _paintHomeNews() {
    const card = this.shadowRoot.querySelector('.newsc'); if (!card) return;
    const d = await this._loadNews(); const it = d && d.items && d.items[0];
    card.hidden = !it || !this._tabs().includes('news'); if (!it) return;
    card.innerHTML = `${it.image ? `<span class="nimg"><img src="${esc(it.image)}" alt="" loading="lazy" onerror="this.parentNode.remove()"></span>` : ''}<span class="nbody">${this._newsLabels(it, this._isNewsUnread(it), false)}<b>${esc(it.title)}</b>${it.blurb ? `<span class="nblurb">${esc(it.blurb)}</span>` : ''}</span>`;
    card.onclick = () => this.openNewsItem(it.id);
    this._paintNewsDot();
  }
  // a new item pops up above the closed launcher once (Intercom's news notification); off with news-popup="off"
  _newsPopup() {
    const pop = this.shadowRoot.querySelector('.npop'); if (!pop) return;
    const d = this._news, it = d && d.items && d.items.find((x) => !x.pinned);
    const off = this.getAttribute('news-popup') === 'off' || (this._cfg && this._cfg.news && this._cfg.news.popup === false) || this.getAttribute('mode') !== 'launcher';
    let popped = ''; try { popped = localStorage.getItem(this._newsKey('news_popped')) || ''; } catch {}
    if (off || !it || this.hasAttribute('open') || !this._isNewsUnread(it) || popped === String(it.id) || Date.now() - new Date(it.published_at).getTime() > 7 * 86400000) { pop.hidden = true; return; }
    clearTimeout(this._newsPopT);
    this._newsPopT = setTimeout(() => {
      if (this.hasAttribute('open')) return;
      pop.querySelector('.npb').innerHTML = `${it.image ? `<span class="npi"><img src="${esc(it.image)}" alt="" onerror="this.parentNode.remove()"></span>` : ''}<span class="npt"><small>New from Team ${esc(d.name || this.botName)}</small><b>${esc(it.title)}</b></span>`;
      pop.hidden = false; try { localStorage.setItem(this._newsKey('news_popped'), String(it.id)); } catch {}
      this._emit('action', { action: 'news_popup', label: it.title, kind: 'news' });
      pop.querySelector('.npb').onclick = () => { pop.hidden = true; this.setAttribute('open', ''); this.openNewsItem(it.id); };
      pop.querySelector('.npx').onclick = () => { pop.hidden = true; };
    }, 6000);
  }
  // ---------------------------------------------------------------- Home (Intercom: hero, recent message, ask, book, search for help)
  _hostPhoto() { const p = this._cfg && this._cfg.host_photo; return p ? (/^https?:/.test(p) ? p : this.api + p) : ''; }
  _renderHome() {
    const sh = this.shadowRoot; if (!this._rendered) return; const first = this._firstName();
    sh.querySelector('.hi1').textContent = first ? `Hi ${first} 👋` : 'Hi there 👋';
    const photo = this._hostPhoto(); sh.querySelector('.havs').innerHTML = photo ? `<img src="${esc(photo)}" alt="${esc((this._cfg && this._cfg.host_name) || 'Deep')}">` : '';
    sh.querySelector('.hclose').hidden = this.getAttribute('mode') !== 'launcher';
    const rc = sh.querySelector('.recent'), last = [...this._transcript].reverse().find((m) => m.text && !m.err);
    rc.hidden = !last;
    if (last) { const who = last.role === 'user' ? 'You' : (last.agent ? (last.author || 'Deep') : this.botName);
      rc.innerHTML = `<span class="rl">Recent message</span><span class="rr"><span class="ra">${photo ? `<img src="${esc(photo)}" alt="">` : SVG.mark}</span><span class="rp"><span>${esc(trunc(plain(last.text), 90))}</span><small>${esc(who)} • ${relShort(last.ts)}</small></span>${SVG.chev}</span>`;
      rc.onclick = () => this.showView('chat'); }
    this._paintHomeNews();
    this._loadHelp().then((d) => {
      const box = sh.querySelector('.harts'); const items = (d && d.top) || [];
      sh.querySelector('.searchc').hidden = !this._tabs().includes('help');
      box.innerHTML = items.map((a) => `<button class="arow" type="button" data-slug="${esc(a.slug)}"><span>${esc(a.title)}</span>${SVG.chev}</button>`).join('');
      box.querySelectorAll('.arow').forEach((b) => { b.onclick = () => this.openArticle(b.dataset.slug); });
    });
  }
  // ---------------------------------------------------------------- Help center (GET /help, /help/collections/{slug}, /help/articles/{slug}, /help/search)
  async _loadHelp(force) {
    if (!this.api || (this._cfg && this._cfg.help === false)) return null;
    if (this._helpData && !force) return this._helpData;
    try { const r = await fetch(this._url('/help')); if (r.ok) this._helpData = await r.json(); } catch {}
    return this._helpData || null;
  }
  async _helpGet(path) { try { const r = await fetch(this._url(path)); return r.ok ? await r.json() : null; } catch { return null; } }
  openHelp(focusSearch) { this._helpPage = null; this.showView('help'); if (focusSearch) setTimeout(() => this.shadowRoot.querySelector('.hq').focus(), 40); }
  openCollection(slug) { this._helpPage = { page: 'collection', slug }; this.showView('help'); this._paintHelpPage(); }
  openArticle(slug) { if (!slug) return; const from = this._view === 'help' && this._helpPage && this._helpPage.page === 'collection' ? this._helpPage : null; this._helpPage = { page: 'article', slug, from }; this.showView('help'); this._paintHelpPage(); }
  async _renderHelp() {
    const h = this.shadowRoot.querySelector('.help'); if (!h) return;
    const q = this.shadowRoot.querySelector('.hq'); if (q && q.value.trim()) return this._helpSearch(q.value);
    const d = await this._loadHelp(); if (this._view !== 'help' || this._helpPage) return;
    const cols = (d && d.collections) || [];
    h.innerHTML = (cols.length ? `<h3 class="hc-h">${cols.length} collection${cols.length > 1 ? 's' : ''}</h3>` + cols.map((c) => `<button class="crowl" type="button" data-slug="${esc(c.slug)}"><span class="ct"><b>${esc(c.title)}</b>${c.description ? `<span class="cdsc">${esc(c.description)}</span>` : ''}<small>${c.articles} article${c.articles === 1 ? '' : 's'}</small></span>${SVG.chev}</button>`).join('') : '')
      + '<div class="hcontact"></div>';
    h.querySelectorAll('.crowl').forEach((b) => { b.onclick = () => this.openCollection(b.dataset.slug); });
    this._renderContact(h.querySelector('.hcontact'));
  }
  async _helpSearch(q) {
    const h = this.shadowRoot.querySelector('.help'); q = (q || '').trim();
    if (!q) { this._helpPage = null; return this._renderHelp(); }
    if (this._view !== 'help') { this._helpPage = null; this.showView('help'); }
    const d = await this._helpGet('/help/search?q=' + encodeURIComponent(q)); const items = (d && d.items) || [];
    if (this.shadowRoot.querySelector('.hq').value.trim() !== q) return;
    this._helpPage = null; this._emit('action', { action: 'help_search', label: q, kind: 'help' });
    h.innerHTML = items.length ? `<h3 class="hc-h">${items.length} result${items.length > 1 ? 's' : ''}</h3>` + items.map((a) => `<button class="crowl" type="button" data-slug="${esc(a.slug)}"><span class="ct"><b>${esc(a.title)}</b>${a.summary ? `<small>${esc(a.summary)}</small>` : ''}</span>${SVG.chev}</button>`).join('')
      : `<div class="hempty">No articles match “${esc(q)}”.<br><br><button class="btn primary" type="button">${SVG.chat}<span>Ask the assistant</span></button></div>`;
    h.querySelectorAll('.crowl').forEach((b) => { b.onclick = () => this.openArticle(b.dataset.slug); });
    const ask = h.querySelector('.hempty .btn'); if (ask) ask.onclick = () => this.ask(q);
  }
  async _paintHelpPage() {
    const h = this.shadowRoot.querySelector('.help'), p = this._helpPage; if (!h || !p) return;
    h.innerHTML = '<div class="sk"><span class="a"></span><span class="l"><i></i><i></i></span></div>'.repeat(3); h.scrollTop = 0;
    if (p.page === 'collection') {
      const c = await this._helpGet('/help/collections/' + encodeURIComponent(p.slug)); if (this._helpPage !== p) return;
      if (!c) { h.innerHTML = '<div class="hempty">This collection is not available.</div>'; return; }
      this.shadowRoot.querySelector('.vtitle').textContent = 'Help';
      h.innerHTML = `<div class="cinfo"><b>${esc(c.title)}</b>${c.description ? `<p>${esc(c.description)}</p>` : ''}<small>${c.articles.length} article${c.articles.length === 1 ? '' : 's'}${c.authors && c.authors.length ? ' · By ' + esc(c.authors.join(' and ')) : ''}</small></div>`
        + c.articles.map((a) => `<button class="crowl" type="button" data-slug="${esc(a.slug)}"><span class="ct"><span class="cdsc">${esc(a.title)}</span></span>${SVG.chev}</button>`).join('');
      h.querySelectorAll('.crowl').forEach((b) => { b.onclick = () => this.openArticle(b.dataset.slug); });
      return;
    }
    const a = await this._helpGet('/help/articles/' + encodeURIComponent(p.slug)); if (this._helpPage !== p) return;
    if (!a) { h.innerHTML = '<div class="hempty">This article is not available any more.</div>'; return; }
    this.shadowRoot.querySelector('.vtitle').textContent = '';
    const photo = this._hostPhoto(), when = a.updated_at ? new Date(a.updated_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : '';
    h.innerHTML = `<article class="article"><h1>${esc(a.title)}</h1>${a.summary ? `<p class="asum">${esc(a.summary)}</p>` : ''}
      <div class="aby"><span class="ra">${photo ? `<img src="${esc(photo)}" alt="">` : SVG.mark}</span><span>${a.author ? 'Written by ' + esc(a.author) : ''}${when ? `<br>Updated ${esc(when)}` : ''}</span></div>
      <div class="abody">${articleMd(a.body)}</div>
      <div class="ahelp"><span>Still need help?</span><button class="btn primary sm a-ask" type="button">${SVG.chat}<span>Ask a question</span></button></div>
      ${a.related && a.related.length ? `<div class="arel"><h3>Related articles</h3><div class="alist">${a.related.map((r) => `<button class="arow" type="button" data-slug="${esc(r.slug)}"><span>${esc(r.title)}</span>${SVG.chev}</button>`).join('')}</div></div>` : ''}</article>`;
    h.querySelector('.a-ask').onclick = () => { this._emit('action', { action: 'help_article_ask', label: a.title, kind: 'question' }); if (this._transcript.length) this.newChat(); else this.showView('chat'); };
    h.querySelectorAll('.arel .arow').forEach((b) => { b.onclick = () => this.openArticle(b.dataset.slug); });
    this._emit('help', { article: a.slug });
  }
  // ---------------------------------------------------------------- history + help
  _setBadge(n) { this._unread = n; const b = this.shadowRoot.querySelector('.hbadge'); b.hidden = !n; b.textContent = String(n); this.shadowRoot.querySelector('.b-history').setAttribute('aria-label', n ? `Conversation history, ${n} unread` : 'Conversation history'); const lb = this.shadowRoot.querySelector('.lbadge'); lb.hidden = !n; lb.textContent = String(n); const tb = this.shadowRoot.querySelector('.tbadge'); if (tb) { tb.hidden = !n; tb.textContent = n ? String(n) : ''; } }
  async _conversations() {
    if (!this.api || (!this._vid && !this.getAttribute('token'))) return { items: [], unread_conversations: 0 };
    try { const r = await fetch(this._url('/conversations'), { headers: this._headers(false) }); return r.ok ? await r.json() : { items: [], unread_conversations: 0, error: true }; } catch { return { items: [], unread_conversations: 0, error: true }; }
  }
  async _refreshBadge() { const d = await this._conversations(); if (!d.error) this._setBadge(d.unread_conversations || 0); return d; }
  async _markRead(sid) { try { await fetch(this._url('/conversations/' + encodeURIComponent(sid) + '/read'), { method: 'POST', headers: this._headers() }); } catch {} }
  // ---------------------------------------------------------------- History: the visitor's bookings (GET /bookings)
  async _loadBookings() {
    if (!this.api || (!this._vid && !this.getAttribute('token'))) return [];
    try { const r = await fetch(this._url('/bookings'), { headers: this._headers(false) }); if (r.ok) { const d = await r.json(); this._bookings = d.items || []; } } catch {}
    return this._bookings || [];
  }
  _paintBookings() {
    const sh = this.shadowRoot, box = sh.querySelector('.bookings'), rows = sh.querySelector('.brows'); if (!box) return; const all = this._bookings || [];
    const q = (this._mquery || '').trim().toLowerCase(); const items = all.filter((b) => !q || (b.schedule_name || '').toLowerCase().includes(q) || (b.label_visitor || '').toLowerCase().includes(q));
    box.hidden = !items.length; if (!items.length) return;
    const chip = (b) => b.state === 'cancelled' ? '<span class="bstate off">Cancelled</span>' : b.state === 'past' ? '<span class="bstate off">Done</span>' : b.status === 'confirmed' ? '<span class="bstate ok">Confirmed</span>' : '<span class="bstate hold">Confirm on Zoom</span>';
    rows.innerHTML = items.map((b) => `<button class="brow ${esc(b.state)}" type="button" role="listitem" data-bid="${esc(String(b.id))}" aria-label="${esc(b.schedule_name)}, ${esc(b.label_visitor)}, ${esc(b.state)}">
        <span class="avatar" aria-hidden="true">${SVG.cal}</span><span class="c"><span class="n">${esc(b.schedule_name)}</span><span class="p">${esc(b.label_visitor)}${b.old_label_visitor ? ' · moved from ' + esc(b.old_label_visitor) : ''}</span></span>${chip(b)}</button>`).join('');
    rows.querySelectorAll('.brow').forEach((el) => { el.onclick = () => { const b = all.find((x) => String(x.id) === el.dataset.bid); if (b) this.openBooking(b); }; });
  }
  openBooking(b) {
    if (this._busy) return; this.showView('chat'); this._clearFollowups();
    const text = `Show my ${b.schedule_name}`, intro = b.state === 'cancelled' ? `This ${b.schedule_name} on ${b.label_visitor} was cancelled.` : b.state === 'past' ? `Your ${b.schedule_name} on ${b.label_visitor} has already taken place.` : b.status === 'confirmed' ? `Your ${b.schedule_name} on ${b.label_visitor} is confirmed.` : `Your ${b.schedule_name} on ${b.label_visitor} is held until you confirm it on Zoom.`;
    const user = this._add('user', '', Date.now()); this._setText(user, text);
    const bot = this._add('bot', '', Date.now()); this._setText(bot, intro);
    this._transcript.push({ role: 'user', text, ts: Date.now() }, { role: 'bot', text: intro, ts: Date.now() });
    this._history.push({ role: 'user', content: text }, { role: 'assistant', content: intro }); this._history = this._history.slice(-12); this._persist(); this._markLast();
    const f = this._bkFlow(bot); f.mode = 'detail'; f.booking = b;
    const pending = b.state === 'upcoming' && b.status !== 'confirmed';
    const rows = [['Meeting', b.schedule_name], ['When', b.label_visitor], ['Was', b.old_label_visitor], ['Duration', b.duration_min ? `${b.duration_min} min · Zoom` : ''], ['Attendees', (b.attendees || []).map((g) => g.name).join(', ')], ['Status', b.state === 'cancelled' ? 'Cancelled' : b.state === 'past' ? 'Done' : b.status === 'confirmed' ? 'Confirmed' : 'Held, confirm on Zoom']].filter((r) => r[1]);
    f.card.innerHTML = `<div class="bk bdetail"><div class="sumbox">${rows.map(([k, v]) => `<div class="sumrow"><span>${k}</span><b>${esc(v)}</b></div>`).join('')}</div>
      <div class="hrow" style="margin-top:8px">${b.state === 'upcoming' && pending && b.handoff_url ? `<a class="btn primary" href="${esc(b.handoff_url)}" target="_blank" rel="noopener">Confirm on Zoom ${SVG.ext}</a>` : ''}${b.state === 'upcoming' && b.join_url ? `<a class="btn primary" href="${esc(b.join_url)}" target="_blank" rel="noopener">${SVG.video}Join Zoom</a>` : ''}${b.state === 'upcoming' && b.ics_url ? `<a class="btn" href="${esc(b.ics_url)}" download>${SVG.cal}Add to calendar</a>` : ''}
        ${b.can_reschedule ? `<button type="button" class="btn bd-move">${SVG.clock}Reschedule</button>` : ''}${b.can_cancel ? `<button type="button" class="btn bd-cancel">${SVG.close}Cancel</button>` : ''}${b.state !== 'upcoming' ? `<button type="button" class="btn primary bd-again">${SVG.cal}Book again</button>` : ''}</div></div>`;
    const up = { id: b.id, schedule_slug: b.schedule_slug, schedule_name: b.schedule_name, label_visitor: b.label_visitor, duration_min: b.duration_min, method: b.method, can_reschedule: !!b.can_reschedule, can_cancel: !!b.can_cancel };
    const mv = f.card.querySelector('.bd-move'); if (mv) mv.onclick = () => this.startReschedule(up, 'Reschedule my call');
    const cx = f.card.querySelector('.bd-cancel'); if (cx) cx.onclick = () => this.startCancel(up, 'Cancel my call');
    const ag = f.card.querySelector('.bd-again'); if (ag) ag.onclick = () => this.startBooking(b.schedule_slug || null, 'Book again');
    this._emit('booking', { status: 'opened', bookingId: b.id, schedule: b.schedule_slug || null });
    requestAnimationFrame(() => this._reveal(f.card));
  }
  async _renderConversations() {
    this._loadBookings().then(() => this._paintBookings());
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
  _renderContact(h) {
    const sc = this._shortcut(); const listen = this._canListen();
    const common = ((this._cfg && Array.isArray(this._cfg.suggestions)) ? this._cfg.suggestions : []).filter((s) => s && !BOOK_RE.test(s));
    const qs = (common.length ? common : [ACTIONS.explore.ask, ACTIONS.about.ask, ACTIONS.usecases.ask].map((q) => this._b(q))).slice(0, 5);
    const item = (cls, icon, label, small, tail) => `<span class="ai">${icon}</span><span class="al">${label}<small>${small}</small></span>${tail || SVG.chev}`;
    h.innerHTML = `<h3>Get in touch</h3><div class="acts">
        <button class="act book h-book" type="button">${item('', SVG.cal, 'Book a meeting', 'Pick a time that suits you, right here')}</button>
        <button class="act h-human" type="button">${item('', SVG.user, 'Talk to a person', 'Leave a message, the team replies by email')}</button>
        ${listen ? `<button class="act h-voice" type="button">${item('', SVG.wave, 'Voice conversation', 'Talk with Deep hands-free')}</button>` : ''}
        ${sc ? `<a class="act" href="${esc(sc.href)}" target="_blank" rel="noopener">${item('', SVG.video, esc(sc.label), esc(host(sc.href)) + ' · opens in a new tab', SVG.ext)}</a>` : ''}
      </div>
      <h3>What Deep can do</h3><ul class="caplist">
        <li>${SVG.checkc}<span>${esc(this._b('Answer questions about LakeB2B, with links to the pages it used'))}</span></li>
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
    meta.innerHTML = role === 'bot' ? `<span class="vh">${esc(this.botName)} said, </span>${esc(this.botName)} • AI Agent • ${when}` : `<span class="vh">You said, </span>${when}`; col.appendChild(meta);
    row.appendChild(col); this.$log.appendChild(row); this._stick = stick; this._scroll(); return d;
  }
  _markAgent(el, author, ts) {  // a reply from the team (app/team.py): same bubble, says who wrote it
    const row = el.closest('.row'); row.classList.add('agent'); const meta = row.querySelector('.meta'); const who = esc(author || 'Deep');
    if (meta) meta.innerHTML = `<span class="vh">${who} from the team said, </span><b>${who}</b> • Team • ${relShort(ts ? new Date(ts).getTime() : Date.now())}`;
  }
  _addAgent(m) {
    const ts = new Date(m.ts).getTime() || Date.now(); const el = this._add('bot', '', ts); this._markAgent(el, m.author, ts); this._setText(el, m.text);
    this._transcript.push({ role: 'bot', agent: true, author: m.author || 'Deep', text: m.text, ts, aid: m.id });
    this._history.push({ role: 'assistant', content: `${m.author || 'Deep'} (from the team): ${m.text}` }); this._history = this._history.slice(-12);
    return el;
  }
  // while the conversation is with the team: new replies appear here, and polling continues every 12 s while open
  async _teamCheck() {
    clearTimeout(this._teamT); const sid = this._sid; if (!this.api || !sid || !this._transcript.length) return;
    const after = this._transcript.reduce((a, m) => Math.max(a, m.aid || 0), 0); let d = null;
    try { const r = await fetch(this._url('/conversations/' + encodeURIComponent(sid) + '/updates?after=' + after), { headers: this._headers(false) }); if (r.ok) d = await r.json(); } catch {}
    if (!d || sid !== this._sid) return;
    this._teamStatus = d.team_status || null; if (d.rating) this._rated = true;
    const fresh = (d.messages || []).filter((m) => !this._transcript.some((t) => t.aid === m.id));
    fresh.forEach((m) => this._addAgent(m));
    if (fresh.length) { this._persist(); this._markLast(); this._announce(`${fresh[fresh.length - 1].author || 'Deep'} from the team replied`);
      if (this.hasAttribute('open') && this._view === 'chat') this._markRead(sid).then(() => this._refreshBadge()); else this._refreshBadge(); }
    if ((this._teamStatus === 'waiting' || this._teamStatus === 'replied') && this.hasAttribute('open')) this._teamT = setTimeout(() => this._teamCheck(), 12000);
  }
  // Fin-style rating of the whole conversation: offered once, after two answers and a quiet moment
  _maybeRate() {
    clearTimeout(this._rateT); this._lastAct = Date.now();
    this._rateT = setTimeout(() => {
      const sid = this._sid, answers = this._transcript.filter((m) => m.role === 'bot' && m.mid && !m.agent && !m.err).length;
      let done = this._rated; try { done = done || localStorage.getItem(this._key('rated:' + sid)); } catch {}
      // only after a plain answer: never on top of a booking picker, a form or a card the visitor is still using
      const last = [...this.$log.querySelectorAll('.row.bot')].pop();
      if (!last || last.querySelector('.hascard, .card, form') || last.classList.contains('wide')) return;
      if (done || answers < 2 || this._busy || !this.hasAttribute('open') || this._view !== 'chat' || Date.now() - this._lastAct < 55000 || this.$log.querySelector('.rcard')) return;
      this._renderRating(sid);
    }, 60000);
  }
  _renderRating(sid) {
    // its own row (not a bot message), so it never counts as the assistant's last answer
    const row = document.createElement('div'); row.className = 'row rate'; row.dataset.role = 'rate'; const el = document.createElement('div'); el.className = 'col'; row.appendChild(el);
    const faces = [['😞', 'Very bad'], ['😕', 'Bad'], ['😐', 'Okay'], ['🙂', 'Good'], ['😍', 'Great']];
    const c = document.createElement('div'); c.className = 'rcard card';
    c.innerHTML = `<div class="bk-t"><b>How was this conversation?</b></div><div class="faces" role="group" aria-label="Rate this conversation">${faces.map((f, i) => `<button type="button" class="face" data-s="${i + 1}" aria-label="${i + 1} of 5: ${f[1]}" title="${f[1]}">${f[0]}</button>`).join('')}</div><p class="note" role="status"></p>`;
    const note = c.querySelector('.note');
    const send = async (score, text) => { try { const r = await fetch(this._url('/conversations/' + encodeURIComponent(sid) + '/rating'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ score, note: text || null }) }); return r.ok; } catch { return false; } };
    c.querySelectorAll('.face').forEach((b) => b.onclick = async () => {
      const score = +b.dataset.s; c.querySelectorAll('.face').forEach((x) => { x.classList.toggle('on', x === b); x.disabled = true; });
      if (!(await send(score))) { note.textContent = "Couldn't save that. Please try again."; c.querySelectorAll('.face').forEach((x) => x.disabled = false); return; }
      this._rated = true; try { localStorage.setItem(this._key('rated:' + sid), String(score)); } catch {} this._emit('rating', { score });
      note.textContent = 'Thanks for rating the conversation.';
      if (score <= 3) { const f = document.createElement('form'); f.className = 'rrow'; f.innerHTML = '<input class="inp" maxlength="1000" placeholder="What could be better? (optional)" aria-label="What could be better?"><button class="btn primary sm" type="submit">Send</button>';
        f.onsubmit = async (e) => { e.preventDefault(); const t = f.querySelector('input').value.trim(); if (!t) return; f.remove(); note.textContent = (await send(score, t)) ? 'Thanks, that helps us improve.' : "Couldn't send that note."; };
        c.appendChild(f); }
    });
    el.appendChild(c); this.$log.appendChild(row); this._stick = true; this._scroll();
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
        b.onclick = async () => { if (rating === 1) { if (await this._rate(mid, 1)) mark(1); return; } this._fbPopover(b, async (reason) => { if (await this._rate(mid, -1, reason)) { mark(-1); this._offerEmail(el); } }); };
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
  _frustrationCard(bot) {  // the visitor seems frustrated (app/mood.py): a person can take over, once per chat
    if (!bot || !bot.isConnected || bot.parentElement.querySelector('.frus')) return; const host = this._hostShort();
    const c = document.createElement('div'); c.className = 'frus'; c.setAttribute('role', 'group'); c.setAttribute('aria-label', 'Get help from ' + host);
    c.innerHTML = `<p><b>Sorry this has been frustrating.</b> ${esc(host)} can take it from here and reply to you directly.</p>
      <div class="frow"><button type="button" class="btn primary sm f-mail">${SVG.mail}Email ${esc(host)}</button><button type="button" class="btn ghost sm f-cal">${SVG.cal}Book a call</button></div>`;
    c.querySelector('.f-mail').onclick = () => { this._emit('action', { action: 'frustration_email' }); c.remove(); this._renderHandover(bot, ''); };
    c.querySelector('.f-cal').onclick = () => { this._emit('action', { action: 'frustration_call' }); c.remove(); this.startBooking(); };
    bot.parentElement.appendChild(c); this._scroll();
  }
  _buyingCard(bot, ev) {  // a buying moment (app/intent.py): a call with Deep while they are still here, once per chat
    if (!bot || !bot.isConnected || bot.parentElement.querySelector('.frus')) return; const host = this._hostShort(); const d = ev.details || {};
    const what = d.volume ? `for ${d.volume}` : 'for what you need';
    const c = document.createElement('div'); c.className = 'frus buy'; c.setAttribute('role', 'group'); c.setAttribute('aria-label', 'Talk to ' + host);
    c.innerHTML = `<p><b>Want exact options and pricing ${esc(what)}?</b> ${esc(host)} can walk you through it on a short call${d.timeline ? ', in good time for your deadline' : ''}.</p>
      <div class="frow"><button type="button" class="btn primary sm f-cal">${SVG.cal}Book a call</button><button type="button" class="btn ghost sm f-mail">${SVG.mail}Email ${esc(host)}</button></div>`;
    c.querySelector('.f-cal').onclick = () => { this._emit('action', { action: 'buying_call' }); c.remove(); this.startBooking(); };
    c.querySelector('.f-mail').onclick = () => { this._emit('action', { action: 'buying_email' }); c.remove(); this._renderHandover(bot, ''); };
    bot.parentElement.appendChild(c); this._scroll();
  }
  _fitCard(bot, ev) {  // wrong fit (app/intent.py): the route the console set for job seekers or sellers
    if (!bot || !bot.isConnected || !/^(https?:|mailto:)/i.test(ev.link || '')) return;
    const f = document.createElement('div'); f.className = 'followups fit'; f.setAttribute('role', 'group'); f.setAttribute('aria-label', 'Where to go instead');
    const a = document.createElement('a'); a.className = 'fu'; a.href = ev.link; if (!/^mailto:/i.test(ev.link)) { a.target = '_blank'; a.rel = 'noopener'; }
    a.innerHTML = `${/^mailto:/i.test(ev.link) ? SVG.mail : SVG.ext}<span>${esc(ev.button || 'Open')}</span>`;
    a.onclick = () => this._emit('action', { action: 'wrong_fit_link', label: ev.kind });
    f.appendChild(a); bot.parentElement.appendChild(f); this._scroll();
  }
  _applyExtras() {  // menu items and the Home card for features the server switched off (GET /widget-config)
    const c = this._cfg || {}, sh = this.shadowRoot;
    sh.querySelectorAll('[data-act="compare"], .cmpc').forEach((x) => { x.hidden = c.compare === false; });
    const m = sh.querySelector('[data-act="email"]'); if (m) m.hidden = c.chat_email === false;
  }
  // ---------------------------------------------------------------- compare side by side (app/compare.py)
  async openCompare() {
    this.showView('chat'); if (this._busy) return;
    this.$log.querySelectorAll('.cmp').forEach((x) => x.closest('.row') && x.closest('.row').remove());
    let d = null; try { const r = await fetch(this._url('/compare/options')); d = r.ok ? await r.json() : null; } catch {}
    const names = (d && d.companies) || [], aspects = (d && d.aspects) || [];
    const bot = this._add('bot', ''); bot.classList.add('hascard'); bot.closest('.row').classList.add('wide');
    const f = document.createElement('form'); f.className = 'cmp card'; f.noValidate = true; const picked = []; let aspect = '';
    f.innerHTML = `<div class="bk-t"><b>Compare side by side</b><small>Pick two or three, and what to compare them on</small></div>
      ${names.length ? `<div class="cmp-l">Companies</div><div class="cmp-chips co" role="group" aria-label="Companies">${names.map((n) => `<button type="button" class="chip" aria-pressed="false" data-v="${esc(n)}">${esc(n)}</button>`).join('')}</div>` : ''}
      <div class="cmp-l">Or type your own</div><input class="inp" name="own" maxlength="120" placeholder="e.g. intent data vs technographics" aria-label="Things to compare">
      ${aspects.length ? `<div class="cmp-l">Compare on</div><div class="cmp-chips as" role="group" aria-label="Compare on">${aspects.map((n) => `<button type="button" class="chip" aria-pressed="false" data-v="${esc(n)}">${esc(n)}</button>`).join('')}</div>` : ''}
      <button class="btn primary block" type="submit" disabled>${SVG.layers}Compare</button><p class="note" role="status">Answers come from each company's own pages.</p>`;
    const go = f.querySelector('button[type=submit]'), own = f.elements.own, note = f.querySelector('.note');
    const sync = () => { const typed = /\S+\s+(vs\.?|versus|and|or)\s+\S+/i.test(own.value.trim()); go.disabled = !(picked.length >= 2 || typed);
      note.textContent = picked.length === 1 && !typed ? 'Pick one more.' : picked.length >= 3 ? 'Three is the most that fits a table.' : "Answers come from each company's own pages."; };
    f.querySelectorAll('.co .chip').forEach((b) => b.onclick = () => { const v = b.dataset.v, i = picked.indexOf(v);
      if (i >= 0) picked.splice(i, 1); else if (picked.length < 3) picked.push(v); else return;
      b.setAttribute('aria-pressed', String(i < 0)); sync(); });
    f.querySelectorAll('.as .chip').forEach((b) => b.onclick = () => { const on = b.getAttribute('aria-pressed') !== 'true';
      f.querySelectorAll('.as .chip').forEach((x) => x.setAttribute('aria-pressed', 'false')); b.setAttribute('aria-pressed', String(on)); aspect = on ? b.dataset.v : ''; });
    own.addEventListener('input', sync);
    f.onsubmit = (e) => { e.preventDefault(); if (go.disabled) return;
      const typed = own.value.trim(); const what = picked.length >= 2 ? (picked.length === 2 ? picked.join(' and ') : picked.slice(0, -1).join(', ') + ' and ' + picked[picked.length - 1]) : typed;
      const q = `Compare ${what} side by side` + (aspect ? `: ${aspect.toLowerCase()}` : '');
      this._emit('action', { action: 'compare', label: q }); bot.closest('.row').remove(); this._send(q); };
    bot.appendChild(f); this._emit('action', { action: 'compare_open' });
    requestAnimationFrame(() => { this._stick = true; this._scroll(); });
  }
  // ---------------------------------------------------------------- email me this chat (POST /chat/email, app/chat_email.py)
  emailChat() {
    this.showView('chat');
    if (!this._transcript.some((m) => m.role === 'bot' && m.text && !m.err)) { this._toast('Ask a question first, then you can email the chat to yourself.'); return; }
    this.$log.querySelectorAll('.cmail').forEach((x) => x.closest('.row') && x.closest('.row').remove());
    const me = this._me || {}; const known = !!(me.signed_in && me.verified && me.email); const host = this._hostShort();
    const bot = this._add('bot', ''); bot.classList.add('hascard'); bot.closest('.row').classList.add('wide');
    const f = document.createElement('form'); f.className = 'cmail card'; f.noValidate = true; const id = 'm' + Math.random().toString(36).slice(2, 7);
    f.innerHTML = `<div class="bk-t"><b>Email me this chat</b><small>The whole conversation, with the pages each answer used</small></div>
      ${known ? '' : `<div class="field"><label for="${id}e">Your email</label><input class="inp" id="${id}e" name="email" type="email" maxlength="200" required autocomplete="email" inputmode="email"></div>`}
      <button class="btn primary block" type="submit">${SVG.mail}Send it to ${known ? esc(me.email) : 'me'}</button>
      <p class="note" role="status">${esc(host)} may follow up on your questions by email. <a href="${esc((this.shadowRoot.querySelector('.privacy') || {}).href || '#')}" target="_blank" rel="noopener">Privacy</a></p>`;
    const em = f.elements.email; if (em) em.value = me.email || store.get(this._key('cmail')) || '';
    const note = f.querySelector('.note'), b = f.querySelector('button[type=submit]');
    f.onsubmit = async (e) => { e.preventDefault(); const email = known ? me.email : em.value.trim();
      if (!known && !EMAIL_RE.test(email)) { em.setAttribute('aria-invalid', 'true'); note.className = 'note warn'; note.textContent = 'Please enter a valid email address.'; em.focus(); return; }
      b.disabled = true; b.classList.add('loading'); note.className = 'note'; note.textContent = 'Sending…';
      try { const r = await fetch(this._url('/chat/email'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ session_id: this._sid, email, name: me.name || undefined }) });
        const d = r.ok ? await r.json() : null;
        if (d && d.ok) { if (!known) store.set(this._key('cmail'), email); f.classList.add('sent');
          f.innerHTML = `<div class="booked"><div class="bk-ok" tabindex="-1"><svg class="chk" viewBox="0 0 30 30" aria-hidden="true"><circle cx="15" cy="15" r="13"/><path d="M9 15.5l4 4 8-8"/></svg><span>Chat sent to ${esc(d.to)}</span></div><p class="note">It should arrive in a minute; check your spam folder if it doesn't. Reply to it to reach ${esc(host)}.</p></div>`;
          this._emit('action', { action: 'chat_emailed' }); this._scroll(); return; }
        let msg = "Couldn't send right now. Please try again.";
        if (r.status === 422) { try { msg = (await r.json()).detail || 'Please check the email address.'; } catch { msg = 'Please check the email address.'; } }
        else if (r.status === 429) msg = 'This chat was emailed a few times already. Please try again later.';
        else if (r.status === 404) msg = 'Ask a question first, then you can email the chat to yourself.';
        b.disabled = false; b.classList.remove('loading'); note.className = 'note warn'; note.textContent = msg.charAt(0).toUpperCase() + msg.slice(1) + (/[.!?]$/.test(msg) ? '' : '.'); }
      catch { b.disabled = false; b.classList.remove('loading'); note.className = 'note warn'; note.textContent = 'Connection problem. Please try again.'; } };
    bot.appendChild(f); this._emit('action', { action: 'chat_email_form' });
    requestAnimationFrame(() => { this._stick = true; this._scroll(); if (em && !this._coarse) em.focus({ preventScroll: true }); });
  }
  _offerEmail(bot) {  // "not helpful": offer to email the host, unless a form or this offer is already there
    if (!bot || !bot.isConnected || bot.querySelector('.hform') || bot.parentElement.querySelector('.followups.email')) return;
    this._followups(bot, [{ icon: 'mail', label: `Email ${(this._cfg && (this._cfg.host_short || this._cfg.host_name)) || 'Deep'} instead`, kind: 'handover', fn: () => this._renderHandover(bot, '') }]);
    const f = bot.parentElement.querySelector('.followups:last-child'); if (f) f.classList.add('email');
  }
  _followups(bot, items) {  // contextual next steps under one answer; never generic, never more than two
    if (!items.length) return; const f = document.createElement('div'); f.className = 'followups'; f.setAttribute('role', 'group'); f.setAttribute('aria-label', 'Suggested next steps');
    items.slice(0, 2).forEach((x) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'fu'; b.innerHTML = `${SVG[x.icon] || SVG.spark}<span>${esc(x.label)}</span>`;
      b.onclick = () => { this._emit('action', { action: 'followup', label: x.label, kind: x.kind || 'question' }); f.remove(); x.fn(); }; f.appendChild(b); });
    bot.parentElement.appendChild(f); this._scroll();
  }
  _answerFollowups(bot, question, answer, nSources) {
    if (this._nudged || !answer || !nSources) return [];
    if (CMP_RE.test(question) && !(this._cfg && this._cfg.compare === false)) return [{ icon: 'layers', label: 'Compare something else', kind: 'compare', fn: () => this.openCompare() }];
    const t = (question + ' ' + answer).toLowerCase(); let item = null;
    if (/\b(pric(e|ing)|cost|quote|demo|trial|walkthrough|how (does|do) (it|this|that) work)\b/.test(t)) item = { icon: 'play', label: 'See it in a walkthrough', kind: 'booking', fn: () => this.startBooking('walkthrough', 'Book a product walkthrough') };
    else if (/\b(data|solution|platform|product|intent|leads?|campaigns?|gtm|go-to-market|abm|prospect)/.test(t) && this._transcript.filter((m) => m.role === 'user').length >= 2) item = { icon: 'user', label: 'Talk to an expert', kind: 'booking', fn: () => this.startBooking(null, 'Talk to an expert') };
    if (item) this._nudged = true;
    return item ? [item] : [];
  }
  _persist() { store.set(this._key('tx:' + this._sid), JSON.stringify(this._transcript.slice(-40))); this._syncHome(); }
  _restore() {
    try { this._transcript = JSON.parse(store.get(this._key('tx:' + this._sid)) || '[]'); } catch { this._transcript = []; }
    this._syncHome();
    this.$log.innerHTML = '';
    if (!this._transcript.length) { this._history = []; this._renderWelcome(); this.$log.scrollTop = 0; return; }
    this._transcript.forEach((m) => { const el = this._add(m.role === 'user' ? 'user' : 'bot', '', m.ts); if (m.agent) { this._markAgent(el, m.author, m.ts); this._setText(el, m.text); return; } this._setText(el, m.text, m.sources); if (m.role === 'bot') { if (m.err) el.classList.add('err'); this._addSources(el, m.sources); this._addTools(el, () => plain(m.text), null, m.mid, m.fb); if (m.ui) this._mountUi(el, m.ui, m); } });
    this._history = this._transcript.map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.agent ? `${m.author || 'Deep'} (from the team): ${m.text}` : m.text })).slice(-12);
    this._markLast(); this._scroll(true);
  }
  // ---------------------------------------------------------------- in-chat booking (docs/BOOKING.md)
  // One card per bot message walks through type -> time -> details -> review -> done. The state lives on the card, so
  // going back keeps every choice; nothing is booked until POST /booking/confirm answers "confirmed" / "pending_zoom".
  async startBooking(prefer, label) {
    if (this._busy) return; this._track(); this.showView('chat'); this._clearFollowups();  // _track: a retry point for a lost beacon
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
    const f = { el, card, step: 'type', types: null, schedule: null, avail: null, day: null, slot: null, who: null, prefill: {}, prefer: null, notice: null, alts: null, mode: 'book', booking: null };
    el._bk = f; return f;
  }
  _bkGo(f, step, focus = true) { f.step = step; this._bkRender(f, focus); }
  _bkRender(f, focus) {
    const STEPS = f.mode === 'reschedule' ? RS_STEPS : BK_STEPS, TITLES = f.mode === 'reschedule' ? RS_TITLES : BK_TITLES;
    const c = f.card, i = STEPS.indexOf(f.step); c.innerHTML = '';
    if (f.step !== 'done') {
      const head = document.createElement('div'); head.className = 'bk-head';
      head.innerHTML = `${i > 0 ? `<button type="button" class="bk-back" aria-label="Back to ${TITLES[STEPS[i - 1]].toLowerCase()}" title="Back">${SVG.back}</button>` : ''}<div class="bk-t"><b tabindex="-1">${TITLES[f.step]}</b><span>Step ${i + 1} of ${STEPS.length}</span></div>`;
      const back = head.querySelector('.bk-back'); if (back) back.onclick = () => { f.notice = null; this._bkGo(f, STEPS[i - 1]); if (STEPS[i - 1] === 'type' && !f.types) this._bkLoadTypes(f); if (STEPS[i - 1] === 'time' && !f.avail) this._bkLoadAvail(f); };
      c.appendChild(head); c.insertAdjacentHTML('beforeend', `<div class="bk-prog" aria-hidden="true">${STEPS.map((s, j) => `<i class="${j <= i ? 'on' : ''}"></i>`).join('')}</div>`);
    }
    if (f.notice) c.insertAdjacentHTML('beforeend', `<div class="banner" role="alert">${SVG.alert}<span>${esc(f.notice)}</span></div>`);
    const body = document.createElement('div'); body.className = 'bk'; c.appendChild(body);
    ({ type: () => this._bkType(f, body), time: () => this._bkTime(f, body), details: () => this._bkDetails(f, body), review: () => (f.mode === 'reschedule' ? this._rsReview(f, body) : this._bkReview(f, body)), done: () => this._bkDone(f, body) })[f.step]();
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
    body.insertAdjacentHTML('beforeend', f.mode === 'reschedule' && f.booking ? `<div class="ahead"><b>${esc(s.name || 'Meeting')}</b><span>Currently ${esc(f.booking.label_visitor)} · pick the new time below</span></div>`
      : `<div class="ahead"><b>${esc(s.name || 'Meeting')}</b><span>${s.duration_min ? s.duration_min + ' min · ' : ''}Zoom video call${s.description ? ' · ' + esc(s.description) : ''}</span></div>`);
    const d = f.avail;
    if (!d) { body.insertAdjacentHTML('beforeend', '<div class="sk" style="padding:0"><span class="l"><i></i><i></i></span></div><p class="note" role="status">Loading open times…</p>'); return; }
    if (!d.ok) {
      body.insertAdjacentHTML('beforeend', `<div class="banner">${SVG.alert}<span>${esc(d.message || "Availability couldn't be loaded right now.")}</span></div><div class="hrow"><button type="button" class="btn retry">${SVG.reset}<span>Try again</span></button>${d.fallback_link ? `<a class="btn" href="${esc(d.fallback_link)}" target="_blank" rel="noopener">Open the scheduler ${SVG.ext}</a>` : ''}</div>`);
      body.querySelector('.retry').onclick = () => this._bkLoadAvail(f); return;
    }
    const pick = (sl) => { f.slot = sl; f.notice = null; this._bkGo(f, f.mode === 'reschedule' ? 'review' : 'details'); this._emit('action', { action: f.mode === 'reschedule' ? 'reschedule_time' : 'booking_time', label: sl.label_visitor, kind: 'booking' }); };
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
        <div class="guests"><div class="glabel">Attendees <span>(optional · they get the invite too)</span></div><div class="glist" role="list" aria-label="Attendees"></div><button type="button" class="linkbtn addg">+ Add attendee</button></div>
        <button class="btn primary block" type="submit">Continue ${SVG.chev}</button>
      </form>`;
    const form = body.querySelector('form'), field = (n) => form.elements[n];
    if (!known) { field('name').value = w.name ?? p.name ?? me.name ?? ''; field('email').value = w.email ?? p.email ?? me.email ?? ''; }
    field('company').value = w.company ?? p.company ?? ''; field('notes').value = w.notes ?? p.reason ?? p.notes ?? '';
    const glist = body.querySelector('.glist'), addg = body.querySelector('.addg'), MAXG = 5;
    const addRow = (g = {}) => { if (glist.children.length >= MAXG) return; const r = document.createElement('div'); r.className = 'grow'; r.setAttribute('role', 'listitem'); const k = glist.children.length + 1;
      r.innerHTML = `<input class="inp gname" maxlength="120" placeholder="Name" aria-label="Attendee ${k} name" autocomplete="off"><input class="inp gemail" type="email" maxlength="200" placeholder="Email" aria-label="Attendee ${k} email" inputmode="email" autocomplete="off"><button type="button" class="gx" aria-label="Remove attendee ${k}" title="Remove">${SVG.close}</button><span class="ferr gerr" hidden></span>`;
      r.querySelector('.gname').value = g.name || ''; r.querySelector('.gemail').value = g.email || '';
      r.querySelector('.gx').onclick = () => { r.remove(); addg.hidden = glist.children.length >= MAXG; f.who = read(); addg.focus(); };
      glist.appendChild(r); addg.hidden = glist.children.length >= MAXG; };
    (w.attendees || []).forEach((g) => addRow(g));
    addg.onclick = () => { addRow(); const last = glist.lastElementChild; if (last) last.querySelector('.gname').focus(); };
    const guests = () => [...glist.children].map((r) => ({ name: r.querySelector('.gname').value.trim(), email: r.querySelector('.gemail').value.trim() })).filter((g) => g.name || g.email);
    const read = () => ({ name: known ? (me.name || '') : field('name').value.trim(), email: known ? me.email : field('email').value.trim(), company: field('company').value.trim(), notes: field('notes').value.trim(), attendees: guests() });
    form.addEventListener('input', () => { f.who = read(); });
    body.querySelector('.chg').onclick = () => { f.who = read(); this._bkGo(f, 'time'); if (!f.avail) this._bkLoadAvail(f); };
    form.onsubmit = (e) => { e.preventDefault(); const who = read(); f.who = who; let bad = null;
      const err = (n, msg) => { const el = field(n); if (!el) return; const fe = el.parentElement.querySelector('.ferr'); el.setAttribute('aria-invalid', String(!!msg)); fe.hidden = !msg; fe.textContent = msg || ''; if (msg) { fe.id = 'e-' + n; el.setAttribute('aria-describedby', fe.id); if (!bad) bad = el; } else el.removeAttribute('aria-describedby'); };
      if (!known) { err('name', who.name.length < 2 ? 'Please enter your name.' : null); err('email', !EMAIL_RE.test(who.email) ? 'Please enter a valid email address.' : null); }
      const seen = new Set([(who.email || '').toLowerCase()]);
      [...glist.children].forEach((r) => { const n = r.querySelector('.gname'), m = r.querySelector('.gemail'), fe = r.querySelector('.gerr'); const nv = n.value.trim(), mv = m.value.trim().toLowerCase();
        if (!nv && !mv) { r.remove(); return; }
        const msg = nv.length < 2 ? "Add this attendee's name." : !EMAIL_RE.test(mv) ? 'Enter a valid email for this attendee.' : seen.has(mv) ? (mv === (who.email || '').toLowerCase() ? "That's your own email; add only the other people." : 'This email is already added.') : null;
        seen.add(mv); fe.hidden = !msg; fe.textContent = msg || ''; (nv.length < 2 ? n : m).setAttribute('aria-invalid', String(!!msg)); if (msg && !bad) bad = nv.length < 2 ? n : m; });
      addg.hidden = glist.children.length >= MAXG; f.who = read();
      if (bad) { bad.focus(); return; }
      this._bkGo(f, 'review'); };
  }
  _bkReview(f, body) {
    const s = f.schedule || {}, w = f.who || {};
    const rows = [['Meeting', s.name], ['When', f.slot.label_visitor], ['Duration', s.duration_min ? `${s.duration_min} min · Zoom` : 'Zoom'], ['Name', w.name], ['Email', w.email], ['Company', w.company], ['Attendees', (w.attendees || []).map((g) => `${g.name} (${g.email})`).join(', ')], ['Topic', w.notes && trunc(w.notes, 120)]].filter((r) => r[1]);
    body.innerHTML = `<div class="sumbox">${rows.map(([k, v]) => `<div class="sumrow"><span>${k}</span><b>${esc(v)}</b></div>`).join('')}</div>
      <button class="btn primary block confirm" type="button">Confirm booking</button><p class="note sstat" role="status">Nothing is booked until you confirm.</p>`;
    const btn = body.querySelector('.confirm'); btn.onclick = () => this._bkConfirm(f, btn, body.querySelector('.sstat'));
  }
  async _bkConfirm(f, btn, stat) {
    const back = f.card.querySelector('.bk-back'); const lock = (on) => { btn.disabled = on; btn.classList.toggle('loading', on); btn.textContent = on ? 'Booking…' : 'Confirm booking'; if (back) back.disabled = on; };
    lock(true); stat.className = 'note sstat'; stat.textContent = this._cfg.booking_mode === 'browser' ? 'Booking it on Zoom for you. This can take a minute or two; please keep this open…' : 'Checking the time with Zoom and booking…';
    const s = f.schedule, w = f.who || {}; let res = null, status = 0; const sid = this._sid, beacon = this._tracked() ? undefined : this._beaconData();
    try { const r = await fetch(this._url('/booking/confirm'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ schedule_slug: s.slug, start: f.slot.start_iso, name: w.name, email: w.email, company: w.company, notes: w.notes, timezone: this.tz, attendees: w.attendees || [], beacon }) }); status = r.status; res = r.ok ? await r.json() : null; if (beacon && r.ok) store.set(this._key('tracked'), sid); } catch {}
    const fail = (msg) => { lock(false); stat.className = 'note sstat warn'; stat.textContent = msg; };
    if (status === 429) return fail('Too many booking attempts. Please wait a minute and try again. Nothing was booked.');
    if (!res) return fail("Couldn't reach the server. Nothing was booked. Please try again.");
    if (res.status === 'confirmed' || res.status === 'pending_zoom') { f.result = res; this._bkGo(f, 'done'); this._bkBooked(res); return; }
    if (res.status === 'slot_taken') { f.notice = res.message || 'That time was just taken. Please pick another.'; f.alts = res.alternatives || null; f.slot = null; this._bkGo(f, 'time'); this._bkLoadAvail(f); this._emit('booking', { status: 'slot_taken', schedule: s.slug }); return; }
    if (res.status === 'unavailable') { fail(res.message || "The scheduler isn't responding right now. Nothing was booked."); if (res.fallback_link) stat.insertAdjacentHTML('afterend', `<div class="hrow"><a class="btn" href="${esc(res.fallback_link)}" target="_blank" rel="noopener">Book directly on Zoom ${SVG.ext}</a></div>`); this._emit('booking', { status: 'unavailable', schedule: s.slug }); return; }
    if (res.status === 'invalid') { f.notice = res.message || 'Please check your details.'; this._bkGo(f, 'details'); return; }
    fail((res.message || "That didn't work.") + ' Nothing was booked; please try again.');
  }
  // ---------------------------------------------------------------- rescheduling an existing booking (docs/BROWSER_BOOKING.md)
  startReschedule(up, label) {
    if (this._busy || !up || !up.id) return; this.showView('chat'); this._clearFollowups();
    const text = label || 'Reschedule my call', intro = `Sure. Your ${up.schedule_name} is on ${up.label_visitor}. Pick a new time and I'll move it.`;
    const user = this._add('user', '', Date.now()); this._setText(user, text);
    const bot = this._add('bot', '', Date.now()); this._setText(bot, intro);
    this._transcript.push({ role: 'user', text, ts: Date.now() }, { role: 'bot', text: intro, ts: Date.now() });
    this._history.push({ role: 'user', content: text }, { role: 'assistant', content: intro }); this._history = this._history.slice(-12); this._persist(); this._markLast();
    this._emit('booking', { status: 'reschedule_started', bookingId: up.id, schedule: up.schedule_slug || null });
    const f = this._bkFlow(bot); f.mode = 'reschedule'; f.booking = up; f.schedule = { slug: up.schedule_slug, name: up.schedule_name, duration_min: up.duration_min };
    this._bkGo(f, 'time'); this._bkLoadAvail(f);
  }
  _rsReview(f, body) {
    const s = f.schedule || {}, u = f.booking || {};
    const rows = [['Meeting', s.name], ['Currently', u.label_visitor], ['New time', f.slot.label_visitor], ['Duration', s.duration_min ? `${s.duration_min} min · Zoom` : 'Zoom']].filter((r) => r[1]);
    body.innerHTML = `<div class="sumbox">${rows.map(([k, v]) => `<div class="sumrow"><span>${k}</span><b>${esc(v)}</b></div>`).join('')}</div>
      <button class="btn primary block confirm" type="button">Move my call</button><p class="note sstat" role="status">Your current time stays until you confirm.</p>`;
    const btn = body.querySelector('.confirm'); btn.onclick = () => this._rsConfirm(f, btn, body.querySelector('.sstat'));
  }
  async _rsConfirm(f, btn, stat) {
    const back = f.card.querySelector('.bk-back'); const lock = (on) => { btn.disabled = on; btn.classList.toggle('loading', on); btn.textContent = on ? 'Moving…' : 'Move my call'; if (back) back.disabled = on; };
    lock(true); stat.className = 'note sstat'; stat.textContent = f.booking.method === 'browser' ? 'Moving it on Zoom for you. This can take a minute or two; please keep this open…' : 'Updating your held time…';
    let res = null, status = 0;
    try { const r = await fetch(this._url(`/booking/${encodeURIComponent(f.booking.id)}/reschedule`), { method: 'POST', headers: this._headers(), body: JSON.stringify({ start: f.slot.start_iso, timezone: this.tz }) }); status = r.status; res = r.ok ? await r.json() : null; } catch {}
    const fail = (msg) => { lock(false); stat.className = 'note sstat warn'; stat.textContent = msg; };
    if (status === 429) return fail('Too many attempts. Please wait a minute and try again. Your current time still stands.');
    if (status === 404) return fail("I couldn't find that booking on this device. Use the link in your confirmation email instead.");
    if (!res) return fail("Couldn't reach the server. Your current time still stands. Please try again.");
    if (res.status === 'rescheduled' || res.status === 'pending_zoom') { f.result = res; this._bkGo(f, 'done'); this._rsMoved(res); return; }
    if (res.status === 'slot_taken') { f.notice = res.message || 'That time is not open. Please pick another.'; f.alts = res.alternatives || null; f.slot = null; this._bkGo(f, 'time'); this._bkLoadAvail(f); return; }
    fail((res.message || "That didn't work.") + (res.status === 'unsupported' ? '' : ' Your current time still stands.'));
  }
  _rsMoved(res) {
    const b = res.booking, pending = res.status !== 'rescheduled';
    const line = pending ? `New time held: ${b.schedule_name} on ${b.label_visitor}; confirm on Zoom to make it final.` : `Booking moved: ${b.schedule_name} to ${b.label_visitor}.`;
    this._history.push({ role: 'assistant', content: line }); this._history = this._history.slice(-12);
    this._transcript.push({ role: 'bot', text: line, ts: Date.now() }); this._persist(); this._announce(pending ? 'New time held. One last step on Zoom.' : 'Call moved.');
    this._toast(pending ? `New time held: ${b.label_visitor}` : `Your call is now on ${b.label_visitor}`); this._bookings = null;
    this._emit('booking', { status: res.status, bookingId: b.id, joinUrl: b.join_url || null, handoffUrl: b.handoff_url || null, slot: b.start_iso, schedule: b.schedule_slug, email: b.email });
    this._loadMe().catch(() => {});
  }
  _bkDone(f, body) {
    const res = f.result, b = res.booking, pending = res.status !== 'confirmed' && res.status !== 'rescheduled', moved = f.mode === 'reschedule';
    body.innerHTML = `<div class="booked">
      <div class="bk-ok" tabindex="-1">${pending ? `<span class="pend">${SVG.clock}</span><span>One last step on Zoom</span>` : `<svg class="chk" viewBox="0 0 30 30" aria-hidden="true"><circle cx="15" cy="15" r="13"/><path d="M9 15.5l4 4 8-8"/></svg><span>${moved ? 'Your call is moved' : "You're booked"}</span>`}</div>
      <div class="bk-when">${esc(b.label_visitor)}</div><div class="bk-sub">${esc(b.schedule_name)} · ${b.duration_min} min · ${esc(b.visitor_tz)}</div>
      ${pending ? `<p class="note">Your ${moved ? 'new ' : ''}time is held. Confirm it on the Zoom scheduler (your details are prefilled) to make it final.</p>` : ''}${moved && res.old_label_visitor ? `<p class="note">Was ${esc(res.old_label_visitor)}.</p>` : ''}
      <div class="hrow" style="margin-top:6px">${pending && b.handoff_url ? `<a class="btn primary" href="${esc(b.handoff_url)}" target="_blank" rel="noopener">Confirm on Zoom ${SVG.ext}</a>` : ''}${b.join_url ? `<a class="btn primary" href="${esc(b.join_url)}" target="_blank" rel="noopener">${SVG.video}Join Zoom</a>` : ''}${b.ics_url ? `<a class="btn" href="${esc(b.ics_url)}" download>${SVG.cal}Add to calendar</a>` : ''}</div>
      <ul class="nexts">
        ${res.emails_queued ? `<li>${SVG.checkc}<span>${moved ? 'An updated invite' : 'A confirmation'}${b.join_url ? ' with the Zoom link' : ''} is on its way to <b>${esc(b.email)}</b>${(b.attendees || []).length ? ` and ${(b.attendees || []).length === 1 ? esc(b.attendees[0].name) : `your ${b.attendees.length} attendees`}` : ''}</span></li>` : ''}
        ${b.ics_url ? `<li>${SVG.checkc}<span>Add it to your calendar so it doesn't slip</span></li>` : ''}
        ${this._cfg.reminders ? `<li>${SVG.checkc}<span>We'll email you a reminder the day before</span></li>` : ''}
        <li>${SVG.spark.replace('aria-hidden', 'class="nx" aria-hidden')}<span>Want to prepare? <button type="button" class="linkbtn bk-prep">Ask me what the call covers and what to have ready</button></span></li>
      </ul>${b.id ? `<p class="note"><button type="button" class="linkbtn rs-change">Need a different time? Change it here</button> · <button type="button" class="linkbtn cx-open">Cancel this booking</button></p>` : ''}</div>`;
    const up = { id: b.id, schedule_slug: b.schedule_slug, schedule_name: b.schedule_name, label_visitor: b.label_visitor, duration_min: b.duration_min, method: b.method, can_reschedule: true, can_cancel: true };
    const ch = body.querySelector('.rs-change'); if (ch) ch.onclick = () => this.startReschedule(up, 'Change the time of my call');
    const pr = body.querySelector('.bk-prep'); if (pr) pr.onclick = () => this._send('Help me prepare for the call: what will we cover and what should I have ready?');
    const cx = body.querySelector('.cx-open'); if (cx) cx.onclick = () => this.startCancel(up, 'Cancel my call');
  }
  // ---------------------------------------------------------------- cancelling a booking from the chat (confirm first; the worker cancels it on Zoom)
  startCancel(up, label) {
    if (this._busy || !up || !up.id) return; this.showView('chat'); this._clearFollowups();
    const text = label || 'Cancel my call', intro = `Your ${up.schedule_name} is on ${up.label_visitor}. Do you want me to cancel it?`;
    const user = this._add('user', '', Date.now()); this._setText(user, text);
    const bot = this._add('bot', '', Date.now()); this._setText(bot, intro);
    this._transcript.push({ role: 'user', text, ts: Date.now() }, { role: 'bot', text: intro, ts: Date.now() });
    this._history.push({ role: 'user', content: text }, { role: 'assistant', content: intro }); this._history = this._history.slice(-12); this._persist(); this._markLast();
    this._emit('booking', { status: 'cancel_started', bookingId: up.id, schedule: up.schedule_slug || null });
    const f = this._bkFlow(bot); f.mode = 'cancel'; f.booking = up;
    f.card.innerHTML = `<div class="bk cx"><div class="sumbox"><div class="sumrow"><span>Meeting</span><b>${esc(up.schedule_name || '')}</b></div><div class="sumrow"><span>When</span><b>${esc(up.label_visitor || '')}</b></div></div>
      <div class="hrow" style="margin-top:8px"><button type="button" class="btn danger cx-yes">Yes, cancel it</button><button type="button" class="btn cx-no">Keep it</button></div><p class="note sstat" role="status">Nothing changes until you confirm.</p></div>`;
    f.card.querySelector('.cx-no').onclick = () => { f.card.querySelector('.bk').innerHTML = '<p class="note">Kept. Your call stays as it is.</p>'; };
    f.card.querySelector('.cx-yes').onclick = () => this._cxConfirm(f, up);
    requestAnimationFrame(() => this._reveal(f.card));
  }
  async _cxConfirm(f, up) {
    const card = f.card, yes = card.querySelector('.cx-yes'), no = card.querySelector('.cx-no'), stat = card.querySelector('.sstat');
    yes.disabled = true; no.disabled = true; yes.classList.add('loading'); yes.textContent = 'Cancelling…';
    stat.textContent = up.method === 'browser' ? 'Cancelling it on Zoom for you. This can take a minute; please keep this open…' : 'Cancelling…';
    let res = null, status = 0;
    try { const r = await fetch(this._url(`/booking/${encodeURIComponent(up.id)}`), { method: 'DELETE', headers: this._headers() }); status = r.status; res = r.ok ? await r.json() : null; } catch {}
    const fail = (msg) => { yes.disabled = false; no.disabled = false; yes.classList.remove('loading'); yes.textContent = 'Yes, cancel it'; stat.className = 'note sstat warn'; stat.textContent = msg; };
    if (status === 429) return fail('Too many attempts. Please wait a minute and try again. Your booking still stands.');
    if (status === 404) return fail("I couldn't find that booking on this device. Use the link in your confirmation email instead.");
    if (!res || res.status !== 'cancelled') return fail((res && res.message) || "Couldn't cancel it right now. Your booking still stands; please try again.");
    const b = res.booking || up;
    card.querySelector('.bk').innerHTML = `<div class="booked"><div class="bk-ok" tabindex="-1"><svg class="chk" viewBox="0 0 30 30" aria-hidden="true"><circle cx="15" cy="15" r="13"/><path d="M9 15.5l4 4 8-8"/></svg><span>Your call is cancelled</span></div>
      <div class="bk-when">${esc(b.label_visitor || up.label_visitor || '')}</div><div class="bk-sub">${esc(b.schedule_name || up.schedule_name || '')}</div>
      ${res.zoom_note ? `<p class="note">${esc(res.zoom_note)}</p>` : ''}
      <ul class="nexts">${res.emails_queued ? `<li>${SVG.checkc}<span>A cancellation note is on its way to <b>${esc(b.email || '')}</b>${b.email ? '' : 'you'} and to Deep</span></li>` : ''}
        <li>${SVG.spark.replace('aria-hidden', 'class="nx" aria-hidden')}<span>Changed your mind? Book a new time any time.</span></li></ul>
      <div class="hrow"><button type="button" class="btn primary cx-rebook">Book a new time</button></div></div>`;
    card.querySelector('.cx-rebook').onclick = () => this.startBooking(b.schedule_slug || null, 'Book a new time');
    const line = `Booking cancelled: ${b.schedule_name || up.schedule_name} on ${b.label_visitor || up.label_visitor}.`;
    this._history.push({ role: 'assistant', content: line }); this._history = this._history.slice(-12);
    this._transcript.push({ role: 'bot', text: line, ts: Date.now() }); this._persist(); this._announce('Call cancelled.');
    this._toast('Your call is cancelled. A confirmation is on its way to you and to Deep.'); this._bookings = null;
    this._emit('booking', { status: 'cancelled', bookingId: up.id, schedule: b.schedule_slug || up.schedule_slug || null });
    this._loadMe().catch(() => {});
    const ok = card.querySelector('.bk-ok'); if (ok) ok.focus({ preventScroll: true });
  }
  _bkBooked(res) {
    const b = res.booking, pending = res.status !== 'confirmed';
    const line = (pending ? `Time held: ${b.schedule_name} on ${b.label_visitor}; confirm on Zoom to make it final.` : `Booking confirmed: ${b.schedule_name} on ${b.label_visitor}.`) + ' If you want to prepare, I can tell you what the call covers and what to have ready.';
    this._history.push({ role: 'assistant', content: line }); this._history = this._history.slice(-12);
    this._transcript.push({ role: 'bot', text: line, ts: Date.now() }); this._persist(); this._announce(pending ? 'Time held. One last step on Zoom.' : 'Booking confirmed.');
    this._emit('booking', { status: res.status, bookingId: b.id, joinUrl: b.join_url || null, handoffUrl: b.handoff_url || null, slot: b.start_iso, schedule: b.schedule_slug, email: b.email });
    this._loadMe().catch(() => {});  // the memory now carries this booking, so "reschedule my call" works in this chat
    this._bookings = null;
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
  _renderHandover(el, prefill, keep) {  // keep: a saved, unsent email (the reminder brought it back): no new draft
    if (el.querySelector('.hform')) return; const me = this._me || {}; const known = !!(me.signed_in && me.verified && me.email);
    el.classList.add('hascard'); el.closest('.row').classList.add('wide');
    const f = document.createElement('form'); f.className = 'hform card'; f.noValidate = true; f.style.marginTop = '12px'; const id = 'h' + Math.random().toString(36).slice(2, 7);
    const host = (this._cfg && (this._cfg.host_short || this._cfg.host_name)) || 'Deep';
    f.innerHTML = `<div class="bk-t"><b>Email ${esc(host)}</b></div>
      ${known ? '' : `<div class="field"><label for="${id}n">Your name</label><input class="inp" id="${id}n" name="name" maxlength="120" required autocomplete="name"></div>
      <div class="field"><label for="${id}e">Email for the reply</label><input class="inp" id="${id}e" name="email" type="email" maxlength="200" required autocomplete="email" inputmode="email"></div>`}
      <div class="field"><label for="${id}m">Your email to ${esc(host)}</label><span class="hwrite${keep ? '' : ' busy'}" aria-live="polite">${SVG.spark}<span>${keep ? 'Your unsent email from earlier. Edit anything, then send.' : 'Writing your email from this chat…'}</span></span><textarea class="inp" id="${id}m" name="message" rows="6" maxlength="2000" required></textarea></div>
      <button class="btn primary block" type="submit">${SVG.mail}Send to ${esc(host)}</button><p class="note" role="status">${known ? 'Replies go to ' + esc(me.email) + '.' : 'A real person replies by email.'}</p>`;
    const field = (n) => f.elements[n]; field('message').value = prefill || ''; if (!known) { if (me.name) field('name').value = me.name; if (me.email) field('email').value = me.email; }
    const note = f.querySelector('.note'); let typed = !!keep, saveT = 0;
    field('message').addEventListener('input', () => { typed = true; clearTimeout(saveT); saveT = setTimeout(() => this._edSet({ message: field('message').value }), 400); });
    this._edSet({ sid: this._sid, message: field('message').value, dismissed: false, pops: 0 });
    if (!keep) this._handoverDraft(f, () => typed); else this._handoverNudge(f);
    f.onsubmit = async (e) => { e.preventDefault(); const b = f.querySelector('button[type=submit]'); const name = known ? (me.name || '') : field('name').value.trim(); const email = known ? me.email : field('email').value.trim(); const message = field('message').value.trim();
      const bad = !known && name.length < 2 ? field('name') : !known && !EMAIL_RE.test(email) ? field('email') : message.length < 2 ? field('message') : null;
      f.querySelectorAll('.inp').forEach((x) => x.setAttribute('aria-invalid', String(x === bad)));
      if (bad) { note.className = 'note warn'; note.textContent = bad.name === 'email' ? 'Please enter a valid email address.' : bad.name === 'name' ? 'Please enter your name.' : 'Please write a short message.'; bad.focus(); return; }
      b.disabled = true; b.classList.add('loading'); note.className = 'note'; note.textContent = 'Sending…';
      try { const r = await fetch(this._url('/handover'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ session_id: this._sid, name, email, message }) });
        const d = r.ok ? await r.json() : null;
        if (d && d.ok) { this._teamStatus = 'waiting'; setTimeout(() => this._teamCheck(), 1500); clearTimeout(f._nudgeT); this._edClear(); f.classList.add('sent');
          if (d.chat_line) { this._transcript.push({ role: 'bot', text: d.chat_line, ts: Date.now() }); this._persist(); }
          f.innerHTML = `<div class="booked"><div class="bk-ok" tabindex="-1"><svg class="chk" viewBox="0 0 30 30" aria-hidden="true"><circle cx="15" cy="15" r="13"/><path d="M9 15.5l4 4 8-8"/></svg><span>${d.chat_line ? 'Email sent to ' + esc(host) : 'Message sent'}</span></div><p class="note">${d.chat_line ? esc(host) + ' will reply to' : 'The team will reply here and to'} <b>${esc(email)}</b>${d.chat_line ? ' and here in this chat' : ''}.${d.visitor_mailed ? ' A copy is in your inbox.' : ''}</p></div>`; f.querySelector('.bk-ok').focus({ preventScroll: true }); this._announce('Message sent'); this._emit('handover', { leadId: d.lead_id, email, briefSent: d.brief_sent }); }
        else { b.disabled = false; b.classList.remove('loading'); note.className = 'note warn'; note.textContent = r.status === 422 ? 'Please check the email address.' : "Couldn't send right now. Please try again."; } }
      catch { b.disabled = false; b.classList.remove('loading'); note.className = 'note warn'; note.textContent = 'Connection problem. Please try again.'; } };
    el.appendChild(f); this._emit('action', { action: 'handover_form' });
    requestAnimationFrame(() => { this._stick = true; this._scroll(); if (!this._coarse) (known ? field('message') : field('name')).focus({ preventScroll: true }); });
  }
  async _handoverDraft(f, typed) {  // the email the assistant writes from the chat (POST /handover/draft); the visitor edits it.
    // Deep's summary of the chat goes in his email only: the visitor sees their own email, nothing else
    const st = f.querySelector('.hwrite'); let d = null;
    try { const r = await fetch(this._url('/handover/draft'), { method: 'POST', headers: this._headers(), body: JSON.stringify({ session_id: this._sid }) }); d = r.ok ? await r.json() : null; } catch {}
    if (!f.isConnected) return;
    const msg = f.elements.message;
    if (d && d.message && msg && !typed()) { msg.value = d.message; msg.scrollTop = 0; this._edSet({ message: d.message }); }
    if (st) { st.classList.remove('busy'); if (d && d.message) st.querySelector('span').textContent = 'Written from your chat. Edit anything, then send.'; else st.remove(); }
    this._handoverNudge(f);
  }
  _handoverNudge(f) {  // 40 s with a finished email and no send: the button asks once, gently
    clearTimeout(f._nudgeT);
    f._nudgeT = setTimeout(() => { if (!f.isConnected || f.classList.contains('sent')) return; const b = f.querySelector('button[type=submit]'), n = f.querySelector('.note');
      if (b && !b.disabled) { b.classList.add('nudge'); if (n && !n.classList.contains('warn')) n.textContent = `Ready when you are: it goes straight to ${this._hostShort()}'s inbox.`; } }, 40000);
  }
  // ---------------------------------------------------------------- unsent email reminder (Email Deep)
  // one unsent email is kept per browser for 3 days (localStorage): a strip above the composer while the form is out of
  // sight, a note above the closed launcher when the visitor closes the chat or comes back, and "Review & send" brings it back
  _hostShort() { return (this._cfg && (this._cfg.host_short || this._cfg.host_name)) || 'Deep'; }
  _edGet() { try { const d = JSON.parse(localStorage.getItem(this._key('edraft')) || 'null'); return d && Date.now() - (d.ts || 0) < 3 * 86400000 ? d : null; } catch { return null; } }
  _edSet(patch, touch = true) { try { const d = { ...(this._edGet() || {}), ...patch }; if (touch || !d.ts) d.ts = Date.now(); localStorage.setItem(this._key('edraft'), JSON.stringify(d)); } catch {} this._edCheck(); }
  _edClear() { try { localStorage.removeItem(this._key('edraft')); } catch {} clearTimeout(this._edPopT); const pop = this.shadowRoot.querySelector('.npop'); if (pop && pop.dataset.kind === 'email') pop.hidden = true; this._edCheck(); }
  _edPending() { const d = this._edGet(); return d && !d.dismissed && d.sid && (d.message || '').trim().length > 1 ? d : null; }
  _edCheck() {
    const bar = this.shadowRoot && this.shadowRoot.querySelector('.edr'); if (!bar || !this.$log) return;
    if (!bar._bound) { bar._bound = true; bar.querySelector('.edr-go').onclick = () => this._edGo(); bar.querySelector('.edr-x').onclick = () => { this._edSet({ dismissed: true }, false); this._emit('action', { action: 'email_reminder_dismissed' }); };
      let raf = 0; this.$log.addEventListener('scroll', () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; this._edCheck(); }); }, { passive: true }); }
    const d = this._edPending(); let show = !!d && this._view === 'chat';
    if (show) { const f = d.sid === this._sid ? this.$log.querySelector('.hform:not(.sent)') : null;
      if (f) { const r = (f.querySelector('button[type=submit]') || f).getBoundingClientRect(), L = this.$log.getBoundingClientRect(); show = r.bottom < L.top + 8 || r.top > L.bottom - 8; } }   // the Send button out of sight
    if (show && bar.hidden) { bar.querySelector('.edr-t').textContent = `Your email to ${this._hostShort()} isn't sent yet`; this._emit('action', { action: 'email_reminder', kind: 'strip' }); }
    bar.hidden = !show;
  }
  async _edGo() {  // "Review & send": the form back in view (re-created after a reload), the send button ready
    const d = this._edPending(); if (!d) return;
    if (!this.hasAttribute('open')) this.setAttribute('open', '');
    if (d.sid !== this._sid) await this.openConversation(d.sid); else this.showView('chat');
    let f = this.$log.querySelector('.hform:not(.sent)');
    if (!f) { const el = this._add('bot', `Your email to ${this._hostShort()} isn't sent yet. Here it is, ready to go.`); this._renderHandover(el, d.message, true); f = el.querySelector('.hform'); }
    if (!f) return;
    f.scrollIntoView({ block: 'center', behavior: this._reduced ? 'auto' : 'smooth' });
    const b = f.querySelector('button[type=submit]'); if (b) { b.classList.remove('nudge'); void b.offsetWidth; b.classList.add('nudge'); setTimeout(() => b.focus({ preventScroll: true }), 350); }
    this._emit('action', { action: 'email_reminder_open' }); setTimeout(() => this._edCheck(), 500);
  }
  _edPop(delay) {  // the note above the closed launcher: at most three times for one email
    const d = this._edPending(), pop = this.shadowRoot && this.shadowRoot.querySelector('.npop');
    if (!d || !pop || this.getAttribute('mode') !== 'launcher' || (d.pops || 0) >= 3) return;
    clearTimeout(this._edPopT);
    this._edPopT = setTimeout(() => {
      if (this.hasAttribute('open') || !this._edPending()) return; clearTimeout(this._newsPopT);
      pop.dataset.kind = 'email';
      pop.querySelector('.npb').innerHTML = `<span class="npt edpop"><small>${SVG.mail}<span>Not sent yet</span></small><b>Your email to ${esc(this._hostShort())} is ready. Tap to review and send it.</b></span>`;
      pop.hidden = false; this._edSet({ pops: (d.pops || 0) + 1 }, false); this._emit('action', { action: 'email_reminder', kind: 'popup' });
      pop.querySelector('.npb').onclick = () => { pop.hidden = true; delete pop.dataset.kind; this._edGo(); };
      pop.querySelector('.npx').onclick = () => { pop.hidden = true; delete pop.dataset.kind; };
    }, delay);
  }
  // ---------------------------------------------------------------- answer cards (docs/UI_CARDS.md)
  _uiModule() {  // lazy: renderer + parser bundle load on the first card; one failure disables cards for this page load
    if (this._uiDead) return Promise.resolve(null);
    if (!this._uiP) this._uiP = import(new URL('./deep-ui.js?v=' + VERSION, import.meta.url).href)
      .then((m) => { const st = document.createElement('style'); st.dataset.deepUi = '1'; st.textContent = m.CSS; this.shadowRoot.appendChild(st); return m; })
      .catch((e) => { this._uiDead = true; this._emit('ui', { state: 'failed', reason: String(e) }); return null; });
    return this._uiP;
  }
  _uiHooks() { return { send: (t) => this._uiAsk(t), open: (u) => { try { window.open(u, '_blank', 'noopener,noreferrer'); } catch {} }, onEvent: (d) => this._emit('ui', d), announce: (t) => this._announce(t) }; }
  _uiAsk(t) { t = String(t || '').replace(/\s+/g, ' ').trim().slice(0, 300); if (!t || this._busy || /[^\s@]+@[^\s@]+\.[^\s@]+/.test(t) || t.includes('://')) return; this._emit('action', { action: 'ui_button', label: t }); this._send(t); }
  _uiForget(card) { card.program = ''; if (card.entry && card.entry.ui) { delete card.entry.ui; this._persist(); } }
  _uiDrop(card) { if (!card || card.closed) return; card.closed = true; this._uiForget(card); if (card.ctl) card.ctl.destroy(); }
  _onUi(bot, ev, card, answer, all) {
    if (this._uiDead) return card;
    if (ev.op === 'start') { if (card) return card;
      if (!answer) this._setText(bot, '…', all);   // same placeholder + dataset.raw as today's empty-answer path; removes skel and the .ln lines
      bot.classList.remove('streaming');            // the caret would otherwise sit under the card
      card = { program: '', ctl: null, done: false, closed: false, entry: null };
      this._uiModule().then((m) => { if (!m || card.closed) return; bot.classList.add('hascard'); bot.closest('.row').classList.add('wide');
        card.ctl = m.createCard(bot, this._uiHooks()); card.ctl.update(card.program);
        if (card.done && !card.ctl.finish(card.program)) this._uiForget(card); this._scroll(); });
      return card; }
    if (!card || card.closed) return card;
    if (ev.op === 'chunk') { card.program += ev.text || ''; if (card.ctl) card.ctl.update(card.program); return card; }
    if (ev.op === 'end') { if (!ev.complete) { this._uiDrop(card); return card; }
      card.program = ev.program || card.program; card.done = true; if (card.ctl && !card.ctl.finish(card.program)) this._uiForget(card); return card; }
    return card;
  }
  _mountUi(bot, program, entry) {  // restore from the transcript: final render, no streaming; a failed render forgets the stored program
    this._uiModule().then((m) => { if (!m) return; bot.classList.add('hascard'); bot.closest('.row').classList.add('wide');
      if (!m.createCard(bot, this._uiHooks()).finish(program) && entry && entry.ui) { delete entry.ui; this._persist(); } });
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
      const r = new Api(); r.lang = this._langTag(this._voiceLang()); r.interimResults = true; r.continuous = true; let finalText = '';
      r.onresult = (e) => { let interim = ''; for (let i = e.resultIndex; i < e.results.length; i++) { const t = e.results[i][0].transcript; if (e.results[i].isFinal) finalText += t + ' '; else interim += t; } label.textContent = interim ? 'Listening… ' + interim.slice(-40) : 'Listening…'; };
      r.onerror = (e) => { show(e.error === 'not-allowed' ? 'Microphone access was denied. Allow it in your browser settings and try again.' : 'Dictation error: ' + e.error); setTimeout(done, 2500); };
      r.onend = () => { if (finalText.trim()) this._insert((this.$q.value && !/\s$/.test(this.$q.value) ? ' ' : '') + finalText.trim()); done(); };
      this._rec = { stop: () => r.stop() }; show('Listening…'); try { r.start(); } catch (e) { show('Could not start dictation.'); setTimeout(done, 2000); }
      return;
    }
    if (this._cfg.stt !== 'server' || !navigator.mediaDevices) { show('Dictation is not available in this browser.'); setTimeout(done, 2500); return; }
    let cap;
    try { cap = await this._capture({ endMs: 2500, giveUpMs: 10000, maxMs: 120000, onVoice: (rms, spoke) => { if (this._rec) label.textContent = spoke ? 'Hearing you… tap the mic when done' : 'Listening…'; } }); }
    catch (e) { show(e && e.name === 'NotAllowedError' ? 'Microphone access was denied. Allow it in your browser settings and try again.' : 'Could not access the microphone.'); setTimeout(done, 2500); return; }
    this._rec = { stop: () => cap.stop() }; show('Listening…');
    const res = await cap.done; this._rec = { stop: () => {} };
    if (!res.spoke) { show("I didn't hear anything. Try again a little closer to the mic."); setTimeout(done, 2200); return; }
    show('Transcribing…'); const d = await this._transcribe(res, this._voiceLang());
    if (d && d.text) this._insert((this.$q.value && !/\s$/.test(this.$q.value) ? ' ' : '') + d.text); else show(d ? "I couldn't make out any words. Try again?" : 'Could not transcribe that.');
    setTimeout(done, d && d.text ? 300 : 2200);
  }
  _stopDictation() { if (this._rec) this._rec.stop(); }
  // ---- recording for server speech-to-text (docs/MEMORY_VOICE.md "Accuracy"): a clean mic signal, the container the
  // browser really records (Safari: mp4), and voice-activity endpointing: stop ~1 s after the speaker stops, never send silence
  _recMime() { const c = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4;codecs=mp4a.40.2', 'audio/mp4']; try { return c.find((m) => MediaRecorder.isTypeSupported(m)) || ''; } catch { return ''; } }
  _recExt(mime) { return /mp4|m4a|aac/.test(mime) ? 'm4a' : /ogg/.test(mime) ? 'ogg' : /wav/.test(mime) ? 'wav' : 'webm'; }
  _sttHints() { const out = []; const add = (c) => { c = String(c || '').toLowerCase().split('-')[0]; if (/^[a-z]{2}$/.test(c) && !out.includes(c)) out.push(c); }; add(this._lastLang); (navigator.languages || [navigator.language]).forEach(add); return out.slice(0, 4).join(','); }
  async _capture({ auto = true, endMs = 1300, giveUpMs = 12000, maxMs = 30000, onVoice = null } = {}) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: this._audioConstraints || STT_AUDIO });
    const mime = this._recMime(); let mr;
    try { mr = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 64000 } : undefined); } catch { mr = new MediaRecorder(stream); }
    let ctx = null, an = null;
    try { const C = window.AudioContext || window.webkitAudioContext; ctx = new C(); if (ctx.state === 'suspended') ctx.resume().catch(() => {}); an = ctx.createAnalyser(); an.fftSize = 1024; ctx.createMediaStreamSource(stream).connect(an); } catch { an = null; }
    const buf = an ? new Float32Array(an.fftSize) : null, chunks = [], t0 = performance.now();
    // noise floor = the quietest 50 ms of the last 3 s (the pauses between words count), so a noisy room raises the bar for
    // "speaking" and "stopped" alike; the browser's own noise suppression stays off because it hurts Whisper's language detection
    let loud = 0, spoke = false, measured = false, last = 0, reason = 'manual', iv = null; const recent = [];
    const finish = (why) => { reason = why; if (mr.state !== 'inactive') { try { mr.stop(); } catch {} } };
    const done = new Promise((resolve) => {
      mr.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      mr.onstop = () => { clearInterval(iv); stream.getTracks().forEach((t) => t.stop()); if (ctx) ctx.close().catch(() => {}); const type = (mr.mimeType || mime || 'audio/webm').split(';')[0];
        // no working level meter (audio context blocked): we cannot tell speech from silence, so send it and let the server's no-speech filter decide
        resolve({ blob: new Blob(chunks, { type }), mime: type, ext: this._recExt(type), spoke: spoke || !measured, reason, ms: Math.round(performance.now() - t0) }); };
    });
    iv = setInterval(() => {
      const now = performance.now() - t0;
      if (an && ctx.state === 'running') {
        an.getFloatTimeDomainData(buf); let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i]; const rms = Math.sqrt(s / buf.length);
        if (rms > 0) measured = true;
        recent.push(rms); if (recent.length > 60) recent.shift();
        const floor = Math.max(0.0015, Math.min(...recent)), start = Math.max(0.012, floor * 3), hold = Math.max(0.007, floor * 1.8);
        if (rms > (spoke ? hold : start)) { loud += 50; last = now; if (loud >= 150) spoke = true; } else loud = Math.max(0, loud - 25);
        if (onVoice) onVoice(rms, spoke);
      }
      if (auto && spoke && now - last > endMs) finish('end');
      else if (auto && !spoke && measured && now > giveUpMs) finish('nospeech');
      if (now > maxMs) finish('max');
    }, 50);
    mr.start(250);
    return { stop: () => finish('manual'), done };
  }
  async _transcribe(res, pick) {
    const fd = new FormData(); fd.append('file', res.blob, 'audio.' + res.ext); if (pick && pick !== 'auto') fd.append('language', pick); fd.append('hints', this._sttHints());
    try { const r = await fetch(this._url('/stt'), { method: 'POST', headers: this._headers(false), body: fd }); const d = r.ok ? await r.json() : null; if (d && d.language && VOICE_LANGS[d.language]) this._lastLang = d.language; return d; }
    catch { return null; }
  }
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
    this._paintVoiceLang(); this._vstate(this._vlabel('listen'), 'listen'); this._vListen();
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
    if (v.muted) { if (v.rec) { v.discard = true; try { v.rec.stop(); } catch {} } this._vstate(this._vlabel('muted'), 'muted'); } else if (!this._busy) this._vListen();
  }
  _toggleCaptions() { const v = this._voice; const sh = this.shadowRoot, b = sh.querySelector('.v-cc'); const on = v ? (v.cc = !v.cc) : true; b.classList.toggle('off', !on); b.setAttribute('aria-pressed', String(on)); b.setAttribute('aria-label', on ? 'Captions on' : 'Captions off'); sh.querySelector('.vcap').classList.toggle('off', !on); }
  // ---- multilingual voice (docs/MEMORY_VOICE.md): the picker sets recognition + synthesis; 'auto' follows the reply's language
  _voiceLangs() { const list = (this._cfg && Array.isArray(this._cfg.voice_languages) && this._cfg.voice_languages.length) ? this._cfg.voice_languages : Object.keys(VOICE_LANGS); return list.filter((c) => VOICE_LANGS[c]); }
  _voiceLang() { const v = local.get('dh_voice_lang') || 'auto'; return VOICE_LANGS[v] ? v : 'auto'; }
  _cycleVoiceLang() { const list = this._voiceLangs(); const i = list.indexOf(this._voiceLang()); const next = list[(i + 1) % list.length] || 'auto'; local.set('dh_voice_lang', next); this._paintVoiceLang(); const v = this._voice; if (v) { this._toast(VOICE_LANGS[next][1] === 'Auto' ? 'Voice language: automatic' : 'Voice language: ' + VOICE_LANGS[next][1]); if (v.state && !v.ended) this._vstate(this._vlabel(v.state), v.state); if (v.state === 'listen' && v.rec) { v.discard = true; try { v.rec.stop(); } catch {} setTimeout(() => this._vListen(), 200); } } }
  _paintVoiceLang() { const b = this.shadowRoot.querySelector('.v-lang'); if (!b) return; const c = this._voiceLang(); b.querySelector('.vl').textContent = c === 'auto' ? 'Auto' : c.toUpperCase(); b.setAttribute('aria-label', 'Voice language: ' + VOICE_LANGS[c][1] + ' (tap to change)'); }
  _langTag(code) { const c = code && VOICE_LANGS[code] && code !== 'auto' ? code : null; return c ? VOICE_LANGS[c][0] : (navigator.language || 'en-US'); }
  _activeLang() { const pick = this._voiceLang(); if (pick !== 'auto') return pick; const l = this._lastLang; return l && VOICE_LANGS[l] ? l : (navigator.language || 'en').slice(0, 2); }
  _vlabel(key) { const t = VOICE_LABELS[this._activeLang()] || VOICE_LABELS.en; return t[key] || VOICE_LABELS.en[key]; }
  _pickVoice(tag) { try { const vs = speechSynthesis.getVoices() || []; const lc = tag.toLowerCase(), base = lc.slice(0, 2); return vs.find((v) => v.lang.toLowerCase() === lc) || vs.find((v) => v.lang.toLowerCase().startsWith(base)) || null; } catch { return null; } }
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
    const v = this._voice; if (!v || v.ended || v.muted) return; this._vstate(this._vlabel('listen'), 'listen'); const Api = this._speechApi(); const pick = this._voiceLang();
    const onText = async (text) => { if (!text || v.ended) return; v.lines.push({ who: 'you', text }); this._caption('you', text); this._vstate(this._vlabel('think'), 'think');
      await this._send(text); if (v.ended) return; const last = this._transcript[this._transcript.length - 1]; const reply = last && last.role === 'bot' ? plain(last.text) : '';
      if (reply) { v.lines.push({ who: 'deep', text: reply }); this._vstate(this._vlabel('speak'), 'speak'); const say = trunc(reply, 600); this._caption('deep', say, say.split(/\s+/)); await this._vSpeak(say); this._captionProgress(1e9); } if (!v.ended) this._vListen(); };
    if (Api && this._cfg.stt !== 'server') {
      const r = new Api(); r.lang = this._langTag(pick); r.interimResults = true; r.continuous = false; let got = '';
      r.onresult = (e) => { let interim = ''; for (let i = e.resultIndex; i < e.results.length; i++) { const t = e.results[i][0].transcript; if (e.results[i].isFinal) got += t; else interim += t; } this._caption('you', (got || interim).trim()); };
      r.onerror = (e) => { if (e.error === 'not-allowed') this._vstate('Microphone access was denied.', 'idle'); };
      r.onend = () => { v.rec = null; if (v.discard) { v.discard = false; return; } if (got) onText(got.trim()); else if (!v.ended && !v.muted && !this._busy) setTimeout(() => this._vListen(), 300); };
      v.rec = r; try { r.start(); } catch { this._vstate('Could not start listening.', 'idle'); }
      return;
    }
    // server speech-to-text: record until the visitor stops talking (not a fixed few seconds); silence is never sent
    this._capture({ endMs: 1300, giveUpMs: 12000, maxMs: 30000, onVoice: (rms, spoke) => { if (spoke && v.state === 'listen' && !this.shadowRoot.querySelector('.vcap .cu').textContent) this._caption('you', '…'); } })
      .then(async (cap) => {
        v.rec = cap; const res = await cap.done; v.rec = null;
        if (v.ended || v.discard || v.muted) { v.discard = false; return; }
        if (!res.spoke || res.blob.size < 1000) { setTimeout(() => this._vListen(), 150); return; }  // nobody spoke: listen again, nothing sent
        this._vstate(this._vlabel('think'), 'think');
        const d = await this._transcribe(res, pick); if (v.ended) return;
        if (d && d.text) onText(d.text.trim()); else if (d) { this._caption('you', ''); setTimeout(() => this._vListen(), 200); } else { this._vstate('Transcription failed. Listening again…', 'idle'); setTimeout(() => { if (!v.ended && !v.muted) this._vListen(); }, 1800); }
      })
      .catch((e) => this._vstate(e && e.name === 'NotAllowedError' ? 'Microphone access was denied.' : 'Could not access the microphone.', 'idle'));
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
      const tag = this._langTag(this._activeLang()); const u = new SpeechSynthesisUtterance(text); u.lang = tag; const voice = this._pickVoice(tag); if (voice) u.voice = voice;
      else if (tag.slice(0, 2) !== (navigator.language || 'en').slice(0, 2) && !v.warnedVoice) { v.warnedVoice = true; this._toast('No ' + ((VOICE_LANGS[tag.slice(0, 2)] || [])[1] || tag) + ' voice is installed on this device; using the default voice'); }
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
    const up = this._me && this._me.memory && this._me.memory.upcoming;
    if (text && !files.length && CANCEL_RE.test(text) && CALL_RE.test(text) && !RESCHED_RE.test(text)) {
      let u = up; if (!u || !u.can_cancel) { try { await this._loadMe(); } catch {} u = this._me && this._me.memory && this._me.memory.upcoming; }
      if (u && u.can_cancel) { this.$q.value = ''; this._autosize(); this._closePops(); return this.startCancel(u, text); }
    }
    if (text && !files.length && RESCHED_RE.test(text) && CALL_RE.test(text)) {
      let u = up; if (!u || !u.can_reschedule) { try { await this._loadMe(); } catch {} u = this._me && this._me.memory && this._me.memory.upcoming; }  // a booking made in this very chat
      if (u && u.can_reschedule) { this.$q.value = ''; this._autosize(); this._closePops(); return this.startReschedule(u, text); }
    }
    if (this._view !== 'chat') this.showView('chat');
    this.$q.value = ''; this._autosize(); this._closePops(); this._clearFollowups(); this._setBusy(true);
    const shown = (text || (files.length > 1 ? 'Please look at the attached files.' : 'Please look at the attached file.')) + files.map((a) => `\n[attached: ${a.name}](/uploads/${a.id})`).join('');
    const user = this._add('user', '', Date.now()); this._setText(user, shown); this._transcript.push({ role: 'user', text: shown, ts: Date.now() }); this._persist(); this._emit('question', { text, attachments: files.map((a) => a.id) });
    this._attachments = []; this._renderAttachments();
    const bot = this._add('bot', ''); const act = this._activity(bot); this._markLast();
    let answer = '', sources = [], all = [], failed = false, mid = null, offer = false, frus = null, buy = null, fit = null, booking = false, card = null; const sid = this._sid;
    this._controller = new AbortController(); const me = this._me || {};
    const fail = (msg) => { failed = true; this._setText(bot, msg); bot.classList.add('err'); };
    try {
      const beacon = this._tracked() ? undefined : this._beaconData();  // the /track fields until the server has them
      const r = await fetch(this._url('/chat'), { method: 'POST', signal: this._controller.signal, headers: this._headers(),
        body: JSON.stringify({ message: text || 'Please look at the attached file.', history: this._history, timezone: this.tz, attachments: files.map((a) => a.id), user_name: me.signed_in ? undefined : (me.name || undefined), user_email: me.signed_in ? undefined : (me.email || undefined), beacon,
                               outreach_event: (!this._outreachSent && +this.getAttribute('outreach-event')) || undefined, ask_auto: this._askAuto || undefined }) });
      this._askAuto = false;
      if (!r.ok) { fail(this._errorText(r.status)); this._emit('error', { error: 'http_' + r.status }); return; }
      this._outreachSent = true;  // the server stamped the pop-up into this session; later turns find it there
      if (beacon) store.set(this._key('tracked'), sid);  // the server stored it before the stream started
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
          else if (ev.type === 'ui') { card = this._onUi(bot, ev, card, answer, all); }
          else if (ev.type === 'sources') { all = ev.items || []; this._emit('sources', { items: all }); }
          else if (ev.type === 'meta') { mid = ev.message_id || null; }
          else if (ev.type === 'lang') { this._lastLang = ev.code || null; }
          else if (ev.type === 'handover') { bot.classList.remove('skel'); this._renderHandover(bot, ev.prefill || ''); this._emit('action', { action: 'handover_requested' }); }
          else if (ev.type === 'handover_offer') { offer = true; this._emit('action', { action: 'unanswered', label: text }); }
          else if (ev.type === 'buying') { buy = ev; this._emit('action', { action: 'buying', label: (ev.kinds || []).join(',') }); }
          else if (ev.type === 'wrong_fit') { fit = ev; this._nudged = true; this._emit('action', { action: 'wrong_fit', label: ev.kind }); }
          else if (ev.type === 'frustration') { frus = ev; this._emit('action', { action: 'frustration', label: (ev.reasons || []).join(',') }); }
          else if (ev.type === 'error') { fail('Something went wrong on our side. ' + (answer ? '' : 'Please try again.')); this._uiDrop(card); this._emit('error', { error: ev.error }); }
          this._scroll();
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') { this._uiDrop(card); this._setText(bot, answer || 'Stopped.'); if (answer) bot.insertAdjacentHTML('beforeend', '<div class="note">Stopped.</div>'); }
      else { this._uiDrop(card); fail("Couldn't reach Deep. Check your connection, then try again."); this._online = false; this._health(); this._emit('error', { error: String(e) }); }
    } finally {
      if (card && !card.done) this._uiDrop(card);   // stream ended without 'ui end' (abort, provider error): no half card
      // _stick still holds "was the reader at the bottom before the last change", so the tail below follows the same rule
      bot.classList.remove('streaming'); if (bot.classList.contains('skel')) this._setText(bot, answer || '…', all);
      if (answer && all.length && !failed && !offer) { sources = usedSources(answer, all); this._addSources(bot, sources); }
      act.done(sources.length);
      const raw = bot.dataset.raw || answer; this._addTools(bot, () => raw, failed ? text : null, mid);
      if (failed) this._followups(bot, [{ icon: 'reset', label: 'Try again', fn: () => this._retry(bot, text) }]);
      else if (frus && !booking) this._frustrationCard(bot);
      else if (buy && !booking) this._buyingCard(bot, buy);
      else if (fit && fit.kind !== 'student') { if (fit.link) this._fitCard(bot, fit); }
      else if (offer) this._followups(bot, [{ icon: 'mail', label: `Email ${(this._cfg && (this._cfg.host_short || this._cfg.host_name)) || 'Deep'}`, kind: 'handover', fn: () => this._renderHandover(bot, '') }, { icon: 'cal', label: 'Book a meeting', kind: 'booking', fn: () => this.startBooking() }]);
      else if (!booking) this._followups(bot, this._answerFollowups(bot, text, answer, sources.length));
      this._history.push({ role: 'user', content: shown }, { role: 'assistant', content: answer }); this._history = this._history.slice(-12);
      const entry = { role: 'bot', text: failed ? bot.dataset.raw : answer, sources, ts: Date.now(), mid, err: failed || undefined, ui: (card && card.done && card.program) || undefined }; this._transcript.push(entry); if (card) card.entry = entry; this._persist();
      this._controller = null; this._setBusy(false); if (!this._voice) this._focusInput(); this._scroll();
      this._emit('answer', { question: text, answer: raw, sources, messageId: mid, failed }); if (!failed) this._maybeRate(); this._edCheck();
      if (this._view === 'chat' && this._sid === sid) await this._markRead(sid);
      this._refreshBadge(); if (this._view === 'messages') this._renderConversations();
      clearTimeout(this._titleT); this._titleT = setTimeout(() => { if (this._view === 'messages') this._renderConversations(); else this._convos = null; }, 6000);
    }
  }
}
if (!customElements.get('deep-assistant')) customElements.define('deep-assistant', DeepAssistant);
export { DeepAssistant };
