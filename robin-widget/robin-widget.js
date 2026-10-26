/*!
 * Champ Robin Chat Widget v1.0.0
 * Intercom-style chat messenger. Zero dependencies, Shadow-DOM isolated.
 *
 *   <script src="robin-widget.js"></script>
 *   <script>Robin.init({ deepAgent: 'https://assistant.deependhq.com' })</script>
 *
 * Window states, stepped with the chevron up / down control:
 *   hidden (launcher) -> half (half screen) -> full (full height)
 * Bot replies are lists of UI blocks (text, buttons, lead_form, time_slots, card,
 * confirmation) so the backend / OpenUI layer can render forms and slots in-chat.
 * Design tokens and rules live in DESIGN.md.
 *
 * Works from a <script> tag (window.Robin) and as a module in any framework (React, Next.js, Vue, Nuxt,
 * Angular, Svelte, SvelteKit...): `import Robin from 'robin-widget'` or `require('robin-widget')`.
 * Imported during server-side rendering it returns the same API doing nothing; call Robin.init() in the
 * browser (a mount hook) and Robin.destroy() on unmount. See README.md, "Use it in any framework".
 */
(function (factory) {
  var win = typeof window !== 'undefined' && window.document ? window : null;
  var Robin = factory(win);
  if (typeof module === 'object' && module && module.exports) module.exports = Robin;        // CommonJS, bundlers
  else if (typeof define === 'function' && define.amd) define(function () { return Robin; });  // AMD
})(function (global) {
  'use strict';

  var VERSION = '1.0.0';
  var API = ['init', 'open', 'close', 'toggle', 'expand', 'collapse', 'setWide', 'ask', 'voice', 'endVoice', 'setTheme',
    'setScheme', 'setBrand', 'setTextSize', 'setReduceMotion', 'setToken', 'on', 'reset', 'destroy'];

  // No browser (server-side rendering): the same API, every call a no-op, so importing it never breaks a build
  // or a server render. The real widget starts when this runs again in the browser.
  if (!global) {
    var stub = { version: VERSION, instance: null };
    API.forEach(function (name) { stub[name] = function () { return name === 'on' ? stub : null; }; });
    stub.HttpAdapter = stub.DeepAgentAdapter = function () {};
    return stub;
  }
  var STORE_KEY = 'robin-widget:v1';
  var TEASER_KEY = 'robin-widget:teaser-dismissed';
  var MODES = ['hidden', 'half', 'full'];

  // 'peek' (the old compact card) opens the half-screen messenger, so older embeds keep working.
  function normMode(mode) { return mode === 'peek' ? 'half' : mode; }

  var DEFAULTS = {
    appName: 'Champ Robin',
    companyName: '',            // optional: "Hi, I'm Champ Robin from <companyName>", "the <companyName> team"
    primaryColor: '#F4A62A',     // deependhq.com marigold (identity kit v1); text on it is picked for contrast
    position: 'right',          // 'right' | 'left'
    colorScheme: 'light',       // 'light' | 'dark' | 'auto' (visitor can switch in settings)
    // Composer extras: "+" menu (attach / emoji / dictate) and a spoken voice conversation.
    attachments: { accept: '.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.txt,.png,.jpg,.jpeg,.webp', maxFiles: 5, maxSizeMB: 10 },
    emoji: true,
    dictation: true,
    voice: true,
    voiceLanguages: ['auto', 'en-US', 'hi-IN'],
    privacyUrl: null,           // shows "By chatting with us, you agree to our Privacy Policy" under the input
    loadFonts: true,           // Bricolage Grotesque + Figtree from Google Fonts
    openingTransition: true,    // launcher click: a layer inside the chat with Robin's stage filling up, then the chat crossfades in
    thinkingOverlay: true,      // while a reply is prepared, the same layer covers the page and the chat (false: loader in the chat)
    motion: 'auto',             // 'auto' (follows the device's reduced-motion setting) | 'full' (always animate)
    greeting: 'Hi there.',
    intro: 'How can we help?',
    placeholder: 'What would you like to know?',   // conversation input
    thinkingText: 'Thinking',   // loader status until the backend reports a more specific step (onStatus)
    disclaimer: 'AI responses can make mistakes. Check important info.',   // one line under the input when there's no privacyUrl
    // Quick starts: your own ({ label, value, icon }), or a deep-agent server's most-asked questions. None by default.
    starters: [],
    // The small card beside the launcher. With a deep-agent server its outreach rules decide what it says and whether
    // this generic one may show at all; null turns it off.
    teaser: { text: 'Have a question? I can help.', delay: 5000 },
    initialMode: 'hidden',      // 'hidden' | 'half' | 'full'
    // The backend, one of: deepAgent (a deep-agent server), endpoint (any server answering with { blocks }) or adapter.
    adapter: null,              // { send(payload) -> Promise<{ blocks }> }
    endpoint: null,             // POST endpoint; used when no adapter is given
    deepAgent: null,            // URL of a deep-agent server: answers, booking and hand-over come from it
    schedulerUrl: null,         // an external booking page offered in Help & contact (a deep-agent server supplies its own)
    visitorToken: null,         // deep-agent: a signed-in visitor's token, minted by your server (sent as X-Visitor-Token)
    userName: null,             // deep-agent: unverified name / email hints for a visitor with no token
    userEmail: null,
    headers: {},
    onEvent: null,              // fn(event) - analytics hook
    persist: true,
    zIndex: 2147483000
  };

  /* ------------------------------------------------------------------ utils */

  function uid(prefix) {
    return (prefix || 'id') + '_' + Math.random().toString(36).slice(2, 9) + Date.now().toString(36).slice(-4);
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function h(tag, attrs) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v == null || v === false) return;
        if (k === 'class') node.className = v;
        else if (k === 'html') node.innerHTML = v;
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
        else if (v === true) node.setAttribute(k, '');
        else node.setAttribute(k, v);
      });
    }
    for (var i = 2; i < arguments.length; i++) append(node, arguments[i]);
    return node;
  }

  function append(node, child) {
    if (child == null || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { append(node, c); }); return; }
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // Minimal, safe formatting: **bold**, [label](https://…), newlines.
  // **bold**, `code`, [links](https://…), newlines, and lines starting "- " or "1. " as lists.
  function rich(text) {
    var html = esc(friendlyDates(text || ''))
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`\n]+)`/g, '<code>$1</code>')
      .replace(/\[GIF\]\((https:\/\/[^\s)"]+)\)/g, '<img class="gif" src="$1" alt="GIF" loading="lazy">')
      .replace(/\[([^\]]+)\]\(((?:https?:\/\/|mailto:)[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    var out = '', list = null, para = [];
    function flush() { if (para.length) { out += para.join('<br>'); para = []; } }
    function close() { if (list) { out += '</' + list + '>'; list = null; } }
    html.split('\n').forEach(function (line) {
      var m = /^\s*(?:[-*•]|(\d{1,2})[.)])\s+(.+)$/.exec(line);
      if (!m) {
        close();
        // A list already has its own spacing: blank lines straight after one add nothing.
        if (line.trim() || para.length || !/<\/[ou]l>$/.test(out)) para.push(line);
        return;
      }
      var tag = m[1] ? 'ol' : 'ul';
      while (para.length && !para[para.length - 1].trim()) para.pop();   // ...nor blank lines just before one
      flush();
      if (list !== tag) { close(); out += '<' + tag + (m[1] && +m[1] > 1 ? ' start="' + (+m[1]) + '"' : '') + '>'; list = tag; }
      out += '<li>' + m[2] + '</li>';
    });
    flush();
    close();
    return out;
  }

  // Sanitizing what the visitor types before it is shown or sent: no control characters (newlines and tabs
  // stay), no invisible direction overrides, at most two blank lines in a row, trimmed and capped at `max`.
  function cleanText(text, max) {
    var t = String(text == null ? '' : text)
      .replace(/\r\n?/g, '\n')
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F\u202A-\u202E\u2066-\u2069]/g, '')
      .replace(/\n{4,}/g, '\n\n\n')
      .trim();
    return max ? t.slice(0, max) : t;
  }

  // One line (names, emails, titles): whitespace collapsed.
  function cleanLine(text, max) {
    return cleanText(text, 0).replace(/\s+/g, ' ').slice(0, max || 200);
  }

  // Only web and mail links leave the widget (never javascript:, data: or other schemes).
  function safeUrl(url) {
    var u = String(url || '').trim();
    return /^(https?:\/\/|mailto:)/i.test(u) ? u : null;
  }

  // The same text without the markup, for copying.
  function plain(text) {
    return String(text || '')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/`([^`\n]+)`/g, '$1')
      .replace(/\[([^\]]+)\]\(([^\s)]+)\)/g, '$1 ($2)');
  }

  // The clipboard API where the page allows it; otherwise (plain http, or the API refuses) a hidden textarea.
  function copyText(text) {
    if (navigator.clipboard && global.isSecureContext) {
      // Some browsers leave the request hanging (a permission prompt nobody answers): give up after a second.
      var slow = new Promise(function (resolve, reject) { setTimeout(function () { reject(new Error('clipboard timeout')); }, 1000); });
      return Promise.race([navigator.clipboard.writeText(text), slow]).catch(function () { return copyFallback(text); });
    }
    return copyFallback(text);
  }

  function copyFallback(text) {
    return new Promise(function (resolve, reject) {
      var ta = h('textarea', { style: 'position:fixed;top:0;left:0;opacity:0', 'aria-hidden': 'true' });
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { /* unsupported */ }
      ta.remove();
      if (ok) resolve(); else reject(new Error('copy failed'));
    });
  }

  function hexToRgb(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim());
    if (!m) return null;
    var n = parseInt(m[1], 16);
    return [n >> 16 & 255, n >> 8 & 255, n & 255];
  }

  function shade(hex, amt) {
    var rgb = hexToRgb(hex);
    if (!rgb) return hex;
    return '#' + rgb.map(function (c) {
      var v = amt < 0 ? c * (1 + amt) : c + (255 - c) * amt;
      return ('0' + Math.round(v).toString(16)).slice(-2);
    }).join('');
  }

  // Any opaque CSS colour as #rrggbb (null if it can't be read or isn't opaque), via the canvas colour parser.
  function toHex(color) {
    if (/^#[0-9a-f]{6}$/i.test(String(color))) return String(color);
    try {
      var ctx = document.createElement('canvas').getContext('2d');
      ctx.fillStyle = '#010203';   // an unreadable colour leaves this in place
      ctx.fillStyle = String(color);
      var v = ctx.fillStyle;
      return /^#[0-9a-f]{6}$/i.test(v) && v !== '#010203' ? v : null;
    } catch (e) { return null; }
  }

  // Pick near-black or near-white text for the brand colour (WCAG relative luminance).
  // WCAG relative luminance and contrast ratio.
  function lumOf(hex) {
    var rgb = hexToRgb(hex) || [0, 0, 0];
    var l = rgb.map(function (v) {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];
  }
  function contrast(a, b) {
    var x = lumOf(a), y = lumOf(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }
  // The colour itself when it reads as text on `bg` (4.5:1), else darkened (dir -1) or lightened (+1) until it does.
  function readable(hex, bg, dir) {
    for (var t = 0; t <= 0.951; t += 0.05) {
      var c = t ? shade(hex, dir * t) : hex;
      if (contrast(c, bg) >= 4.5) return c;
    }
    return dir < 0 ? '#000000' : '#FFFFFF';
  }

  // Text on a colour: dark ink or white, whichever reads better.
  function inkFor(hex) {
    if (!hexToRgb(hex)) return '#FFFFFF';
    var dark = contrast(hex, '#0E1A33'), light = contrast(hex, '#FFFFFF');
    if (light > dark) return '#FFFFFF';
    return dark >= 4.5 ? '#0E1A33' : '#000000';   // a mid colour (e.g. #4A7BF7) needs pure black to reach 4.5:1
  }

  function ago(ts) {
    var s = Math.round((Date.now() - ts) / 1000);
    if (s < 60) return 'now';
    if (s < 3600) return Math.floor(s / 60) + 'm';
    if (s < 86400) return Math.floor(s / 3600) + 'h';
    return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  var fmtDay = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
  var fmtTime = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' });
  // Day tiles in the booking picker: "THU / 23 / OCT".
  var fmtDow = new Intl.DateTimeFormat(undefined, { weekday: 'short' });
  var fmtNum = new Intl.DateTimeFormat(undefined, { day: 'numeric' });
  var fmtMon = new Intl.DateTimeFormat(undefined, { month: 'short' });
  var localTz = (Intl.DateTimeFormat().resolvedOptions().timeZone || '').replace(/_/g, ' ');
  // "India Standard Time" rather than "Asia/Calcutta" wherever a time zone is shown.
  var tzName = (function () {
    try {
      var z = new Intl.DateTimeFormat(undefined, { timeZoneName: 'long' }).formatToParts(new Date()).filter(function (x) { return x.type === 'timeZoneName'; })[0];
      return z ? z.value : localTz;
    } catch (e) { return localTz; }
  })();
  // "1:00 – 1:45 PM" for a call of known length, else its start.
  function timeRange(d, mins) {
    if (!mins) return fmtTime.format(d);
    var e = new Date(+d + mins * 60000);
    try { return fmtTime.formatRange ? fmtTime.formatRange(d, e) : fmtTime.format(d) + ' – ' + fmtTime.format(e); }
    catch (x) { return fmtTime.format(d) + ' – ' + fmtTime.format(e); }
  }

  function loadStore(persist) {
    var empty = { scheme: null, visitor: {}, conversations: [] };
    if (!persist) return empty;
    try { return cleanStore(Object.assign(empty, JSON.parse(localStorage.getItem(STORE_KEY)) || {})); }
    catch (e) { return empty; }
  }

  // Saved data from an older version, another tab or a hand edit: only well-formed conversations are kept.
  function cleanStore(st) {
    var v = st.visitor && typeof st.visitor === 'object' ? st.visitor : {};
    st.visitor = {};
    ['name', 'email', 'company'].forEach(function (k) { if (typeof v[k] === 'string' && v[k]) st.visitor[k] = v[k]; });
    st.conversations = (Array.isArray(st.conversations) ? st.conversations : []).filter(function (c) {
      if (!c || typeof c.id !== 'string' || !Array.isArray(c.messages)) return false;
      c.messages = c.messages.filter(function (m) { return m && Array.isArray(m.blocks); });
      return c.messages.length > 0;
    });
    return st;
  }

  // A one-line gist of a message for previews and titles: a GIF says so, links keep their words.
  function gist(text) {
    return plain(String(text || '').replace(/\[GIF\]\([^)]*\)/gi, 'GIF').replace(/\[([^\]]+)\]\([^)\s]+\)/g, '$1')).replace(/\s+/g, ' ').trim();
  }

  function readSession(key) { try { return sessionStorage.getItem(key); } catch (e) { return null; } }
  function writeSession(key, v) { try { sessionStorage.setItem(key, v); } catch (e) { /* private mode */ } }

  // Fonts must be registered on the document; a shadow root can use them but not declare them.
  function loadFonts() {
    if (document.getElementById('robin-widget-fonts')) return;
    document.head.appendChild(h('link', {
      id: 'robin-widget-fonts', rel: 'stylesheet',
      href: 'https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..700&family=Figtree:wght@400..700&display=swap'
    }));
  }

  var SpeechRec = global.SpeechRecognition || global.webkitSpeechRecognition || null;

  function fmtSize(n) {
    if (n < 1024) return n + ' B';
    if (n < 1048576) return Math.round(n / 1024) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  function fileExt(name) {
    var m = /\.([a-z0-9]{1,5})$/i.exec(name || '');
    return m ? m[1].toUpperCase() : 'FILE';
  }

  // `accept` uses the <input accept> syntax: ".pdf,.docx,image/*".
  function acceptOk(file, accept) {
    if (!accept) return true;
    var name = file.name.toLowerCase(), type = (file.type || '').toLowerCase();
    return accept.split(',').some(function (rule) {
      rule = rule.trim().toLowerCase();
      if (!rule) return false;
      if (rule[0] === '.') return name.slice(-rule.length) === rule;
      if (rule.slice(-2) === '/*') return type.indexOf(rule.slice(0, -1)) === 0;
      return type === rule;
    });
  }

  // What Robin says out loud: message text without markdown, plus a pointer to any form or picker.
  function spokenText(msg) {
    if (!msg || msg.role !== 'bot') return '';
    var parts = [], visual = false;
    msg.blocks.forEach(function (b) {
      if (b.type === 'text' || b.type === 'error') parts.push(b.text);
      else if (b.type === 'confirmation') parts.push([b.title].concat((b.lines || []).map(function (l) { return l.text || l; })).join('. '));
      else if (b.type !== 'buttons') visual = true;
    });
    var text = parts.join(' ').replace(/\*\*(.+?)\*\*/g, '$1').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/\s*→\s*/g, ', then ').replace(/\s+/g, ' ').trim();
    if (visual) text += ' I\'ve put the details in the chat.';
    return text;
  }

  function voiceError(code) {
    return {
      'not-allowed': 'Microphone access is blocked. Allow it in your browser settings.',
      'service-not-allowed': 'Microphone access is blocked. Allow it in your browser settings.',
      'audio-capture': 'No microphone was found.',
      'network': 'Voice needs an internet connection.'
    }[code] || 'Voice stopped unexpectedly. Tap the mic to try again.';
  }

  function pickVoice(lang) {
    if (!global.speechSynthesis) return null;
    var voices = global.speechSynthesis.getVoices(), base = lang.slice(0, 2);
    var match = voices.filter(function (v) { return v.lang === lang; });
    if (!match.length) match = voices.filter(function (v) { return v.lang.slice(0, 2) === base; });
    return match.filter(function (v) { return /natural|neural|google/i.test(v.name); })[0] || match[0] || null;
  }

  // Emoji picker set: glyph + search keywords (first keyword is the accessible name).
  var EMOJI = ('😀 grinning smile happy|😃 smiley happy|😄 smile laugh|😁 beaming grin|😆 laughing|😅 sweat relief|😂 joy tears laugh|' +
    '🙂 slight smile|😉 wink|😊 blush happy|😍 heart eyes love|🤩 star struck wow|😘 kiss|😎 cool sunglasses|🤓 nerd|🤔 thinking hmm|' +
    '🤨 skeptical eyebrow|😐 neutral|🙄 eye roll|😏 smirk|😌 relieved|😴 sleepy tired|🤯 mind blown|😮 surprised wow|🥳 party celebrate|' +
    '😢 sad cry|😭 sob crying|😤 huff|😡 angry|🤗 hug|🤝 handshake deal|🙏 thanks please pray|👍 thumbs up yes like|' +
    '👎 thumbs down no|👏 clap applause|🙌 raised hands celebrate|👋 wave hello hi bye|✌️ peace victory|🤞 fingers crossed luck|👌 ok perfect|' +
    '💪 strong muscle|👀 eyes look|🤷 shrug|🙋 raise hand question|❤️ heart love|🧡 orange heart|💯 hundred perfect|🔥 fire hot|✨ sparkles new|' +
    '⭐ star|🌟 glowing star|🎉 tada party celebrate|🎯 target goal bullseye|🚀 rocket launch ship|💡 idea bulb|✅ check done yes|❌ cross no wrong|' +
    '⚡ lightning fast|⏰ alarm clock time|⏳ hourglass wait|📅 calendar date|🗓️ schedule calendar|📞 phone call|✉️ envelope email mail|📧 email|' +
    '💼 briefcase work business|📈 chart up growth|📊 bar chart data stats|📉 chart down|💰 money bag|💵 dollar cash|🧾 receipt invoice|' +
    '📝 memo note write|📎 paperclip attach|📌 pin|🔗 link|🔍 search magnify|📱 mobile phone|💻 laptop computer|🎟️ ticket event|🏆 trophy win award|' +
    '🥇 first medal gold|🎤 microphone talk|🧠 brain smart|🤖 robot bot ai|👥 people team|🏢 office building company|🌍 globe world|' +
    '✈️ plane travel flight|🏨 hotel|☕ coffee|🍕 pizza|🍻 cheers drinks|🎂 cake birthday|🎁 gift present|🌱 seedling growth|💬 speech chat message|' +
    '❓ question|❗ exclamation important|➡️ arrow right next|🔒 lock secure private').split('|').map(function (s) {
    var i = s.indexOf(' ');
    return { e: s.slice(0, i), k: s.slice(i + 1) };
  });

  /* ------------------------------------------------------------------ icons */

  function svg(body) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + '</svg>';
  }

  var ICON = {
    chevronDown: svg('<path d="m6 9 6 6 6-6"/>'),
    chevronUp: svg('<path d="m18 15-6-6-6 6"/>'),
    expand: svg('<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>'),
    shrink: svg('<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>'),
    close: svg('<path d="M18 6 6 18M6 6l12 12"/>'),
    back: svg('<path d="m15 18-6-6 6-6"/>'),
    arrow: svg('<path d="m9 18 6-6-6-6"/>'),
    pen: svg('<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>'),
    copy: svg('<rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>'),
    volume: svg('<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>'),
    thumbUp: svg('<path d="M7 10v11H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zM7 10l4-7a2.5 2.5 0 0 1 2.5 2.5V9h5.2a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 17.3 21H7"/>'),
    thumbDown: svg('<path d="M17 14V3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1zM17 14l-4 7a2.5 2.5 0 0 1-2.5-2.5V15H5.3a2 2 0 0 1-2-2.3l1.4-8A2 2 0 0 1 6.7 3H17"/>'),
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor"/></svg>',
    send: svg('<path d="M12 19V5M5 12l7-7 7 7"/>'),
    gear: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
    home: svg('<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>'),
    messages: svg('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.6A8 8 0 1 1 21 12z"/>'),
    check: svg('<path d="M20 6 9 17l-5-5"/>'),
    calendar: svg('<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>'),
    help: svg('<circle cx="12" cy="12" r="9"/><path d="M9.5 9.2a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.2-2.5 3.6M12 17h.01"/>'),
    tag: svg('<path d="M12.6 2.6A2 2 0 0 0 11.2 2H4a2 2 0 0 0-2 2v7.2a2 2 0 0 0 .6 1.4l8.7 8.7a2.4 2.4 0 0 0 3.4 0l6.6-6.6a2.4 2.4 0 0 0 0-3.4z"/><circle cx="7.5" cy="7.5" r="1.5"/>'),
    plus: svg('<path d="M12 5v14M5 12h14"/>'),
    clip: svg('<path d="M21 11.5l-8.5 8.5a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8"/>'),
    smile: svg('<circle cx="12" cy="12" r="9"/><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01"/>'),
    mic: svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/>'),
    micOff: svg('<path d="m2 2 20 20M9 9v2a3 3 0 0 0 5.1 2.1M15 9.3V6a3 3 0 0 0-5.9-.7M19 11a7 7 0 0 1-1.2 3.9M5 11a7 7 0 0 0 11 5.7M12 18v3M9 21h6"/>'),
    wave: svg('<path d="M4 11.5v1M8 8v8M12 5v14M16 8v8M20 11v2"/>'),
    cc: svg('<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10.5 10.2a2 2 0 1 0 0 3.6M17 10.2a2 2 0 1 0 0 3.6"/>'),
    hangup: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 9c-3.3 0-6.4 1-8.8 2.8-.5.4-.7 1-.6 1.6l.4 2c.1.7.8 1.2 1.5 1.1l3-.5c.6-.1 1.1-.6 1.2-1.2l.3-1.9a10.5 10.5 0 0 1 6 0l.3 1.9c.1.6.6 1.1 1.2 1.2l3 .5c.7.1 1.4-.4 1.5-1.1l.4-2c.1-.6-.1-1.2-.6-1.6A14.6 14.6 0 0 0 12 9z"/></svg>',
    globe: svg('<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/>'),
    refresh: svg('<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8M21 3v5h-5"/>'),
    user: svg('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
    mail: svg('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>'),
    building: svg('<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1M10 21v-3h4v3"/>'),
    headset: svg('<path d="M3 14v-2a9 9 0 0 1 18 0v2"/><rect x="3" y="14" width="4" height="6" rx="1.5"/><rect x="17" y="14" width="4" height="6" rx="1.5"/><path d="M21 18a4 4 0 0 1-4 4h-3"/>'),
    phone: svg('<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>'),
    sun: svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
    moon: svg('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'),
    monitor: svg('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>'),
    palette: svg('<circle cx="13.5" cy="6.5" r="1"/><circle cx="17.5" cy="10.5" r="1"/><circle cx="8.5" cy="7.5" r="1"/><circle cx="6.5" cy="12.5" r="1"/><path d="M12 2a10 10 0 0 0 0 20c1.1 0 2-.9 2-2 0-.5-.2-1-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1.1.9-2 2-2h2.4A5.6 5.6 0 0 0 22 9.8C22 5.5 17.5 2 12 2z"/>'),
    trash: svg('<path d="M3 6h18M8 6V4h8v2M6 6l1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14M10 11v6M14 11v6"/>'),
    alert: svg('<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>'),
    clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    lock: svg('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'),
    sparkles: svg('<path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>'),
    trending: svg('<path d="m3 17 6-6 4 4 8-8"/><path d="M14 7h7v7"/>'),
    external: svg('<path d="M14 3h7v7M10 14 21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>'),
    arrowRight: svg('<path d="M5 12h14M13 6l6 6-6 6"/>'),
    download: svg('<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>'),
    sidebar: svg('<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>'),
    search: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
    type: svg('<path d="M4 7V5h16v2M9 19h6M12 5v14"/>'),
    gif: svg('<rect x="2.5" y="5" width="19" height="14" rx="3"/><path d="M10 10H8.6a1.6 1.6 0 0 0-1.6 1.6v.8A1.6 1.6 0 0 0 8.6 14H10v-2H9M13 10v4M16 14v-4h2.4M16 12h2"/>')
  };

  // Icons are wrapped in <span class="i i-NAME"> so each one can carry its own hover animation.
  function icon(name, cls) {
    return h('span', { class: 'i i-' + name + (cls ? ' ' + cls : ''), 'aria-hidden': 'true', html: ICON[name] || '' });
  }

  // Default icons for reply buttons and quick starts, by value; an option's own `icon` wins.
  var VALUE_ICONS = { about: 'help', book_demo: 'calendar', pricing: 'tag', contact: 'headset', thanks: 'check' };
  var FIELD_ICONS = { name: 'user', email: 'mail', company: 'building', phone: 'phone' };
  var FORM_ICONS = { pricing: 'tag', contact: 'headset', booking: 'calendar' };

  function optionIcon(o) {
    if (o.icon && ICON[o.icon]) return o.icon;
    return VALUE_ICONS[o.value] || (o.url ? 'external' : null);
  }

  /* ---------------------------------------------------------------- avatars */

  // Logo: the Champ Robin mark (logo pack, robin-mark.svg), a swallow in flight heading up and to the right:
  // wing swept back, forked tail. One vector path used as a CSS mask, so it takes any colour (--logo: Robin
  // plum on light, snow on dark, the launcher's ink on the launcher) and stays sharp at every size.
  var CR_PATH = 'M50.5 6 C54.5 6 57.5 8.5 58 12.5 L63 14.5 L57.5 15.5 C56.5 18 54.5 19.5 52.5 20 C51.5 25.5 48.5 31 44.5 35.5 C40 40.5 34 43.5 28.5 44 L8 58 L21 44 L3 46 L24.5 38.5 C28 35 31 31 33.5 27.5 C27 22.5 16.5 19 4 17 C19.5 11.5 32 11 43 13.5 C44.5 9 47 6 50.5 6 Z';
  var CR_MASK = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path fill="#000" d="' + CR_PATH + '"/></svg>');

  // The live swallow: three stacked copies of the masked logo, clipped to the far wing, the body and the near
  // wing, so each wing flaps round its own pivot while the body layer moves for the current state (CSS).
  // `still` keeps it at rest (avatars in lists).
  function bird(still) {
    return h('span', { class: 'cr' + (still ? ' still' : ''), 'aria-hidden': 'true' },
      h('span', { class: 'cr-m' }, h('i', { class: 'cr-far' }), h('i', { class: 'cr-body' }), h('i', { class: 'cr-near' })));
  }

  // The small swallow in its ring: a light 90% circle with the gap centred at the bottom and a darker 10% arc
  // revolving round it, still seen as it crosses the gap. The swallow sits inside at the guide's proportion (168 of
  // 232). Used in the header and beside answers.
  function ringedBird() {
    var c = '<circle cx="20" cy="20" r="19" pathLength="100" transform="rotate(-252 20 20)" class="';
    return [h('span', { class: 'mr-ring', html: '<svg viewBox="0 0 40 40">' + c + 'mr-track"/>' + c + 'mr-arc"/></svg>' }), bird()];
  }

  // Robin's stage (build guide v4): the live swallow inside a 90% ring whose gap stays at the bottom, on a soft
  // aura, with a sign for each state so it reads without text: dots from the beak (chat), rings closing in
  // (listen), sound arcs from the beak (talk), thought bubbles (thinking), the swallow filling up like liquid
  // (loading), the ring closing into a magnifying glass (search), the ring closing green (success) or breaking
  // red (error), and a badge sitting in the gap.
  // It is laid out in the guide's 320x280 box (the pixel values in its CSS are the guide's) and scaled by --s.
  // One animation-frame loop draws the ring and the fill while it is on the page.
  // opts: state, cycle (seconds per loading fill, default 4), level() (live mic level 0..1, or null to use the
  // guide's simulated amplitude), still (reduced motion: drawn once, no loop). Returns { el, set(state) }.
  var STAGE_BADGE = { chat: 'messages', listen: 'mic', muted: 'micOff', talk: 'volume', success: 'check', error: 'alert' };
  var STAGE_DWELL = 600;   // ms each stage state shows at least
  function robinStage(opts) {
    opts = opts || {};
    function many(cls, n) { var a = []; for (var i = 0; i < n; i++) a.push(h('i', { style: '--i:' + i })); return h('span', { class: cls }, a); }
    var fill = h('span', { class: 'rs-b rs-fill' }, bird());
    var birds = h('span', { class: 'rs-birds' }, h('span', { class: 'rs-b rs-g g2' }, bird()), h('span', { class: 'rs-b rs-g g1' }, bird()),
      h('span', { class: 'rs-b rs-main' }, bird()), fill);
    var badge = h('span', { class: 'rs-badge' });
    var el = h('span', { class: 'rs', 'aria-hidden': 'true' }, h('span', { class: 'rs-box' },
      h('i', { class: 'rs-aura' }), h('i', { class: 'rs-shadow' }), many('rs-in', 3),
      h('span', { class: 'rs-ring', html: '<svg viewBox="0 0 240 240"><g><circle class="rs-base" cx="120" cy="120" r="116" pathLength="100"/>' +
        '<circle class="rs-comet" cx="120" cy="120" r="116" pathLength="100"/></g></svg>' }),
      h('i', { class: 'rs-handle' }), birds, many('rs-dots', 3), many('rs-arcs', 3), many('rs-bub', 3), badge));
    var ring = el.querySelector('g'), base = el.querySelector('.rs-base'), comet = el.querySelector('.rs-comet');
    var st = { state: null, next: null, t0: 0, gone: 0 };

    // One frame of the ring (and the fill), t seconds into the state. Values from the guide (section 6).
    function draw(t) {
      var s = st.state, gap = 10, spin = 0, bw = 1, bo = .22, len = 0, pos = 0, co = 0, dash = null;
      var lvl = opts.level && opts.level();
      var amp = lvl == null ? Math.abs(Math.sin(9 * t) * Math.sin(3.3 * t)) : lvl;
      var burst = Math.abs(Math.sin(2.2 * t) * Math.sin(0.9 * t + 1));
      if (s === 'idle') { len = 10; pos = (t * 100 / 2.4) % 100; co = .85; }
      else if (s === 'chat') gap = 10 + 6 * (.5 + .5 * Math.sin(3.9 * t));
      else if (s === 'listen') { gap = 14; bw = 1 + 2.5 * amp; bo = .22 + .45 * amp; }
      else if (s === 'muted') gap = 14;
      else if (s === 'talk') { gap = 12; len = 8 + 14 * burst; pos = (55 * t) % 100; co = .7; }
      else if (s === 'loading') bo = .18;
      else if (s === 'thinking') { len = 14; pos = (72 * t) % 100; co = .85; }
      else if (s === 'search') { gap = 0; bw = 1.6; bo = .75; }
      else if (s === 'success') { var e = 1 - Math.pow(1 - Math.min(1, t / .6), 3); gap = 10 * (1 - e); bw = 1 + .5 * e; bo = .22 + .6 * e; }
      else if (s === 'error') { gap = 25; dash = '14 3 22 5 18 4 9 25'; bw = 1.5; bo = .55; var m = t % 2.6; spin = 6 * Math.max(0, 1 - m / .8) * Math.sin(40 * m); }
      if (opts.still) { co = 0; spin = 0; }
      // Stroke widths are on-screen pixels, whatever the scale.
      var k = 1 / (parseFloat(getComputedStyle(el).getPropertyValue('--s')) || 1);
      base.style.strokeDasharray = dash || (100 - gap) + ' ' + gap;
      base.style.strokeWidth = bw * k;
      base.style.opacity = bo;
      comet.style.strokeDasharray = len + ' ' + (100 - len);
      comet.style.strokeDashoffset = -pos;
      comet.style.strokeWidth = 2 * k;
      comet.style.opacity = co;
      ring.setAttribute('transform', 'rotate(' + (90 - 360 * (1 - gap / 200) + spin).toFixed(2) + ' 120 120)');
      if (s === 'loading') {
        // A wavy liquid line rises through the swallow, flattening when full; the fill loops every `cycle`.
        var cyc = opts.cycle || 4, pk = opts.still ? 1 : Math.min(1, (t % cyc) / (cyc * .85));
        var pct = (1 - Math.pow(1 - pk, 2.2)) * 100, top = 100 - (8 + pct * .84), a = pct > 99 ? 0 : 2.2, pts = [];
        for (var i = 0; i <= 20; i++) pts.push(i * 5 + '% ' + (top + a * Math.sin(i * .7 + t * 6)).toFixed(2) + '%');
        fill.style.clipPath = 'polygon(' + pts.join(',') + ',100% 100%,0% 100%)';
      }
    }
    function loop(now) {
      // Stops a second after the stage leaves the page (a re-render may put it straight back).
      if (!el.isConnected) { if (!st.gone) st.gone = now; else if (now - st.gone > 1000) return; }
      else { st.gone = 0; if (st.state && !el.closest('[data-mode=hidden]')) draw((now - st.t0) / 1000); }
      requestAnimationFrame(loop);
    }
    function apply(state) {
      st.state = state;
      st.t0 = performance.now();
      el.dataset.state = state;
      badge.replaceChildren();
      if (STAGE_BADGE[state]) badge.append(h('span', { class: 'rs-bi', html: ICON[STAGE_BADGE[state]] }));
      if (el.isConnected) draw(0);
    }
    // A new state: the swallow dips out (200ms), then the state sets in and its clock restarts. Each state holds
    // for at least STAGE_DWELL, so a quick run of steps (thinking, searching, writing) is still seen one by one;
    // states that arrive meanwhile wait their turn in order (a repeat of the last one is dropped).
    var queue = [], busy = false;
    function set(state) {
      var last = queue.length ? queue[queue.length - 1] : (st.next || st.state);
      if (state === last) return;
      if (!st.state || opts.still) { queue = []; apply(state); return; }
      queue.push(state);
      pump();
    }
    function pump() {
      if (busy || !queue.length) return;
      busy = true;
      setTimeout(function () {
        var state = st.next = queue.shift();
        birds.classList.add('swap');
        setTimeout(function () {
          st.next = null;
          birds.classList.remove('swap');
          apply(state);
          busy = false;
          pump();
        }, 200);
      }, Math.max(0, STAGE_DWELL - (performance.now() - st.t0)));
    }
    apply(opts.state || 'idle');
    if (opts.still) requestAnimationFrame(function () { draw(0); });
    else requestAnimationFrame(loop);
    return { el: el, set: set };
  }

  // New answers fade in word by word. Only text nodes are split, so links and bold keep working;
  // long answers speed up so the whole reveal stays around a second.
  function revealWords(root) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), nodes = [], n, words = 0, i = 0;
    while ((n = walker.nextNode())) {
      if (n.nodeValue.trim() && n.parentNode.closest('.bubble')) { nodes.push(n); words += n.nodeValue.trim().split(/\s+/).length; }
    }
    var step = Math.min(30, 1100 / Math.max(words, 1));
    nodes.forEach(function (t) {
      var frag = document.createDocumentFragment();
      t.nodeValue.split(/(\s+)/).forEach(function (part) {
        if (!part) return;
        if (!part.trim()) { frag.appendChild(document.createTextNode(part)); return; }
        frag.appendChild(h('span', { class: 'w', style: 'animation-delay:' + Math.round(140 + i++ * step) + 'ms' }, part));
      });
      t.parentNode.replaceChild(frag, t);
    });
  }

  // Robin's mark above greetings and empty states: the gliding swallow, `ringed` in its 90% ring.
  function markBird(ringed) {
    if (!ringed) return h('span', { class: 'dl' }, bird());
    // The large ringed marks (Home, a new conversation, the Settings preview) are live: the swallow glides on
    // a soft breathing glow, with its shadow on the ground below.
    return h('span', { class: 'dl mr' }, h('i', { class: 'dl-aura' }), h('i', { class: 'dl-shadow' }), ringedBird());
  }


  /* --------------------------------------------------------------- styles */

  // Dark: deependhq.com's navy night (identity kit v1): the site's bg / surface / card steps, its three text tiers,
  // marigold as the accent, build green and its danger text; hairlines keep a crisp edge on the navy.
  var DARK_TOKENS = '--paper:#0E1A33;--surface:#15213A;--sunk:#1C2841;--line:#303C53;--line-2:#434E64;' +
    '--ink:#F4EBD9;--ink-2:#A9ABA6;--ink-3:#9098AA;--hero:#0B1529;--ok:#30E060;--ok-bg:#12301F;--ok-line:#1F5E36;' +
    '--danger:#F37050;--on-danger:#0E1A33;--shadow-lg:0 24px 60px -12px rgba(0,0,0,.6),0 2px 6px rgba(0,0,0,.3);--shadow-sm:0 1px 2px rgba(0,0,0,.3);' +
    '--ring:rgba(255,255,255,.08);--robin-primary-soft:var(--robin-primary-soft-dark);--robin-primary-text:var(--robin-primary-text-dark);' +
    '--logo:#F4EBD9;--navy:#F4EBD9;--ai:#F4A62A;--ai-deep:#F8C26A;--ai-mid:#F4A62A;--ai-lav:#795D33;--ai-pale:#423B37;--ai-pink:#F7C46B;' +
    '--user-bubble:#1C2841;--ai-wash:rgba(244,166,42,.12);--on-ai:#0E1A33';

  var CSS = [
    ':host{all:initial}',
    '*{box-sizing:border-box}',
    '.root{' +
      // deependhq.com's paper band on white: navy ink in three tiers, paper cream fills, tan hairlines.
      '--paper:#FFFFFF;--surface:#FFFFFF;--sunk:#FBF5EA;--line:#EAE3D5;--line-2:#DCD2BF;' +
      '--ink:#0E1A33;--ink-2:#3F4A5E;--ink-3:#5A6478;' +
      // Conversation screen: navy controls, the marigold accent family (marigold-ink as text), cream user bubbles.
      '--logo:#0E1A33;--cr-mask:url("' + CR_MASK + '");--navy:#0E1A33;--ai:#8A5A00;--ai-deep:#6E4800;--ai-mid:#F4A62A;--ai-lav:#F8C877;--ai-pale:#FCE6BE;--ai-pink:#F7B955;' +
      '--user-bubble:#F4EBD9;--ai-wash:#FDF4E3;' +
      '--hero:#0E1A33;--hero-ink:#F4EBD9;--hero-2:#A9ABA6;' +
      '--ok:#26784C;--ok-bg:#EDF6F0;--ok-line:#CFE7D8;--danger:#B42318;--on-danger:#FFFFFF;--on-ai:#FFFFFF;' +
      '--shadow-lg:0 24px 60px -12px rgba(14,26,51,.32),0 2px 6px rgba(14,26,51,.08);' +
      '--shadow-sm:0 1px 2px rgba(14,26,51,.05),0 6px 18px -8px rgba(14,26,51,.14);' +
      '--ring:rgba(14,26,51,.06);--ease:cubic-bezier(.16,1,.3,1);' +
      '--robin-primary-soft:var(--robin-primary-soft-light);--robin-primary-text:var(--robin-primary-text-light);' +
      '--font:"Figtree",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;' +
      '--display:"Bricolage Grotesque","Figtree",-apple-system,"Segoe UI",system-ui,sans-serif;' +
      'font:15px/1.5 var(--font);color:var(--ink);-webkit-font-smoothing:antialiased}',
    '.root[data-scheme=dark]{' + DARK_TOKENS + '}',
    '@media (prefers-color-scheme:dark){.root[data-scheme=auto]{' + DARK_TOKENS + '}}',
    'button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer;-webkit-tap-highlight-color:transparent}',
    'button:focus-visible,input:focus-visible,a:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--robin-primary-text);outline-offset:2px}',
    '.panel:focus{outline:none}',
    'svg{display:block}',
    '.av{border-radius:50%;overflow:hidden;flex:none;display:block}',
    '.av svg,.av img{width:100%;height:100%;object-fit:cover}',
    // The live swallow: three masked copies of the mark, clipped to the tail (far), the body and head, and the wing
    // (near). The wing beats from its shoulder; the tail flicks from its root.
    '.cr{position:relative;display:block;width:100%;height:100%}',
    '.cr-m{position:absolute;inset:0}',
    '.cr-m>i{position:absolute;inset:0;background:var(--logo);-webkit-mask:var(--cr-mask) center/contain no-repeat;mask:var(--cr-mask) center/contain no-repeat}',
    '.cr-far{clip-path:polygon(0% 57%,39% 59%,45.5% 70%,46% 100%,0% 100%);transform-origin:41% 64%}',
    // The body reaches a little under each wing so no hairline shows where the layers meet.
    '.cr-body{clip-path:polygon(64.5% 0%,100% 0%,100% 100%,44% 100%,43.5% 71%,37.5% 61%,0% 59%,0% 39%,52% 42%,65.5% 20%)}',
    '.cr-near{clip-path:polygon(0% 0%,66.5% 0%,67.5% 21%,54% 44%,0% 41%);transform-origin:60% 34%}',
    // In list avatars the swallow sits at rest on a soft disc.
    '.av:has(>.cr){display:grid;place-items:center;background:var(--sunk)}',
    '.av>.cr{width:66%;height:66%}',
    '.av.mark>.cr{width:100%;height:100%}',
    '.av.mark:has(>.cr){background:none}',
    '.mr{position:relative}',
    '.mr-ring{position:absolute;inset:0;display:block;color:var(--logo);transition:color .38s var(--ease)}',
    '.mr-ring svg{display:block;width:100%;height:100%;overflow:visible}',
    '.mr-ring circle{fill:none;stroke:currentColor;stroke-width:var(--mr-sw,1);stroke-linecap:round;transition:opacity .38s var(--ease)}',
    '.mr-track{opacity:.22;stroke-dasharray:90 10}',
    // On dark the light track needs a little more weight to read as a ring.
    '.root[data-scheme=dark] .mr-track{opacity:.34}',
    '@media (prefers-color-scheme:dark){.root[data-scheme=auto] .mr-track{opacity:.34}}',
    '.mr-arc{opacity:0;stroke-dasharray:10 90;animation:mrArc 2.4s linear infinite}',
    // The arc runs clockwise all the way round, staying in view as it crosses the gap. It only shows while it
    // moves, so with reduced motion the ring is the plain 90% circle.
    '@keyframes mrArc{from{stroke-dashoffset:0;opacity:.85}to{stroke-dashoffset:-100;opacity:.85}}',
    '.av.mark.mr>.cr,.p-logo.mr>.cr,.dl.mr>.cr{position:absolute;left:14%;top:14%;width:72%;height:72%}',
    // Large marks: a faint glow in the accent colour (lavender, or the chosen brand colour).
    '.dl-aura{position:absolute;inset:-16%;border-radius:50%;pointer-events:none;background:radial-gradient(circle,color-mix(in srgb,var(--ai) 11%,transparent) 0,transparent 68%);filter:blur(12px);animation:auBreath 4s ease-in-out infinite}',
    // The shadow breathes with the glide (same 3.4s): narrower and fainter as the swallow rises.
    '.dl-shadow{position:absolute;left:28%;right:28%;bottom:9%;height:7%;border-radius:50%;pointer-events:none;background:radial-gradient(closest-side,color-mix(in srgb,var(--logo) 26%,transparent),transparent);animation:shBreath 3.4s ease-in-out infinite}',
    '.dot{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px rgba(47,143,91,.18);flex:none}',

    /* launcher */
    '.launcher{position:fixed;bottom:20px;right:20px;width:56px;height:56px;border-radius:50%;background:var(--robin-primary);color:var(--robin-on-primary);box-shadow:0 12px 28px -8px rgba(14,26,51,.45),inset 0 0 0 1px rgba(255,255,255,.14);display:grid;place-items:center;transition:transform .3s var(--ease),opacity .2s ease}',
    '.launcher:hover{transform:translateY(-2px)}',
    '.launcher:active{transform:scale(.95)}',
    '.launcher .ic{position:absolute;width:26px;height:26px;transition:transform .35s var(--ease),opacity .2s ease}',
    '.launcher .ic-chat{width:34px;height:34px}',
    '.launcher .cr{--logo:currentColor}',
    '.launcher .ic-close{opacity:0;transform:rotate(-90deg) scale(.6)}',
    '.root:not([data-mode=hidden]) .launcher .ic-chat{opacity:0;transform:rotate(90deg) scale(.6)}',
    '.root:not([data-mode=hidden]) .launcher .ic-close{opacity:1;transform:none}',
    '.root[data-mode=full] .launcher{opacity:0;transform:scale(.6);pointer-events:none}',
    '.badge{position:absolute;top:-3px;right:-3px;min-width:20px;height:20px;padding:0 6px;border-radius:10px;background:var(--hero);color:var(--hero-ink);font-size:11px;font-weight:700;display:grid;place-items:center;box-shadow:0 0 0 2px var(--paper)}',
    '.badge[hidden]{display:none}',

    /* teaser */
    '.teaser{position:fixed;bottom:88px;right:20px;width:300px;max-width:calc(100vw - 40px)}',
    '.teaser[hidden]{display:none}',
    '.tz-card{position:relative;padding:11px 12px 12px 14px;border:1.5px solid transparent;border-radius:20px 20px 6px 20px;' +
      'background:linear-gradient(var(--surface),var(--surface)) padding-box,linear-gradient(110deg,var(--ai-pink),var(--ai) 50%,var(--ai-lav)) border-box;background-size:100% 100%,220% 100%;' +
      'box-shadow:0 18px 40px -16px rgba(14,26,51,.38),0 4px 10px -6px rgba(14,26,51,.12);transform-origin:bottom right}',
    '.tz-head{display:flex;align-items:center;gap:8px;margin-bottom:4px}',
    '.tz-logo{display:block;width:26px;height:26px;flex:none}',
    '.tz-logo>*{display:block;width:100%;height:100%;object-fit:cover}',
    '.tz-head b{font-family:var(--display);font-size:14px;font-weight:650;color:var(--navy)}',
    '.tz-time{font-size:11.5px;color:var(--ink-3)}',
    '.tz-x{margin-left:auto;width:26px;height:26px;border-radius:50%;display:grid;place-items:center;color:var(--ink-3);transition:background .15s,color .15s,transform .2s var(--ease)}',
    '.tz-x:hover{background:var(--sunk);color:var(--navy);transform:rotate(90deg)}',
    '.tz-x svg{width:13px;height:13px}',
    '.tz-body{display:block;width:100%;min-height:24px;text-align:left;font-size:14.5px;line-height:1.45;color:var(--ink)}',
    '.tz-body .typing{display:inline-flex;padding:7px 0}.tz-body .typing i{background:var(--ai-mid)}',
    '.tz-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}',
    '.tz-chips:empty{display:none}',
    '.tz-chip{display:inline-flex;align-items:center;gap:6px;min-height:30px;padding:4px 11px 4px 5px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--navy);font-size:12.5px;font-weight:500;transition:border-color .2s,background .2s,color .2s,transform .2s var(--ease)}',
    '.tz-chip .i{width:21px;height:21px;border-radius:50%;color:var(--ai);transition:background .2s,color .2s}',
    '.tz-chip .i svg{width:12px;height:12px}',
    '.tz-chip:hover{border-color:var(--ai-lav);background:var(--ai-wash);color:var(--ai-deep);transform:translateY(-1px)}',
    '.tz-chip:hover .i{background:var(--ai);color:var(--on-ai)}',
    '.tz-chip:active{transform:scale(.96)}',

    /* panel + window states */
    '.panel{position:fixed;right:20px;bottom:88px;width:384px;height:min(max(480px,52vh),calc(100vh - 108px));background:var(--paper);color:var(--ink);border-radius:22px;box-shadow:var(--shadow-lg),0 0 0 1px var(--ring);overflow:hidden;display:flex;flex-direction:column;transform-origin:bottom right;' +
      'transition:height .42s var(--ease),width .42s var(--ease),bottom .42s var(--ease),opacity .2s ease,transform .3s var(--ease)}',
    '.root[data-mode=hidden] .panel{opacity:0;transform:translateY(16px) scale(.96);visibility:hidden;pointer-events:none;transition:opacity .16s ease,transform .22s ease,height .3s var(--ease),width .3s var(--ease),bottom .3s var(--ease),visibility 0s .3s}',
    '.root[data-mode=half] .panel{width:400px;height:min(max(480px,52vh),calc(100vh - 108px))}',
    '.root[data-mode=full] .panel{width:440px;bottom:16px;height:calc(100vh - 32px)}',
    // Wide: full height at half the screen's width; the thread and input stay a readable column.
    '.root[data-wide] .panel{width:min(max(440px,50vw),calc(100vw - 40px))}',
    '.root[data-wide] .thread{width:100%;max-width:780px;margin:0 auto;padding-left:24px;padding-right:24px}',
    '.root[data-wide] .msg.bot .col{max-width:min(calc(100% - 36px),560px)}',
    '.root[data-wide] .composer{padding-left:max(24px,calc((100% - 732px) / 2));padding-right:max(24px,calc((100% - 732px) / 2))}',
    '.root[data-wide] .epick{left:max(24px,calc((100% - 732px) / 2));right:auto;width:360px}',
    '.root[data-pos=left] .launcher,.root[data-pos=left] .panel,.root[data-pos=left] .teaser{right:auto;left:20px}',
    '.root[data-pos=left] .panel{transform-origin:bottom left}',
    '.root[data-pos=left] .tz-card{border-radius:20px 20px 20px 6px;transform-origin:bottom left}',
    '.grab{display:none}',
    '.view{display:flex;flex-direction:column;flex:1 1 auto;min-height:0;animation:fade .24s var(--ease)}',
    '.scroll{flex:1;overflow-y:auto;min-height:0;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:var(--line-2) transparent}',

    /* stepper + icon buttons */
    '.stepper{display:inline-flex;align-items:center;gap:2px;padding:2px;border-radius:999px;background:var(--sunk)}',
    '.stepper button,.ibtn{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;color:var(--ink-2);transition:background .15s,color .15s,opacity .15s}',
    '.stepper button:hover:not(:disabled){background:var(--surface);color:var(--ink)}',
    '.ibtn:hover{background:var(--sunk);color:var(--ink)}',
    '.stepper .off{display:none}',
    '.stepper svg,.ibtn svg{width:18px;height:18px}',

    /* home */
    /* home and messages, in the conversation screen's style (header, cards, purple accents) */
    '.home,.msgs{background:var(--paper)}',
    '.head-name{font-family:var(--display);font-size:15.5px;font-weight:650;color:var(--navy)}',
    '.head-l>.presence{width:32px;height:32px}',
    '.head-title{margin:0 0 0 4px;font-family:var(--display);font-size:20px;font-weight:650;letter-spacing:-.015em;color:var(--navy)}',
    '.head-count{min-width:22px;height:22px;padding:0 7px;border-radius:999px;display:grid;place-items:center;background:var(--ai-wash);color:var(--ai);font-size:12px;font-weight:700}',
    '.home-scroll{padding:0 16px 14px;display:flex;flex-direction:column;gap:12px}',
    '.home-scroll>*{flex:none}',   // scroll rather than squash the cards
    '.home-hero{padding:14px 4px 0;text-align:center}',   // room above for the mark's glow
    '.home-hero .dl{display:block;width:128px;height:128px;margin:0 auto 6px;--mr-sw:.36}',
    '.home-hero h2,.home-hero h3{margin:0;font-family:var(--display);font-size:22px;font-weight:650;line-height:1.15;letter-spacing:-.02em}',
    '.home-hero h2{color:var(--ink-3)}.home-hero h3{color:var(--navy)}',
    '.root[data-mode=half] .home-hero h2,.root[data-mode=half] .home-hero h3{font-size:20px}',
    // The ask field looks like the conversation input and takes its pink-to-purple edge on hover.
    '.home .ask{display:flex;align-items:center;gap:10px;width:100%;min-height:54px;padding:6px 6px 6px 18px;border:1.5px solid transparent;border-radius:24px;text-align:left;' +
      'background:linear-gradient(var(--surface),var(--surface)) padding-box,linear-gradient(var(--line),var(--line)) border-box;box-shadow:0 12px 28px -16px rgba(14,26,51,.24),0 2px 6px -2px rgba(14,26,51,.06);transition:box-shadow .3s}',
    '.home .ask:hover,.home .ask:focus-visible{background:linear-gradient(var(--surface),var(--surface)) padding-box,linear-gradient(110deg,var(--ai-pink),var(--ai) 50%,var(--ai-pink)) border-box;box-shadow:0 14px 30px -16px color-mix(in srgb,var(--ai) 50%,transparent);outline:none}',
    '.ask-t{flex:1;min-width:0;color:var(--ink-3);font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.ask-go{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;flex:none;background:var(--navy);color:var(--paper);transition:transform .25s var(--ease)}',
    '.ask-go svg{width:18px;height:18px}',
    '.home .ask:hover .ask-go{transform:translateX(2px)}',
    // Cards on Home: a small caps title, then rows with purple icon tiles that fill purple on hover.
    '.hcard{border-radius:18px;background:var(--surface);box-shadow:0 1px 2px rgba(14,26,51,.04),0 10px 26px -18px rgba(14,26,51,.2),0 0 0 1px var(--line);overflow:hidden}',
    '.hcard-t{display:flex;align-items:center;gap:7px;padding:12px 16px 4px;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)}',
    '.hcard-t .i svg{width:13px;height:13px}',
    '.home .row{min-height:50px;padding:9px 14px}',
    '.home .row .t{color:var(--navy);font-weight:500}',
    '.home .row .ico{border-radius:10px;background:var(--ai-wash);color:var(--ai);transition:background .2s,color .2s,transform .25s var(--ease)}',
    '.home .row:hover{background:var(--ai-wash)}',
    '.home .row:hover .ico{background:var(--ai);color:var(--on-ai)}',
    '.home .row:hover .chev{color:var(--ai)}',
    // Messages: conversations as card rows; a friendly empty state.
    '.mlist{padding:6px 12px 12px;display:flex;flex-direction:column;gap:8px}',
    '.mrow{display:flex;align-items:center;gap:12px;width:100%;padding:10px 12px;border-radius:16px;text-align:left;background:var(--surface);box-shadow:0 0 0 1px var(--line),0 4px 12px -10px rgba(14,26,51,.25);transition:background .15s,box-shadow .2s,transform .18s var(--ease)}',
    '.mrow:hover{background:var(--ai-wash);box-shadow:0 0 0 1px var(--ai-lav),0 8px 18px -12px color-mix(in srgb,var(--ai) 45%,transparent)}',
    '.mrow:active{transform:scale(.98)}',
    '.mrow .av{width:40px;height:40px}',
    '.mrow .grow{flex:1;min-width:0}',
    '.mrow-top{display:flex;align-items:baseline;gap:8px}',
    '.mrow .t{flex:1;min-width:0;font-weight:600;color:var(--navy);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.mrow .time{margin:0;align-self:auto;flex:none;font-size:11.5px;color:var(--ink-3)}',
    '.mrow .s{display:block;margin-top:1px;font-size:13px;color:var(--ink-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.mrow .chev{display:grid;flex:none;color:var(--ink-3);transition:transform .2s var(--ease),color .2s}',
    '.mrow .chev svg{width:16px;height:16px}',
    '.mrow:hover .chev{transform:translateX(2px);color:var(--ai)}',
    '.mempty{display:flex;flex-direction:column;align-items:center;text-align:center;padding:64px 28px 24px}',
    // Messages search: the Home ask field's look (white pill, hairline that turns pink-to-purple on hover and focus).
    '.msearch-wrap{flex:none;padding:2px 12px 6px}',
    '.msearch{display:flex;align-items:center;gap:10px;min-height:48px;padding:4px 6px 4px 16px;border:1.5px solid transparent;border-radius:24px;cursor:text;' +
      'background:linear-gradient(var(--surface),var(--surface)) padding-box,linear-gradient(var(--line),var(--line)) border-box;box-shadow:0 12px 28px -16px rgba(14,26,51,.24),0 2px 6px -2px rgba(14,26,51,.06);transition:box-shadow .3s}',
    '.msearch:hover,.msearch:focus-within{background:linear-gradient(var(--surface),var(--surface)) padding-box,linear-gradient(110deg,var(--ai-pink),var(--ai) 50%,var(--ai-pink)) border-box;box-shadow:0 14px 30px -16px color-mix(in srgb,var(--ai) 50%,transparent)}',
    '.msearch-i{display:grid;flex:none;color:var(--ink-3);transition:color .2s}',
    '.msearch-i svg{width:18px;height:18px}',
    '.msearch:focus-within .msearch-i{color:var(--ai)}',
    '.msearch-q{flex:1;min-width:0;height:38px;padding:0;border:0;outline:none;background:transparent;font:inherit;font-size:15px;color:var(--ink)}',
    '.msearch-q:focus-visible{outline:none}',
    '.msearch-q::placeholder{color:var(--ink-3)}',
    '.msearch-q::-webkit-search-cancel-button{-webkit-appearance:none;display:none}',
    '.msearch-x{display:grid;place-items:center;flex:none;width:32px;height:32px;border-radius:50%;color:var(--ink-3);transition:background .15s,color .15s}',
    '.msearch-x:hover{background:var(--sunk);color:var(--ink)}',
    '.msearch-x[hidden],.mrow[hidden],.mnone[hidden]{display:none}',
    '.msearch-x svg{width:15px;height:15px}',
    '.mnone{margin:28px 16px;text-align:center;color:var(--ink-3);font-size:14px}',
    // Help & contact: Home's rows with a quieter line under each title; the about text with the privacy link.
    '.helpv .row .s{font-size:12.5px;line-height:1.4;color:var(--ink-3);white-space:normal}',
    '.help-about{margin:6px 16px 12px;color:var(--ink-2);font-size:13.5px;line-height:1.5}',
    '.help-about a{color:var(--ai);text-decoration:underline;text-underline-offset:2px}',
    // An unread reply (from the server's list): a small accent dot beside the title.
    '.mdot{flex:none;width:8px;height:8px;margin:0 6px 0 auto;border-radius:50%;background:var(--ai)}',
    '.mdot+.time{margin-left:0}',
    // Home: a returning visitor's line under the greeting, and "Your bookings".
    '.hero-line{margin:6px 0 0;color:var(--ink-2);font-size:14px}',
    '.bk{padding:10px 14px 12px}',
    '.bk+.bk{border-top:1px solid var(--line)}',
    '.bk-top{display:flex;align-items:flex-start;gap:12px}',
    '.bk-top .grow{flex:1;min-width:0;padding-top:1px}',
    '.bk-date{display:flex;flex-direction:column;align-items:center;justify-content:center;width:40px;height:44px;flex:none;border-radius:11px;background:var(--ai-wash);color:var(--ai);line-height:1}',
    '.bk-date .m{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}',
    '.bk-date .d{margin-top:3px;font-size:17px;font-weight:700;color:var(--navy);font-variant-numeric:tabular-nums}',
    '.bk-rel{font-weight:700;color:var(--ai)}',
    '.bk-top .ico{display:grid;place-items:center;width:34px;height:34px;flex:none;border-radius:10px;background:var(--ai-wash);color:var(--ai)}',
    '.bk-top .ico svg{width:16px;height:16px}',
    '.bk-top .t{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;font-weight:600;line-height:1.35;color:var(--navy)}',
    '.bk-top .s{display:block;margin-top:3px;font-size:12.5px;line-height:1.4;color:var(--ink-3);overflow-wrap:anywhere}',
    '.bk-acts{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0 52px}',
    '.bk-act{display:inline-flex;align-items:center;gap:6px;min-height:30px;padding:0 12px;border-radius:999px;font-size:12.5px;font-weight:600;color:var(--navy);background:var(--surface);box-shadow:0 0 0 1px var(--line);transition:background .15s,box-shadow .2s,color .15s}',
    '.bk-act svg{width:13px;height:13px}',
    '.bk-act:hover{background:var(--ai-wash);box-shadow:0 0 0 1px var(--ai-lav)}',
    '.bk-act.go{background:var(--robin-primary);color:var(--robin-on-primary);box-shadow:none}',
    '.bk-act.go:hover{filter:brightness(1.08)}',
    '.bk-act.danger{width:auto;min-height:30px;padding:0 12px;gap:6px;font-size:12.5px;color:var(--danger)}',   // not the Settings row's full-width .danger
    '.bk-act.danger:hover{background:color-mix(in srgb,var(--danger) 7%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--danger) 30%,transparent)}',
    // GIFs: the picker's grid, and a sent GIF inside its bubble.
    '.ggrid{grid-template-columns:repeat(3,1fr);gap:6px}',
    '.ggrid button{aspect-ratio:1;overflow:hidden;padding:0;border-radius:10px;background:var(--sunk)}',
    '.ggrid img{display:block;width:100%;height:100%;object-fit:cover}',
    '.bubble img.gif{display:block;max-width:min(240px,100%);border-radius:12px}',
    '.presence[data-state=gif]{--p-c:#E8A21A}.presence[data-state=offline]{--p-c:var(--ink-3)}',
    '.presence[data-state=gif] .p-badge svg{animation:nudge .8s ease-in-out infinite}',
    '.mempty .dl{display:block;width:44px;height:44px;margin-bottom:16px}',
    '.mempty h4{margin:0 0 6px;font-family:var(--display);font-size:19px;font-weight:650;color:var(--navy)}',
    '.mempty p{margin:0;max-width:280px;color:var(--ink-2);font-size:14px}',
    // Settings: cards with small caps titles; the avatar choices and the appearance switch sit inside them.
    '.setv{background:var(--paper)}',
    '.sset .seg{margin:8px 14px 14px}',
    '.setv .seg button{color:var(--ink-2)}',
    '.setv .seg button[aria-checked=true]{color:var(--navy)}',
    '.setv .seg button[aria-checked=true] .i{color:var(--ai)}',
    '.setv .seg-ind{box-shadow:0 1px 3px rgba(14,26,51,.12),0 0 0 1px var(--line)}',
    '.setv .danger{gap:12px;min-height:58px;padding:10px 14px;color:var(--navy);font-weight:500;transition:background .15s}',
    '.setv .danger:hover{background:color-mix(in srgb,var(--danger) 6%,transparent)}',
    '.dz-ic{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;flex:none;background:color-mix(in srgb,var(--danger) 10%,transparent);color:var(--danger)}',
    '.dz-ic .i svg{width:16px;height:16px}',
    '.setv .danger .grow{flex:1;min-width:0}',
    '.setv .danger .t{display:block;font-weight:600;color:var(--danger)}',
    '.setv .danger .s{display:block;font-size:12.5px;color:var(--ink-3)}',
    '.setv .danger .chev{display:grid;color:var(--ink-3);transition:transform .2s var(--ease)}',
    '.setv .danger .chev svg{width:16px;height:16px}',
    '.setv .danger:hover .chev{transform:translateX(2px);color:var(--danger)}',
    // Home's "pick up" row: the conversation's name, the last message under it, and how long ago.
    '.home .row.last .t,.home .row.last .s{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.home .row.last .t{font-weight:600}',
    '.home .row.last .time{align-self:center;margin:0}',
    '.home .row.last .av{width:38px;height:38px}',
    '.root .msgs .pill{background:var(--navy);color:var(--paper);box-shadow:0 12px 24px -12px rgba(14,26,51,.7)}',
    '.root .msgs .pill:hover{filter:brightness(1.15)}',
    // Home and Messages motion: the greeting, ask field and cards rise in turn; the swallow mark glides;
    // conversation rows arrive one by one.
    '.home-hero>*,.home .ask,.home .hcard{animation:rise .5s var(--ease) backwards}',
    '.home-hero>:nth-child(2){animation-delay:.05s}.home-hero>:nth-child(3){animation-delay:.1s}',
    '.home .ask{animation-delay:.15s}.home .hcard{animation-delay:.22s}.home .hcard+.hcard{animation-delay:.29s}',
    '.mlist .mrow{animation:rise .4s var(--ease) backwards;animation-delay:calc(var(--i,0) * 45ms)}',
    '.mempty>*{animation:rise .5s var(--ease) backwards}.mempty>:nth-child(2){animation-delay:.06s}.mempty>:nth-child(3){animation-delay:.12s}',
    '.card{background:var(--surface);border-radius:16px;box-shadow:var(--shadow-sm),0 0 0 1px var(--line);overflow:hidden}',
    '.eyebrow{font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)}',
    '.card .eyebrow{padding:14px 16px 4px}',
    '.row{display:flex;align-items:center;gap:12px;width:100%;min-height:52px;padding:10px 16px;text-align:left;transition:background .12s}',
    '.row:hover{background:var(--sunk)}',
    '.row + .row{box-shadow:inset 0 1px 0 var(--line)}',
    '.row .ico{width:32px;height:32px;border-radius:50%;background:var(--sunk);color:var(--robin-primary-text);display:grid;place-items:center;flex:none}',
    '.row:hover .ico{background:var(--surface)}',
    '.row .ico svg{width:16px;height:16px}',
    '.row .grow{flex:1;min-width:0}',
    '.row .t{display:block;font-weight:600}',
    '.row .s{display:block;font-size:13px;color:var(--ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.row .chev{width:16px;height:16px;color:var(--ink-3);flex:none;transition:transform .2s var(--ease)}',
    '.row:hover .chev{transform:translateX(2px);color:var(--ink)}',
    '.row .av{width:36px;height:36px}',
    '.time{font-size:12px;color:var(--ink-3);align-self:flex-start;margin-top:3px;flex:none}',

    /* tabs */
    '.tabs{display:flex;gap:6px;padding:8px 10px calc(8px + env(safe-area-inset-bottom));background:var(--surface);box-shadow:inset 0 1px 0 var(--line)}',
    '.tab{flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;min-height:48px;justify-content:center;border-radius:14px;font-size:12.5px;font-weight:600;color:var(--ink-3);transition:background .15s,color .15s}',
    '.tab svg{width:21px;height:21px}',
    '.tab:hover{color:var(--navy)}',
    '.tab[aria-selected=true]{color:var(--navy)}',
    '.tab[aria-selected=true] svg{color:var(--ai)}',

    /* bars */

    /* conversation screen: a clean white canvas */
    '.chat{position:relative;background:var(--paper)}',
    // Header: three elements, home / title menu / window menu, on the canvas itself.
    // Home and the title pill on the left; wider view, size chevrons, settings and close on the right.
    '.chat-head{position:relative;z-index:3;flex:none;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 12px 8px 14px}',
    '.head-l{display:flex;align-items:center;gap:8px;min-width:0}',
    '.head-r{display:flex;align-items:center;gap:6px;flex:none}',
    '.chat-head .cbtn{width:36px;height:36px}',
    '.chat-head .title-pill{min-height:36px;padding-left:3px}',
    // The swallow fills most of the pill's height.
    '.chat-head .title-pill .presence{width:32px;height:32px}',
    // The size chevrons as one bordered pill (a single round button when only one applies).
    '.chat-head .stepper{gap:0;padding:0;border-radius:999px;background:var(--surface);box-shadow:0 0 0 1px var(--line),0 1px 3px rgba(14,26,51,.06)}',
    '.chat-head .stepper button{width:34px;height:34px;color:var(--navy)}',
    '.chat-head .stepper button:hover:not(:disabled){color:var(--ai);background:var(--ai-wash)}',
    '.cbtn{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;flex:none;background:var(--surface);color:var(--navy);box-shadow:0 0 0 1px var(--line),0 1px 3px rgba(14,26,51,.06);transition:background .15s,box-shadow .2s,transform .18s var(--ease)}',
    '.cbtn:hover{color:var(--ai);background:var(--ai-wash);box-shadow:0 0 0 1px var(--ai-lav),0 6px 14px -8px color-mix(in srgb,var(--ai) 55%,transparent)}',
    '.title-pill:hover{box-shadow:0 0 0 1px var(--ai-lav),0 6px 14px -8px color-mix(in srgb,var(--ai) 55%,transparent)}',
    '.title-pill:hover>i{color:var(--ai)}',
    // Tooltips (replacing the browser's): a small navy label with an arrow pointing at the control, above it, or
    // below when there's no room; it fades and slides in quickly after a brief pause.
    '.tip{position:fixed;left:0;top:0;z-index:40;width:max-content;max-width:200px;padding:3px 8px;border-radius:7px;background:var(--navy);color:var(--paper);font-size:11px;font-weight:600;line-height:1.35;pointer-events:none;opacity:0;transform:translateY(3px) scale(.97);transition:opacity .1s ease,transform .14s var(--ease);box-shadow:0 6px 16px -8px rgba(14,26,51,.55)}',
    '.tip.below{transform:translateY(-3px) scale(.97)}',
    '.tip.on{opacity:1;transform:none}',
    '.tip::after{content:"";position:absolute;top:100%;left:var(--ax,50%);margin-left:-4px;border:4px solid transparent;border-top-color:var(--navy)}',
    '.tip.below::after{top:auto;bottom:100%;border-top-color:transparent;border-bottom-color:var(--navy)}',
    '.cbtn:active,.title-pill:active{transform:scale(.94)}',
    '.cbtn svg{width:18px;height:18px}',
    '.cbtn[aria-expanded=true],.title-pill[aria-expanded=true]{background:var(--sunk)}',
    '.title-pill{display:inline-flex;align-items:center;gap:8px;min-width:0;min-height:40px;padding:0 14px 0 6px;border-radius:999px;background:var(--surface);color:var(--navy);box-shadow:0 0 0 1px var(--line),0 1px 3px rgba(14,26,51,.06);font-weight:600;font-size:15px;transition:background .15s,box-shadow .2s,transform .18s var(--ease)}',
    '.title-pill>span:last-of-type{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.title-pill>i{display:grid;flex:none}',
    '.title-pill>i svg{width:16px;height:16px;transition:transform .25s var(--ease)}',
    '.title-pill[aria-expanded=true]>i svg{transform:rotate(180deg)}',
    // Presence: the swallow in the title pill, a small status badge at its lower right, and a fine ring or soft waves
    // hugging it, all kept inside the pill. One colour per state.
    '.presence{position:relative;display:grid;place-items:center;flex:none;width:26px;height:26px;--p-c:var(--ai)}',
    '.presence .p-logo{display:block;width:100%;height:100%}',
    '.p-ring,.p-wave{position:absolute;inset:-2px;border-radius:50%;pointer-events:none;opacity:0}',
    '.p-ring{inset:0}',
    // Answer arrived: the ring closes in green; failed: it turns red.
    '.presence[data-state=done] .mr-ring{color:var(--ok)}.presence[data-state=error] .mr-ring{color:var(--danger)}',
    '.presence[data-state=done] .mr-track,.presence[data-state=error] .mr-track{opacity:1}',
    '.p-ring{background:conic-gradient(from 0deg,transparent 0 40%,var(--p-c) 100%);-webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 2px),#000 calc(100% - 1.5px));mask:radial-gradient(farthest-side,transparent calc(100% - 2px),#000 calc(100% - 1.5px))}',
    '.p-wave{border:1.5px solid var(--p-c)}',
    '.p-badge{position:absolute;right:-3px;bottom:-3px;width:14px;height:14px;border-radius:50%;display:grid;place-items:center;background:var(--p-c);color:#fff;box-shadow:0 0 0 2px var(--surface)}',
    '.p-badge svg{width:8px;height:8px;stroke-width:2.8}',
    '.presence[data-state=listening]{--p-c:#E5484D}.presence[data-state=muted]{--p-c:var(--ink-3)}.presence[data-state=speaking]{--p-c:var(--ai-mid)}',
    '.presence[data-state=done]{--p-c:var(--ok)}.presence[data-state=error]{--p-c:var(--danger)}.presence[data-state=emoji]{--p-c:#E8A21A}',
    '.presence[data-state=attaching],.presence[data-state=stopped]{--p-c:var(--navy)}',
    '.presence[data-state=attaching] .p-badge,.presence[data-state=stopped] .p-badge{color:var(--paper)}',
    '.presence[data-state=muted] .p-ring{opacity:.5;background:var(--p-c)}',
    // Header menus drop down under their button.
    '.hpop{position:absolute;z-index:9;top:58px;min-width:220px;max-width:calc(100% - 28px);padding:5px;border-radius:16px;background:var(--surface);box-shadow:var(--shadow-lg),0 0 0 1px var(--line);transform-origin:top center;animation:popin .16s var(--ease) both}',
    '.hpop{left:14px;width:250px;transform-origin:top left}',
    '.hpop button{display:flex;align-items:center;gap:10px;width:100%;min-height:40px;padding:8px 12px;border-radius:11px;font-size:14px;color:var(--navy);text-align:left}',
    '.hpop button:hover,.hpop button:focus-visible{background:var(--sunk)}',
    '.hpop button:focus-visible,.pmenu button:focus-visible,.egrid button:focus-visible{outline:none;box-shadow:inset 0 0 0 2px var(--ai)}',
    '.hpop button i{display:grid;flex:none;color:var(--ink-3)}',
    '.hpop button svg{width:17px;height:17px}',
    '.hpop button span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.hpop button[aria-current=true]{font-weight:700}',
    '.hpop button[aria-current=true] i{color:var(--ai)}',
    '.hpop hr{margin:4px 8px;border:0;border-top:1px solid var(--line)}',

    /* thread */
    '.thread{position:relative;min-height:100%;padding:10px 18px 22px;display:flex;flex-direction:column;gap:22px}',
    '.msg{display:flex;gap:10px;align-items:flex-start;max-width:100%}',
    '.msg .av{width:28px;height:28px}',
    '.msg .col{display:flex;flex-direction:column;gap:12px;min-width:0;flex:1}',
    '.msg.user{justify-content:flex-end}',
    '.msg.user .col{align-items:flex-end;flex:none;max-width:82%}',
    // Robin's answer: a name line (mark, name, time), the content full width under it, then quiet actions.
    // Only the visitor's question sits in a (light grey) bubble.
    '.msg.bot{flex-direction:column;align-items:stretch;gap:8px}',
    '.ai-head{display:flex;align-items:center;gap:8px;font-size:13px;line-height:20px;color:var(--ink-3)}',
    '.ai-head .av.mark{width:34px;height:34px;border-radius:0;overflow:visible}',
    '.ai-head b{font-weight:650;color:var(--navy)}',
    '.ai-head time{display:flex;align-items:center;gap:8px;font-variant-numeric:tabular-nums}',
    '.ai-head time::before{content:"";width:3px;height:3px;border-radius:50%;background:currentColor;opacity:.6}',
    '.msg.bot .col{padding-left:38px}',
    '.bubble{overflow-wrap:anywhere;max-width:100%;line-height:1.65;color:var(--ink)}',
    '.msg.bot .bubble{font-size:15px}',
    '.bubble strong{font-weight:700;color:var(--navy)}',
    '.bubble a{color:var(--ai);text-decoration:underline;text-decoration-color:color-mix(in srgb,var(--ai) 40%,transparent);text-underline-offset:3px}',
    '.bubble a:hover{text-decoration-color:currentColor}',
    '.bubble ul,.bubble ol{margin:6px 0;padding-left:22px}',
    '.bubble li{margin:4px 0;padding-left:2px}',
    '.bubble li::marker{color:var(--ai);font-weight:600}',
    '.bubble code{padding:1px 6px;border-radius:6px;background:var(--sunk);font:13px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--navy)}',
    '.msg.user .bubble{padding:10px 16px;border-radius:20px 20px 6px 20px;background:var(--user-bubble);color:var(--navy);line-height:1.45}',
    '.msg.user .bubble a{color:inherit}',
    '.msg.user .bubble strong{color:inherit}',
    '.bubble.error{padding:11px 14px;border-radius:14px;background:color-mix(in srgb,var(--danger) 6%,var(--surface));box-shadow:0 0 0 1px color-mix(in srgb,var(--danger) 22%,transparent)}',
    '.caret{display:inline-block;width:7px;height:7px;margin-left:5px;border-radius:50%;background:var(--ai);vertical-align:middle}',
    '.stopped{align-self:flex-start;margin:-12px 0 0 28px;font-size:12.5px;color:var(--ink-3)}',
    // Actions: always shown under the latest answer, on hover or focus under older ones.
    // Copy, Read aloud and the thumbs always show under every answer.
    '.ai-actions{display:flex;gap:2px;margin:-2px 0 0 22px}',
    // Thumbs-down: what went wrong, under the answer's actions.
    '.fb-form{margin:6px 0 2px 22px;padding:12px 14px;border-radius:14px;background:var(--surface);box-shadow:0 1px 2px rgba(28,28,28,.05),0 0 0 1px var(--line);display:grid;gap:10px;animation:rise .25s var(--ease) both}',
    '.fb-t{font-weight:650;font-size:13.5px;color:var(--ink)}',
    '.fb-chips{display:flex;flex-wrap:wrap;gap:6px}',
    '.fb-chip{min-height:30px;padding:4px 11px;font-size:12.5px;color:var(--ink)}',
    '.chat .fb-chip[aria-pressed=true]{border-color:var(--ai);background:var(--ai-wash);color:var(--ai)}',
    '.fb-note{width:100%;resize:none;padding:8px 10px;border-radius:10px;border:1px solid var(--line-2);background:var(--paper);color:var(--ink);font:inherit;font-size:13px;line-height:1.45}',
    '.fb-note:focus{outline:none;border-color:var(--ai);box-shadow:0 0 0 3px var(--ai-wash)}',
    '.fb-row{display:flex;justify-content:flex-end;gap:6px}',
    '.fb-skip,.fb-send{min-height:32px;padding:5px 14px;border-radius:999px;font-weight:600;font-size:13px}',
    '.fb-skip{color:var(--ink-2)}',
    '.fb-skip:hover{background:var(--sunk)}',
    '.fb-send{background:var(--ai);color:var(--on-ai)}',
    '.fb-done{display:flex;align-items:center;gap:6px;margin:4px 0 0 26px;font-size:12.5px;color:var(--ok)}',
    '.fb-done .i svg{width:14px;height:14px}',
    // Answer cards: the server renderer's classes, in Champ Robin's tokens.
    '.uic{--da-line:var(--line);--da-r-md:14px;--da-subtle:var(--sunk);--da-surface:var(--surface);--da-ink:var(--ink);--da-text:var(--ink-2);--da-muted:var(--ink-3);--da-lavender:var(--ai-wash);--da-primary:var(--ai);--da-primary-soft:var(--ai-wash);--da-success:var(--ok);--da-ok-text:var(--ok);--da-danger:var(--danger);--da-danger-soft:rgba(180,35,24,.1);--da-danger-text:var(--danger);color:var(--ink)}',
    '.uic:empty{display:none}',
    '.uic .ui-card{margin-top:2px;border-radius:14px}',
    '.uic .ui-btn{display:inline-flex;align-items:center;gap:6px;border-radius:999px;border:1px solid var(--line-2);background:var(--surface);color:var(--ink);font:inherit;font-weight:600;cursor:pointer;transition:border-color .15s,background .15s}',
    '.uic .ui-btn:hover{border-color:var(--ai);background:var(--ai-wash);color:var(--ai)}',
    '.uic .ui-btn:focus-visible{outline:2px solid var(--ai);outline-offset:2px}',
    '.act{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;color:var(--ink-3);transition:background .15s,color .15s,transform .15s var(--ease)}',
    '.act:hover{color:var(--ai);background:var(--ai-wash)}',
    '.act:active{transform:scale(.88)}',
    '.act svg{width:16px;height:16px;transition:fill .2s}',
    '.act[aria-pressed=true],.act.done{color:var(--ai)}',
    '.act[aria-pressed=true] svg{fill:color-mix(in srgb,var(--ai) 20%,transparent)}',
    // Idle: centred mark, greeting and quick starts.
    '.idle{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:8px 4px 4px;text-align:center}',
    '.idle .rs{--s:.45;margin-bottom:8px}',
    '.idle h3{margin:0;font-family:var(--display);font-size:24px;font-weight:600;letter-spacing:-.02em;color:var(--navy)}',
    '.idle p{margin:6px 0 18px;max-width:280px;color:var(--ink-2);font-size:14.5px}',
    '.idle .chips{justify-content:center}',
    // Loading: the circling swallow in the middle of the space under the question, the status line beneath.
    '.ai-loading{flex:1;min-height:170px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding-bottom:12px}',
    '.ai-loading.out{position:absolute;left:0;right:0;opacity:0;transition:opacity .2s ease;pointer-events:none}',
    // Robin's stage (guide v4 section 4): everything sits in the 320x280 box, scaled by --s. The ring is the
    // swallow's colour; success and failure turn it green and red.
    '.rs{--s:.45;--rs-ring:var(--logo);--rs-ink:var(--paper);--rs-glow:rgba(11,30,45,.10);position:relative;display:block;flex:none;width:calc(320px * var(--s));height:calc(280px * var(--s));color:var(--rs-ring)}',
    '.root[data-scheme=dark] .rs{--rs-glow:rgba(255,255,255,.16)}',
    '@media (prefers-color-scheme:dark){.root[data-scheme=auto] .rs{--rs-glow:rgba(255,255,255,.16)}}',
    '.rs[data-state=success]{--rs-ring:#12B76A;--rs-ink:#fff;--rs-glow:rgba(18,183,106,.30)}',
    '.rs[data-state=error]{--rs-ring:#D92D20;--rs-ink:#fff;--rs-glow:rgba(217,45,32,.28)}',
    '.rs-box{position:absolute;left:0;top:0;width:320px;height:280px;transform:scale(var(--s));transform-origin:0 0}',
    '.rs-box>*{position:absolute;display:block}',
    '.rs-aura{left:30px;top:10px;width:260px;height:260px;border-radius:50%;filter:blur(36px);background:radial-gradient(circle,var(--rs-glow) 0,transparent 70%)}',
    '.rs[data-state=loading] .rs-aura,.rs[data-state=thinking] .rs-aura{background:conic-gradient(from 0deg,var(--rs-glow),transparent 35%,var(--rs-glow) 55%,transparent 85%,var(--rs-glow))}',
    '.rs-shadow{left:105px;top:236px;width:110px;height:10px;border-radius:50%;background:radial-gradient(closest-side,color-mix(in srgb,var(--logo) 20%,transparent),transparent);opacity:0}',
    '.rs-ring{left:40px;top:20px;width:240px;height:240px}',
    '.rs-ring svg{display:block;width:100%;height:100%;overflow:visible}',
    '.rs-ring circle{fill:none;stroke:currentColor;transition:stroke .38s var(--ease)}',
    '.rs-comet{stroke-linecap:round;opacity:0}',
    '.rs-birds{left:76px;top:56px;width:168px;height:168px;transition:opacity .2s var(--ease),transform .2s var(--ease)}',
    '.rs-birds.swap{opacity:0;transform:scale(.88)}',
    '.rs-b{position:absolute;inset:0}',
    '.rs-g,.rs-fill{display:none}',
    '.rs-g.g1{opacity:.18}.rs-g.g2{opacity:.09}',
    '.rs[data-state=success] .rs-g,.rs[data-state=loading] .rs-fill{display:block}',
    '.rs[data-state=loading] .rs-main{opacity:.14}',
    // Signs: rings closing in (listen), dots from the beak (chat), sound arcs (talk), thought bubbles (thinking).
    '.rs-in i{position:absolute;left:55px;top:35px;width:210px;height:210px;border-radius:50%;border:calc(1.5px / var(--s)) solid var(--rs-ring);opacity:0}',
    '.rs-dots{left:250px;top:168px}',
    '.rs-dots i{position:absolute;top:0;left:calc(var(--i) * 11px);width:7px;height:7px;border-radius:50%;background:var(--logo);opacity:0}',
    '.rs-arcs{left:246px;top:150px}',
    '.rs-arcs i{position:absolute;width:calc(14px + var(--i) * 12px);height:calc(14px + var(--i) * 12px);left:calc(-7px - var(--i) * 6px);top:calc(13px - var(--i) * 6px);border-radius:50%;border:calc(1.6px / var(--s)) solid transparent;border-right-color:var(--rs-ring);opacity:0}',
    '.rs-bub{left:0;top:0}',
    '.rs-bub i{position:absolute;border-radius:50%;border:calc(1.5px / var(--s)) solid var(--rs-ring);opacity:0;transform-origin:0 100%}',
    '.rs-bub i:nth-child(1){left:248px;top:146px;width:8px;height:8px}.rs-bub i:nth-child(2){left:258px;top:116px;width:14px;height:14px}.rs-bub i:nth-child(3){left:266px;top:74px;width:30px;height:24px}',
    // The badge in the ring's gap: the state's icon on a disc in the ring's colour.
    '.rs-badge{left:142px;top:238px;width:36px;height:36px}',
    // Search: a handle grows out of the ring at the lower right, so the closed ring reads as a magnifying glass.
    '.rs-handle{left:240px;top:217px;width:50px;height:7px;border-radius:4px;background:var(--rs-ring);opacity:0;transform-origin:0 50%;transform:rotate(45deg) scaleX(0);transition:transform .35s var(--ease),opacity .2s}',
    '.rs[data-state=search] .rs-handle{opacity:.85;transform:rotate(45deg) scaleX(1)}',
    '.rs-bi{display:grid;place-items:center;width:100%;height:100%;border-radius:50%;background:var(--rs-ring);color:var(--rs-ink)}',
    '.rs-bi svg{width:18px;height:18px}',
    '.rs[data-state=listen] .rs-bi svg,.rs[data-state=muted] .rs-bi svg{fill:currentColor}',
    // In the chat the stage sits under the question; over the panel (thinking, opening) it is larger.
    '.veil .rs,.boot .rs{--s:.62}',
    // Opening, inside the chat window only: a white layer over the panel with the loader stage in its middle,
    // while the chat's content waits undisplayed. On reveal the layer fades and the stage swells away, and the
    // content appears, so its own entrance animations play then.
    '.boot{position:absolute;inset:0;z-index:16;display:grid;place-items:center;background:var(--paper);transition:opacity .45s ease}',
    '.root[data-opening=loading] .panel>.view{display:none}',
    '.root[data-opening=revealing] .boot{opacity:0;pointer-events:none}',
    '.boot .rs{transition:transform .5s var(--ease)}',
    '.root[data-opening=revealing] .boot .rs{transform:scale(1.12)}',
    // Thinking: a layer over the chat panel only (the panel clips it to its rounded corners), with the
    // loader stage, the status and a Stop button in the middle. Above the chat, below the call screen.
    '.veil{position:absolute;inset:0;z-index:15;display:grid;place-items:center;cursor:progress;background:color-mix(in srgb,var(--paper) 66%,transparent);' +
      '-webkit-backdrop-filter:blur(0);backdrop-filter:blur(0);opacity:0;transition:opacity .3s ease,-webkit-backdrop-filter .4s ease,backdrop-filter .4s ease}',
    '.veil.on{opacity:1;-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}',
    '.veil.out{opacity:0;-webkit-backdrop-filter:blur(0);backdrop-filter:blur(0);transition-duration:.45s;pointer-events:none}',
    '.veil-in{display:flex;flex-direction:column;align-items:center;gap:10px;transform:scale(.85);transition:transform .5s var(--ease)}',
    '.veil.on .veil-in{transform:none}',
    '.veil.out .veil-in{transform:scale(1.1)}',
    '.veil .ai-status{width:300px;max-width:calc(100% - 32px);min-height:26px;font-size:17px;font-weight:600}',
    // The status gets a light sweeping through it.
    '.veil .ai-status span{background:linear-gradient(90deg,var(--ai) 0,var(--ai) 38%,var(--ai-pink) 50%,var(--ai) 62%,var(--ai) 100%) 0 0/260% 100%;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}',
    '.veil-stop{display:inline-flex;align-items:center;gap:8px;min-height:38px;margin-top:4px;padding:0 16px 0 12px;border-radius:999px;background:var(--navy);color:var(--paper);font-size:13.5px;font-weight:600;cursor:pointer;box-shadow:0 8px 20px -10px rgba(14,26,51,.6);transition:transform .15s var(--ease),filter .15s}',
    '.veil-stop:hover{filter:brightness(1.15)}',
    '.veil-stop:focus-visible{outline-color:var(--ai)}',
    '.veil-stop:active{transform:scale(.94)}',
    '.veil-stop span{display:grid}.veil-stop svg{width:14px;height:14px}',
    '.ai-status{position:relative;min-height:22px;width:100%;text-align:center;font-size:15px;font-weight:500;color:var(--ai)}',
    '.ai-status span{display:block}',
    '.ai-status span.out{position:absolute;left:0;right:0;top:0;opacity:0;transition:opacity .18s ease}',
    '.dl{display:block}',
    // Typing dots: the teaser uses these.
    '.typing{display:inline-flex;gap:4px;padding:15px 16px}',
    '.typing i{width:7px;height:7px;border-radius:50%;background:var(--ink-3);animation:blink 1.2s infinite ease-in-out}',
    '.typing i:nth-child(2){animation-delay:.15s}.typing i:nth-child(3){animation-delay:.3s}',

    /* blocks */
    '.chips{display:flex;flex-wrap:wrap;gap:6px}',
    // Call types: one per row, the name (and what it is) left, the length as a tag.
    '.chips.sched{display:grid;gap:6px;width:100%}',
    '.chips.sched .chip{display:flex;align-items:center;gap:10px;width:100%;min-height:50px;padding:9px 12px;border-radius:14px;text-align:left}',
    '.sc-name{flex:1;min-width:0}',
    '.sc-t{display:block;line-height:1.35;overflow-wrap:anywhere}',
    '.sc-s{display:block;margin-top:2px;font-size:12px;font-weight:500;color:var(--ink-3);line-height:1.35}',
    '.sc-dur{flex:none;padding:2px 8px;border-radius:999px;background:var(--sunk);color:var(--ink-2);font-size:11.5px;font-weight:600;white-space:nowrap}',
    '.chips.sched .chip.on .sc-dur{background:var(--surface)}',
    '.chip{min-height:36px;padding:7px 14px;border-radius:999px;border:1px solid var(--line-2);background:var(--surface);font-weight:600;font-size:13.5px;transition:border-color .15s,background .15s}',
    '.chip:hover:not(:disabled){border-color:var(--robin-primary);background:var(--robin-primary-soft)}',
    '.chip:disabled{cursor:default;opacity:.4}',
    '.chip.on{opacity:1;background:var(--robin-primary);border-color:var(--robin-primary);color:var(--robin-on-primary)}',
    '.form{background:var(--surface);border-radius:14px;padding:12px 14px;box-shadow:0 1px 2px rgba(28,28,28,.05),0 0 0 1px var(--line);width:100%;min-width:min(250px,100%)}',
    '.form h4{margin:0;font-family:var(--display);font-size:17px;font-weight:700;letter-spacing:-.01em}',
    '.form .hint{margin:2px 0 0;color:var(--ink-2);font-size:13px}',
    '.form .fields{margin:14px 0 4px}',
    '.field{display:block;margin-bottom:12px}',
    '.field > span{display:block;font-size:12.5px;font-weight:600;color:var(--ink-2);margin-bottom:5px}',
    '.field input{width:100%;height:42px;padding:0 12px;border:1px solid var(--line-2);border-radius:11px;font:inherit;font-size:15px;color:var(--ink);background:var(--paper);transition:border-color .15s,box-shadow .15s}',
    '.field input:focus{outline:none;border-color:var(--robin-primary-text);box-shadow:0 0 0 4px var(--robin-primary-soft)}',
    '.field[data-err] input{border-color:var(--danger)}',
    '.field .err{color:var(--danger);font-size:12.5px;margin-top:4px;display:none}',
    '.field[data-err] .err{display:block}',
    '.primary{width:100%;min-height:44px;padding:10px 14px;border-radius:12px;background:var(--robin-primary);color:var(--robin-on-primary);font-weight:700;transition:filter .15s,transform .15s}',
    '.primary:hover:not(:disabled){filter:brightness(1.08)}',
    '.primary:active:not(:disabled){transform:scale(.99)}',
    '.primary:disabled{opacity:.4;cursor:default}',
    '.form .done{display:flex;gap:12px;align-items:flex-start}',
    '.done .tick{width:28px;height:28px;border-radius:50%;background:var(--ok-bg);color:var(--ok);display:grid;place-items:center;flex:none}',
    '.done .tick svg{width:15px;height:15px}',
    '.done .t{font-weight:700}',
    '.done .s{color:var(--ink-2);font-size:13px}',
    '.meta-line{display:flex;align-items:center;gap:6px;margin-top:4px;font-size:12.5px;color:var(--ink-2)}',
    '.meta-line svg{width:13px;height:13px}',
    '.info-card{border-radius:14px;overflow:hidden;background:var(--surface);box-shadow:0 1px 2px rgba(28,28,28,.05),0 0 0 1px var(--line)}',
    '.info-card img{width:100%;display:block;aspect-ratio:16/9;object-fit:cover}',
    '.info-card .in{padding:14px 16px}',
    '.info-card h4{margin:0 0 4px;font-family:var(--display);font-size:17px;font-weight:700;line-height:1.3;overflow-wrap:anywhere}',
    '.info-card p{margin:0;color:var(--ink-2);font-size:14px}',
    '.info-card a.link{display:inline-block;margin-top:10px;padding-top:10px;width:100%;border-top:1px dashed var(--line-2);font-size:14px;font-weight:600;color:var(--robin-primary-text);text-decoration:none}',
    // Confirmation: a card like the others with a faint green wash at the top, a green badge beside the title,
    // and the details as rows with icon tiles, split by dashed lines like a ticket.
    '.confirm{position:relative;overflow:hidden;border-radius:18px;padding:12px 14px 6px;background:var(--surface);box-shadow:0 1px 2px rgba(14,26,51,.04),0 10px 26px -16px rgba(14,26,51,.22),0 0 0 1px var(--line)}',
    '.confirm::before{content:"";position:absolute;left:0;right:0;top:0;height:64px;background:linear-gradient(180deg,color-mix(in srgb,var(--ok) 11%,transparent),transparent);pointer-events:none}',
    '.cf-head{position:relative;display:flex;align-items:center;gap:11px;padding-bottom:6px}',
    // The widget's own confirmation: a scrim over the panel and a centred card.
    '.cd-veil{position:absolute;inset:0;z-index:40;display:grid;place-items:center;padding:20px;background:color-mix(in srgb,var(--paper) 55%,transparent);backdrop-filter:blur(2px);animation:fade .18s ease both}',
    '.cd-card{width:min(320px,100%);padding:18px 18px 14px;border-radius:18px;background:var(--surface);box-shadow:var(--shadow-lg),0 0 0 1px var(--line);animation:rise .24s var(--ease) both}',
    '.cd-ic{display:grid;place-items:center;width:36px;height:36px;margin-bottom:10px;border-radius:11px;background:color-mix(in srgb,var(--danger) 12%,transparent);color:var(--danger)}',
    '.cd-ic svg{width:17px;height:17px}',
    '.cd-card h3{margin:0;font-family:var(--display);font-size:16.5px;font-weight:600;line-height:1.3;color:var(--navy)}',
    '.cd-card p{margin:6px 0 0;font-size:13.5px;line-height:1.5;color:var(--ink-2);overflow-wrap:anywhere}',
    '.cd-row{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px;margin-top:16px}',
    '.cd-no,.cd-yes{white-space:nowrap}',
    '.cd-card:focus{outline:none}',
    '.cd-no,.cd-yes{min-height:38px;padding:7px 16px;border-radius:999px;font-weight:600;font-size:13.5px;transition:background .15s,filter .15s}',
    '.cd-no{background:var(--sunk);color:var(--navy)}',
    '.cd-no:hover{background:var(--line)}',
    '.cd-yes{background:var(--danger);color:var(--on-danger)}',
    '.cd-yes:hover{filter:brightness(1.06)}',
    '.cd-yes.go{background:var(--robin-primary);color:var(--robin-on-primary)}',
    '.cd-card.go .cd-ic{background:var(--ai-wash);color:var(--ai)}',
    '.cd-in{display:block;width:100%;height:42px;margin-top:12px;padding:0 12px;border:1px solid var(--line-2);border-radius:12px;background:var(--paper);color:var(--ink);font:inherit;font-size:16px}',   // 16px: phones don't zoom in
    '.cd-in:focus{outline:none;border-color:var(--robin-primary-text);box-shadow:0 0 0 4px var(--robin-primary-soft)}',
    '.cf-badge{position:relative;display:grid;place-items:center;width:34px;height:34px;flex:none}',
    '.cf-badge .tick{position:relative;z-index:1;width:34px;height:34px;border-radius:50%;display:grid;place-items:center;background:var(--ok);color:#fff;box-shadow:0 6px 14px -6px color-mix(in srgb,var(--ok) 75%,transparent)}',
    '.cf-badge .tick svg{width:17px;height:17px;stroke-width:2.6}',
    '.cf-ring{position:absolute;inset:0;border-radius:50%;border:2px solid var(--ok);opacity:0}',
    '.cf-dot{position:absolute;left:50%;top:50%;width:5px;height:5px;margin:-2.5px 0 0 -2.5px;border-radius:50%;background:var(--ok);opacity:0}',
    '.cf-dot:nth-child(3n){background:var(--ai)}.cf-dot:nth-child(3n+1){background:var(--ai-pink)}',
    '.confirm .t{font-family:var(--display);font-size:16px;font-weight:650;letter-spacing:-.01em;color:var(--navy)}',
    '.cf-lines{position:relative;margin:0;padding:0;list-style:none}',
    '.cf-lines li{display:flex;align-items:center;gap:10px;padding:7px 0;font-size:13.5px;line-height:1.4;color:var(--ink-2)}',
    '.cf-lines li>span:last-child{min-width:0;overflow-wrap:anywhere}',
    '.cf-lines li+li{border-top:1px dashed var(--line-2)}',
    '.cf-ic{width:26px;height:26px;border-radius:9px;display:grid;place-items:center;flex:none;background:var(--ok-bg);color:var(--ok)}',
    '.cf-ic svg{width:14px;height:14px}',
    '.error{display:flex;align-items:center;gap:10px;color:var(--danger);font-size:14px}',
    '.error button{display:inline-flex;align-items:center;gap:4px;font-weight:700;text-decoration:underline;text-underline-offset:2px}',
    '.error button svg{width:14px;height:14px}',

    /* composer: one rounded box with "+" menu, textarea, voice and send (deependhq pattern) */
    '.composer{flex:none;position:relative;padding:8px 12px 0;background:var(--paper)}',
    '.cbox{position:relative;padding:5px;border:1px solid var(--line-2);border-radius:16px;background:var(--surface);box-shadow:var(--shadow-sm);transition:border-color .15s,box-shadow .15s,background .15s}',
    '.cbox:focus-within{border-color:color-mix(in srgb,var(--robin-primary) 60%,transparent);box-shadow:0 0 0 3px var(--robin-primary-soft)}',
    '.cbox.drop{border-color:var(--robin-primary);border-style:dashed;background:var(--robin-primary-soft)}',
    '.tabox{flex:1;min-width:0}',
    'textarea.q{display:block;width:100%;min-height:32px;max-height:120px;padding:5px 4px;border:0;background:transparent;color:var(--ink);font:inherit;font-size:15px;line-height:22px;resize:none;outline:none;caret-color:var(--robin-primary)}',
    'textarea.q::placeholder{color:var(--ink-3)}',
    '.cicon{width:32px;height:32px;display:inline-grid;place-items:center;border-radius:10px;color:var(--ink-3);flex:none;transition:background .15s,color .15s,filter .15s}',
    '.cicon:hover:not(:disabled){background:var(--sunk);color:var(--ink)}',
    '.cicon svg{width:17px;height:17px}',
    '.cicon:disabled{opacity:.35;cursor:not-allowed}',
    '.cicon.speak{color:var(--robin-primary-text)}',
    '.cicon.speak:hover:not(:disabled){background:var(--robin-primary-soft);color:var(--robin-primary-text)}',
    '.plus-wrap{position:relative;flex:none}',
    '.b-plus svg{transition:transform .18s var(--ease)}',
    '.b-plus[aria-expanded=true]{background:var(--robin-primary-soft);color:var(--robin-primary-text)}',
    '.b-plus[aria-expanded=true] svg{transform:rotate(45deg)}',
    '.send{width:32px;height:32px;margin-left:2px;display:inline-grid;place-items:center;border-radius:10px;background:var(--robin-primary);color:var(--robin-on-primary);flex:none;transition:background .15s,color .15s,filter .15s}',
    '.send:hover:not(:disabled){filter:brightness(1.08)}',
    '.send:disabled{background:var(--sunk);color:var(--ink-3);cursor:not-allowed}',
    '.send svg{width:17px;height:17px}',

    // Conversation composer: a large rounded panel floating above the bottom edge, text on top and the
    // controls underneath. Focus or a reply in progress draws a pink-to-purple edge (moving while generating).
    '.chat .composer{z-index:3;padding:4px 14px 0;background:none}',
    '.chat .cbox{padding:0;border:1.5px solid transparent;border-radius:30px;background:linear-gradient(var(--surface),var(--surface)) padding-box,linear-gradient(var(--line),var(--line)) border-box;box-shadow:0 14px 34px -16px rgba(14,26,51,.24),0 2px 6px -2px rgba(14,26,51,.06);transition:box-shadow .3s}',
    '.chat .cbox:focus-within,.chat .cbox.busy{background:linear-gradient(var(--surface),var(--surface)) padding-box,linear-gradient(110deg,var(--ai-pink),var(--ai) 50%,var(--ai-pink)) border-box;background-size:100% 100%,220% 100%;box-shadow:0 16px 36px -16px color-mix(in srgb,var(--ai) 50%,transparent)}',
    '.chat .cbox.drop{background:linear-gradient(var(--surface),var(--surface)) padding-box,linear-gradient(var(--ai),var(--ai)) border-box}',
    '.chat .tabox{padding:15px 20px 2px}',
    '.chat textarea.q{min-height:26px;padding:0;font-size:15.5px}',
    '.cctl{display:flex;align-items:center;gap:8px;padding:6px 10px 10px}',
    '.cctl .sp{flex:1}',
    '.chat .cicon,.chat .send{width:38px;height:38px;border-radius:50%}',
    '.chat .cicon{color:var(--navy);box-shadow:0 0 0 1px var(--line)}',
    '.chat .cicon:hover:not(:disabled){color:var(--ai);background:var(--ai-wash);box-shadow:0 0 0 1px var(--ai-lav)}',
    '.chat .cicon svg,.chat .send svg{width:18px;height:18px}',
    '.chat .cicon.speak:hover:not(:disabled){color:var(--ai);background:var(--ai-wash);box-shadow:0 0 0 1px var(--ai-lav)}',
    '.chat .cicon.recok{box-shadow:none}',
    '.chat .b-plus[aria-expanded=true]{background:var(--sunk);color:var(--navy)}',
    '.chat .send{margin:0;background:var(--navy);color:var(--paper)}',
    '.chat .send:disabled{background:var(--sunk);color:var(--ink-3)}',
    '.chat .send.stop svg{width:15px;height:15px}',
    '.chat .recmeter{height:38px}',
    '.chat .attach{padding:10px 12px 0}',
    '.chat .foot{padding:5px 12px 7px;font-size:11px;line-height:16px}',
    '.chat .foot span:not(.i){white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',   // always a single line
    '.chat .foot a{color:var(--ai);font-weight:600;text-decoration:none}',
    '.chat .foot a:hover{text-decoration:underline}',
    // Inside answers: suggestion pills with purple icons, and cards with navy actions and purple focus.
    '.chat .chips{gap:8px}',
    '.chat .chip{min-height:34px;padding:6px 14px 6px 11px;border-color:var(--line);color:var(--navy);font-weight:500;box-shadow:0 1px 2px rgba(14,26,51,.04)}',
    '.chat .chip .ci svg{color:var(--ai)}',
    '.chat .chip:hover:not(:disabled){border-color:var(--ai-lav);background:var(--ai-wash)}',
    '.chat .chip.on{background:var(--navy);border-color:var(--navy);color:var(--paper)}',
    '.chat .chip.on .ci svg{color:inherit}',
    // Quick tiles: the icon sits in a small circle that fills purple, with the glyph turning white, on hover.
    '.chat .chip .ci{display:grid;place-items:center;width:22px;height:22px;margin-left:-4px;border-radius:50%;transition:background .2s,color .2s,transform .25s var(--ease)}',
    '.chat .chip .ci svg{width:13px;height:13px;transition:color .2s}',
    '.chat .chip:hover:not(:disabled) .ci{background:var(--ai);transform:scale(1.06)}',
    '.chat .chip:hover:not(:disabled) .ci svg{color:var(--on-ai)}',
    '.chat .chip:hover:not(:disabled){color:var(--ai-deep)}',
    '.chat .form,.chat .info-card{border-radius:18px;box-shadow:0 1px 2px rgba(14,26,51,.04),0 10px 26px -16px rgba(14,26,51,.22),0 0 0 1px var(--line)}',
    '.chat .form h4,.chat .info-card h4{color:var(--navy)}',
    '.chat .hico,.chat .tick.cal{background:var(--ai-wash);color:var(--ai)}',
    '.chat .field input:focus{border-color:var(--ai);box-shadow:0 0 0 4px color-mix(in srgb,var(--ai) 14%,transparent)}',
    '.chat .inp:focus-within .fi{color:var(--ai)}',
    '.chat .primary{border-radius:14px;background:var(--navy);color:var(--paper)}',
    // Details form: a head (icon tile, title, "2 of 3" count), a thin bar that fills as required fields are
    // completed, floating-label fields that tick themselves when right, and a submit that lifts once all are done.
    '.lf-head{display:flex;align-items:flex-start;gap:11px}',
    '.lf-head .hico{width:32px;height:32px;border-radius:11px;flex:none}',
    '.lf-head .hico svg{width:16px;height:16px}',
    '.lf-titles{flex:1;min-width:0;padding-top:1px}',
    '.lf-titles h4{margin:0;font-size:15.5px;line-height:1.3}',
    // What is being booked, above the fields.
    '.lf-sum{display:flex;align-items:flex-start;gap:10px;margin:10px 0 0;padding:10px 12px;border-radius:12px;background:var(--ai-wash)}',
    '.lf-sum .si{display:grid;place-items:center;width:28px;height:28px;flex:none;border-radius:9px;background:var(--surface);color:var(--ai)}',
    '.lf-sum .si svg{width:14px;height:14px}',
    '.lf-sum .grow{flex:1;min-width:0}',
    '.lf-sum b{display:block;font-size:13.5px;line-height:1.35;color:var(--navy);overflow-wrap:anywhere}',
    '.lf-sum span{display:block;margin-top:2px;font-size:12.5px;color:var(--ink-2)}',
    '.lf-count{flex:none;margin-top:4px;padding:2px 9px;border-radius:999px;background:var(--sunk);color:var(--ink-2);font-size:11.5px;font-weight:600;font-variant-numeric:tabular-nums;transition:background .3s,color .3s}',
    '.lf:has(.lf-submit.ready) .lf-count{background:color-mix(in srgb,var(--ok) 14%,transparent);color:var(--ok)}',
    '.lf-bar{height:4px;margin:10px 0 0;border-radius:2px;background:var(--sunk);overflow:hidden}',
    '.lf-fill{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--ai-mid),var(--ai));transform-origin:left;transform:scaleX(0);transition:transform .5s var(--ease)}',
    '.lf .fields{margin:10px 0 2px}',
    '.lf .field{margin-bottom:8px}',
    '.fl .inp input{height:46px;padding:17px 38px 3px 12px;border:1.5px solid var(--line);border-radius:14px;background:var(--surface);transition:border-color .2s,box-shadow .2s}',
    '.fl .inp.has-i input{padding-left:38px}',
    '.fl .inp .fi{left:12px}',
    '.fl-label{position:absolute;left:12px;top:50%;transform:translateY(-50%);font-size:14px;color:var(--ink-3);pointer-events:none;white-space:nowrap;transition:top .2s var(--ease),transform .2s var(--ease),font-size .2s,color .2s}',
    '.fl .has-i .fl-label{left:38px}',
    '.fl input:focus+.fl-label,.fl input:not(:placeholder-shown)+.fl-label{top:5px;transform:none;font-size:11px;font-weight:600;letter-spacing:.01em}',
    '.fl input:focus+.fl-label{color:var(--ai)}',
    '.fl input:focus{border-color:var(--ai);box-shadow:0 0 0 4px color-mix(in srgb,var(--ai) 13%,transparent)}',
    '.fl-ok{position:absolute;right:13px;top:50%;width:20px;height:20px;margin-top:-10px;border-radius:50%;display:grid;place-items:center;background:var(--ok);color:#fff;transform:scale(0);transition:transform .35s cubic-bezier(.34,1.56,.64,1)}',
    '.fl-ok svg{width:12px;height:12px;stroke-width:3}',
    '.fl[data-ok] .fl-ok{transform:scale(1)}',
    '.fl[data-ok] input{border-color:color-mix(in srgb,var(--ok) 45%,var(--line))}',
    '.fl[data-err] input,.fl[data-err] input:focus{border-color:var(--danger);box-shadow:0 0 0 4px color-mix(in srgb,var(--danger) 10%,transparent)}',
    '.fl[data-err] .fl-label{color:var(--danger)}',
    '.lf-submit{min-height:40px;margin-top:2px;transition:box-shadow .3s,filter .15s,transform .15s}',
    '.lf-submit.ready{box-shadow:0 12px 24px -12px color-mix(in srgb,var(--navy) 80%,transparent)}',
    // Booking: day tiles over a navy marker that slides to the chosen day; times grouped by part of day;
    // a footer naming the picked time beside "Book it".
    // The days: fixed-width chips in a row that scrolls sideways; the navy marker slides under the chosen one.
    '.sdays-w{position:relative;margin:10px 0}',
    '.sdays{position:relative;display:flex;gap:6px;padding:2px;overflow-x:auto;overscroll-behavior-x:contain;scroll-behavior:smooth;scrollbar-width:none}',
    '.sdays::-webkit-scrollbar{display:none}',
    '.sd-marker{position:absolute;left:2px;top:2px;bottom:2px;width:50px;border-radius:14px;background:var(--navy);box-shadow:0 10px 20px -12px rgba(14,26,51,.7);transform:translateX(calc(var(--at,0) * 56px));transition:transform .45s var(--ease)}',
    '.sd-nav{position:absolute;top:0;bottom:0;z-index:2;display:none;align-items:center;width:34px;color:var(--navy)}',
    '.sd-nav.l{left:0;justify-content:flex-start;background:linear-gradient(90deg,var(--surface) 50%,transparent)}',
    '.sd-nav.r{right:0;justify-content:flex-end;background:linear-gradient(270deg,var(--surface) 50%,transparent)}',
    '.sd-nav svg{width:18px;height:18px}',
    '.sdays-w[data-l] .sd-nav.l,.sdays-w[data-r] .sd-nav.r{display:flex}',
    '.sday{flex:0 0 50px;position:relative;z-index:1;display:flex;flex-direction:column;align-items:center;gap:0;padding:5px 4px 4px;border-radius:14px;box-shadow:inset 0 0 0 1px var(--line);color:var(--ink-3);transition:color .25s,box-shadow .25s}',
    '.sday:hover{box-shadow:inset 0 0 0 1px var(--ai-lav)}',
    '.sday[aria-selected=true]{color:var(--paper);box-shadow:none}',
    '.sd-dow,.sd-mon{font-size:10.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase}',
    '.sd-num{font-family:var(--display);font-size:18px;font-weight:700;line-height:1.15;color:var(--navy);transition:color .25s}',
    '.sday[aria-selected=true] .sd-num{color:inherit}',
    '.sgroup+.sgroup{margin-top:8px}',
    '.sg-t{margin-bottom:5px;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)}',
    '.sgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:6px}',
    '.stime{display:flex;align-items:center;justify-content:center;gap:6px;min-height:34px;border-radius:12px;box-shadow:inset 0 0 0 1px var(--line);color:var(--navy);font-weight:600;font-size:14px;font-variant-numeric:tabular-nums;transition:background .2s,color .2s,box-shadow .2s,transform .18s var(--ease)}',
    '.stime:hover{background:var(--ai-wash);box-shadow:inset 0 0 0 1px var(--ai-lav)}',
    '.stime:active{transform:scale(.95)}',
    '.stime[aria-pressed=true]{background:var(--navy);color:var(--paper);box-shadow:none}',
    '.st-check{display:none}.stime[aria-pressed=true] .st-check{display:grid}',
    '.st-check svg{width:14px;height:14px;stroke-width:2.6}',
    '.sfoot{display:flex;align-items:center;gap:10px;margin-top:10px;padding-top:10px;border-top:1px solid var(--line)}',
    '.spicked{flex:1;min-width:0;font-size:13px;color:var(--ink-2)}',
    '.sp-in{display:flex;align-items:center;gap:7px}.sp-in b{color:var(--navy);font-weight:650}.sp-hint{color:var(--ink-3)}',
    '.sp-i{display:grid;color:var(--ai)}.sp-i svg{width:15px;height:15px}',
    '.sbook{width:auto;flex:none;min-height:36px;padding:7px 14px}',
    '.chat .info-card a.link{color:var(--ai)}',
    '.pmenu{position:absolute;left:-6px;bottom:calc(100% + 12px);z-index:7;min-width:200px;padding:4px;border:1px solid var(--line);border-radius:12px;background:var(--surface);box-shadow:var(--shadow-lg);transform-origin:left bottom;animation:popin .14s var(--ease) both}',
    '.pmenu[hidden]{display:none}',
    '.pmenu button{display:flex;align-items:center;gap:10px;width:100%;min-height:38px;padding:8px 10px;border-radius:9px;font-size:14px;text-align:left}',
    '.pmenu button:hover:not(:disabled),.pmenu button:focus-visible{background:var(--sunk)}',
    '.pmenu button:disabled{opacity:.5;cursor:not-allowed}',
    '.pmenu svg{width:17px;height:17px;color:var(--ink-3);flex:none}',
    '.pmenu small{margin-left:auto;font-size:11px;color:var(--ink-3)}',
    '.foot{text-align:center;font-size:11.5px;color:var(--ink-3);padding:7px 0 9px}',
    '.foot a{color:inherit;text-underline-offset:2px}',
    '.foot.note{color:var(--danger)}',

    /* attachments (in the box, and as sent chips in the thread) */
    '.attach{display:flex;flex-wrap:wrap;gap:6px;padding:4px 4px 6px}',
    '.attach:empty{display:none}',
    '.achip{display:inline-flex;align-items:center;gap:8px;max-width:100%;padding:4px;border-radius:10px;background:var(--sunk);font-size:12.5px}',
    '.achip img,.achip .ext{width:30px;height:30px;border-radius:7px;object-fit:cover;flex:none}',
    '.ext{display:grid;place-items:center;background:var(--surface);color:var(--robin-primary-text);font-size:9.5px;font-weight:700;letter-spacing:.02em;box-shadow:0 0 0 1px var(--line)}',
    '.achip .meta,.fchip .meta{display:flex;flex-direction:column;min-width:0;line-height:1.3}',
    '.achip .nm{max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}',
    '.achip .sz,.fchip .sz{color:var(--ink-3);font-size:11px}',
    '.achip .x{width:22px;height:22px;border-radius:6px;display:grid;place-items:center;color:var(--ink-3)}',
    '.achip .x:hover{background:var(--line);color:var(--ink)}',
    '.achip .x svg{width:13px;height:13px}',
    '.achip.err{box-shadow:0 0 0 1px var(--danger)}',
    '.achip.err .sz{color:var(--danger)}',
    '.fchips{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end}',
    '.msg.bot .fchips{justify-content:flex-start}',
    '.fchip{display:inline-flex;align-items:center;gap:10px;max-width:260px;padding:6px 12px 6px 6px;border-radius:14px;background:var(--surface);box-shadow:0 0 0 1px var(--line);font-size:13px}',
    '.fchip img,.fchip .ext{width:36px;height:36px;border-radius:9px;object-fit:cover;flex:none}',
    '.fchip .ext{box-shadow:none;background:var(--sunk)}',
    '.fchip .nm{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',

    /* emoji picker */
    '.epick{position:absolute;left:12px;right:12px;bottom:calc(100% + 2px);z-index:8;padding:10px;border:1px solid var(--line);border-radius:16px;background:var(--surface);box-shadow:var(--shadow-lg);transform-origin:bottom center;animation:popin .16s var(--ease) both}',
    '.epick input{width:100%;height:38px;padding:0 12px;border:1px solid var(--line-2);border-radius:11px;background:var(--paper);color:var(--ink);font:inherit;font-size:14px;outline:none}',
    '.epick input:focus{border-color:var(--robin-primary);box-shadow:0 0 0 3px var(--robin-primary-soft)}',
    '.epick input::-webkit-search-cancel-button{-webkit-appearance:none}',
    '.egrid{display:grid;grid-template-columns:repeat(8,1fr);gap:2px;max-height:196px;overflow-y:auto;margin-top:8px;scrollbar-width:thin;scrollbar-color:var(--line-2) transparent}',
    '.egrid button{aspect-ratio:1;border-radius:8px;display:grid;place-items:center;font-size:22px;line-height:1;font-family:"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif}',
    '.egrid button:hover,.egrid button:focus-visible{background:var(--sunk)}',
    '.eempty{grid-column:1/-1;padding:18px 4px;color:var(--ink-3);font-size:13px;text-align:center}',

    /* dictation: the box turns into a recorder; text streams into the field */
    '.recui{display:none}',
    '.cbox.rec .recui{display:inline-flex}',
    '.cbox.rec .plus-wrap,.cbox.rec .speak,.cbox.rec .send{display:none}',
    '.recmeter{align-items:center;gap:8px;height:32px;padding:0 6px;font-size:12.5px;font-weight:600;color:var(--ink-2);font-variant-numeric:tabular-nums;flex:none}',
    '.recdot{width:8px;height:8px;border-radius:50%;background:#E5484D;flex:none;animation:pulse 1.2s ease-in-out infinite}',
    '.eq{display:inline-flex;align-items:center;gap:2px;height:16px}',
    '.eq i{width:3px;height:100%;border-radius:2px;background:var(--robin-primary);animation:eq .9s ease-in-out infinite}',
    '.eq i:nth-child(2){animation-delay:.15s}.eq i:nth-child(3){animation-delay:.3s}.eq i:nth-child(4){animation-delay:.45s}',
    '.cicon.recok{margin-left:2px;background:var(--robin-primary);color:var(--robin-on-primary)}',
    '.cicon.recok:hover:not(:disabled){background:var(--robin-primary);color:var(--robin-on-primary);filter:brightness(1.08)}',

    /* voice conversation: full-panel call screen */
    '.voice{position:absolute;inset:0;z-index:20;display:flex;flex-direction:column;color:#F4EBD9;background:radial-gradient(120% 80% at 50% 0%,#243048 0%,#0E1A33 55%,#08101F 100%);animation:fade .25s var(--ease)}',
    '.voice[hidden]{display:none}',
    '.vhead{display:flex;align-items:center;gap:8px;padding:14px 10px 0 20px}',
    '.vt{font-family:var(--display);font-weight:600;font-size:16px}',
    '.vhead .vtime{margin-left:auto;margin-right:4px;font-size:13px;color:#C9BEB1;font-variant-numeric:tabular-nums;letter-spacing:.04em}',
    '.vhead .ibtn{color:#FFF8F1}',
    '.vhead .ibtn:hover{background:rgba(255,248,241,.12);color:#FFF8F1}',
    '.vstage{flex:1;min-height:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:26px;padding:0 28px;text-align:center}',
    '.vorb{display:grid;place-items:center;padding:0;border-radius:24px;background:none;--logo:#FFF8F1;transition:opacity .3s}',
    '.vorb .rs{--s:.62;--rs-ink:#0E1A33;--rs-glow:color-mix(in srgb,var(--robin-primary) 38%,transparent)}',
    '.vorb .rs[data-state=success]{--rs-ink:#fff;--rs-glow:rgba(18,183,106,.30)}.vorb .rs[data-state=error]{--rs-ink:#fff;--rs-glow:rgba(217,45,32,.28)}',
    '.root[data-mode=half] .vstage{gap:16px}',
    '.root[data-mode=half] .vorb .rs{--s:.5}',
    '.root[data-mode=half] .vctl{padding-bottom:20px}',
    '.voice[data-state=muted] .vorb{opacity:.6}',
    '.vstat{font-size:16px;color:#E6DCD0;min-height:24px}',
    '.vcap{max-width:310px;min-height:66px;font-size:15px;line-height:1.5;color:#FFF8F1;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}',
    '.vcap[hidden]{display:-webkit-box;visibility:hidden}',
    '.vcap b{display:block;margin-bottom:2px;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#C9BEB1}',
    '.vctl{display:flex;justify-content:center;gap:16px;padding:0 0 calc(28px + env(safe-area-inset-bottom))}',
    '.vbtn{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;background:rgba(255,248,241,.1);color:#FFF8F1;font-size:14px;font-weight:700;transition:background .15s,transform .15s}',
    '.vbtn:hover{background:rgba(255,248,241,.18)}',
    '.vbtn:active{transform:scale(.95)}',
    '.vbtn svg{width:24px;height:24px}',
    '.vbtn[aria-pressed=true]{background:#F4EBD9;color:#0E1A33}',
    '.vbtn.end{background:#E5484D}',
    '.vbtn.end:hover{background:#D63B40}',
    '.vbtn.end svg{width:28px;height:28px}',
    '.callbar{flex:none;display:flex;align-items:center;gap:10px;padding:8px 10px 8px 16px;background:var(--hero);color:var(--hero-ink);font-size:13px;font-weight:600}',
    '.callbar[hidden]{display:none}',
    '.callbar .recdot{background:#57B983}',
    '.callbar .vtime{color:var(--hero-2);font-weight:500;font-variant-numeric:tabular-nums}',
    '.callbar .sp{flex:1}',
    '.callbar button{min-height:32px;padding:4px 14px;border-radius:999px;background:rgba(247,240,232,.12);font-size:12.5px;font-weight:700}',
    '.callbar button.end{background:#E5484D;color:#FFFFFF}',

    /* messages list, settings */
    '.floating{padding:12px 16px 14px;display:flex;justify-content:center;flex:none}',
    '.pill{display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:10px 20px 10px 16px;border-radius:999px;background:var(--hero);color:var(--hero-ink);font-weight:700;box-shadow:var(--shadow-sm)}',
    '.root[data-scheme=dark] .pill{background:var(--robin-primary);color:var(--robin-on-primary)}',
    '@media (prefers-color-scheme:dark){.root[data-scheme=auto] .pill{background:var(--robin-primary);color:var(--robin-on-primary)}}',
    '.pill svg{width:18px;height:18px}',
    '.settings{padding:4px 16px 18px;display:flex;flex-direction:column;gap:14px}',
    '.settings>*{flex:none}',
    '.seg{display:flex;gap:3px;padding:3px;border-radius:12px;background:var(--sunk)}',
    '.seg button{flex:1;min-height:38px;border-radius:9px;font-size:13.5px;font-weight:600;color:var(--ink-2)}',
    '.seg button[aria-checked=true]{background:var(--surface);color:var(--ink);box-shadow:var(--shadow-sm)}',
    '.danger{width:100%;min-height:48px;padding:12px 16px;text-align:left;color:var(--danger);font-weight:600}',

    '@keyframes blink{0%,80%,100%{opacity:.3;transform:translateY(0)}40%{opacity:1;transform:translateY(-3px)}}',
    '@keyframes fade{from{opacity:0}to{opacity:1}}',
    '@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}',
    '@keyframes popin{from{opacity:0;transform:translateY(6px) scale(.97)}to{opacity:1;transform:none}}',
    '@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}',
    '@keyframes eq{0%,100%{transform:scaleY(.3)}50%{transform:scaleY(1)}}',

    /* ---- motion: entrances use `backwards` fill so hover/press transforms still work afterwards ---- */
    '@keyframes launch{from{opacity:0;transform:translateY(14px) scale(.5)}}',
    '@keyframes pop{from{opacity:0;transform:scale(.4)}}',
    '@keyframes popsm{0%{transform:scale(.9)}100%{transform:none}}',
    '@keyframes chipin{from{opacity:0;transform:translateY(6px) scale(.86)}}',
    '@keyframes msgr{from{opacity:0;transform:translate(14px,8px) scale(.94)}}',
    '@keyframes draw{to{stroke-dashoffset:0}}',
    '@keyframes shake{20%{transform:translateX(-5px)}40%{transform:translateX(5px)}60%{transform:translateX(-3px)}80%{transform:translateX(2px)}}',
    '@keyframes ping{0%{transform:scale(1);opacity:.55}70%,100%{transform:scale(2.8);opacity:0}}',
    '@keyframes ring{from{box-shadow:0 0 0 0 color-mix(in srgb,var(--robin-primary) 55%,transparent)}to{box-shadow:0 0 0 18px transparent}}',
    '@keyframes slidedown{from{opacity:0;transform:translateY(-100%)}}',
    '@keyframes fly{0%{transform:none;opacity:1}45%{transform:translateY(-16px);opacity:0}46%{transform:translateY(12px);opacity:0}100%{transform:none;opacity:1}}',
    '@keyframes disc{from{opacity:0;transform:translate(40px,-40px) scale(.7)}}',
    '@keyframes nudge{0%,100%{transform:none}30%{transform:rotate(-12deg)}60%{transform:rotate(9deg)}}',

    // Launcher: pops in on page load, rings + wiggles once when the teaser appears, unread badge pops.
    '.launcher{animation:launch .6s var(--ease) .2s backwards}',
    '.launcher.nudge{animation:ring 1.4s var(--ease) 2}',
    '.launcher.nudge .ic-chat{animation:nudge .6s ease-in-out 2}',
    '.badge:not([hidden]){animation:pop .35s var(--ease) backwards}',
    // Teaser: the card springs up from the launcher and its edge keeps flowing; the message fades in, then
    // the quick starts rise in one after the other.
    '@keyframes tzin{from{opacity:0;transform:translateY(16px) scale(.9)}}',
    '.teaser:not([hidden]) .tz-card{animation:tzin .55s cubic-bezier(.34,1.56,.64,1) both,edgeflow 3s ease-in-out .6s infinite alternate}',
    '.teaser .msgtxt{display:block;animation:fade .35s var(--ease)}',
    '.tz-chip{opacity:0;transform:translateY(6px)}',
    '.teaser.ready .tz-chip{opacity:1;transform:none;transition:opacity .35s var(--ease),transform .35s var(--ease),border-color .2s,background .2s,color .2s}',
    '.teaser.ready .tz-chip+.tz-chip{transition-delay:.08s,.08s,0s,0s,0s}',
    '.teaser.ready .tz-chip:hover{transform:translateY(-1px)}',
    // Online dot breathes a soft ping.
    '.dot{position:relative}',
    '.dot::after{content:"";position:absolute;inset:0;border-radius:50%;background:inherit;animation:ping 2.6s cubic-bezier(0,0,.2,1) infinite}',

    // Conversation screen: the idle swallow rises in with the greeting.
    '.idle>*{animation:rise .5s var(--ease) backwards}',
    '.idle>:nth-child(2){animation-delay:.06s}.idle>:nth-child(3){animation-delay:.12s}.idle>:nth-child(4){animation-delay:.18s}',
    '@keyframes tshine{from{background-position:100% 0}to{background-position:0 0}}',
    // Stage motion (guide v4 section 5): signs, badge and aura per state; body and wings below.
    '@keyframes rsIn{from{opacity:0;transform:scale(.6)}}',
    '@keyframes crRingIn{0%{transform:scale(1.55);opacity:0}35%{opacity:.5}100%{transform:scale(.72);opacity:0}}',
    '@keyframes crBeakDot{0%{transform:translate(-14px,4px) scale(.3);opacity:0}30%{transform:none;opacity:1}70%{opacity:1}100%{transform:translate(4px,-2px);opacity:0}}',
    '@keyframes crArc{0%{transform:translateX(-6px);opacity:0}30%{opacity:1}100%{transform:translateX(8px);opacity:0}}',
    '@keyframes crBubble{0%,8%{transform:scale(0);opacity:0}25%{transform:scale(1.1);opacity:1}35%,75%{transform:scale(1);opacity:1}100%{transform:translateY(-6px);opacity:0}}',
    '@keyframes crBadge{0%{transform:scale(0)}70%{transform:scale(1.12)}100%{transform:scale(1)}}',
    '@keyframes auBreath{0%,100%{transform:scale(.9);opacity:.75}50%{transform:scale(1.05);opacity:1}}',
    '@keyframes auPulse{0%,100%{transform:scale(.88)}50%{transform:scale(1.12)}}',
    '@keyframes auTalk{from{transform:scale(.96)}to{transform:scale(1.08)}}',
    '@keyframes auSpin{to{transform:rotate(360deg)}}',
    '@keyframes auFlash{0%{transform:scale(.6);opacity:0}30%{transform:scale(1.1);opacity:1}100%{transform:scale(1);opacity:.6}}',
    '@keyframes auShake{0%,100%{transform:none}5%,15%,25%{transform:translateX(-10px)}10%,20%,30%{transform:translateX(10px)}}',
    '@keyframes shBreath{0%,100%{transform:scaleX(1);opacity:.9}50%{transform:scaleX(.82);opacity:.5}}',
    '.rs{animation:rsIn .45s var(--ease) backwards}',
    '.rs-bi{animation:crBadge .42s var(--ease) both}',
    '.rs[data-state=idle] .rs-shadow{animation:shBreath 3.4s ease-in-out infinite}',
    '.rs[data-state=listen] .rs-in i{animation:crRingIn 1.8s ease-out infinite;animation-delay:calc(var(--i) * .6s)}',
    '.rs[data-state=chat] .rs-dots i{animation:crBeakDot 1.1s ease-out infinite;animation-delay:calc(var(--i) * .18s)}',
    '.rs[data-state=talk] .rs-arcs i{animation:crArc 1.1s ease-out infinite;animation-delay:calc(var(--i) * .2s)}',
    '.rs[data-state=thinking] .rs-bub i{animation:crBubble 2.4s ease-out infinite;animation-delay:calc(var(--i) * .3s)}',
    '.rs[data-state=idle] .rs-aura{animation:auBreath 4s ease-in-out infinite}',
    '.rs[data-state=chat] .rs-aura{animation:auBreath 1.6s ease-in-out infinite}',
    '.rs[data-state=listen] .rs-aura{animation:auPulse 1.2s ease-in-out infinite}',
    '.rs[data-state=talk] .rs-aura{animation:auTalk .3s ease-in-out infinite alternate}',
    '.rs[data-state=loading] .rs-aura{animation:auSpin 3s linear infinite}',
    '.rs[data-state=thinking] .rs-aura{animation:auSpin 6s linear infinite}',
    '.rs[data-state=success] .rs-aura{animation:auFlash 2.8s ease-out both}',
    '.rs[data-state=error] .rs-aura{animation:auShake 2.6s ease-in-out infinite}',
    // Body and wings per state (idle keeps the swallow's own glide).
    '.rs[data-state=chat] .cr-m{animation:crPeck 1.6s ease-in-out infinite}',
    '.rs[data-state=chat] .cr-near{animation:wgNear .55s ease-in-out infinite}.rs[data-state=chat] .cr-far{animation:wgFar .55s ease-in-out infinite}',
    '.rs[data-state=listen] .cr-m{animation:crListen 1.2s ease-in-out infinite}',
    '.rs[data-state=listen] .cr-near{animation:wgNear 1.2s ease-in-out infinite}.rs[data-state=listen] .cr-far{animation:wgFar 1.2s ease-in-out infinite}',
    '.rs[data-state=muted] .cr-m,.rs[data-state=muted] .cr-near,.rs[data-state=muted] .cr-far{animation:none}',
    '.rs[data-state=talk] .cr-m{animation:crTalk .3s ease-in-out infinite alternate}',
    '.rs[data-state=talk] .cr-near{animation:wgNear .6s ease-in-out infinite}.rs[data-state=talk] .cr-far{animation:wgFar .6s ease-in-out infinite}',
    '.rs[data-state=loading] .cr-m{animation:crHover 2.6s ease-in-out infinite}',
    '.rs[data-state=loading] .cr-near{animation:wgNear .45s ease-in-out infinite}.rs[data-state=loading] .cr-far{animation:wgFar .45s ease-in-out infinite}',
    '.rs[data-state=thinking] .cr-m{animation:crHover 2.6s ease-in-out infinite}',
    '.rs[data-state=thinking] .cr-near{animation:wgNearGlide 2.6s ease-in-out infinite}.rs[data-state=thinking] .cr-far{animation:wgFarGlide 2.6s ease-in-out infinite}',
    // Search: the swallow hovers and scans inside the lens, gliding, on a slowly turning aura.
    '.rs[data-state=search] .cr-m{animation:crHover 2.6s ease-in-out infinite}',
    '.rs[data-state=search] .cr-near{animation:wgNearGlide 2.6s ease-in-out infinite}.rs[data-state=search] .cr-far{animation:wgFarGlide 2.6s ease-in-out infinite}',
    '.rs[data-state=search] .rs-aura{background:conic-gradient(from 0deg,var(--rs-glow),transparent 35%,var(--rs-glow) 55%,transparent 85%,var(--rs-glow));animation:auSpin 6s linear infinite}',
    '.rs[data-state=success] .cr-m{animation:crLand 2.8s cubic-bezier(.4,0,.2,1) both}',
    '.rs[data-state=success] .cr-near{animation:wgNearGlide 1.4s ease-in-out infinite}.rs[data-state=success] .cr-far{animation:wgFarGlide 1.4s ease-in-out infinite}',
    '.rs[data-state=error] .cr-m{animation:crFail 2.6s ease-in-out infinite}',
    '.rs[data-state=error] .cr-near{animation:wgNear .16s ease-in-out infinite}.rs[data-state=error] .cr-far{animation:wgFar .16s ease-in-out infinite}',
    // Ghost swallows (success) run the same animations a beat behind.
    '.rs .g1 .cr-m,.rs .g1 .cr-near,.rs .g1 .cr-far{animation-delay:.1s}.rs .g2 .cr-m,.rs .g2 .cr-near,.rs .g2 .cr-far{animation-delay:.22s}',
    '.veil .ai-status span{animation:statusin .4s var(--ease) backwards,tshine 2.2s linear infinite}',
    '.ai-loading{animation:fade .35s var(--ease) backwards}',
    '@keyframes statusin{from{opacity:0;transform:translateY(5px)}}',
    '.ai-status span{animation:statusin .4s var(--ease) backwards}',
    '.caret{animation:pulse 1s ease-in-out infinite}',
    '.stopped{animation:fade .3s ease}',
    // Composer edge: the gradient flows back and forth while a reply is generated.
    '@keyframes edgeflow{from{background-position:0 0,0% 0}to{background-position:0 0,100% 0}}',
    '.chat .cbox.busy{animation:edgeflow 2.4s ease-in-out infinite alternate}',
    '.chat .send.stop{animation:popsm .25s var(--ease)}',

    '.row .ico{transition:transform .25s var(--ease),background .15s}',
    '.row:hover .ico{transform:scale(1.08)}',
    '.settings>*{animation:rise .4s var(--ease) backwards;animation-delay:calc(var(--i,0) * 45ms)}',
    '.settings>*:nth-child(2){--i:1}.settings>*:nth-child(3){--i:2}',

    // Tabs: one indicator pill slides between Home and Messages.
    '.tabs{position:relative}',
    '.tab{position:relative;z-index:1}',
    '.tab[aria-selected=true]{background:transparent}',
    '.tab svg{transition:transform .3s var(--ease)}',
    '.tab[aria-selected=true] svg{transform:translateY(-1px)}',
    '.tab-ind{position:absolute;left:10px;top:8px;bottom:calc(8px + env(safe-area-inset-bottom));width:calc((100% - 26px) / 2);border-radius:14px;background:var(--ai-wash);transform:translateX(calc(var(--x,0) * (100% + 6px)));transition:transform .38s var(--ease)}',

    // Chat: user bubbles slide in from the right, Robin from the left; a reply's blocks stagger.
    '.msg.user{animation:msgr .42s var(--ease) backwards;transform-origin:bottom right}',
    // An answer: its name line fades in, its blocks rise in turn, and its actions arrive last.
    '.msg.bot{animation:fade .3s ease backwards}',
    // ...the mark spins in and its dots light up once round the cross (the loader settling into it),
    // words fade in from a soft blur, chips pop in one by one, cards catch a light sweep, and each action pops.
    '@keyframes markin{from{opacity:0;transform:rotate(-120deg) scale(.3)}}',
    '@keyframes wordin{from{opacity:0;filter:blur(4px)}}',
    '@keyframes sheen{to{transform:translateX(110%)}}',
    '.msg.bot:not(.quiet):not(.from-stream) .ai-head .av{animation:markin .7s var(--ease) backwards}',
    // Presence motion. Listening: two soft red waves spread in turn and the mic badge throbs gently. Speaking: the
    // same, a little faster. Thinking: a fine arc chases round; writing: the same arc, slower, and the pen moves.
    // Emoji: the smile wiggles. Every new badge pops in. (The swallow itself moves per state: see below.)
    // The swallow (guide §3, §5): wings flap continuously (wgNear/wgFar) or glide (two quick flaps, then hold),
    // always in sync; the body moves per state. Moves are in % so they scale with any size of logo.
    '@keyframes wgNear{0%,100%{transform:rotate(0) scaleY(1)}50%{transform:rotate(24deg) scaleY(.55)}}',
    '@keyframes wgFar{0%,100%{transform:rotate(0) scaleX(1)}50%{transform:rotate(-9deg) scaleX(.88)}}',
    '@keyframes wgNearGlide{0%,30%,100%{transform:rotate(0) scaleY(1)}8%,23%{transform:rotate(24deg) scaleY(.55)}15%{transform:rotate(0) scaleY(1)}}',
    '@keyframes wgFarGlide{0%,30%,100%{transform:rotate(0) scaleX(1)}8%,23%{transform:rotate(-9deg) scaleX(.88)}15%{transform:rotate(0) scaleX(1)}}',
    '@keyframes crGlide{0%,100%{transform:translateY(0) rotate(0)}50%{transform:translateY(-7%) rotate(-3deg)}}',
    '@keyframes crPeck{0%,100%{transform:rotate(0) translate(0,0)}15%{transform:rotate(-12deg) translate(5%,3.5%)}30%{transform:rotate(0)}45%{transform:rotate(-9deg) translate(3.5%,2.5%)}60%{transform:rotate(0)}}',
    '@keyframes crListen{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}',
    '@keyframes crTalk{0%{transform:translateY(0) rotate(0)}100%{transform:translateY(-4%) rotate(-4deg)}}',
    '@keyframes crHover{0%,100%{transform:translateY(0) rotate(-7deg)}50%{transform:translateY(-5%) rotate(4deg)}}',
    '@keyframes crLand{0%{transform:translate(-65%,36%) scale(.55) rotate(12deg);opacity:0}30%{transform:translate(10%,-18%) scale(1.1) rotate(-6deg);opacity:1}50%,100%{transform:none;opacity:1}}',
    '@keyframes crFail{0%,100%{transform:none}5%,15%,25%{transform:translateX(-7%) rotate(-5deg)}10%,20%,30%{transform:translateX(7%) rotate(5deg)}40%,85%{transform:translateY(6%) rotate(16deg)}}',
    // Idle (and anywhere without a state): glide.
    '.cr .cr-m{animation:crGlide 3.4s ease-in-out infinite}',
    '.cr .cr-near{animation:wgNearGlide 3.4s ease-in-out infinite}',
    '.cr .cr-far{animation:wgFarGlide 3.4s ease-in-out infinite}',
    '.cr.still .cr-m,.cr.still .cr-near,.cr.still .cr-far{animation:none}',
    // Writing / emoji: peck, wings beating. Listening: pulse. Speaking: a quick bob. Thinking: hover and tilt.
    // Done: swoop in and land. Error: shake, then droop.
    '.presence[data-state=writing] .cr-m,.presence[data-state=emoji] .cr-m{animation:crPeck 1.6s ease-in-out infinite}',
    '.presence[data-state=writing] .cr-near,.presence[data-state=emoji] .cr-near{animation:wgNear .55s ease-in-out infinite}',
    '.presence[data-state=writing] .cr-far,.presence[data-state=emoji] .cr-far{animation:wgFar .55s ease-in-out infinite}',
    '.presence[data-state=listening] .cr-m{animation:crListen 1.2s ease-in-out infinite}',
    '.presence[data-state=listening] .cr-near{animation:wgNear 1.2s ease-in-out infinite}',
    '.presence[data-state=listening] .cr-far{animation:wgFar 1.2s ease-in-out infinite}',
    '.presence[data-state=speaking] .cr-m{animation:crTalk .3s ease-in-out infinite alternate}',
    '.presence[data-state=speaking] .cr-near{animation:wgNear .6s ease-in-out infinite}',
    '.presence[data-state=speaking] .cr-far{animation:wgFar .6s ease-in-out infinite}',
    '.presence[data-state=thinking] .cr-m{animation:crHover 2.6s ease-in-out infinite}',
    '.presence[data-state=thinking] .cr-near{animation:wgNearGlide 2.6s ease-in-out infinite}',
    '.presence[data-state=thinking] .cr-far{animation:wgFarGlide 2.6s ease-in-out infinite}',
    '.presence[data-state=done] .cr-m{animation:crLand 1.2s cubic-bezier(.4,0,.2,1) both}',
    '.presence[data-state=done] .cr-near{animation:wgNearGlide 1.2s ease-in-out}',
    '.presence[data-state=done] .cr-far{animation:wgFarGlide 1.2s ease-in-out}',
    '.presence[data-state=error] .cr-m{animation:crFail 2.2s ease-in-out}',
    '.presence[data-state=error] .cr-near{animation:wgNear .16s ease-in-out 6}',
    '.presence[data-state=error] .cr-far{animation:wgFar .16s ease-in-out 6}',
    '@keyframes pbadge{from{transform:scale(0)}}',
    '@keyframes pwave{0%{opacity:.55;transform:scale(.92)}100%{opacity:0;transform:scale(1.3)}}',
    '@keyframes pthrob{50%{transform:scale(1.12)}}',
    '@keyframes pspin{to{transform:rotate(360deg)}}',
    '@keyframes pscribble{0%,100%{transform:translate(0,0) rotate(0)}25%{transform:translate(1px,-1px) rotate(-10deg)}75%{transform:translate(-1px,1px) rotate(8deg)}}',
    '.p-badge{animation:pbadge .35s var(--ease) backwards}',
    '.presence[data-state=listening] .p-wave{animation:pwave 1.6s ease-out infinite}',
    '.presence[data-state=listening] .p-wave+.p-wave{animation-delay:.8s}',
    '.presence[data-state=listening] .p-badge{animation:pbadge .35s var(--ease) backwards,pthrob 1s ease-in-out .35s infinite}',
    '.presence[data-state=speaking] .p-wave{animation:pwave 1.1s ease-out infinite}',
    '.presence[data-state=speaking] .p-wave+.p-wave{animation-delay:.55s}',
    '.presence[data-state=speaking] .p-badge{animation:pbadge .35s var(--ease) backwards,pthrob .7s ease-in-out .35s infinite}',
    '.presence[data-state=thinking] .p-ring{opacity:1;animation:pspin .9s linear infinite}',
    '.presence[data-state=thinking] .p-badge svg{animation:twinkle 1.4s ease-in-out infinite}',
    '.presence[data-state=writing] .p-ring{opacity:1;animation:pspin 2.2s linear infinite}',
    '.presence[data-state=writing] .p-badge svg{animation:pscribble .6s ease-in-out infinite}',
    '.presence[data-state=emoji] .p-badge svg{animation:nudge .8s ease-in-out infinite}',
    '.presence[data-state=attaching] .p-badge svg{animation:nudge .6s ease-in-out 2}',
    '.w{animation:wordin .55s ease backwards}',
    '.msg.bot:not(.quiet) .chips:not(.picked) .chip{animation:chipin .45s var(--ease) backwards}',
    '.msg.bot:not(.quiet) .chips:not(.picked) .chip:nth-child(1){animation-delay:.3s}.msg.bot:not(.quiet) .chips:not(.picked) .chip:nth-child(2){animation-delay:.37s}',
    '.msg.bot:not(.quiet) .chips:not(.picked) .chip:nth-child(3){animation-delay:.44s}.msg.bot:not(.quiet) .chips:not(.picked) .chip:nth-child(n+4){animation-delay:.51s}',
    '.chat .form,.chat .info-card{position:relative;overflow:hidden}',
    '.msg.bot:not(.quiet) .form::after,.msg.bot:not(.quiet) .info-card::after{content:"";position:absolute;inset:0;z-index:2;pointer-events:none;' +
      'background:linear-gradient(105deg,transparent 30%,color-mix(in srgb,var(--ai) 12%,transparent) 50%,transparent 70%);transform:translateX(-110%);animation:sheen 1.1s ease .45s forwards}',
    '.msg.bot:not(.quiet) .act{animation:pop .4s var(--ease) backwards}',
    '.msg.bot:not(.quiet) .act:nth-child(1){animation-delay:.55s}.msg.bot:not(.quiet) .act:nth-child(2){animation-delay:.61s}.msg.bot:not(.quiet) .act:nth-child(3){animation-delay:.67s}.msg.bot:not(.quiet) .act:nth-child(4){animation-delay:.73s}',
    '.msg.bot .col>*{animation:rise .45s var(--ease) backwards}',
    '.msg.bot .col>*:nth-child(2){animation-delay:.08s}.msg.bot .col>*:nth-child(3){animation-delay:.16s}.msg.bot .col>*:nth-child(4){animation-delay:.24s}',
    '.msg.quiet,.msg.quiet .col>*,.msg.from-stream,.msg.from-stream .col>:first-child{animation:none}',   // already on screen
    '.chip{transition:border-color .15s,background .15s,transform .2s var(--ease)}',
    '.chip:hover:not(:disabled){transform:translateY(-1px)}',
    '.chip:active:not(:disabled){transform:scale(.96)}',
    '.chip.on{animation:popsm .25s var(--ease)}',

    // Buttons: press squish, hover nudges (close turns, gear spins, chevrons point).
    '.ibtn,.cicon,.stepper button,.send,.tab,.vbtn,.pill,.primary{transition:background .15s,color .15s,filter .15s,opacity .15s,transform .18s var(--ease)}',
    '.ibtn:active,.cicon:active:not(:disabled),.stepper button:active:not(:disabled),.send:active:not(:disabled),.tab:active,.pill:active{transform:scale(.9)}',
    '.ibtn svg,.stepper svg,.cicon svg{transition:transform .3s var(--ease)}',
    '.ibtn[aria-label=Close]:hover svg{transform:rotate(90deg)}',
    '.ibtn[aria-label=Settings]:hover svg{transform:rotate(60deg)}',
    '.ibtn[aria-label=Back]:hover svg{transform:translateX(-2px)}',
    '.step-up:hover:not(:disabled) svg{transform:translateY(-2px)}',
    '.step-down:hover svg{transform:translateY(2px)}',
    '.b-wide:hover svg{transform:scale(1.14)}',
    '.cicon.speak:hover:not(:disabled) svg{transform:scaleY(1.25)}',
    '.pill svg{transition:transform .3s var(--ease)}',
    '.pill:hover svg{transform:rotate(90deg)}',

    // Composer: send pops when it becomes available and its arrow flies off on send.
    '.send:not(:disabled){animation:popsm .25s var(--ease)}',
    '.send.fly svg{animation:fly .5s var(--ease)}',
    '.pmenu:not([hidden]) button{animation:rise .28s var(--ease) backwards}',
    '.pmenu button:nth-child(2){animation-delay:.04s}.pmenu button:nth-child(3){animation-delay:.08s}',
    '.pmenu button svg{transition:transform .25s var(--ease)}',
    '.pmenu button:hover:not(:disabled) svg{transform:scale(1.15)}',
    '.egrid button{transition:transform .15s var(--ease),background .15s}',
    '.egrid button:hover{transform:scale(1.2)}',
    '.egrid button:active{transform:scale(.88)}',
    '.achip.new{animation:chipin .32s var(--ease) backwards}',
    '.achip{transition:opacity .16s,transform .16s var(--ease)}',
    '.achip.out{opacity:0;transform:scale(.85)}',
    '.cbox.rec{animation:popsm .25s var(--ease)}',

    // Forms: invalid fields shake, checkmarks draw themselves, picked slot pops.
    '.field[data-err] .inp{animation:shake .34s ease-in-out}',
    // Form and booking motion: fields and day tiles arrive one by one; the times slide in from the side of
    // the day you moved to, group by group; the picked time and its tick pop; the footer line rises in.
    '@keyframes slidel{from{opacity:0;transform:translateX(-18px)}}',
    '@keyframes slider{from{opacity:0;transform:translateX(18px)}}',
    '.msg.bot:not(.quiet) .lf .field{animation:rise .4s var(--ease) backwards;animation-delay:calc(.15s + var(--i,0) * 70ms)}',
    '.msg.bot:not(.quiet) .sday{animation:chipin .4s var(--ease) backwards;animation-delay:calc(.15s + var(--i,0) * 60ms)}',
    '.stimes.from-r{animation:slider .35s var(--ease)}.stimes.from-l{animation:slidel .35s var(--ease)}',
    '.sgroup{animation:rise .35s var(--ease) backwards}.sgroup+.sgroup{animation-delay:.06s}.sgroup+.sgroup+.sgroup{animation-delay:.12s}',
    '.stime[aria-pressed=true]{animation:popsm .3s var(--ease)}',
    '.stime[aria-pressed=true] .st-check{animation:pop .3s var(--ease)}',
    '.sp-in{animation:rise .3s var(--ease)}',
    '.sbook:not(:disabled){animation:popsm .3s var(--ease)}',
    '.tick.draw{animation:pop .4s var(--ease) backwards}',
    '.tick.draw svg path{stroke-dasharray:24;stroke-dashoffset:24;animation:draw .5s var(--ease) .18s forwards}',
    '.msg.quiet .tick.draw,.msg.quiet .tick.draw svg path{animation:none;stroke-dashoffset:0}',
    '.seg button{transition:background .2s,color .2s,box-shadow .2s}',

    // Voice: controls rise in, ripples spread from the orb while it listens, call bar slides down.
    '.vorb-wrap{position:relative;display:grid;place-items:center}',
    '.vstage>*,.vctl .vbtn{animation:rise .45s var(--ease) backwards}',
    '.vstage>*:nth-child(2){animation-delay:.06s}.vstage>*:nth-child(3){animation-delay:.1s}',
    '.vctl .vbtn:nth-child(1){animation-delay:.12s}.vctl .vbtn:nth-child(2){animation-delay:.16s}.vctl .vbtn:nth-child(3){animation-delay:.2s}.vctl .vbtn:nth-child(4){animation-delay:.24s}',
    '.vstat{transition:opacity .2s}',
    '.callbar:not([hidden]){animation:slidedown .3s var(--ease) backwards}',
    '.grab::after{transition:width .2s var(--ease),left .2s var(--ease),opacity .2s}',
    '.grab:hover::after{width:44px;left:14px;opacity:.7}',

    /* ---- icons: placement, sizes, colours ---- */
    '.i{display:inline-grid;place-items:center;flex:none;line-height:0}',
    '.i svg{transition:transform .25s var(--ease)}',
    '.eyebrow{display:flex;align-items:center;gap:6px}',
    '.eyebrow .i svg{width:13px;height:13px}',
    '.chip{display:inline-flex;align-items:center;gap:6px}',
    '.chip .ci svg{width:15px;height:15px;color:var(--robin-primary-text)}',
    '.chip.on .ci svg{color:inherit}',
    '.form h4{display:flex;align-items:center;gap:9px}',
    '.hico{width:28px;height:28px;border-radius:50%;background:var(--robin-primary-soft);color:var(--robin-primary-text);display:grid;place-items:center;animation:pop .4s var(--ease) .1s backwards}',
    '.hico svg{width:15px;height:15px}',
    '.inp{position:relative}',
    '.inp .fi{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--ink-3);pointer-events:none;transition:color .2s}',
    '.inp .fi svg{width:16px;height:16px}',
    '.inp.has-i input{padding-left:38px}',
    '.inp:focus-within .fi{color:var(--robin-primary-text)}',
    '.field[data-err] .fi{color:var(--danger)}',
    '.field[data-err] .err{display:flex;align-items:center;gap:5px;animation:rise .25s var(--ease)}',
    '.field .err .i svg{width:13px;height:13px}',
    '.primary{display:flex;align-items:center;justify-content:center;gap:8px}',
    '.primary .pi svg{width:16px;height:16px}',
    '.tick.cal{background:var(--robin-primary-soft);color:var(--robin-primary-text);animation:pop .4s var(--ease) backwards}',
    // Confirmation motion: the badge bounces in and draws its tick, a ring spreads and eight dots burst
    // outwards, then the detail rows slide in one after another. Earlier messages stay still.
    '@keyframes cfbadge{0%{opacity:0;transform:scale(.3)}60%{opacity:1;transform:scale(1.14)}100%{transform:none}}',
    '@keyframes cfring{0%{opacity:.8;transform:scale(1)}100%{opacity:0;transform:scale(2.2)}}',
    '@keyframes cfdot{0%{opacity:0;transform:rotate(var(--a)) translateX(12px) scale(.4)}25%{opacity:1}100%{opacity:0;transform:rotate(var(--a)) translateX(36px) scale(1)}}',
    '@keyframes cfrow{from{opacity:0;transform:translateX(-10px)}}',
    '.msg.bot:not(.quiet) .cf-badge .tick{animation:cfbadge .55s var(--ease) .1s backwards}',
    '.msg.bot:not(.quiet) .cf-badge .tick svg path{animation-delay:.42s}',
    '.msg.bot:not(.quiet) .cf-ring{animation:cfring .8s ease-out .5s}',
    '.msg.bot:not(.quiet) .cf-dot{animation:cfdot .8s ease-out .5s}',
    '.msg.bot:not(.quiet) .confirm .t{animation:rise .4s var(--ease) .2s backwards}',
    '.msg.bot:not(.quiet) .cf-lines li{animation:cfrow .4s var(--ease) backwards}',
    '.cf-lines li:nth-child(1){animation-delay:.6s}.cf-lines li:nth-child(2){animation-delay:.68s}.cf-lines li:nth-child(3){animation-delay:.76s}.cf-lines li:nth-child(n+4){animation-delay:.84s}',
    '.msg.quiet .confirm li,.msg.quiet .hico,.msg.quiet .tick.cal{animation:none}',
    '.info-card a.link{display:inline-flex;align-items:center;gap:6px}',
    '.info-card a.link .pi svg{width:14px;height:14px}',
    '.error .ei{color:var(--danger)}',
    '.error > span:not(.i){flex:1}',
    '.error button{flex:none;white-space:nowrap}',
    '.error .ei svg{width:16px;height:16px}',
    '.msg:not(.quiet) .error .ei svg{animation:shake .4s ease-in-out .25s}',
    '.foot{display:flex;align-items:center;justify-content:center;gap:6px}',
    '.foot .i svg{width:12px;height:12px}',
    '.foot .i-sparkles{color:var(--robin-primary-text)}',
    '.foot .i-sparkles svg{animation:twinkle 2.8s ease-in-out 3}',
    '.foot.note .i svg{animation:shake .4s ease-in-out}',
    '.seg{position:relative}',
    '.seg button{position:relative;z-index:1;display:flex;align-items:center;justify-content:center;gap:6px}',
    '.seg button[aria-checked=true]{background:transparent;box-shadow:none}',
    '.seg button .i svg{width:15px;height:15px}',
    '.seg button[aria-checked=true] .i{color:var(--robin-primary-text)}',
    '.seg-ind{position:absolute;top:3px;bottom:3px;left:3px;width:calc((100% - 12px) / 3);border-radius:9px;background:var(--surface);box-shadow:var(--shadow-sm);transform:translateX(calc(var(--x,0) * (100% + 3px)));transition:transform .38s var(--ease)}',
    '.danger{display:flex;align-items:center;gap:10px}',
    '.danger .i svg{width:17px;height:17px}',
    '.bk-act.danger .i svg{width:13px;height:13px}',
    '.vt{display:flex;align-items:center;gap:8px}',
    '.vt .i{color:var(--robin-primary-hi)}',
    '.vt .i svg{width:18px;height:18px}',
    '.vt:hover .i svg{animation:wavepulse 1.1s ease-in-out infinite}',
    '.callbar .cphone{color:#57B983}',
    '.callbar .cphone svg{width:14px;height:14px}',
    '.callbar:hover .cphone svg{animation:nudge 1.4s ease-in-out infinite}',

    /* ---- icon micro-animations: each icon reacts to hover in its own way ---- */
    '@keyframes ibob{50%{transform:translateY(-3px)}}',
    '@keyframes iswing{25%{transform:rotate(-16deg)}75%{transform:rotate(10deg)}}',
    '@keyframes iflip{50%{transform:scaleY(.35)}}',
    '@keyframes ispin{to{transform:rotate(180deg)}}',
    '@keyframes itilt{50%{transform:rotate(-22deg)}}',
    '@keyframes irise{50%{transform:translate(2px,-2px)}}',
    '@keyframes wavepulse{0%,100%{transform:scaleY(1)}50%{transform:scaleY(.55)}}',
    '@keyframes twinkle{0%,100%{transform:scale(1) rotate(0);opacity:1}50%{transform:scale(.78) rotate(18deg);opacity:.55}}',
    '@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}',

    /* ---- live icons: each icon has its own move, played on hover ---- */
    '@keyframes lbob{0%,26%,100%{transform:none}13%{transform:translateY(-3px)}}',
    '@keyframes lflip{0%,22%,100%{transform:none}11%{transform:scaleY(.35)}}',
    '@keyframes lswing{0%,30%,100%{transform:none}8%{transform:rotate(-14deg)}18%{transform:rotate(9deg)}25%{transform:rotate(-3deg)}}',
    '@keyframes lwig{0%,24%,100%{transform:none}6%{transform:rotate(-12deg)}14%{transform:rotate(9deg)}20%{transform:rotate(-4deg)}}',
    '@keyframes lpop{0%,20%,100%{transform:none}10%{transform:scale(1.18)}}',
    '@keyframes lspin{0%{transform:none}26%,100%{transform:rotate(360deg)}}',
    '@keyframes ltilt{0%,26%,100%{transform:none}13%{transform:rotate(-20deg)}}',
    '@keyframes lrise{0%,26%,100%{transform:none}13%{transform:translate(2px,-2px)}}',
    '@keyframes lslide{0%,26%,100%{transform:none}13%{transform:translateX(3px)}}',
    '@keyframes lback{0%,26%,100%{transform:none}13%{transform:translateX(-3px)}}',
    '@keyframes ldrop{0%,26%,100%{transform:none}13%{transform:translateY(3px)}}',
    '@keyframes lplus{0%,26%,100%{transform:none}13%{transform:rotate(90deg)}}',
    '@keyframes lturn{to{transform:rotate(360deg)}}',
    '.i-help,.i-messages,.i-user,.i-mail,.i-monitor,.i-building{--live:lbob}',
    '.i-calendar{--live:lflip}',
    '.i-tag{--live:lswing}',
    '.i-tag svg{transform-origin:30% 30%}',
    '.i-headset,.i-phone,.i-trash,.i-palette{--live:lwig}',
    '.i-check,.i-alert,.i-sparkles{--live:lpop}',
    '.i-sun,.i-clock{--live:lspin}',
    '.i-moon{--live:ltilt}',
    '.i-trending,.i-external{--live:lrise}',
    '.i-arrowRight{--live:lslide}',
    // Icons sit still and play their move only while the pointer is on them (or on the row, chip or card that
    // holds them), looping for as long as it stays.
    ':hover>.eyebrow .i svg,.lf-head:hover .hico svg,.row:hover .ico svg,' +
      '.chip:hover:not(:disabled) .ci svg,.seg button:hover .i svg,.danger:hover .i svg,.primary:hover:not(:disabled) .pi svg,a.link:hover .pi svg' +
      '{animation:var(--live,lbob) 1.8s ease-in-out infinite}',
    // Chrome icons (launcher, tabs, header, input box, call controls) answer hover the same way.
    '.launcher:hover .ic-close svg{animation:ldrop 1.8s ease-in-out infinite}',
    '.tab:hover > span{animation:lbob 1.8s ease-in-out infinite}',
    '.cbtn:hover svg,.ibtn:hover svg,.stepper button:hover:not(:disabled) svg,.cicon:hover:not(:disabled) svg,.send:hover:not(:disabled) svg,' +
      '.pmenu button:hover svg,.row:hover .chev svg,.pill:hover svg,.vbtn:hover svg' +
      '{animation:var(--live,lbob) 1.8s ease-in-out infinite}',
    '.ibtn[aria-label=Close] svg,.cicon.b-plus svg,.pill svg{--live:lplus}',
    '.ibtn[aria-label=Back] svg{--live:lback}',
    '.step-down svg,.launcher .ic-close svg{--live:ldrop}',
    '.b-wide svg,.pmenu button svg,.vbtn svg{--live:lpop}',
    '.row .chev svg{--live:lslide}',
    '.vbtn.end svg{--live:lwig}',
    '.ibtn[aria-label=Settings]:hover svg{animation:lturn 2.4s linear infinite}',
    '.cicon.speak:hover:not(:disabled) svg{animation:wavepulse 1.1s ease-in-out infinite}',
    // Disabled controls stay still.
    '.cicon:disabled svg,.send:disabled:not(.fly) svg,.stepper button:disabled svg{animation:none}',
    '.chat .send svg{--live:lslide}',
    '.send.stop svg{animation:none}',
    // Conversation header: Home hops, wider view pushes outward, the chevrons point, settings turns, close makes a
    // quarter turn, and the title's chevron dips.
    '@keyframes lhop{0%,28%,100%{transform:none}8%{transform:translateY(-3px) scaleY(1.05)}16%{transform:scaleY(.9)}22%{transform:translateY(-1px)}}',
    '@keyframes lout{0%,26%,100%{transform:none}10%{transform:scale(1.22)}18%{transform:scale(.94)}}',
    '.chat-head .cbtn[aria-label=Home] svg{--live:lhop}',
    '.chat-head .b-wide svg{--live:lout}',
    '.chat-head .cbtn[aria-label="Close chat"] svg{--live:lplus}',
    '.chat-head .cbtn[aria-label=Settings]:hover svg{animation:lturn 2.4s linear infinite}',
    '.title-pill:hover:not([aria-expanded=true])>i svg{animation:ldrop 1.8s ease-in-out infinite}',
    // Answer actions: copy pops, read aloud wiggles, the thumbs nod. A pressed thumb holds still.
    '@keyframes lnod{0%,26%,100%{transform:none}9%{transform:rotate(-14deg) translateY(-1px)}17%{transform:rotate(6deg)}}',
    '.act svg{transition:transform .25s var(--ease)}',
    '.act:hover svg{animation:var(--live,lpop) 1.8s ease-in-out infinite}',
    '.act[aria-label="Read aloud"] svg{--live:lwig}',
    '.act[aria-label="Good response"] svg,.act[aria-label="Bad response"] svg{--live:lnod}',
    '.act[aria-pressed=true] svg,.act.done svg{animation:none}',
    'button:hover .i-help svg,button:hover .i-messages svg,button:hover .i-user svg,button:hover .i-mail svg,button:hover .i-monitor svg{animation:ibob .5s var(--ease)}',
    'button:hover .i-calendar svg{animation:iflip .45s ease-in-out}',
    'button:hover .i-tag svg{animation:iswing .6s ease-in-out;transform-origin:30% 30%}',
    'button:hover .i-headset svg,button:hover .i-phone svg,button:hover .i-trash svg{animation:nudge .5s ease-in-out}',
    'button:hover .i-check svg{animation:popsm .3s var(--ease)}',
    'button:hover .i-sun svg,button:hover .i-clock svg{animation:ispin .6s var(--ease)}',
    'button:hover .i-moon svg{animation:itilt .5s ease-in-out}',
    'button:hover .i-trending svg,button:hover .i-external svg,a:hover .i-external svg{animation:irise .5s var(--ease)}',
    'button:hover:not(:disabled) .i-arrowRight svg,a:hover .i-arrowRight svg{animation:lslide 1.8s ease-in-out infinite}',
    '.card:hover > .eyebrow .i-trending svg{animation:irise .5s var(--ease)}',
    '.inp:focus-within .fi svg{animation:ibob .45s var(--ease)}',

    /* ---- Settings: live preview, brand colour, text size, reduce motion ---- */
    // Text size scales each screen as a whole (header, messages, forms, chips, cards, input and tabs), so
    // everything keeps its proportions: small 15px text becomes 13.5px, large 17px. The panel keeps its size.
    '.root[data-text=s] .panel>.view{zoom:.9}',
    '.root[data-text=l] .panel>.view{zoom:1.133}',
    '.setv.quiet,.setv.quiet .settings>*{animation:none}',
    '.sprev{padding:16px 16px 10px;background:linear-gradient(180deg,var(--surface),color-mix(in srgb,var(--robin-primary) 6%,var(--surface)))}',
    '.sp-screen{display:flex;flex-direction:column;gap:10px;line-height:1.45}',
    '.sp-mark{align-self:center;margin-bottom:2px}',
    '.sp-mark .dl{width:64px;height:64px;--mr-sw:.6}',
    '.sp-user{align-self:flex-end;max-width:80%;padding:8px 14px;border-radius:18px 18px 6px 18px;background:var(--user-bubble);color:var(--navy)}',
    '.sp-bot{display:flex;align-items:flex-start;gap:8px;max-width:92%;color:var(--ink)}',
    '.sp-bot .av{width:24px;height:24px;margin-top:-1px}',
    '.sp-box{display:flex;align-items:center;gap:8px;margin-top:4px;padding:5px 5px 5px 14px;border-radius:16px;background:var(--surface);box-shadow:0 0 0 1px var(--line-2)}',
    '.sp-ph{flex:1;min-width:0;color:var(--ink-3);font-size:.9em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.sp-send{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--navy);color:var(--paper)}',
    '.sp-send svg{width:15px;height:15px}',
    '.sp-foot{display:flex;align-items:center;justify-content:space-between;margin-top:10px;font-size:12px;color:var(--ink-3)}',
    '.sp-launch{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--robin-primary);color:var(--robin-on-primary);box-shadow:0 6px 14px -6px rgba(14,26,51,.45)}',
    '.sp-launch .cr{width:18px;height:18px;--logo:currentColor}',
    '.brand-row{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px 12px;margin:-2px 14px 14px}',
    '.brand-row .t{font-size:14px;font-weight:600;color:var(--navy)}',
    '.swatches{display:flex;gap:10px}',
    // A fine outline in the text colour keeps dark swatches (navy) visible on dark surfaces too.
    '.sw{display:grid;place-items:center;width:28px;height:28px;border-radius:50%;background:var(--c);color:var(--ci);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ink) 16%,transparent);transition:transform .18s var(--ease),box-shadow .2s}',
    '.sw:hover{transform:scale(1.08)}',
    '.sw[aria-checked=true]{box-shadow:0 0 0 2px var(--surface),0 0 0 4px color-mix(in srgb,var(--c) 75%,var(--ink))}',
    '.sw svg{width:14px;height:14px;stroke-width:3}',
    '.sw.def{--c:#8A5A00;--ci:#fff;background:conic-gradient(#0E1A33 0 50%,#F4A62A 0)}',
    // A chosen brand colour: the swallow and ring, the accent family, the user's bubbles and the filled controls.
    '.root[data-brand]{--logo:var(--b-logo);--ai:var(--b-ai);--ai-deep:var(--b-ai-deep);--ai-mid:var(--b-ai-mid);--ai-lav:var(--b-ai-lav);--ai-pale:var(--b-ai-pale);--ai-pink:var(--b-ai-pink);--ai-wash:var(--b-ai-wash)}',
    '.root[data-brand][data-scheme=dark]{--logo:var(--b-logo-d);--ai:var(--b-ai-d);--ai-deep:var(--b-ai-deep-d);--ai-mid:var(--b-ai-d);--ai-lav:var(--b-ai-lav-d);--ai-pale:var(--b-ai-pale-d);--ai-pink:var(--b-ai-pink-d);--ai-wash:var(--b-ai-wash-d)}',
    '@media (prefers-color-scheme:dark){.root[data-brand][data-scheme=auto]{--logo:var(--b-logo-d);--ai:var(--b-ai-d);--ai-deep:var(--b-ai-deep-d);--ai-mid:var(--b-ai-d);--ai-lav:var(--b-ai-lav-d);--ai-pale:var(--b-ai-pale-d);--ai-pink:var(--b-ai-pink-d);--ai-wash:var(--b-ai-wash-d)}}',
    '.root[data-brand] .msg.user .bubble,.root[data-brand] .sp-user,.root[data-brand] .sp-send,.root[data-brand] .ask-go,.root[data-brand] .msgs .pill,' +
      '.root[data-brand] .veil-stop,.root[data-brand] .chat .send:not(:disabled),.root[data-brand] .chat .primary,' +
      '.root[data-brand] .sd-marker,.root[data-brand] .stime[aria-pressed=true]{background:var(--robin-primary);color:var(--robin-on-primary)}',
    '.root[data-brand] .chat .chip.on{background:var(--robin-primary);border-color:var(--robin-primary);color:var(--robin-on-primary)}',
    '.tsize button{font-family:var(--display);font-weight:650}',
    '.tsize .ts-s{font-size:12px}.tsize .ts-m{font-size:15px}.tsize .ts-l{font-size:19px}',
    '.srow{display:flex;align-items:center;gap:12px;width:100%;min-height:60px;padding:12px 14px;text-align:left}',
    '.srow .grow{flex:1;min-width:0}',
    '.srow .t{display:block;font-weight:600;color:var(--navy)}',
    '.srow .s{display:block;font-size:12.5px;color:var(--ink-3)}',
    '.switch{position:relative;flex:none;width:40px;height:24px;border-radius:999px;background:var(--line-2);transition:background .2s}',
    '.switch::after{content:"";position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.2);transition:transform .25s var(--ease)}',
    '.srow[aria-checked=true] .switch{background:var(--robin-primary)}',
    '.srow[aria-checked=true] .switch::after{transform:translateX(16px)}',
    // Wide: the preview stays in view on the left, the cards scroll on the right.
    '@media (min-width:1300px){.root[data-wide] .settings{display:grid;grid-template-columns:minmax(220px,300px) minmax(340px,1fr);align-items:start;width:100%;max-width:920px;margin:0 auto}' +
      '.root[data-wide] .settings>*{grid-column:2}' +
      '.root[data-wide] .settings>.sprev{grid-column:1;grid-row:1 / span 5;position:sticky;top:0}}',
    '.swatches{flex-wrap:wrap}',

    /* ---- chat history sidebar ---- */
    '.side{position:absolute;z-index:5;left:0;top:60px;bottom:0;width:248px;display:none;flex-direction:column;gap:8px;padding:8px 10px 12px 12px;background:var(--sunk);border-top:1px solid var(--line);border-right:1px solid var(--line)}',
    '.chat.docked .side{display:flex;animation:slidel .28s var(--ease)}',
    '.chat.docked>.scroll,.chat.docked>.composer{margin-left:248px}',
    '.b-side,.chat.docked .b-side{display:none}',
    '.chat.can-side:not(.docked) .b-side{display:grid}',
    '.side-top{display:flex;align-items:center;justify-content:space-between;gap:8px;padding-left:4px}',
    '.side-top b{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)}',
    '.side-top .cbtn{width:34px;height:34px}',
    '.side-top .cbtn svg,.b-side svg{width:18px;height:18px}',
    '.side-new{display:flex;align-items:center;justify-content:center;gap:8px;flex:none;min-height:42px;border-radius:12px;background:var(--robin-primary);color:var(--robin-on-primary);font-weight:600;font-size:14px;box-shadow:0 8px 18px -12px var(--robin-primary);transition:filter .15s,transform .15s}',
    '.side-new:hover{filter:brightness(1.08)}.side-new:active{transform:scale(.98)}',
    '.side-new svg{width:16px;height:16px}',
    '.side-list{flex:1;min-height:0;overflow-y:auto;margin:0 -4px;padding:0 4px;scrollbar-width:thin;scrollbar-color:var(--line-2) transparent}',
    '.side-h{padding:12px 8px 4px;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)}',
    '.side-item{display:block;width:100%;padding:8px 10px;border-radius:10px;text-align:left;font-size:13.5px;font-weight:500;color:var(--navy);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:background .15s}',
    '.side-item:hover{background:var(--surface)}',
    '.side-item[aria-current=true]{background:var(--surface);box-shadow:0 0 0 1px var(--line);font-weight:650}',
    '.side-empty{margin:10px 8px;font-size:13px;color:var(--ink-3)}',

    // Half the screen is no wider than the normal panel on small screens, so the expand button goes.
    '@media (max-width:899px){.b-wide{display:none}}',

    /* phones: the panel becomes a bottom sheet with a grab handle */
    '@media (max-width:480px){',
    '.panel{left:0!important;right:0!important;width:100%!important;bottom:0!important;border-radius:22px 22px 0 0}',
    '.root[data-mode=half] .panel{height:62vh;height:62dvh}',
    '.root[data-mode=full] .panel{height:100vh;height:100dvh;border-radius:0}',
    '.root:not([data-mode=hidden]) .launcher,.root:not([data-mode=hidden]) .teaser{display:none}',
    '.grab{display:block;position:absolute;z-index:2;top:0;left:50%;transform:translateX(-50%);width:72px;height:16px;border-radius:8px}',
    '.grab::after{content:"";position:absolute;top:6px;left:18px;width:36px;height:4px;border-radius:2px;background:var(--ink-3);opacity:.45}',
    '.stepper button,.chat-head .stepper button,.ibtn{width:40px;height:40px}',
    '.chat .composer{padding-bottom:env(safe-area-inset-bottom)}',
    '.root .panel textarea.q,.root .panel .epick input,.root .panel .msearch-q,.root .panel .field input{font-size:16px}',
    '.root[data-text=s] .panel textarea.q,.root[data-text=s] .panel .epick input,.root[data-text=s] .panel .msearch-q,.root[data-text=s] .panel .field input{font-size:17.8px}',
    '}',
    // `motion: 'full'` keeps the animation on even when the device asks for reduced motion.
    '@media (prefers-reduced-motion:reduce){.root:not([data-motion=full]) *,.root:not([data-motion=full]) *::before,.root:not([data-motion=full]) *::after{animation:none!important;transition:none!important}' +
      '.root:not([data-motion=full]) .tick.draw svg path{stroke-dashoffset:0!important}' +
      '.root:not([data-motion=full]) .rs-g,.root:not([data-motion=full]) .rs-aura,.root:not([data-motion=full]) .dl-aura{display:none}' +
      '.root:not([data-motion=full]) .sdays{scroll-behavior:auto}}',
    // The same when Settings turns on reduce motion, whatever the device asks for.
    '.root[data-motion=reduce] *,.root[data-motion=reduce] *::before,.root[data-motion=reduce] *::after{animation:none!important;transition:none!important}',
    '.root[data-motion=reduce] .tick.draw svg path{stroke-dashoffset:0!important}',
    '.root[data-motion=reduce] .rs-g,.root[data-motion=reduce] .rs-aura,.root[data-motion=reduce] .dl-aura{display:none}',
    '.root[data-motion=reduce] .sdays{scroll-behavior:auto}'
  ].join('\n');

  /* ------------------------------------------------------- no backend set */

  // Robin.init without deepAgent, endpoint or adapter: nothing is invented. The chat says it isn't connected and the
  // presence shows offline, so a missing setting is obvious on the page and in the console.
  function NoBackend() {}
  NoBackend.prototype.send = function () {
    var e = new Error('This chat isn’t connected yet. Please try again later.');
    e.fromServer = true;   // shown as it is, not as "Something went wrong"
    return Promise.reject(e);
  };

  function HttpAdapter(endpoint, headers) {
    this.endpoint = endpoint;
    this.headers = headers || {};
  }

  // JSON normally; multipart (`payload` JSON field + `files` parts) when the visitor attached files.
  // The Stop button aborts the request through `opts.signal`.
  HttpAdapter.prototype.send = function (payload, opts) {
    var files = payload.files || [], headers = Object.assign({}, this.headers), body;
    var data = Object.assign({}, payload);
    delete data.files;
    if (files.length) {
      body = new FormData();
      body.append('payload', JSON.stringify(data));
      files.forEach(function (f) { body.append('files', f, f.name); });
    } else {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(data);
    }
    return fetch(this.endpoint, { method: 'POST', headers: headers, body: body, signal: opts && opts.signal }).then(function (r) {
      if (!r.ok) throw new Error('Robin endpoint returned ' + r.status);
      return r.json();
    });
  };

  // The deep-agent backend (`deepAgent: 'https://assistant.example.com'`), unchanged, through its public API:
  //   POST /chat              server-sent events: status (the loader's line, and the stage: searching / writing),
  //                           token (the answer, streamed), sources ([n] markers become links), schedules /
  //                           availability / booking_review (the booking steps), handover and handover_offer
  //   GET  /booking/availability   call types and open times      POST /booking/confirm   the booking itself
  //   POST /handover          "talk to the team"                  POST /upload             attached files
  // Each Robin conversation is one deep-agent session (X-Session-Id); X-Visitor-Id is kept in localStorage so
  // the backend's memory and history recognise a returning visitor. The page's origin must be in the
  // backend's ALLOWED_ORIGINS (or be the backend's own origin).
  var DEEP_VID_KEY = 'robin-widget:visitor';
  var BOOKING_WORDS = /^\s*(book|schedule)\b/i;   // deep-agent: booking phrasings ("Book…", "Schedule…") open the booking card

  function DeepAgentAdapter(base, cfg) {
    this.base = String(base || '').replace(/\/+$/, '');
    this.headers = (cfg && cfg.headers) || {};
    this.token = (cfg && cfg.visitorToken) || null;
    this.hints = { name: cleanLine((cfg && cfg.userName) || '', 120), email: cleanLine((cfg && cfg.userEmail) || '', 200) };
    this.tz = localTzId();
    this.vid = null;
    this.ctx = {};   // conversation id -> { schedule: { slug, name, duration_min } }
  }

  // The minutes a time zone is ahead of UTC at instant t (null for a zone the browser doesn't know).
  function tzOffset(tz, t) {
    try {
      var p = {};
      new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
        .formatToParts(new Date(t)).forEach(function (x) { p[x.type] = x.value; });
      return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute) - t;
    } catch (e) { return null; }
  }

  // deep-agent writes a booking's time as "Tue 27 Oct, 21:30 (Asia/Calcutta)" (its own zone, no year): the moment
  // it means, taking the year that puts it nearest to now.
  var SLOT_LABEL = /\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),? (\d{1,2}):(\d{2}) \(([A-Za-z_]+(?:\/[A-Za-z_+-]+)+|UTC)\)/;
  function slotFromLabel(m) {
    var mon = 'JanFebMarAprMayJunJulAugSepOctNovDec'.indexOf(m[2]) / 3, now = Date.now(), best = null;
    [-1, 0, 1].forEach(function (dy) {
      var guess = Date.UTC(new Date(now).getUTCFullYear() + dy, mon, +m[1], +m[3], +m[4]), off = tzOffset(m[5], guess);
      if (off == null) return;
      var off2 = tzOffset(m[5], guess - off), t = guess - (off2 == null ? off : off2);   // right across a DST change
      if (best == null || Math.abs(t - now) < Math.abs(best - now)) best = t;
    });
    return best == null ? null : new Date(best);
  }

  // Those labels inside the server's own sentences (a pop-up, the welcome line, a booking reply) read the friendly way,
  // in the visitor's clock: "Tue, Oct 27 · 9:30 PM". Display only; the text kept and sent is unchanged.
  function friendlyDates(text) {
    if (!text || !SLOT_LABEL.test(text)) return text;
    return String(text).replace(new RegExp(SLOT_LABEL.source, 'g'), function (all) {
      var d = slotFromLabel(SLOT_LABEL.exec(all));
      return d ? fmtDay.format(d) + ' · ' + fmtTime.format(d) : all;
    });
  }

  // A booking's time in the visitor's own clock and words: "Today", "Tomorrow" or "Tue, 28 Oct", then
  // "3:00 – 3:30 PM". Without a start (an email link's booking), the server's label is read for one.
  function bookingWhen(b) {
    var s = new Date(b && b.start_iso), e = new Date(b && b.end_iso);
    if (b && isNaN(s)) {
      var lm = SLOT_LABEL.exec(b.label_visitor || ''), fromLabel = lm && slotFromLabel(lm);
      if (fromLabel) { s = fromLabel; e = new Date(+s + (b.duration_min || 0) * 60000); }
    }
    if (!b || isNaN(s)) { var raw = cleanLine(b && b.label_visitor, 80); return { day: raw, time: '', rel: '', full: raw, short: raw, month: '', date: '' }; }
    var now = new Date(), d0 = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var days = Math.round((new Date(s.getFullYear(), s.getMonth(), s.getDate()) - d0) / 864e5);
    var rel = days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : '';
    var day = s.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short', year: s.getFullYear() === now.getFullYear() ? undefined : 'numeric' });
    var tf = { hour: 'numeric', minute: '2-digit' }, time;
    try { time = !isNaN(e) && e > s && Intl.DateTimeFormat.prototype.formatRange ? new Intl.DateTimeFormat([], tf).formatRange(s, e) : s.toLocaleTimeString([], tf); }
    catch (x) { time = s.toLocaleTimeString([], tf); }
    return { day: day, time: time, rel: rel, full: (rel ? rel + ', ' : '') + day + ' · ' + time, short: (rel || day) + ' · ' + time,
      month: s.toLocaleDateString([], { month: 'short' }), date: String(s.getDate()) };
  }

  function pageUrl() { return String(location.href).split('#')[0].slice(0, 500); }

  function localTzId() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch (e) { return 'UTC'; }
  }

  DeepAgentAdapter.prototype.visitorId = function () {
    if (this.vid) return this.vid;
    var v = null;
    try { v = localStorage.getItem(DEEP_VID_KEY); } catch (e) { /* private mode */ }
    if (!v || !/^[A-Za-z0-9_-]{8,64}$/.test(v)) {
      v = uid('v');
      try { localStorage.setItem(DEEP_VID_KEY, v); } catch (e) { /* private mode */ }
    }
    return (this.vid = v);
  };

  // Robin's conversation ids already fit the backend's session id rule ([A-Za-z0-9_-]{8,64}).
  DeepAgentAdapter.prototype.request = function (method, path, body, sid, signal) {
    var headers = Object.assign({ 'X-Visitor-Id': this.visitorId() }, this.headers);
    if (this.token) headers['X-Visitor-Token'] = String(this.token);
    if (sid) headers['X-Session-Id'] = String(sid).replace(/[^A-Za-z0-9_-]/g, '').slice(0, 64);
    if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
    return fetch(this.base + path, {
      method: method, headers: headers, signal: signal,
      body: body ? (body instanceof FormData ? body : JSON.stringify(body)) : undefined
    }).then(function (r) {
      if (r.ok) return r;
      return r.json().catch(function () { return {}; }).then(function (j) {
        var detail = j && j.detail, err = new Error(typeof detail === 'string' ? detail : 'The assistant answered ' + r.status);
        err.fromServer = typeof detail === 'string';
        throw err;
      });
    });
  };

  DeepAgentAdapter.prototype.send = function (payload, opts) {
    var input = payload.input || {}, o = opts || {};
    var cid = payload.conversationId, ctx = this.ctx[cid] || (this.ctx[cid] = {});
    if (!ctx.tracked) {
      ctx.tracked = true;
      this.track(cid);
      // A pop-up tapped into a booking or a hand-over (not a chat, which sends its id with the message).
      if (this.outreachEvent && input.type === 'action') { this.markOutreach(this.outreachEvent, 'opened', cid); this.outreachEvent = null; }
    }
    if (this.outreachEvent && ctx.chatted) { this.markOutreach(this.outreachEvent, 'opened', cid); this.outreachEvent = null; }
    if (input.type === 'action') {
      var value = String(input.value || ''), label = input.label || value;
      if (input.name === 'select_slot') {
        var sc = (input.data && input.data.context) || {};
        return sc.kind === 'reschedule' ? this.reschedule(cid, ctx, input.data, o.signal) : Promise.resolve(this.detailsForm(ctx, input.data || {}));
      }
      if (value.indexOf('reschedule:') === 0) { var rp = value.split(':'); return this.rescheduleSlots(ctx, rp[1], rp.slice(2).join(':'), o.signal); }
      if (value.indexOf('cancel:') === 0) return this.cancelBooking(cid, value.slice(7), o.signal);
      if (input.name === 'submit_lead') {
        var c = (input.data && input.data.context) || {};
        return c.kind === 'handover' ? this.handover(cid, input.data.values, c, o.signal) : this.confirm(cid, ctx, input.data.values, c, o.signal);
      }
      if (value === 'handover') return Promise.resolve(this.handoverForm(payload));
      if (value.indexOf('schedule:') === 0) return this.slots(ctx, value.slice(9), o.signal);
      if (value === 'book' || value === 'book_demo' || (input.name === 'starter' && BOOKING_WORDS.test(label))) return this.startBooking(ctx, o.signal);
      return this.chat(payload, label, o);
    }
    return this.chat(payload, input.text || '', o);
  };

  // One chat turn: upload any files, POST /chat, and read its event stream into Robin's blocks.
  DeepAgentAdapter.prototype.chat = function (payload, text, o) {
    var self = this, cid = payload.conversationId, ctx = this.ctx[cid] || (this.ctx[cid] = {});
    var history = (payload.history || []).map(function (m) {
      return { role: m.role === 'user' ? 'user' : 'assistant', content: m.text || '' };
    }).filter(function (m) { return m.content; });
    // Robin's history ends with this very message (after any attachment line); the backend takes it separately.
    var tail = history[history.length - 1];
    if (tail && tail.role === 'user' && (tail.content === text || (text && tail.content.slice(-text.length) === text) ||
      (!text && /^\[Attached:/.test(tail.content)))) history.pop();
    if (payload.input.auto) history = [];   // an email chip's question: the backend counts it only as a first turn
    var files = payload.files || [];
    var uploads = files.length ? Promise.all(files.map(function (f) {
      var fd = new FormData();
      fd.append('file', f, f.name);
      return self.request('POST', '/upload', fd, cid, o.signal).then(function (r) { return r.json(); }).then(function (j) { return j.id; });
    })) : Promise.resolve([]);
    var first = !ctx.chatted, auto = !!payload.input.auto;
    ctx.chatted = true;
    return uploads.then(function (ids) {
      var body = { message: text || 'Attached files', history: history.slice(-40), timezone: self.tz, attachments: ids };
      if (first && self.outreachEvent) { body.outreach_event = self.outreachEvent; self.markOutreach(self.outreachEvent, 'opened', cid); self.outreachEvent = null; }
      if (auto) body.ask_auto = true;   // an email chip's question, sent for the visitor
      var me = self.me || {};
      if (!me.signed_in && (self.hints.name || me.name)) body.user_name = self.hints.name || me.name;
      if (!me.signed_in && (self.hints.email || me.email)) body.user_email = self.hints.email || me.email;
      return self.request('POST', '/chat', body, cid, o.signal);
    }).then(function (r) {
      var answer = '', sources = [], extra = [], failed = null, ref = null, card = null;
      function cited(t) {   // [n] markers become links to their sources
        return t.replace(/\[(\d{1,2})\]/g, function (all, n) {
          var s = sources.filter(function (x) { return String(x.n) === n; })[0];
          return s && s.url ? '[' + n + '](' + s.url + ')' : all;
        });
      }
      function on(ev) {
        if (ev.type === 'status' && ev.label && o.onStatus) o.onStatus(ev.label);
        else if (ev.type === 'lang' && ev.code) self.lang = ev.code;   // the conversation's language, for server speech
        else if (ev.type === 'token') { answer += ev.text || ''; if (o.onText) o.onText(cited(answer)); }
        else if (ev.type === 'sources') sources = ev.items || [];
        else if (ev.type === 'ui' && ev.op === 'end') card = ev.complete && typeof ev.program === 'string' && ev.program.length <= 4000 ? ev.program : null;
        else if (ev.type === 'schedules') extra.push(self.scheduleChoices(ev.items || []));
        else if (ev.type === 'availability') {
          var b = self.slotBlock(ctx, ev);
          if (b.length) extra = extra.filter(function (x) { return x.type !== 'buttons' || !x.schedules; }).concat(b);
        } else if (ev.type === 'booking_review' && ev.status === 'review' && ev.slot) {
          ctx.schedule = ev.schedule || ctx.schedule;
          extra = extra.concat(self.detailsForm(ctx, { start: ev.slot.start_iso, context: self.slotContext(ev.schedule) }, ev.prefill).blocks);
        } else if (ev.type === 'booking_review' && ev.alternatives && ev.alternatives.length && ev.schedule) {
          ctx.schedule = ev.schedule;
          extra.push(self.timesBlock(ev.schedule, ev.alternatives));
        } else if (ev.type === 'slots' && ev.ok && ev.slots && ev.slots.length && ev.schedule
          && !extra.some(function (x) { return x.type === 'time_slots'; })) {
          ctx.schedule = ev.schedule;
          extra.push(self.timesBlock(ev.schedule, ev.slots));
        } else if (ev.type === 'handover' || ev.type === 'handover_offer') {
          extra.push({ type: 'buttons', options: [{ label: 'Talk to the team', value: 'handover', icon: 'headset' },
            { label: 'Book a meeting', value: 'book', icon: 'calendar' }] });
        } else if (ev.type === 'meta') ref = ev.message_id || null;
        else if (ev.type === 'error') failed = ev.error;
      }
      return readEvents(r, on).then(function () {
        if (!answer && failed) throw new Error(failed);
        var blocks = answer ? [{ type: 'text', text: cited(answer) }] : [];
        if (card) blocks.push({ type: 'ui_card', program: card });   // the answer's card: a table, figures, steps
        var links = sources.filter(function (s) { return s.url; }).slice(0, 4).map(function (s) {
          return { label: s.title || s.url, url: s.url };
        });
        if (links.length) blocks.push({ type: 'buttons', options: links });
        var out = { blocks: blocks.concat(extra), ref: ref };
        // After the first exchange the backend writes a 3-6 word title in the background; it is fetched a few
        // seconds later (by then it is ready, so this asks for no new one) and applied when it comes.
        if (!ctx.titled && answer) {
          ctx.titled = true;
          out.title = sleep(5000).then(function () {
            return self.json('POST', '/conversations/' + encodeURIComponent(self.sid(cid)) + '/title');
          }).then(function (t) { return t && t.title && t.title_source !== 'fallback' ? t.title : null; });
        }
        return out;
      });
    });
  };

  DeepAgentAdapter.prototype.sid = function (cid) {
    return String(cid).replace(/[^A-Za-z0-9_-]/g, '').slice(0, 64);
  };

  // GET/POST that answer JSON; failures resolve to null (these features are extras, never the chat's problem).
  DeepAgentAdapter.prototype.json = function (method, path, body, sid) {
    return this.request(method, path, body, sid).then(function (r) { return r.json(); }).catch(function () { return null; });
  };

  // Once, at start: the server's health, widget settings, who the visitor is, and an email link's token.
  DeepAgentAdapter.prototype.setup = function () {
    var self = this;
    return Promise.all([this.request('GET', '/healthz').then(function (r) { return r.json(); }),
      this.json('GET', '/widget-config'), this.json('GET', '/me')]).then(function (r) {
      var health = r[0], conf = r[1] || {}, me = r[2] || {};
      self.me = me;
      self.conf = conf;
      var mem = me.memory || {};
      var exts = conf.upload_types || [];
      return {
        version: health && health.version,
        privacyUrl: conf.privacy_url || null,
        starters: conf.suggestions || null,
        upload: exts.length ? { accept: exts.map(function (x) { return x.charAt(0) === '.' ? x : '.' + x; }).join(','), maxSizeMB: conf.upload_max_mb || 10 } : null,
        voiceLanguages: conf.voice_languages && conf.voice_languages.length ? conf.voice_languages : null,
        gifs: !!conf.gif, ttsServer: conf.tts === 'server', sttServer: conf.stt === 'server',
        greeting: mem.headline ? { headline: mem.headline, line: mem.line || '' } : null,
        visitor: { name: me.name || mem.name || '', email: me.email || mem.email || '', company: mem.company || '' },
        claim: self.claimToken()
      };
    });
  };

  // An email's "Ask Deep" link: #t=… on the backend's /ask page, or #ask-deep=… on the site. Read once, then cleared.
  DeepAgentAdapter.prototype.claimToken = function () {
    var hash = (global.location && global.location.hash || '').replace(/^#/, ''), p = {};
    hash.split('&').forEach(function (kv) {
      var i = kv.indexOf('=');
      if (i > 0) { try { p[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); } catch (e) { /* a malformed escape is ignored */ } }
    });
    var token = p['ask-deep'] || (/\/ask\/?$/.test(global.location.pathname) ? p.t : null);
    if (!token) return null;
    try { global.history.replaceState(null, '', global.location.pathname + global.location.search); } catch (e) { /* sandboxed */ }
    return { token: token, q: p.q && /^[a-z_]+$/.test(p.q) ? p.q : null };
  };

  DeepAgentAdapter.prototype.claim = function (claim, cid) {
    return this.request('POST', '/ask/claim', { token: claim.token, q: claim.q, timezone: this.tz,
      gpc: !!(global.navigator && (navigator.globalPrivacyControl || navigator.doNotTrack === '1')) }, cid)
      .then(function (r) { return r.json(); });
  };

  // The session origin beacon, once per conversation.
  DeepAgentAdapter.prototype.track = function (cid) {
    var scr = global.screen ? screen.width + 'x' + screen.height : null;
    this.json('POST', '/track', { session_id: this.sid(cid), visitor_id: this.visitorId(), page: pageUrl(),
      referrer: document.referrer ? document.referrer.slice(0, 500) : null, timezone: this.tz,
      lang: (navigator.language || '').slice(0, 32) || null, screen: scr });
  };

  // Outreach: which pop-up, if any, the owner's rules want on this page now (docs/OUTREACH.md).
  DeepAgentAdapter.prototype.outreach = function (dwell, scroll) {
    var shown = [], visit = { first: null, pages: [] };
    try { shown = JSON.parse(sessionStorage.getItem('robin-widget:outreach-shown') || '[]'); } catch (e) { /* private mode */ }
    // The pages of this visit (the backend's rules can wait for "viewed 3 pages" or a landing page).
    try { visit = JSON.parse(sessionStorage.getItem('robin-widget:visit') || 'null') || visit; } catch (e) { /* private mode */ }
    var here = pageUrl();
    if (!visit.first) visit.first = here;
    if (visit.pages[visit.pages.length - 1] !== location.pathname) visit.pages = visit.pages.concat(location.pathname.slice(0, 300)).slice(-60);
    try { sessionStorage.setItem('robin-widget:visit', JSON.stringify(visit)); } catch (e) { /* private mode */ }
    return this.json('POST', '/outreach/check', { visitor_id: this.visitorId(), page: pageUrl(),
      path: location.pathname.slice(0, 300), title: (document.title || '').slice(0, 200), referrer: document.referrer ? document.referrer.slice(0, 500) : null,
      first_page: visit.first, pages: visit.pages, dwell_s: Math.round(dwell || 0), scroll_pct: Math.round(scroll || 0), shown: shown.slice(-60), tz: this.tz,
      gpc: !!(navigator.globalPrivacyControl || navigator.doNotTrack === '1') }).then(function (res) {
      if (res && res.rule && res.rule.id != null) {
        shown.push(res.rule.id);
        try { sessionStorage.setItem('robin-widget:outreach-shown', JSON.stringify(shown)); } catch (e) { /* private mode */ }
      }
      return res;
    });
  };

  // The pop-up was tapped (the next chat carries it) or dismissed.
  DeepAgentAdapter.prototype.outreachOpened = function (eventId) { if (eventId) this.outreachEvent = eventId; };
  DeepAgentAdapter.prototype.outreachDismissed = function (eventId) { if (eventId) this.markOutreach(eventId, 'dismissed'); };
  DeepAgentAdapter.prototype.markOutreach = function (eventId, action, cid) {
    this.json('POST', '/outreach/event', { event_id: eventId, action: action, visitor_id: this.visitorId(), session_id: cid ? this.sid(cid) : null });
  };

  // Thumbs on an answer (the backend's message id came with it), with the reason a thumbs-down gave.
  DeepAgentAdapter.prototype.feedback = function (ref, value, cid, note) {
    if (!ref || !value) return;
    this.json('POST', '/feedback', { message_id: ref, rating: value === 'up' ? 1 : -1, note: note ? cleanText(note, 1000) : null }, cid);
  };

  // A signed-in visitor (or signed out, with null): the server then knows who is talking and prefills forms.
  DeepAgentAdapter.prototype.setToken = function (token) {
    var self = this;
    this.token = token || null;
    return this.json('GET', '/me').then(function (me) { if (me) self.me = Object.assign({}, me, { memory: (self.me || {}).memory }); return me; });
  };

  // The server's own answer-card renderer (static/deep-ui.js), loaded on the first card; a failure turns cards off.
  DeepAgentAdapter.prototype.cardRenderer = function () {
    if (!this.cardP) {
      var self = this;
      this.cardP = import(/* webpackIgnore: true */ /* @vite-ignore */ this.base + '/static/deep-ui.js')
        .catch(function () { self.cardP = Promise.resolve(null); return null; });
    }
    return this.cardP;
  };

  // The visitor's conversations on the server (this browser's visitor id, or the signed-in user on any device).
  DeepAgentAdapter.prototype.conversations = function () {
    return this.json('GET', '/conversations').then(function (r) { return (r && r.items) || []; });
  };
  DeepAgentAdapter.prototype.conversation = function (cid) {
    return this.json('GET', '/conversations/' + encodeURIComponent(this.sid(cid))).then(function (r) {
      return r && r.messages ? r.messages.map(function (m) {
        var blocks = [{ type: 'text', text: m.text || '' }];
        var links = (m.sources || []).filter(function (s) { return s && s.url; }).slice(0, 4).map(function (s) { return { label: s.title || s.url, url: s.url }; });
        if (m.role === 'bot' && links.length) blocks.push({ type: 'buttons', options: links });
        return { role: m.role === 'user' ? 'user' : 'bot', ts: Date.parse(m.ts) || Date.now(), ref: m.role === 'bot' ? m.id : null,
          feedback: m.feedback === 1 ? 'up' : m.feedback === -1 ? 'down' : null, blocks: blocks };
      }) : null;
    });
  };
  DeepAgentAdapter.prototype.markRead = function (cid) { this.json('POST', '/conversations/' + encodeURIComponent(this.sid(cid)) + '/read'); };
  DeepAgentAdapter.prototype.rename = function (cid, title) {
    return this.json('PATCH', '/conversations/' + encodeURIComponent(this.sid(cid)), { title: String(title).slice(0, 80) });
  };

  // The visitor's bookings: upcoming ones show on Home with join, calendar, reschedule and cancel.
  DeepAgentAdapter.prototype.bookings = function () {
    return this.json('GET', '/bookings').then(function (r) { return (r && r.items) || []; });
  };

  DeepAgentAdapter.prototype.schedulerLink = function () {
    return this.json('GET', '/booking/availability?schedule=&tz=' + encodeURIComponent(this.tz)).then(function (d) { return d && d.fallback_link; });
  };

  DeepAgentAdapter.prototype.gifs = function (q) {
    return this.json('GET', '/gifs?q=' + encodeURIComponent(q || '')).then(function (r) { return (r && r.items) || []; });
  };

  // Server speech, when the backend has it: text to an audio Blob, and a recording to text.
  DeepAgentAdapter.prototype.speak = function (text) {
    return this.request('POST', '/tts', { text: String(text).slice(0, 4000) }).then(function (r) { return r.blob(); });
  };
  DeepAgentAdapter.prototype.transcribe = function (blob, lang) {
    var fd = new FormData();
    fd.append('file', blob, 'speech.webm');
    if (lang && lang !== 'auto') fd.append('language', lang);
    fd.append('hints', (navigator.languages || [navigator.language]).join(','));
    return this.request('POST', '/stt', fd).then(function (r) { return r.json(); });
  };

  // Reschedule (a new time for a booking's call type) and cancel, from the Home card or the chat.
  DeepAgentAdapter.prototype.rescheduleSlots = function (ctx, id, slug, signal) {
    var self = this;
    return this.callType(id, slug, signal).then(function (s) {
      if (!s) return { blocks: [{ type: 'text', text: 'I couldn\'t find that booking\'s call type. Try "Book a meeting" instead.' }] };
      return self.slots(ctx, s, signal).then(function (res) {
        res.blocks.forEach(function (b) { if (b.type === 'time_slots') b.context = { kind: 'reschedule', id: id, slug: s }; });
        return res;
      });
    });
  };

  // A booking's call type: given, or (from an email link, which names it but has no slug) looked up among the
  // visitor's bookings, then among the call types by name.
  DeepAgentAdapter.prototype.claimed = function (booking) { this.claimBooking = booking || null; };
  DeepAgentAdapter.prototype.callType = function (id, slug, signal) {
    if (slug) return Promise.resolve(slug);
    var self = this, name = this.claimBooking && String(this.claimBooking.id) === String(id) ? this.claimBooking.schedule_name : null;
    return this.bookings().then(function (items) {
      var b = items.filter(function (x) { return String(x.id) === String(id); })[0];
      if (b && b.schedule_slug) return b.schedule_slug;
      if (!name) return null;
      return self.request('GET', '/booking/availability?schedule=&tz=' + encodeURIComponent(self.tz), null, null, signal)
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var c = (d.choices || []).filter(function (x) { return x.name === name; })[0];
          return c ? c.slug : null;
        });
    });
  };
  DeepAgentAdapter.prototype.reschedule = function (cid, ctx, data, signal) {
    var self = this, c = data.context || {};
    return this.request('POST', '/booking/' + encodeURIComponent(c.id) + '/reschedule', { start: data.start, timezone: this.tz }, cid, signal)
      .then(function (r) { return r.json(); })
      .then(function (res) {
        var b = res.booking || {};
        if (res.status === 'rescheduled' || res.status === 'pending_zoom') {
          return { blocks: [{ type: 'confirmation', title: res.status === 'rescheduled' ? 'Booking moved' : 'One last step on Zoom', lines: [
            { icon: 'calendar', text: cleanLine(b.schedule_name, 120) || 'Your call' },
            { icon: 'clock', text: bookingWhen(b).full },
            { icon: 'mail', text: 'Both of you get an email' }] }]
            .concat(res.message ? [{ type: 'text', text: res.message }] : [],
              b.handoff_url ? [{ type: 'buttons', options: [{ label: 'Finish on Zoom', url: b.handoff_url }] }] : []) };
        }
        if (res.status === 'slot_taken') {
          return self.rescheduleSlots(ctx, c.id, c.slug, signal).then(function (more) {
            return { blocks: [{ type: 'text', text: res.message || 'That time was just taken. Please pick another.' }].concat(more.blocks) };
          });
        }
        return { blocks: [{ type: 'text', text: res.message || 'The booking couldn\'t be moved. Your original time still stands.' }] };
      });
  };
  DeepAgentAdapter.prototype.cancelBooking = function (cid, id, signal) {
    return this.request('DELETE', '/booking/' + encodeURIComponent(id), null, cid, signal)
      .then(function (r) { return r.json(); })
      .then(function (res) {
        var b = res.booking || {};
        if (res.status === 'cancelled' && res.already) {
          return { blocks: [{ type: 'confirmation', title: 'Already cancelled', lines: [
            { icon: 'calendar', text: cleanLine(b.schedule_name, 120) || 'Your call' },
            { icon: 'clock', text: bookingWhen(b).full }] },
            { type: 'buttons', options: [{ label: 'Book a new time', value: 'book', icon: 'calendar' }] }] };
        }
        if (res.status === 'cancelled') {
          return { blocks: [{ type: 'confirmation', title: 'Booking cancelled', lines: [
            { icon: 'calendar', text: cleanLine(b.schedule_name, 120) || 'Your call' },
            { icon: 'clock', text: bookingWhen(b).full },
            { icon: 'mail', text: 'Both of you get an email' }] }]
            .concat(res.zoom_note ? [{ type: 'text', text: res.zoom_note }] : [],
              [{ type: 'buttons', options: [{ label: 'Book a new time', value: 'book', icon: 'calendar' }] }]) };
        }
        // A failure after trying ("retry") explains itself; otherwise the server's line would wrongly say "Cancelled".
        return { blocks: [{ type: 'text', text: (res.retry && res.message) || 'The booking couldn\'t be cancelled right now. It still stands.' }] };
      });
  };

  // Server-sent events from a fetch response: one `data: {json}` per event, events split by a blank line.
  function readEvents(res, on) {
    var buf = '';
    function feed(chunk) {
      buf += chunk;
      var parts = buf.split(/\r?\n\r?\n/);
      buf = parts.pop();
      parts.forEach(function (part) {
        var data = part.split(/\r?\n/).filter(function (l) { return l.indexOf('data:') === 0; })
          .map(function (l) { return l.slice(5).replace(/^ /, ''); }).join('\n');
        if (!data) return;
        try { on(JSON.parse(data)); } catch (e) { /* a malformed event is skipped */ }
      });
    }
    if (!res.body || !res.body.getReader) return res.text().then(function (t) { feed(t + '\n\n'); });
    var reader = res.body.getReader(), dec = new TextDecoder();
    return (function pump() {
      return reader.read().then(function (r) {
        if (r.done) { feed(dec.decode() + '\n\n'); return; }
        feed(dec.decode(r.value, { stream: true }));
        return pump();
      });
    })();
  }

  // A few open times (a review's alternatives, a slots summary) as Robin's time picker.
  DeepAgentAdapter.prototype.timesBlock = function (schedule, slots) {
    return { type: 'time_slots', title: schedule.name, durationMinutes: schedule.duration_min,
      slots: slots.map(function (x) { return x.start_iso; }).filter(Boolean), context: this.slotContext(schedule) };
  };

  // What a time picker carries back with the chosen time: the call type it was for.
  DeepAgentAdapter.prototype.slotContext = function (schedule) {
    schedule = schedule || {};
    return { slug: schedule.slug, name: cleanLine(schedule.name, 120) || null, duration_min: schedule.duration_min || null };
  };

  DeepAgentAdapter.prototype.scheduleChoices = function (items) {
    return { type: 'buttons', schedules: true, options: items.map(function (s) {
      return { label: cleanLine(s.name, 120), meta: s.duration_min ? s.duration_min + ' min' : null, sub: cleanLine(s.description, 140) || null,
        value: 'schedule:' + s.slug, icon: 'calendar' };
    }) };
  };

  // "Book a meeting": the call types (one only: straight to its times).
  DeepAgentAdapter.prototype.startBooking = function (ctx, signal) {
    var self = this;
    return this.request('GET', '/booking/availability?schedule=&tz=' + encodeURIComponent(this.tz), null, null, signal)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var choices = d.choices || [];
        if (choices.length === 1) return self.slots(ctx, choices[0].slug, signal);
        if (choices.length) return { blocks: [{ type: 'text', text: 'Which kind of call suits you?' }, self.scheduleChoices(choices)] };
        return { blocks: self.unavailable(d) };
      });
  };

  DeepAgentAdapter.prototype.slots = function (ctx, slug, signal) {
    var self = this;
    return this.request('GET', '/booking/availability?schedule=' + encodeURIComponent(slug) + '&tz=' + encodeURIComponent(this.tz), null, null, signal)
      .then(function (r) { return r.json(); })
      .then(function (d) { return { blocks: self.slotBlock(ctx, d) }; });
  };

  // An availability answer as Robin's time picker (open times only), or what to do when there are none.
  DeepAgentAdapter.prototype.slotBlock = function (ctx, d) {
    if (!d || !d.ok) return this.unavailable(d);
    ctx.schedule = d.schedule;
    var open = [];
    (d.days || []).forEach(function (day) {
      (day.slots || []).forEach(function (s) { if (s.available) open.push(s.start_iso); });
    });
    if (!open.length) return [{ type: 'text', text: 'There are no open times for ' + (d.schedule && d.schedule.name || 'that call') + ' in the next days.' }]
      .concat(d.fallback_link ? [{ type: 'buttons', options: [{ label: 'See the full calendar', url: d.fallback_link }] }] : []);
    return [{ type: 'time_slots', title: d.schedule.name, durationMinutes: d.schedule.duration_min, slots: open,
      context: this.slotContext(d.schedule) }];
  };

  DeepAgentAdapter.prototype.unavailable = function (d) {
    var none = d && d.error === 'unknown_schedule' && !(d.choices || []).length;
    return [{ type: 'text', text: (!none && d && d.message) || 'Booking isn\'t available right now.' }]
      .concat(d && d.fallback_link ? [{ type: 'buttons', options: [{ label: 'Book on Zoom instead', url: d.fallback_link }] }] : []);
  };

  // A time is picked: the details form; "Confirm booking" sends it to /booking/confirm.
  DeepAgentAdapter.prototype.detailsForm = function (ctx, data, prefill) {
    var me = this.me || {}, mem = me.memory || {}, dc = data.context || {};
    var s = dc.name ? { name: dc.name, duration_min: dc.duration_min, slug: dc.slug } : ctx.schedule || {}, slug = dc.slug || s.slug;
    var p = { name: me.name || mem.name, email: me.email || mem.email, company: mem.company };
    Object.keys(prefill || {}).forEach(function (k) { if (prefill[k]) p[k] = prefill[k]; });
    var when = new Date(data.start);
    return { blocks: [{ type: 'lead_form', title: 'Your details', submitLabel: 'Confirm booking',
      hint: 'Nothing is booked until you confirm.',
      summary: { title: cleanLine(s.name, 120) || 'Your call', text: isNaN(when) ? '' : fmtDay.format(when) + ' · ' + timeRange(when, s.duration_min) },
      context: { kind: 'booking', slug: slug, start: data.start, name: s.name || null, duration_min: s.duration_min || null },
      fields: [
        { name: 'name', label: 'Name', required: true, autocomplete: 'name', value: p.name },
        { name: 'email', label: 'Email', type: 'email', required: true, autocomplete: 'email', value: p.email },
        { name: 'company', label: 'Company', autocomplete: 'organization', value: p.company },
        { name: 'notes', label: 'What would you like to cover?', value: p.reason }
      ] }] };
  };

  DeepAgentAdapter.prototype.confirm = function (cid, ctx, values, c, signal) {
    var self = this;
    values = values || {};
    // The backend's own limits (ConfirmIn), so a long paste never turns into a 422.
    return this.request('POST', '/booking/confirm', { schedule_slug: cleanLine(c.slug, 120), start: cleanLine(c.start, 40),
      name: cleanLine(values.name, 120), email: cleanLine(values.email, 200), company: cleanLine(values.company, 120),
      notes: cleanText(values.notes, 1000), timezone: this.tz }, cid, signal)
      .then(function (r) { return r.json(); })
      .then(function (res) {
        var b = res.booking || {};
        if (res.status === 'confirmed' || res.status === 'pending_zoom') {
          var links = [];
          if (b.join_url) links.push({ label: 'Join Zoom', url: b.join_url });
          if (b.handoff_url && !b.join_url) links.push({ label: 'Finish on Zoom', url: b.handoff_url });
          if (b.ics_url) links.push({ label: 'Add to calendar', url: b.ics_url });
          if (b.manage_url) links.push({ label: 'Manage booking', url: b.manage_url });
          return { blocks: [{ type: 'confirmation', title: res.status === 'confirmed' ? 'You\'re booked!' : 'One last step on Zoom', lines: [
            { icon: 'calendar', text: cleanLine(b.schedule_name, 120) || 'Your call' },
            { icon: 'clock', text: bookingWhen(b).full },
            { icon: 'mail', text: 'Details sent to ' + (b.email || values.email || 'your email') }
          ] }].concat(res.message ? [{ type: 'text', text: res.message }] : [], links.length ? [{ type: 'buttons', options: links }] : []) };
        }
        if (res.status === 'slot_taken') {
          return self.slots(ctx, c.slug, signal).then(function (more) {
            return { blocks: [{ type: 'text', text: res.message || 'That time was just taken. Please pick another.' }].concat(more.blocks) };
          });
        }
        if (res.status === 'invalid') {
          return { blocks: [{ type: 'text', text: res.message || 'Please check your details.' }].concat(self.detailsForm(ctx,
            { start: c.start, context: { slug: c.slug, name: c.name, duration_min: c.duration_min } },
            { name: values.name, email: values.email, company: values.company, reason: values.notes }).blocks) };
        }
        return { blocks: [{ type: 'text', text: res.message || 'The booking didn\'t go through. Please try again.' }]
          .concat(res.fallback_link ? [{ type: 'buttons', options: [{ label: 'Book on Zoom instead', url: res.fallback_link }] }] : []) };
      });
  };

  DeepAgentAdapter.prototype.handoverForm = function (payload) {
    var last = (payload.history || []).filter(function (m) { return m.role === 'user' && m.text; }).pop();
    var me = this.me || {}, mem = me.memory || {};
    return { blocks: [{ type: 'lead_form', title: 'Talk to the team', hint: 'They reply by email.', submitLabel: 'Send',
      context: { kind: 'handover' },
      fields: [
        { name: 'name', label: 'Name', required: true, autocomplete: 'name', value: me.name || mem.name },
        { name: 'email', label: 'Email', type: 'email', required: true, autocomplete: 'email', value: me.email || mem.email },
        { name: 'message', label: 'How can they help?', required: true, value: last && last.text !== 'Talk to the team' ? last.text : '' }
      ] }] };
  };

  DeepAgentAdapter.prototype.handover = function (cid, values, c, signal) {
    values = values || {};
    return this.request('POST', '/handover', { session_id: this.sid(cid), name: cleanLine(values.name, 120),
      email: cleanLine(values.email, 200), message: cleanText(values.message, 2000) || 'Please get in touch.' }, cid, signal)
      .then(function (r) { return r.json(); })
      .then(function (res) {
        return { blocks: [{ type: 'confirmation', title: 'Request sent', lines: [
          { icon: 'mail', text: 'The team will reply to ' + (values.email || 'your email') },
          res.host_email ? { icon: 'headset', text: 'Or email ' + res.host_email } : null
        ].filter(Boolean) }] };
      });
  };

  var BLOCK_TYPES = ['text', 'buttons', 'lead_form', 'time_slots', 'card', 'confirmation', 'error', 'files', 'ui_card'];

  function normalizeBlocks(res) {
    var blocks = (res && (res.blocks || (res.text ? [{ type: 'text', text: res.text }] : null))) || [];
    return blocks.filter(function (b) {
      if (b && b.type === 'ui_card') return typeof b.program === 'string' && b.program.length <= 4000;   // an answer card's program, drawn as text only
      return b && (BLOCK_TYPES.indexOf(b.type) !== -1 || typeof b.text === 'string');
    }).map(function (b) {
      return BLOCK_TYPES.indexOf(b.type) !== -1 ? b : { type: 'text', text: b.text };
    });
  }

  /* ---------------------------------------------------------------- widget */

  function RobinWidget(config, listeners) {
    this.cfg = Object.assign({}, DEFAULTS, config || {});
    this.userCfg = config || {};   // what the site set itself wins over what a backend suggests
    this.store = loadStore(this.cfg.persist);
    this.scheme = this.store.scheme || this.cfg.colorScheme;
    this.brand = this.store.brand || null;          // a colour chosen in Settings; null keeps the designed look
    this.textSize = this.store.textSize || 'm';      // 's' | 'm' | 'l', for the conversation's text
    this.sideOpen = this.store.sidebar !== false;    // chat history beside a wide conversation
    this.mode = 'hidden';
    this.wide = false;          // full height at half the screen's width (only while mode is 'full')
    this.view = 'home';
    this.activeId = null;
    this.typing = false;
    this.unread = 0;
    this.draft = '';
    this.attachments = [];      // files staged in the composer: { id, file, name, size, type, error, url }
    this.previews = {};         // attachment id -> image object URL (this session only)
    this.cx = null;             // the live composer's elements
    this.dict = null;           // active dictation
    this.call = null;           // active voice conversation
    this.voiceLangIdx = 0;
    this.handlers = {};
    (listeners || []).forEach(function (l) { this.on(l[0], l[1]); }, this);   // Robin.on handlers hear the first open too
    this.retryFiles = {};       // error message id -> the files its Retry sends again (this session only)
    this.threadPos = {};        // conversation id -> where the thread was scrolled when last left
    if (this.cfg.attachments === true) this.cfg.attachments = DEFAULTS.attachments;
    if (!Array.isArray(this.cfg.starters)) this.cfg.starters = [];
    if (!this.cfg.voiceLanguages || !this.cfg.voiceLanguages.length) this.cfg.voiceLanguages = ['auto'];
    this.adapter = this.cfg.adapter ||
      (this.cfg.deepAgent ? new DeepAgentAdapter(this.cfg.deepAgent, this.cfg)
        : this.cfg.endpoint ? new HttpAdapter(this.cfg.endpoint, this.cfg.headers) : new NoBackend());
    if (this.adapter instanceof NoBackend) {
      this.backend = { offline: true };
      if (global.console) console.warn('[Robin] No backend is set: pass deepAgent, endpoint or adapter to Robin.init().');
    }
    if (this.cfg.loadFonts) loadFonts();
    this.mount();
    if (this.cfg.persist) {
      this.storageFn = this.onStorage.bind(this);
      global.addEventListener('storage', this.storageFn);
    }
    // Open from the start without taking focus from the page.
    this.booting = true;
    if (this.cfg.initialMode !== 'hidden') this.open(this.cfg.initialMode);
    else this.scheduleTeaser();
    this.booting = false;
    if (this.adapter.setup) this.connect();
  }

  var P = RobinWidget.prototype;

  P.mount = function () {
    var self = this, c = this.cfg;
    this.host = h('div', { id: 'robin-widget' });
    this.host.style.cssText = 'position:fixed;width:0;height:0;bottom:0;right:0;z-index:' + c.zIndex;
    document.body.appendChild(this.host);
    this.shadow = this.host.attachShadow({ mode: 'open' });

    this.root = h('div', { class: 'root', 'data-mode': 'hidden', 'data-pos': c.position, 'data-motion': c.motion });
    this.applyColors();

    this.panel = h('section', { class: 'panel', role: 'dialog', tabindex: '-1', 'aria-label': c.appName + ' chat', 'aria-hidden': 'true' });
    this.badge = h('span', { class: 'badge', hidden: true });
    this.launcher = h('button', { class: 'launcher', 'aria-expanded': 'false', onclick: function () { self.toggle(); } },
      h('span', { class: 'ic ic-chat' }, bird()),
      h('span', { class: 'ic ic-close', html: ICON.chevronDown }),
      this.badge);
    this.teaserEl = h('div', { hidden: true });

    this.root.append(this.panel, this.teaserEl, this.launcher);
    // Escape peels back one layer at a time: popover, dictation, call screen, then the panel.
    this.root.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && self.veil && self.veil.isConnected) { e.stopPropagation(); self.stopReply(); return; }
      if (e.key !== 'Escape' || self.mode === 'hidden') return;
      e.stopPropagation();
      if (self.closePopovers()) return;
      if (self.dict) { self.stopDictation(false); return; }
      if (self.call && self.voiceEl && !self.voiceEl.hidden) { self.minimiseVoice(); return; }
      self.close();
    });
    // Clicking outside the "+" menu or the emoji picker closes it.
    this.root.addEventListener('pointerdown', function (e) {
      var cx = self.cx, path = e.composedPath(), pop = self.headPop;
      if (pop && path.indexOf(pop) === -1 && path.indexOf(pop.anchor) === -1) self.closeHeadMenu();
      if (!cx) return;
      if (cx.menu && !cx.menu.hidden && path.indexOf(cx.plusWrap) === -1) self.closeMenu();
      if (cx.picker && path.indexOf(cx.picker) === -1 && path.indexOf(cx.plusWrap) === -1) self.closeEmoji();
    });
    this.shadow.append(h('style', null, CSS), this.root);
    // The history sidebar docks only on wide screens: re-check when the window crosses that width.
    if (global.matchMedia) {
      this.wideMq = global.matchMedia('(min-width: 1100px)');
      this.onWideMq = function () { self.syncSide(); };
      if (this.wideMq.addEventListener) this.wideMq.addEventListener('change', this.onWideMq);
    }
    this.initTips();
    this.syncChrome();
  };

  // Tooltips for the widget's controls, in place of the browser's: a navy label that fades in above the control
  // after a short pause (below it when there's no room above), kept inside the window. A control's `title`
  // becomes its tip the first time the pointer reaches it (it keeps an aria-label either way), so labels that
  // change later, like the size chevrons', stay current. Keyboard focus shows the tip at once; touch never does.
  P.initTips = function () {
    var self = this, timer = 0, current = null;
    var tip = this.tipEl = h('div', { class: 'tip', 'aria-hidden': 'true' });
    this.root.append(tip);
    function hide() { clearTimeout(timer); current = null; tip.classList.remove('on'); }
    function show(el) {
      var text = el.getAttribute('data-tip');
      if (!text || el.disabled || !el.isConnected) return;
      tip.textContent = text;
      var r = el.getBoundingClientRect(), tw = tip.offsetWidth, th = tip.offsetHeight;
      var below = r.top < th + 10;
      var x = Math.max(8, Math.min(global.innerWidth - tw - 8, r.left + r.width / 2 - tw / 2));
      tip.style.left = x + 'px';
      tip.style.top = (below ? r.bottom + 6 : r.top - th - 6) + 'px';
      tip.style.setProperty('--ax', Math.round(r.left + r.width / 2 - x) + 'px');
      tip.classList.toggle('below', below);
      tip.classList.add('on');
    }
    function enter(e, now) {
      var el = e.target.closest && e.target.closest('[title],[data-tip]');
      if (!el || el === current) return;
      if (el.hasAttribute('title')) {
        el.setAttribute('data-tip', el.getAttribute('title'));
        if (!el.hasAttribute('aria-label')) el.setAttribute('aria-label', el.getAttribute('title'));
        el.removeAttribute('title');
      }
      hide();
      current = el;
      timer = setTimeout(function () { if (current === el) show(el); }, now ? 0 : 150);
    }
    this.root.addEventListener('pointerover', function (e) { if (e.pointerType !== 'touch') enter(e); });
    this.root.addEventListener('pointerout', function (e) { if (current && !current.contains(e.relatedTarget)) hide(); });
    this.root.addEventListener('focusin', function (e) { if (e.target.matches && e.target.matches(':focus-visible')) enter(e, true); });
    this.root.addEventListener('focusout', hide);
    this.root.addEventListener('pointerdown', hide);
    this.root.addEventListener('keydown', hide);
    this.root.addEventListener('scroll', hide, true);
  };

  P.applyColors = function () {
    var p = toHex(this.brand || this.cfg.primaryColor) || DEFAULTS.primaryColor, s = this.root.style, ink = inkFor(p);
    s.setProperty('--robin-primary', p);
    s.setProperty('--robin-on-primary', ink);
    // Light/dark variants are set inline; the stylesheet picks one per scheme
    // (inline custom properties would otherwise beat the dark-scheme rule).
    s.setProperty('--robin-primary-soft-light', 'color-mix(in srgb, ' + p + ' 12%, transparent)');
    s.setProperty('--robin-primary-soft-dark', 'color-mix(in srgb, ' + p + ' 22%, transparent)');
    // Brand colour used as text must stay readable on paper and on dark surfaces.
    s.setProperty('--robin-primary-text-light', readable(ink === '#FFFFFF' ? p : shade(p, -0.45), '#FFFFFF', -1));
    s.setProperty('--robin-primary-text-dark', readable(shade(p, 0.35), '#1C2841', 1));
    s.setProperty('--robin-primary-hi', shade(p, 0.35));   // voice orb highlight
    s.setProperty('--robin-primary-lo', shade(p, -0.4));   // voice orb shadow side
    // A brand colour chosen in Settings also takes over the swallow, its ring and the accent family the
    // stylesheet maps from these (light and dark sets, picked per scheme like the variants above).
    // The accent is also text (links, labels, focus): light text on white and dark text on the dark surfaces reach 4.5:1.
    var ai = readable(p, '#FFFFFF', -1), aiD = readable(shade(p, 0.35), '#1C2841', 1);
    var accent = {
      '--b-logo': p, '--b-ai': ai, '--b-ai-deep': shade(ai, -0.3), '--b-ai-mid': shade(p, 0.15), '--b-ai-lav': shade(p, 0.55),
      '--b-ai-pale': shade(p, 0.78), '--b-ai-pink': shade(p, 0.45), '--b-ai-wash': 'color-mix(in srgb, ' + p + ' 8%, transparent)',
      '--b-logo-d': shade(p, 0.4), '--b-ai-d': aiD, '--b-ai-deep-d': readable(shade(p, 0.5), '#1C2841', 1), '--b-ai-lav-d': shade(p, -0.2),
      '--b-ai-pale-d': shade(p, -0.55), '--b-ai-pink-d': shade(p, 0.2), '--b-ai-wash-d': 'color-mix(in srgb, ' + p + ' 14%, transparent)'
    };
    Object.keys(accent).forEach(function (k) { if (this.brand) s.setProperty(k, accent[k]); else s.removeProperty(k); }, this);
    this.root.toggleAttribute('data-brand', !!this.brand);
  };

  /* -- window state -- */

  // Every state change goes through here. Half <-> full only resizes the panel,
  // so the open thread, scroll position and half-typed form fields survive.
  P.setMode = function (mode) {
    mode = normMode(mode);
    var prev = this.mode;
    if (MODES.indexOf(mode) === -1 || prev === mode) return;
    if (this.call && mode === 'hidden') this.endVoice();
    var pin = this.atBottom();
    this.mode = mode;
    var unwide = mode !== 'full' && this.wide;
    if (unwide) this.wide = false;
    var resizeOnly = (prev === 'half' || prev === 'full') && (mode === 'half' || mode === 'full');
    if (resizeOnly) {
      this.syncChrome();
      this.syncSteppers();
      this.keepPinned(pin);
    } else {
      this.render();
    }
    if (unwide) this.emit('wide_change', { wide: false });
    if (prev === 'hidden') this.emit('open', { mode: mode, from: prev });
    else if (mode === 'hidden') this.emit('close', { mode: mode, from: prev });
    else this.emit('mode_change', { mode: mode, from: prev });
  };

  P.open = function (mode) {
    if (mode === 'hidden') { this.close(); return; }
    this.hideTeaser(false);
    this.unread = 0;
    mode = normMode(mode);
    this.setMode(MODES.indexOf(mode) > 0 ? mode : 'half');
    this.focusFirst();
    if (this.backend && this.backend.offline) this.note(this.adapter instanceof NoBackend ? this.cfg.appName + ' isn’t connected yet.'
      : this.cfg.appName + ' can’t reach its server right now. Messages may not send.');
  };

  // A backend with more than answers (the deep-agent adapter) says once, at start, what it offers: the privacy
  // link, quick starts, upload rules, voice languages, a returning visitor's greeting, GIFs and server speech.
  // What the site configured itself always wins. An email link's token in the page's fragment opens its chat.
  P.connect = function () {
    var self = this, u = this.userCfg;
    this.adapter.setup().then(function (info) {
      if (self.destroyed) return;
      info = info || {};
      self.backend = info;
      if (info.privacyUrl && !u.privacyUrl) self.cfg.privacyUrl = safeUrl(info.privacyUrl);
      if (info.starters && info.starters.length && !u.starters) {
        self.cfg.starters = info.starters.slice(0, 3).map(function (t) { var l = cleanLine(t, 80); return { label: l, value: l }; });
      }
      if (info.upload && self.cfg.attachments && !u.attachments) self.cfg.attachments = Object.assign({}, self.cfg.attachments, info.upload);
      if (info.voiceLanguages && !u.voiceLanguages) self.cfg.voiceLanguages = info.voiceLanguages;
      if (self.mode !== 'hidden') self.refresh();
      if (info.claim) self.openClaim(info.claim);
    }, function () {
      if (self.destroyed) return;
      self.backend = { offline: true };
      self.syncPresence();
      self.emit('backend_offline', {});
    });
  };

  // Opened from a booking email's "Ask" link: the chat the email was about, its suggested questions as chips,
  // and the chip's own question sent straight away when the email asked for that.
  P.openClaim = function (claim) {
    var self = this, convo = this.startConversation();
    this.adapter.claim(claim, convo.id).then(function (res) {
      if (self.destroyed || !res || !res.ok) return;
      var b = res.booking || {};
      if (!convo.title) convo.title = cleanLine(b.schedule_name, 60) || 'Your booking';
      // Each question does what it says: "a different time" opens the times for this booking, "book a new time"
      // the booking card; the rest are asked in the chat.
      var qs = (res.questions || []).slice(0, 4).map(function (q) {
        var l = cleanLine(q.text, 120);
        if (q.action === 'reschedule' && b.id) return { label: l, value: 'reschedule:' + b.id + ':', icon: 'clock' };
        if (q.action === 'book') return { label: l, value: 'book', icon: 'calendar' };
        return { label: l, value: l };
      });
      var when = b.start_iso || b.label_visitor ? bookingWhen(b).full : '';
      var join = safeUrl(b.join_url);
      self.pushMessage(convo, { role: 'bot', blocks: [{ type: 'text', text: res.opened_from ? 'You opened this from ' + cleanLine(res.opened_from, 120) + '. How can I help?' : 'How can I help with your booking?' }]
        .concat(when ? [{ type: 'card', title: cleanLine(b.schedule_name, 120) || 'Your call', text: when + (b.status === 'cancelled' ? ' (cancelled)' : ''),
          cta: join ? { label: 'Join Zoom', url: join } : null }] : [],
        qs.length ? [{ type: 'buttons', options: qs }] : []) });
      if (self.adapter.claimed) self.adapter.claimed(b);
      if (res.question && res.autosend) self.sendInput({ type: 'message', text: res.question.text, auto: true }, res.question.text);
    }, function (err) {
      if (self.destroyed) return;
      self.pushMessage(convo, { role: 'bot', blocks: [{ type: 'error', text: (err && err.message) || 'This link is not valid any more.' }] });
    });
  };

  P.close = function () {
    this.finishOpening();
    this.hideThinkVeil();   // the reply carries on; reopening brings the layer back if it's still thinking
    if (this.mode === 'hidden') return;
    this.stopReading();
    if (this.recording) this.recording.stop();
    var inside = !!this.shadow.activeElement;   // focus was in the widget: hand it to the launcher, else leave the page's
    this.setMode('hidden');
    if (inside) this.launcher.focus();
  };

  P.toggle = function () {
    this.mode === 'hidden' ? this.openWithTransition('half') : this.close();
  };

  // Opening from the launcher (or teaser), inside the chat window only, on root[data-opening]:
  //   loading   - the chat opens at once, covered by its own layer with Robin's stage (filling up) in the middle;
  //               the chat's content waits underneath (not displayed), and the page is untouched;
  //   revealing - once the chat is ready (web fonts loaded, at most 1.5s) and the loader has shown long
  //               enough not to flicker (0.75s), the layer fades while the content appears and rises in;
  //   ready     - the layer is removed.
  // Reduced motion, or `openingTransition: false`, opens directly.
  P.openWithTransition = function (mode) {
    var self = this;
    if (this.mode !== 'hidden' || this.opening) return;
    if (!this.cfg.openingTransition || this.reduceMotion()) { this.open(mode); return; }
    var o = this.opening = { timers: [] };
    this.root.dataset.opening = 'loading';
    this.open(mode);
    o.el = h('div', { class: 'boot', role: 'status', 'aria-label': 'Opening ' + this.cfg.appName }, robinStage({ state: 'loading', cycle: 1 }).el);
    this.panel.append(o.el);
    var fonts = document.fonts && document.fonts.ready ? Promise.race([document.fonts.ready, sleep(1500)]) : Promise.resolve();
    Promise.all([fonts, sleep(750)]).then(function () {
      if (self.opening !== o) return;
      if (!o.el.isConnected) self.panel.append(o.el);   // a re-render meanwhile emptied the panel
      self.root.dataset.opening = 'revealing';
      self.focusFirst();
      o.timers.push(setTimeout(function () { if (self.opening === o) self.finishOpening(); }, 460));
    });
  };

  // Ends the opening sequence: when it completes, or early when the chat is closed or destroyed.
  P.finishOpening = function () {
    var o = this.opening;
    if (!o) return;
    this.opening = null;
    o.timers.forEach(clearTimeout);
    o.el.remove();
    delete this.root.dataset.opening;
  };

  P.expand = function () {
    var i = MODES.indexOf(this.mode);
    if (i < MODES.length - 1) this.open(MODES[i + 1]);
  };

  P.collapse = function () {
    var i = MODES.indexOf(this.mode);
    if (i <= 1) this.close();
    else this.setMode(MODES[i - 1]);
  };

  // Wide is a width on top of full height: turning it on from half goes to full first.
  // Like half <-> full it only resizes the panel, so the thread and anything half-typed survive.
  // Only an open conversation can be widened.
  P.setWide = function (on) {
    on = !!on;
    if (on === (this.wide && this.mode === 'full')) return;
    if (on && !this.inThread()) return;
    var pin = this.atBottom();
    this.wide = on;
    if (on && this.mode !== 'full') {
      this.setMode('full');
    } else {
      this.syncChrome();
      this.syncSteppers();
      this.keepPinned(pin);
    }
    this.emit('wide_change', { wide: on });
  };

  P.inThread = function () {
    return this.mode !== 'hidden' && this.view === 'thread' && !!this.active();
  };

  P.atBottom = function () {
    var sc = this.scrollEl;
    return !!sc && sc.scrollHeight - sc.scrollTop - sc.clientHeight < 24;
  };

  // While the panel resizes, text reflows; a thread that was at its end stays at its end
  // every frame of the transition, and one scrolled back keeps its place.
  P.keepPinned = function (pin) {
    var sc = this.scrollEl;
    if (!pin || !sc) return;
    var until = Date.now() + 480;
    (function stick() {
      sc.scrollTop = sc.scrollHeight;
      if (Date.now() < until) requestAnimationFrame(stick);
    })();
  };

  // Conversations need room: open the half-screen messenger from the launcher.
  P.toMessenger = function () {
    if (this.mode === 'half' || this.mode === 'full') return false;
    var prev = this.mode;
    if (prev === 'hidden') { this.hideTeaser(false); this.unread = 0; }
    this.mode = 'half';
    this.emit(prev === 'hidden' ? 'open' : 'mode_change', { mode: 'half', from: prev });
    return true;
  };

  /* -- public API -- */

  P.setScheme = function (scheme) {
    this.scheme = ['light', 'dark', 'auto'].indexOf(scheme) !== -1 ? scheme : 'light';
    this.store.scheme = this.scheme;
    this.save();
    this.refresh();
    this.emit('scheme_change', { scheme: this.scheme });
  };

  // A hex colour, or null for the designed look (the site's colour on the launcher and buttons only).
  P.setBrand = function (color) {
    if (color != null && !/^#[0-9a-f]{6}$/i.test(String(color))) return;
    this.brand = color || null;
    if (this.brand) this.store.brand = this.brand; else delete this.store.brand;
    this.save();
    this.applyColors();
    this.refresh();
    this.emit('brand_change', { color: color });
  };

  P.setTextSize = function (size) {
    this.textSize = ['s', 'm', 'l'].indexOf(size) !== -1 ? size : 'm';
    this.store.textSize = this.textSize;
    this.save();
    this.refresh();
    this.emit('text_size_change', { size: this.textSize });
  };

  // On: everything holds still, as with the device's reduced-motion setting. Off: back to the configured
  // behaviour, or full animation if that would still hold it still (so the switch always does what it says).
  P.setReduceMotion = function (on) {
    delete this.store.motion;
    if (on) this.store.motion = 'reduce';
    else if (this.reduceMotion()) this.store.motion = 'full';
    this.save();
    this.refresh();
    this.emit('motion_change', { reduce: !!on });
  };

  // Re-renders after a setting changes. On the Settings screen it keeps the scroll position and skips the
  // cards' entrance, so only the change itself shows.
  // The control that had focus gets it back (the screen is rebuilt with the same controls in the same order).
  P.refresh = function () {
    var quiet = this.view === 'settings';
    var sc = this.view !== 'thread' && this.panel.querySelector(quiet ? '.settings' : '.view .scroll'), top = sc ? sc.scrollTop : 0;
    var controls = [].slice.call(this.panel.querySelectorAll('button,input'));
    var was = this.shadow.activeElement, at = controls.indexOf(was);
    var caret = was && was.tagName === 'INPUT' && typeof was.selectionStart === 'number' ? [was.selectionStart, was.selectionEnd] : null;
    this.settingsQuiet = quiet;
    this.render();
    this.settingsQuiet = false;
    sc = sc && this.panel.querySelector(quiet ? '.settings' : '.view .scroll');
    if (sc) sc.scrollTop = top;
    var again = at !== -1 && !(this.dialogEl && this.dialogEl.contains(was)) && this.panel.querySelectorAll('button,input')[at];
    if (again) {
      again.focus({ preventScroll: true });
      if (caret && again.setSelectionRange) try { again.setSelectionRange(caret[0], caret[1]); } catch (e) { /* not a text field */ }
    }
  };

  P.on = function (type, fn) {
    (this.handlers[type] = this.handlers[type] || []).push(fn);
    return this;
  };

  // Continues the open thread if there is one, otherwise starts a new one.
  // A signed-in visitor's token from the host page (null signs out): forms prefill and the server knows who it is.
  P.setToken = function (token) {
    this.cfg.visitorToken = token || null;
    if (this.adapter.setToken) return this.adapter.setToken(token);
  };

  P.ask = function (text) {
    if (this.active()) {
      this.view = 'thread';
      this.toMessenger();
      this.render();
    } else {
      this.startConversation();
    }
    this.sendInput({ type: 'message', text: text }, text);
  };

  P.reset = function () {
    this.stopReply(true);
    this.endVoice();
    this.hideThinkVeil();
    this.msgQuery = '';
    this.store.conversations = [];
    this.store.visitor = {};
    this.activeId = null;
    this.view = 'home';
    this.draft = '';
    this.attachments.forEach(function (a) { if (a.url) URL.revokeObjectURL(a.url); });
    this.attachments = [];
    Object.keys(this.previews).forEach(function (k) { URL.revokeObjectURL(this.previews[k]); }, this);
    this.previews = {};
    this.retryFiles = {};
    this.threadPos = {};
    this.bookingList = null;
    this.bookSync = 0;
    this.unread = 0;
    this.updateBadge();
    this.save();
    this.render();
  };

  P.destroy = function () {
    this.destroyed = true;
    this.stopReading();
    if (this.recording) this.recording.stop();
    if (this.offScroll) this.offScroll();
    clearTimeout(this.teaserShowTimer);
    // A reply still loading is cancelled, so it can't save into the store or emit events afterwards.
    if (this.run) { if (this.run.ctrl) this.run.ctrl.abort(); this.run = null; }
    this.finishOpening();
    this.hideThinkVeil();
    this.endVoice();
    this.stopDictation(false);
    clearTimeout(this.teaserTimer);
    clearTimeout(this.noteTimer);
    if (this.wideMq && this.wideMq.removeEventListener) this.wideMq.removeEventListener('change', this.onWideMq);
    if (this.storageFn) global.removeEventListener('storage', this.storageFn);
    this.host.remove();
  };

  /* -- state helpers -- */

  P.emit = function (type, data) {
    var evt = Object.assign({ type: type, at: new Date().toISOString() }, data);
    (this.handlers[type] || []).concat(this.handlers['*'] || []).forEach(function (fn) {
      try { fn(evt); } catch (e) { console.error('[Robin] handler error', e); }
    });
    if (typeof this.cfg.onEvent === 'function') {
      try { this.cfg.onEvent(evt); } catch (e) { console.error('[Robin] onEvent error', e); }
    }
    document.dispatchEvent(new CustomEvent('robin:event', { detail: evt }));
  };

  // The store is written whole. Past 100 conversations the oldest go; when the browser's quota is full, older
  // conversations are dropped one by one until it fits (never the open one). Private mode just doesn't save.
  P.save = function () {
    if (!this.cfg.persist || this.destroyed) return;
    var list = this.store.conversations, active = this.activeId;
    function dropOldest() {
      var old = list.filter(function (c) { return c.id !== active; }).sort(function (a, b) { return a.updatedAt - b.updatedAt; })[0];
      if (!old) return false;
      list.splice(list.indexOf(old), 1);
      return true;
    }
    while (list.length > 100 && dropOldest()) { /* keep the newest 100 */ }
    for (var i = 0; i < 50; i++) {
      try { localStorage.setItem(STORE_KEY, JSON.stringify(this.store)); return; } catch (e) {
        var full = e && (e.name === 'QuotaExceededError' || e.name === 'NS_ERROR_DOM_QUOTA_REACHED' || e.code === 22 || e.code === 1014);
        if (!full || !dropOldest()) return;
      }
    }
  };

  // Another tab saved: take its conversations (it wrote last), keeping what is newer here and the reply loading here.
  P.onStorage = function (e) {
    if (e.key !== STORE_KEY || !e.newValue || this.destroyed) return;
    var other;
    try { other = cleanStore(JSON.parse(e.newValue)); } catch (x) { return; }
    var mine = {}, run = this.run;
    this.store.conversations.forEach(function (c) { mine[c.id] = c; });
    var next = other.conversations.map(function (c) {
      var m = mine[c.id];
      return m && (m.updatedAt >= c.updatedAt || (run && run.convo === m)) ? m : c;
    });
    this.store.conversations.forEach(function (c) {   // this tab's own draft or the chat answering here
      var draft = !c.messages.some(function (m) { return m.role === 'user'; });
      if ((draft || (run && run.convo === c)) && !next.some(function (n) { return n.id === c.id; })) next.push(c);
    });
    this.store.conversations = next;
    this.store.visitor = other.visitor;
    ['scheme', 'brand', 'textSize', 'sidebar'].forEach(function (k) { if (k in other) this.store[k] = other[k]; }, this);
    if (this.mode !== 'hidden' && (this.view === 'home' || this.view === 'messages')) this.refresh();
    else this.syncHistory();
  };

  P.conversations = function () {
    return this.store.conversations
      .filter(function (c) { return c.messages.length > 1 || c.messages.some(function (m) { return m.role === 'user'; }); })
      .sort(function (a, b) { return b.updatedAt - a.updatedAt; });
  };

  P.active = function () {
    var id = this.activeId;
    return this.store.conversations.filter(function (c) { return c.id === id; })[0] || null;
  };

  // Opens a fresh thread (reusing an untouched draft) with Robin's intro.
  P.startConversation = function () {
    var draft = this.store.conversations.filter(function (c) {   // untouched: the greeting only
      return c.messages.length <= 1 && !c.messages.some(function (m) { return m.role === 'user'; });
    })[0];
    if (!draft) {
      draft = { id: uid('conv'), title: '', createdAt: Date.now(), updatedAt: Date.now(), messages: [{
        id: uid('m'), role: 'bot', ts: Date.now(),
        blocks: [{ type: 'text', text: 'Hi, I\'m ' + this.cfg.appName + (this.cfg.companyName ? ' from ' + this.cfg.companyName : '') +
          (this.cfg.starters.length ? '. Ask me anything, or pick a topic below.' : '. Ask me anything.') }]
      }] };
      this.store.conversations.push(draft);
    }
    this.activeId = draft.id;
    this.view = 'thread';
    this.toMessenger();
    this.render();
    return draft;
  };

  P.openThread = function (id) {
    var self = this;
    this.activeId = id;
    this.view = 'thread';
    this.toMessenger();
    var cv = this.active();
    if (cv && cv.unread) { cv.unread = 0; this.save(); }
    this.render();
    this.focusFirst();
    if (this.adapter.markRead) this.adapter.markRead(id);
    // A conversation known only from the server's list loads its full history on first open.
    if (cv && cv.remote && this.adapter.conversation) {
      var n = cv.messages.length;
      this.adapter.conversation(id).then(function (msgs) {
        if (!msgs || !msgs.length || self.destroyed || !cv.remote || cv.messages.length !== n) return;
        cv.messages = msgs.map(function (m) { return Object.assign({ id: uid('m') }, m); });
        cv.remote = false;
        self.save();
        if (self.activeId === id && self.view === 'thread' && self.mode !== 'hidden' && !self.typing) self.render();
      });
    }
  };

  // The visitor's conversations on the server (another device when signed in, or from before this browser's
  // storage was cleared) join the list; titles the server wrote replace first-question ones; unread replies get
  // a dot. At most every 20 s, when Messages opens.
  P.syncConversations = function () {
    var self = this, now = Date.now();
    if (!this.adapter.conversations || now - (this.convSync || 0) < 20000) return;
    this.convSync = now;
    this.adapter.conversations().then(function (items) {
      if (self.destroyed) return;
      var changed = false;
      items.forEach(function (it) {
        if (!it || !/^[A-Za-z0-9_-]{8,64}$/.test(it.session_id || '')) return;
        var cv = self.store.conversations.filter(function (c) { return c.id === it.session_id; })[0];
        var ts = Date.parse(it.last_ts) || Date.parse(it.started) || now, title = cleanLine(it.title, 80);
        if (!cv) {
          if (!it.questions) return;
          self.store.conversations.push({ id: it.session_id, title: title, createdAt: Date.parse(it.started) || ts, updatedAt: ts,
            remote: true, unread: it.unread || 0, messages: [
              { id: uid('m'), role: 'user', ts: ts, blocks: [{ type: 'text', text: cleanText(it.first_message, 200) || title || 'Conversation' }] },
              { id: uid('m'), role: 'bot', ts: ts, blocks: [{ type: 'text', text: cleanText(it.preview, 200) }] }] });
          changed = true;
          return;
        }
        if (title && it.title_source && it.title_source !== 'fallback' && cv.title !== title) { cv.title = title; changed = true; }
        var unread = cv.id === self.activeId ? 0 : it.unread || 0;
        if (unread !== (cv.unread || 0)) { cv.unread = unread; changed = true; }
      });
      if (!changed) return;
      self.save();
      if (self.view === 'messages' && self.mode !== 'hidden') self.refresh();
      else self.syncHistory();
    });
  };

  // Rename from the title menu; a backend that keeps conversations stores it too.
  P.renameActive = function () {
    var self = this, cv = this.active();
    if (!cv) return;
    this.confirmDialog({ icon: 'pen', tone: 'primary', title: 'Rename this conversation', yes: 'Save', no: 'Cancel',
      input: { value: cv.title || '', label: 'Conversation name', max: 80 } }).then(function (t) {
      t = t == null ? '' : cleanLine(t, 80);
      if (!t || self.destroyed) return;
      var now = self.store.conversations.filter(function (c) { return c.id === cv.id; })[0] || cv;
      now.title = t;
      self.save();
      self.syncHistory();
      if (self.adapter.rename) self.adapter.rename(cv.id, t);
    });
  };

  P.pushMessage = function (convo, msg) {
    msg.id = uid('m');
    msg.ts = Date.now();
    convo.messages.push(msg);
    convo.updatedAt = msg.ts;
    if (msg.role === 'user' && !convo.title) {
      var tb = msg.blocks.filter(function (b) { return b.type === 'text'; })[0];
      var fb = msg.blocks.filter(function (b) { return b.type === 'files'; })[0];
      convo.title = (tb ? gist(tb.text) : 'Attachment: ' + fb.files.map(function (f) { return f.name; }).join(', ')).slice(0, 60);
    }
    if (msg.role === 'bot' && convo.id !== this.activeId) convo.unread = (convo.unread || 0) + 1;   // a reply to a chat left meanwhile
    this.save();
    if (msg.role === 'user' && this.starterRow) { this.starterRow.remove(); this.starterRow = null; }
    if (this.view === 'thread' && this.activeId === convo.id && this.threadEl) {
      var node = this.renderMessage(msg);
      // A reply that streamed in is already on screen: swap it in without replaying its entrance.
      if (this.fromStream) node.classList.add('from-stream');
      else if (msg.role === 'bot' && !this.reduceMotion()) revealWords(node);
      this.threadEl.append(node);
      this.scrollThread();
    }
    this.fromStream = false;   // consumed whether or not the message was drawn
    // A conversation's first question puts it in the history (and to the top of it).
    if (msg.role === 'user') this.syncHistory();
    if (msg.role === 'bot' && this.mode === 'hidden') {
      this.unread++;
      this.updateBadge();
    }
  };

  // `files` are staged composer attachments; they go to the adapter as File objects.
  P.sendInput = function (input, echo, files) {
    var self = this, convo = this.active() || this.startConversation();
    if (input.text != null) input.text = cleanText(input.text, 4000);
    if (input.label != null) input.label = cleanLine(input.label, 200);
    if (echo != null) echo = cleanText(echo, 4000);
    var blocks = [];
    files = files || [];
    if (files.length) {
      input.attachments = files.map(function (a) {
        if (a.url) self.previews[a.id] = a.url;
        return { id: a.id, name: a.name, size: a.size, type: a.type };
      });
      blocks.push({ type: 'files', files: input.attachments });
    }
    if (echo) blocks.push({ type: 'text', text: echo });
    if (this.run) {   // one reply at a time; the old one (or its held reply) lands first
      var old = this.run, elsewhere = old.convo !== convo && !old.res;
      this.stopReply(true);
      // Asked in another chat while this one was still answering: say so there, with a way to ask again.
      if (elsewhere && !old.text) this.pushMessage(old.convo, { role: 'bot', blocks: [{ type: 'error', text: 'Stopped when you asked in another chat.', retry: old.input }] });
    }
    if (blocks.length) {
      this.pushMessage(convo, { role: 'user', blocks: blocks });
      if (input.type === 'message' && echo) this.emit('question_asked', { text: echo, conversationId: convo.id, via: input.via || 'text' });
      if (files.length) this.emit('files_sent', { count: files.length, conversationId: convo.id });
    }
    // One reply in flight at a time. `run` ties every callback to this request, so a stopped or
    // superseded reply can't touch the screen afterwards.
    if (this.run) this.stopReply(true);
    var run = this.run = { ctrl: global.AbortController ? new AbortController() : null, convo: convo, text: '', input: input };
    this.statusText = this.cfg.thinkingText;
    this.workState = 'thinking';
    this.presenceFlash = null;
    clearTimeout(this.flashTimer);
    this.setTyping(true);
    var started = Date.now();
    var opts = {
      signal: run.ctrl ? run.ctrl.signal : undefined,
      onStatus: function (text) { if (self.run === run) self.setStatus(text); },
      onText: function (text) { if (self.run === run) self.streamText(text); }
    };
    return Promise.resolve()
      .then(function () {
        return self.adapter.send({
          conversationId: convo.id,
          visitor: self.store.visitor,
          input: input,
          history: convo.messages.slice(-20).map(function (m) {
            return { role: m.role, text: m.blocks.map(function (b) {
              if (b.type === 'text') return b.text;
              if (b.type === 'files') return '[Attached: ' + b.files.map(function (f) { return f.name; }).join(', ') + ']';
              return '';
            }).filter(Boolean).join('\n') };
          }),
          page: { url: pageUrl(), title: document.title },
          files: files.map(function (a) { return a.file; })
        }, opts);
      })
      .then(function (res) {
        if (self.run === run) run.res = res;   // it has arrived: Stop from here on shows it rather than dropping it
        var wait = 550 - (Date.now() - started);
        return (wait > 0 ? sleep(wait) : Promise.resolve()).then(function () { return res; });
      })
      .then(function (res) {
        // A form sent (details for a quote or a booking): the swallow swoops in and the ring closes green, then
        // the reply shows.
        var stage = self.workStage, done = input.type === 'action' && input.name === 'submit_lead' &&
          normalizeBlocks(res).some(function (b) { return b.type === 'confirmation'; });
        if (self.run !== run || !done || !stage || !stage.el.isConnected) return res;
        self.workState = 'success';  // the backend has saved it: Stop during the pause still shows the reply  // and nothing turns the ring back to thinking meanwhile
        stage.set('success');
        return sleep(self.reduceMotion() ? 500 : 1300).then(function () { return res; });
      })
      .then(function (res) {
        if (self.run === run) self.landReply(run, res);
      })
      .catch(function (err) {
        if (self.run !== run) return;   // stopped by the visitor: stopReply already tidied up
        console.error('[Robin]', err);
        self.finishReply(run);
        var why = err && err.fromServer && cleanLine(err.message, 240);
        var em = { role: 'bot', blocks: [{ type: 'error', text: why || 'Something went wrong while answering. Please try again.', retry: input }] };
        self.pushMessage(convo, em);
        if (files.length) self.retryFiles[em.id] = files;   // Retry sends the files again
        self.syncPresence('error', 2200);
      });
  };

  // The reply in place: its message (with the server's id, for 👍 / 👎), the title it brought, the chat marked
  // read, Home's bookings refreshed after an action. Used by a reply that finished and one held when Stop came.
  P.landReply = function (run, res) {
    var self = this, convo = run.convo, input = run.input || {}, blocks = normalizeBlocks(res);
    this.finishReply(run);
    if (blocks.length) this.pushMessage(convo, { role: 'bot', blocks: blocks, ref: (res && res.ref) || null });
    if (res && res.title) Promise.resolve(res.title).then(function (t) {
      t = cleanLine(t, 80);
      if (t && convo.title !== t && !self.destroyed) { convo.title = t; self.save(); self.syncHistory(); }
    }, function () { /* the title is a nicety */ });
    if (this.adapter.markRead && this.activeId === convo.id && this.view === 'thread' && this.mode !== 'hidden') this.adapter.markRead(convo.id);
    if (input.type === 'action') this.bookSync = 0;   // a booking, a move or a cancel shows on Home at once
    this.syncPresence('done', 1200);
  };

  // Ends the loading state for `run`: the loader fades, a streamed draft hands over to the final message.
  P.finishReply = function (run) {
    this.run = null;
    this.fromStream = !!run.text;
    if (this.streamEl) { this.streamEl.remove(); this.streamEl = null; }
    this.setTyping(false);
  };

  // Stop: cancels the request (where the backend supports it) and ends loading cleanly. Text that had
  // already streamed in is kept as the reply. `quiet` skips the note (a new question replaced it).
  P.stopReply = function (quiet) {
    var run = this.run;
    if (!run) return;
    // The reply had already arrived (held for the success ring): show it instead of dropping it.
    if (run.res) { this.landReply(run, run.res); return; }
    if (run.ctrl) run.ctrl.abort();
    this.finishReply(run);
    this.fromStream = false;
    if (run.text) this.pushMessage(run.convo, { role: 'bot', blocks: [{ type: 'text', text: run.text }] });
    if (!quiet && this.threadEl && run.convo.id === this.activeId) {
      this.threadEl.append(h('div', { class: 'stopped', role: 'status' }, 'Response stopped'));
      this.scrollThread();
    }
    this.emit('reply_stopped', { conversationId: run.convo.id, partial: !!run.text });
    this.syncPresence('stopped', 1200);
  };

  // Progress message under the loader. Each change fades the old line out and the new one in.
  P.setStatus = function (text) {
    this.statusText = text;
    if (this.workState !== 'success') {
      this.workState = /search|look(ing)? up|browsing/i.test(text || '') ? 'search'
        : /writ|preparing|drafting|composing|typing/i.test(text || '') ? 'chat' : 'thinking';
    }
    var stage = this.workStage;
    if (stage && stage.ready && stage.el.isConnected) stage.set(this.workState);
    var box = this.statusEl;
    if (!box) return;
    var last = box.lastChild;
    if (last && !last.classList.contains('out') && last.textContent === text) return;
    [].slice.call(box.children).forEach(function (old) {
      if (old.classList.contains('out')) return;
      old.classList.add('out');
      setTimeout(function () { old.remove(); }, 180);
    });
    box.append(h('span', null, text));
  };

  // Streaming: the answer appears as it arrives, in place of the loader.
  P.streamText = function (text) {
    if (!this.run) return;
    this.run.text = text;
    if (!this.threadEl || this.run.convo.id !== this.activeId) return;
    if (!this.streamEl) {
      this.hideThinkVeil();   // the answer has started: let it be seen arriving
      if (this.typingEl) { this.typingEl.remove(); this.typingEl = null; }
      this.streamTextEl = h('div', { class: 'bubble' });
      this.streamEl = h('div', { class: 'msg bot streaming', 'aria-hidden': 'true', inert: true }, this.botHead(), h('div', { class: 'col' }, this.streamTextEl));
      this.syncPresence();
      this.threadEl.append(this.streamEl);
    }
    this.streamTextEl.innerHTML = rich(text) + '<i class="caret" aria-hidden="true"></i>';
    if (this.atBottom()) this.scrollThread(true);
  };

  // Loading: Robin's stage animates in the middle of the space left under the question, with the
  // current status beneath it ("Thinking" until the adapter reports a more specific step).
  P.setTyping = function (on) {
    this.typing = on;
    if (this.typingEl) {
      // The loader lifts out of the flow where it stands and fades, so the answer takes its place without a jump.
      var el = this.typingEl;
      el.style.top = el.offsetTop + 'px';
      el.style.height = el.offsetHeight + 'px';
      el.classList.add('out');
      setTimeout(function () { el.remove(); }, 220);
      this.typingEl = this.statusEl = null;
    }
    if (on && this.veilWanted()) {
      this.showThinkVeil();
    } else if (on) {
      if (this.threadEl && !this.streamEl && this.busyHere()) {
        this.statusEl = h('div', { class: 'ai-status', role: 'status', 'aria-live': 'polite' });
        this.typingEl = h('div', { class: 'ai-loading' },
          this.thinkStage(), this.statusEl);
        this.threadEl.append(this.typingEl);
        this.setStatus(this.statusText || this.cfg.thinkingText);
        this.scrollThread();
      }
    } else {
      this.hideThinkVeil();
    }
    if (this.chatEl) this.chatEl.classList.toggle('busy', this.busyHere());
    this.syncPresence();
    if (this.sendBtn) this.syncSend();
  };

  // The stage while Robin works on an answer: loading (the swallow fills) for the first 1.2s, then whatever
  // the backend reports: search (the magnifying glass) while it searches, chat (dots from the beak) while it
  // writes the answer, thinking (thought bubbles, the comet circling) otherwise.
  P.thinkStage = function () {
    var self = this, s = this.workStage = robinStage({ state: 'loading', still: this.reduceMotion() });
    setTimeout(function () { s.ready = true; s.set(self.workState || 'thinking'); }, 1200);
    return s.el;
  };

  // Thinking covers the whole chat window (`thinkingOverlay`), except during a voice call, once text is
  // streaming in, with reduced motion, or while the chat is closed. Otherwise the loader sits in the thread.
  P.veilWanted = function () {
    return !!this.cfg.thinkingOverlay && this.mode !== 'hidden' && !this.call && !this.streamEl && this.busyHere() &&
      !(this.run && this.run.text) && !this.reduceMotion();
  };

  // Thinking in the chat window: a blurred layer over the chat panel only (the page stays as it is), with
  // the large loader stage and the status in its middle. The chat's own stop button is under the layer, so
  // the layer carries one (Escape works too). A re-render empties the panel; the layer is put back and the
  // status re-pointed.
  P.showThinkVeil = function () {
    var self = this;
    if (!this.veil) {
      this.veilStatus = h('div', { class: 'ai-status' });
      var stop = h('button', { class: 'veil-stop', type: 'button', onclick: function () { self.stopReply(); } },
        h('span', { html: ICON.stop }), 'Stop');
      this.veil = h('div', { class: 'veil', role: 'status', 'aria-live': 'polite', 'aria-label': this.cfg.appName + ' is thinking' },
        h('div', { class: 'veil-in' }, this.thinkStage(), this.veilStatus, stop));
      this.panel.append(this.veil);
      void this.veil.offsetWidth;   // commit the transparent start so the fade and blur transition from it
      this.veil.classList.add('on');
      stop.focus({ preventScroll: true });
    } else if (!this.veil.isConnected) {
      this.panel.append(this.veil);
    }
    this.syncInert();   // the chat under the layer can't be reached by Tab or the pointer while it is up
    this.statusEl = this.veilStatus;
    this.setStatus(this.statusText || this.cfg.thinkingText);
  };

  // The layer fades, clears its blur and the loader swells away while the answer appears underneath.
  P.hideThinkVeil = function () {
    var v = this.veil;
    if (!v) return;
    var hadFocus = v.contains(this.shadow.activeElement);
    if (this.statusEl === this.veilStatus) this.statusEl = null;
    this.veil = this.veilStatus = null;
    this.syncInert();
    v.classList.remove('on');
    v.classList.add('out');
    setTimeout(function () { v.remove(); }, 460);
    if (hadFocus && this.composerTa) this.composerTa.focus({ preventScroll: true });
  };

  // A reply is loading for the conversation on screen (not one the visitor has left).
  P.busyHere = function () {
    return !!(this.typing && this.run && this.run.convo.id === this.activeId);
  };

  P.reduceMotion = function () {
    var m = this.motionMode();
    if (m === 'reduce') return true;
    return m !== 'full' && !!(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);
  };

  // 'auto' | 'full' | 'reduce': the Settings switch, if it has been used, else the config.
  P.motionMode = function () {
    return this.store.motion || this.cfg.motion;
  };

  // New messages glide into view; opening a thread jumps straight to the end.
  P.scrollThread = function (instant) {
    var sc = this.scrollEl;
    var smooth = !instant && !this.reduceMotion();
    if (sc) requestAnimationFrame(function () { sc.scrollTo({ top: sc.scrollHeight, behavior: smooth ? 'smooth' : 'auto' }); });
  };

  P.updateBadge = function () {
    this.badge.hidden = !this.unread;
    this.badge.textContent = this.unread > 9 ? '9+' : String(this.unread);
  };

  P.focusFirst = function () {
    var self = this;
    if (this.booting) return;
    requestAnimationFrame(function () {
      if (self.mode === 'hidden' || self.destroyed) return;
      // Composer if there is one; otherwise the dialog itself, so no button wears a stray focus ring.
      (self.panel.querySelector('textarea') || self.panel).focus({ preventScroll: true });
    });
  };

  /* -- teaser -- */

  // With a backend that has outreach rules (docs/OUTREACH.md), they decide whether a pop-up shows and what it
  // says, re-checked as the visitor reads (time on page, scroll); otherwise the configured teaser shows.
  P.scheduleTeaser = function () {
    var self = this, t = this.cfg.teaser;
    if (!t || readSession(TEASER_KEY) || this.adapter instanceof NoBackend) return;
    if (!this.adapter.outreach) { this.showTeaser(null, t.delay || 0); return; }
    var t0 = Date.now(), scrolled = 0, waitScroll = 0, generic = false, done = false;
    function onScroll() {
      var d = document.documentElement;
      scrolled = Math.max(scrolled, Math.min(100, Math.round(100 * (global.scrollY + global.innerHeight) / Math.max(1, d.scrollHeight))));
      if (waitScroll && scrolled >= waitScroll) { waitScroll = 0; check(); }
    }
    global.addEventListener('scroll', onScroll, { passive: true });
    this.offScroll = function () { global.removeEventListener('scroll', onScroll); self.offScroll = null; };
    function check() {
      if (done || self.destroyed || self.mode !== 'hidden') { if (self.offScroll) self.offScroll(); return; }
      self.adapter.outreach((Date.now() - t0) / 1000, scrolled).then(function (res) {
        if (done || self.destroyed || self.mode !== 'hidden' || readSession(TEASER_KEY)) return;
        if (res && res.rule) { done = true; if (self.offScroll) self.offScroll(); self.showTeaser(res.rule, 0); return; }
        if (!generic && (!res || res.default !== false)) { generic = true; self.showTeaser(null, t.delay || 0); }
        var wait = res && res.recheck || {};
        waitScroll = wait.scroll_pct || 0;
        if (wait.dwell_s) self.teaserTimer = setTimeout(check, Math.max(1, wait.dwell_s - (Date.now() - t0) / 1000) * 1000);
        else if (!waitScroll && self.offScroll) self.offScroll();
      });
    }
    check();
  };

  // The card above the launcher: Robin's logo and name, typing dots that turn into the message, and two quick
  // starts that go straight into a conversation. Its edge flows pink to purple; the launcher rings once.
  // `rule`: an outreach pop-up ({ title, text, replies, event_id }), or null for the configured teaser.
  P.showTeaser = function (rule, delay) {
    var self = this, a = this.adapter, text = friendlyDates(cleanText(rule ? rule.text : (this.cfg.teaser || {}).text, 300));
    if (!text) return;
    clearTimeout(this.teaserShowTimer);
    this.teaserShowTimer = setTimeout(function () {
      if (self.mode !== 'hidden' || self.destroyed) return;
      var opened = function () { if (rule && a.outreachOpened) a.outreachOpened(rule.event_id); };
      var dots = h('span', { class: 'typing', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'));
      var chips = rule
        ? (rule.replies || []).slice(0, 2).map(function (r) {
            var label = cleanLine(r.label, 80);
            return h('button', { class: 'tz-chip', type: 'button', onclick: function () {
              self.hideTeaser(true);
              opened();
              self.startConversation();
              if (r.book) self.sendInput({ type: 'action', name: 'button', value: 'book', label: label }, label);
              else self.sendInput({ type: 'message', text: label }, label);
            } }, icon(r.book ? 'calendar' : 'sparkles'), label);
          })
        : (self.cfg.starters || []).slice(0, 2).map(function (s) {
            return h('button', { class: 'tz-chip', type: 'button', onclick: function () { self.hideTeaser(true); self.pickStarter(s); } },
              icon(optionIcon(s) || 'sparkles'), s.label);
          });
      var title = rule && rule.title ? cleanLine(rule.title, 80) : '';
      var teaser = h('div', { class: 'teaser', role: 'status' },
        h('div', { class: 'tz-card' },
          h('div', { class: 'tz-head' },
            h('span', { class: 'tz-logo' }, bird()), h('b', null, self.cfg.appName), h('span', { class: 'tz-time' }, 'now'),
            h('button', { class: 'tz-x', type: 'button', 'aria-label': 'Dismiss', title: 'Dismiss', html: ICON.close, onclick: function () {
              self.hideTeaser(true);
              if (rule && a.outreachDismissed) a.outreachDismissed(rule.event_id);
            } })),
          h('button', { class: 'tz-body', type: 'button', 'aria-label': (title ? title + '. ' : '') + text, onclick: function () { opened(); self.openWithTransition('half'); } }, dots),
          chips.length ? h('div', { class: 'tz-chips' }, chips) : null));
      self.teaserEl.replaceWith(teaser);
      self.teaserEl = teaser;
      self.launcher.classList.add('nudge');
      setTimeout(function () { self.launcher.classList.remove('nudge'); }, 2900);
      setTimeout(function () {
        dots.replaceWith(h('span', { class: 'msgtxt' }, title ? [h('b', null, title), ' '] : null, text));
        teaser.classList.add('ready');
      }, 900);
      self.emit('teaser_shown', rule ? { rule: rule.id } : {});
    }, delay || 0);
  };

  P.hideTeaser = function (dismissed) {
    if (this.offScroll) this.offScroll();
    clearTimeout(this.teaserTimer);
    clearTimeout(this.teaserShowTimer);
    this.teaserEl.hidden = true;
    if (dismissed) writeSession(TEASER_KEY, '1');
  };


  // The bot's face in lists: the swallow at rest (on a soft disc).
  P.avatar = function (raw) {
    var node = bird(true);
    return raw ? node : h('span', { class: 'av' }, node);
  };

  // Beside Robin's answers in a conversation: the live swallow.
  P.chatAvatar = function () {
    return h('span', { class: 'av mark mr' }, ringedBird());
  };

  // Robin's presence: the swallow logo in the conversation header, with a small badge at its lower right
  // and a fine ring or soft waves round it showing what is happening right now. Ongoing activity decides the state (listening beats
  // speaking beats thinking/writing beats the emoji picker); short events flash over it for a moment.
  var PRESENCE = {
    idle: { label: 'Ready' },
    listening: { icon: 'mic', label: 'Listening' },
    muted: { icon: 'micOff', label: 'Muted' },
    speaking: { icon: 'volume', label: 'Speaking' },
    thinking: { icon: 'sparkles', label: 'Thinking' },
    writing: { icon: 'pen', label: 'Writing' },
    emoji: { icon: 'smile', label: 'Picking an emoji' },
    gif: { icon: 'gif', label: 'Picking a GIF' },
    offline: { icon: 'alert', label: 'Offline' },
    attaching: { icon: 'clip', label: 'File attached' },
    done: { icon: 'check', label: 'Done' },
    stopped: { icon: 'stop', label: 'Stopped' },
    error: { icon: 'alert', label: 'Something went wrong' }
  };

  P.presence = function () {
    this.presenceEl = h('span', { class: 'presence', role: 'img' },
      h('span', { class: 'p-logo mr' }, ringedBird()), h('i', { class: 'p-ring' }), h('i', { class: 'p-wave' }), h('i', { class: 'p-wave' }));
    this.syncPresence();
    return this.presenceEl;
  };

  P.presenceState = function () {
    var call = this.call;
    if (this.dict || this.recording) return 'listening';
    if (call) return call.state === 'speaking' ? 'speaking' : call.state === 'muted' ? 'muted' : call.state === 'thinking' ? 'thinking'
      : call.state === 'error' ? 'error' : 'listening';
    if (this.readingBtn) return 'speaking';
    if (this.typing) return this.streamEl ? 'writing' : 'thinking';
    if (this.cx && this.cx.picker) return this.cx.picker.classList.contains('gpick') ? 'gif' : 'emoji';
    if (this.backend && this.backend.offline) return 'offline';
    return 'idle';
  };

  // `flash`: show that state for `ms`, then fall back to whatever is going on.
  P.syncPresence = function (flash, ms) {
    var self = this;
    if (flash) {
      this.presenceFlash = flash;
      clearTimeout(this.flashTimer);
      this.flashTimer = setTimeout(function () { self.presenceFlash = null; self.syncPresence(); }, ms || 1400);
    }
    var el = this.presenceEl, base = this.presenceState();
    var state = base === 'listening' || base === 'speaking' ? base : this.presenceFlash || base;   // a live mic or voice outranks a flash
    if (!el || el.dataset.state === state) return;
    var p = PRESENCE[state];
    el.dataset.state = state;
    el.setAttribute('aria-label', this.cfg.appName + ': ' + p.label);
    el.title = p.label;
    var old = el.querySelector('.p-badge');
    if (old) old.remove();
    if (p.icon) el.append(h('span', { class: 'p-badge', html: ICON[p.icon] }));   // a fresh badge replays its entrance
  };

  /* -- render -- */

  P.syncChrome = function () {
    var open = this.mode !== 'hidden';
    this.root.dataset.mode = this.mode;
    this.launcher.tabIndex = this.mode === 'full' ? -1 : 0;   // hidden at full height, so out of the Tab order
    this.root.toggleAttribute('data-wide', this.wide && this.mode === 'full');
    this.root.dataset.scheme = this.scheme;
    this.root.dataset.motion = this.motionMode();
    this.root.dataset.text = this.textSize;
    this.panel.setAttribute('aria-hidden', String(!open));
    this.launcher.setAttribute('aria-expanded', String(open));
    this.launcher.setAttribute('aria-label', (open ? 'Close ' : 'Open ') + this.cfg.appName + ' chat');
    this.updateBadge();
  };

  P.render = function () {
    // Wide is for reading one conversation (Settings opened from it stays wide): Home and Messages go back
    // to normal width.
    if (!this.inThread() && this.view !== 'settings' && this.wide) { this.wide = false; this.emit('wide_change', { wide: false }); }
    this.syncChrome();
    if (this.dict) this.stopDictation(true); // keeps the words heard so far in the draft
    if (this.mode === 'hidden') return; // keep content so the panel fades out cleanly
    // Where the open thread was scrolled, so coming back to it (from Settings, Help, a re-render) keeps the place.
    if (this.threadEl && this.scrollEl && this.activeId) this.threadPos[this.activeId] = { top: this.scrollEl.scrollTop, end: this.atBottom() };

    this.threadEl = this.scrollEl = this.typingEl = this.statusEl = this.streamEl = this.sendBtn = this.composerTa = this.presenceEl = this.cx = this.chatEl = this.headPop = null;
    var view;
    if (this.view === 'thread' && this.active()) view = this.renderThread();
    else if (this.view === 'messages') view = this.renderMessages();
    else if (this.view === 'settings') view = this.renderSettings();
    else if (this.view === 'help') view = this.renderHelp();
    else { this.view = 'home'; view = this.renderHome(); }

    var self = this;
    var grab = h('button', { class: 'grab', type: 'button', 'aria-label': 'Resize chat', onclick: function () {
      self.mode === 'full' ? self.setMode('half') : self.expand();
    } });
    // An ongoing call survives re-renders: its bar sits above the view, its screen on top.
    var parts = [grab];
    if (this.callbarEl) parts.push(this.callbarEl);
    parts.push(view);
    if (this.voiceEl) parts.push(this.voiceEl);
    if (this.opening && this.opening.el) parts.push(this.opening.el);   // a re-render while opening keeps the loader
    if (this.dialogEl) parts.push(this.dialogEl);                       // ...and an open question, with its focus
    var inDialog = this.dialogEl && this.dialogEl.contains(this.shadow.activeElement) ? this.shadow.activeElement : null;
    this.panel.replaceChildren.apply(this.panel, parts);
    if (inDialog) inDialog.focus({ preventScroll: true });
    if (this.view === 'thread') {
      if (this.busyHere()) {
        this.setTyping(true);
        if (this.run.text) this.streamText(this.run.text);
      }
      var pos = this.threadPos[this.activeId], sc = this.scrollEl;
      if (pos && !pos.end && sc) requestAnimationFrame(function () { sc.scrollTop = pos.top; });
      else this.scrollThread(true);
    }
    this.syncInert();
    // Something asked for while the chat was closed (emoji or GIF picker, "+" menu) opens in the conversation.
    if (this.reopen && this.cx) {
      var again = this.reopen;
      this.reopen = null;
      if (again === 'emoji') this.openEmoji(); else if (again === 'gif') this.openGif(); else this.openMenu();
    }
  };

  P.go = function (view) { this.view = view; this.render(); this.focusFirst(); };

  P.openHelp = function () {
    var self = this;
    if (this.view !== 'help') this.helpFrom = this.view;
    this.go('help');
    // The server's own booking page, once (a deep-agent server names it with its call types).
    if (!this.schedulerUrl && this.adapter.schedulerLink && !this.schedulerAsked) {
      this.schedulerAsked = true;
      this.adapter.schedulerLink().then(function (u) {
        self.schedulerUrl = safeUrl(u);
        if (self.schedulerUrl && self.view === 'help' && self.mode !== 'hidden') self.refresh();
      });
    }
  };

  P.openSettings = function () {
    if (this.view !== 'settings') this.settingsFrom = this.view;
    this.go('settings');
  };

  P.ibtn = function (icon, label, fn) {
    return h('button', { class: 'ibtn', type: 'button', 'aria-label': label, title: label, html: ICON[icon], onclick: fn });
  };

  // Chevron pair: up steps half -> full, down steps back to half. Only the useful one shows: down at full
  // height, up at half (closing to the launcher is the × beside them).
  P.stepper = function () {
    var self = this;
    var el = h('div', { class: 'stepper', role: 'group', 'aria-label': 'Window size' },
      h('button', { class: 'step-down', type: 'button', html: ICON.chevronDown, onclick: function () { self.collapse(); } }),
      h('button', { class: 'step-up', type: 'button', html: ICON.chevronUp, onclick: function () { self.expand(); } }));
    this.syncStepper(el);
    return el;
  };

  P.syncStepper = function (el) {
    var up = el.querySelector('.step-up'), down = el.querySelector('.step-down');
    var upLabel = { half: 'Expand to full height', full: 'Already full height' }[this.mode] || 'Expand to full height';
    var downLabel = { half: 'Minimise to launcher', full: 'Shrink to half screen' }[this.mode] || 'Minimise to launcher';
    var upOff = this.mode === 'full', downOff = this.mode !== 'full';
    // A focused chevron that is about to go hands focus to its partner.
    var focused = this.shadow.activeElement;
    up.classList.toggle('off', upOff);
    down.classList.toggle('off', downOff);
    el.classList.toggle('single', upOff || downOff);
    if (upOff && focused === up) down.focus();
    if (downOff && focused === down) up.focus();
    up.setAttribute('aria-label', upLabel); up.title = upLabel;
    down.setAttribute('aria-label', downLabel); down.title = downLabel;
  };

  P.syncSteppers = function () {
    var self = this;
    this.panel.querySelectorAll('.stepper').forEach(function (el) { self.syncStepper(el); });
    this.panel.querySelectorAll('.b-wide').forEach(function (el) { self.syncWideBtn(el); });
    this.syncSide();
  };

  // Expand icon: widens the messenger to half the screen (at full height); press again to go back.
  // `cls`: the button style, 'ibtn' (default) or 'cbtn' (the conversation header's round bordered buttons).
  P.wideBtn = function (cls) {
    var self = this;
    var el = h('button', { class: (cls || 'ibtn') + ' b-wide', type: 'button', onclick: function () {
      self.setWide(!(self.wide && self.mode === 'full'));
    } });
    this.syncWideBtn(el);
    return el;
  };

  P.syncWideBtn = function (el) {
    var on = this.wide && this.mode === 'full';
    var label = on ? 'Back to normal width' : 'Expand to half the screen';
    el.innerHTML = on ? ICON.shrink : ICON.expand;
    el.setAttribute('aria-label', label);
    el.title = label;
  };

  P.pickStarter = function (s) {
    this.emit('starter_click', { label: s.label, value: s.value });
    this.startConversation();
    this.sendInput({ type: 'action', name: 'starter', value: s.value, label: s.label }, s.label);
    this.focusFirst();
  };

  P.preview = function (cv) {
    var last = cv.messages[cv.messages.length - 1];
    var b = last.blocks.filter(function (x) { return x.text || x.title || x.files; })[0] || {};
    var files = b.files ? 'Attachment: ' + b.files.map(function (f) { return f.name; }).join(', ') : '';
    return (last.role === 'user' ? 'You: ' : '') + gist(b.text || b.title || files || cv.title || '');
  };

  // The latest conversation, to pick up again, named by its first question: Home's row (the name, the last
  // message under it, how long ago and an arrow).
  P.continueRow = function (cls) {
    var self = this, cv = this.conversations()[0];
    if (!cv) return null;
    var name = cv.title || 'Your last conversation';
    var open = function () { self.openThread(cv.id); };
    return h('button', { class: cls + ' last', type: 'button', onclick: open },
      h('span', { class: 'av' }, this.avatar(true)),
      h('span', { class: 'grow' }, h('span', { class: 't' }, name), h('span', { class: 's' }, this.preview(cv))),
      h('span', { class: 'time' }, ago(cv.updatedAt)),
      h('span', { class: 'chev', html: ICON.arrow }));
  };

  // Home, in the conversation screen's style: the window controls along the top, a greeting, an "ask" field
  // that opens a conversation, the last conversation to pick up, and popular questions.
  P.renderHome = function () {
    var self = this, c = this.cfg, welcome = this.backend && this.backend.greeting;
    var recent = this.continueRow('row');
    this.syncBookings();
    var popular = c.starters.length ? h('div', { class: 'hcard' },
      h('div', { class: 'hcard-t' }, icon('trending'), 'Popular questions'),
      c.starters.slice(0, 3).map(function (s) {
        return h('button', { class: 'row', type: 'button', onclick: function () { self.pickStarter(s); } },
          icon(optionIcon(s) || 'arrow', 'ico'),
          h('span', { class: 'grow t' }, s.label),
          h('span', { class: 'chev', html: ICON.arrow }));
      })) : null;

    return h('div', { class: 'view home' },
      h('div', { class: 'chat-head' },
        h('div', { class: 'head-l' }, this.presence(), h('b', { class: 'head-name' }, c.appName)),
        h('div', { class: 'head-r' },
          this.stepper(),
          this.cbtn('help', 'Help & contact', function () { self.openHelp(); }),
          this.cbtn('gear', 'Settings', function () { self.openSettings(); }),
          this.cbtn('close', 'Close chat', function () { self.close(); }))),
      h('div', { class: 'scroll home-scroll' },
        h('div', { class: 'home-hero' },
          markBird(true),
          h('h2', null, welcome ? cleanLine(welcome.headline, 80) : c.greeting),
          h('h3', null, c.intro),
          welcome && welcome.line ? h('p', { class: 'hero-line' }, friendlyDates(cleanLine(welcome.line, 160))) : null),
        h('button', { class: 'ask', type: 'button', onclick: function () { self.startConversation(); self.focusFirst(); } },
          h('span', { class: 'ask-t' }, c.placeholder), h('span', { class: 'ask-go', html: ICON.arrowRight })),
        recent ? h('div', { class: 'hcard' }, h('div', { class: 'hcard-t' }, icon('messages'), 'Pick up where you left off'), recent) : null,
        this.bookingsCard(),
        popular),
      this.tabs());
  };

  // The visitor's bookings, from a backend that keeps them (at most every 30 s, when Home shows).
  P.syncBookings = function () {
    var self = this, now = Date.now();
    if (!this.adapter.bookings || now - (this.bookSync || 0) < 30000) return;
    this.bookSync = now;
    this.adapter.bookings().then(function (items) {
      if (self.destroyed) return;
      var before = JSON.stringify(self.bookingList || []);
      self.bookingList = items;
      if (JSON.stringify(items) !== before && self.view === 'home' && self.mode !== 'hidden') self.refresh();
    });
  };

  // "Your bookings" on Home: each upcoming call with Join, Add to calendar, Reschedule and Cancel, as its
  // booking allows. Reschedule and cancel happen in a conversation, where the result shows.
  P.bookingsCard = function () {
    var self = this, list = (this.bookingList || []).filter(function (b) { return b && b.state === 'upcoming'; }).slice(0, 3);
    if (!list.length) return null;
    function inChat(value, label) {
      return function () { self.startConversation(); self.sendInput({ type: 'action', name: 'button', value: value, label: label }, label); };
    }
    function link(url) { var go = safeUrl(url); return go ? function () { global.open(go, '_blank', 'noopener'); } : null; }
    function act(label, ic, fn, cls) {
      return fn ? h('button', { class: 'bk-act' + (cls ? ' ' + cls : ''), type: 'button', onclick: fn }, icon(ic), label) : null;
    }
    return h('div', { class: 'hcard' },
      h('div', { class: 'hcard-t' }, icon('calendar'), 'Your bookings'),
      list.map(function (b) {
        var name = cleanLine(b.schedule_name, 120) || 'Call', w = bookingWhen(b), when = w.full;
        return h('div', { class: 'bk' },
          h('div', { class: 'bk-top' },
            w.date ? h('span', { class: 'bk-date', 'aria-hidden': 'true' }, h('span', { class: 'm' }, w.month), h('span', { class: 'd' }, w.date)) : icon('calendar', 'ico'),
            h('span', { class: 'grow' }, h('span', { class: 't', title: name }, name),
              h('span', { class: 's' }, w.rel ? h('b', { class: 'bk-rel' }, w.rel) : null, w.rel ? ' · ' : null, w.time ? w.day + ' · ' + w.time : w.day))),
          h('div', { class: 'bk-acts' },
            act('Join', 'external', link(b.join_url), 'go'),
            b.join_url ? null : act('Finish on Zoom', 'external', link(b.handoff_url), 'go'),   // a hold the visitor confirms on Zoom
            act('Add to calendar', 'calendar', link(b.ics_url)),
            b.can_reschedule ? act('Reschedule', 'clock', inChat('reschedule:' + b.id + ':' + (b.schedule_slug || ''), 'Reschedule my call')) : null,
            b.can_cancel ? act('Cancel', 'trash', function () {
              self.confirmDialog({ icon: 'calendar', title: 'Cancel this booking?', text: name + (when ? ' · ' + when : ''),
                yes: 'Cancel booking', no: 'Keep booking' }).then(function (ok) { if (ok) inChat('cancel:' + b.id, 'Cancel my call')(); });
            }, 'danger') : null));
      }));
  };

  // A round bordered header button, as on the conversation screen.
  P.cbtn = function (ic, label, fn) {
    return h('button', { class: 'cbtn', type: 'button', 'aria-label': label, title: label, html: ICON[ic], onclick: fn });
  };

  P.tabs = function () {
    var self = this, ids = ['home', 'messages'];
    var now = Math.max(0, ids.indexOf(this.view));
    var from = this.lastTab == null ? now : this.lastTab;
    this.lastTab = now;
    function tab(id, icon, label) {
      return h('button', { class: 'tab', type: 'button', role: 'tab', 'aria-selected': String(self.view === id), onclick: function () { self.go(id); } },
        h('span', { html: ICON[icon] }), label);
    }
    // The indicator starts under the previous tab and slides to the new one.
    var ind = h('span', { class: 'tab-ind', 'aria-hidden': 'true', style: '--x:' + from });
    if (from !== now) requestAnimationFrame(function () { requestAnimationFrame(function () { ind.style.setProperty('--x', now); }); });
    return h('nav', { class: 'tabs', role: 'tablist', 'aria-label': 'Sections' },
      ind,
      tab('home', 'home', 'Home'),
      tab('messages', 'messages', 'Messages'));
  };

  // Messages: a search field (in the Home ask field's style) over the conversations, shown as soft card rows
  // (logo, title and time, a one-line preview, an arrow) that tint lavender on hover and arrive one by one;
  // a friendly empty state; a navy "New conversation" button.
  P.renderMessages = function () {
    var self = this, list = this.conversations(), rows = [];
    this.syncConversations();
    var body = list.length
      ? h('div', { class: 'mlist' }, list.map(function (cv, i) {
          var row = h('button', { class: 'mrow', type: 'button', style: '--i:' + Math.min(i, 8), onclick: function () { self.openThread(cv.id); } },
            h('span', { class: 'av' }, self.avatar(true)),
            h('span', { class: 'grow' },
              h('span', { class: 'mrow-top' }, h('span', { class: 't' }, cv.title || 'Conversation'),
                cv.unread ? h('i', { class: 'mdot', role: 'img', 'aria-label': 'Unread reply' }) : null, h('span', { class: 'time' }, ago(cv.updatedAt))),
              h('span', { class: 's' }, self.preview(cv))),
            h('span', { class: 'chev', html: ICON.arrow }));
          rows.push({ el: row, text: searchText(cv) });
          return row;
        }))
      : h('div', { class: 'mempty' },
          markBird(),
          h('h4', null, 'No conversations yet'),
          h('p', null, 'Ask a question to get started. Your chats with ' + this.cfg.appName + ' are kept here on this device.'));

    return h('div', { class: 'view msgs' },
      h('div', { class: 'chat-head' },
        h('div', { class: 'head-l' }, h('h2', { class: 'head-title' }, 'Messages'), list.length ? h('span', { class: 'head-count' }, String(list.length)) : null),
        h('div', { class: 'head-r' }, this.stepper(), this.cbtn('help', 'Help & contact', function () { self.openHelp(); }),
          this.cbtn('gear', 'Settings', function () { self.openSettings(); }),
          this.cbtn('close', 'Close chat', function () { self.close(); }))),
      list.length ? this.messageSearch(rows, body) : null,
      h('div', { class: 'scroll' }, body),
      h('div', { class: 'floating' },
        h('button', { class: 'pill', type: 'button', onclick: function () { self.startConversation(); self.focusFirst(); } },
          h('span', { html: ICON.plus }), 'New conversation')),
      this.tabs());
  };

  // Help & contact, in Settings' style: the ways to reach a person (book a meeting, talk to the team, a voice
  // conversation, the booking page), the common questions, and what the chat is and keeps, with the privacy
  // link and the latest conversation to download.
  P.renderHelp = function () {
    var self = this, c = this.cfg, last = this.conversations()[0];
    function row(ic, title, sub, fn) {
      return h('button', { class: 'row', type: 'button', onclick: fn }, icon(ic, 'ico'),
        h('span', { class: 'grow' }, h('span', { class: 't' }, title), sub ? h('span', { class: 's' }, sub) : null),
        h('span', { class: 'chev', html: ICON.arrow }));
    }
    function inChat(value, label) {
      return function () { self.startConversation(); self.sendInput({ type: 'action', name: 'button', value: value, label: label }, label); };
    }
    var booking = safeUrl(this.schedulerUrl || c.schedulerUrl), privacy = safeUrl(c.privacyUrl);
    // Questions only: a starter that books or reaches the team is already a row above.
    var questions = (c.starters || []).filter(function (s) {
      return !/^(book|book_demo|handover|contact)$/.test(s.value) && !BOOKING_WORDS.test(s.label) && !/\b(person|human|team|someone)\b/i.test(s.label);
    });
    return h('div', { class: 'view home setv helpv' },
      h('div', { class: 'chat-head' },
        h('div', { class: 'head-l' }, this.cbtn('back', 'Back', function () { self.go(self.helpFrom || 'home'); }), h('h2', { class: 'head-title' }, 'Help & contact')),
        h('div', { class: 'head-r' }, this.stepper(), this.cbtn('close', 'Close chat', function () { self.close(); }))),
      h('div', { class: 'scroll settings' },
        h('div', { class: 'hcard' },
          h('div', { class: 'hcard-t' }, icon('headset'), 'Get in touch'),
          row('calendar', 'Book a meeting', 'Pick a time that suits you', inChat('book', 'Book a meeting')),
          row('headset', 'Talk to a person', 'Leave your question; the team replies by email', inChat('handover', 'Talk to the team')),
          c.voice && SpeechRec ? row('wave', 'Voice conversation', 'Talk to ' + c.appName + ' out loud', function () { self.startVoice(); }) : null,
          booking ? row('external', 'Open the booking page', 'Pick a time on the scheduler', function () { global.open(booking, '_blank', 'noopener'); }) : null),
        questions.length ? h('div', { class: 'hcard' },
          h('div', { class: 'hcard-t' }, icon('trending'), 'Common questions'),
          questions.slice(0, 4).map(function (s) { return row(optionIcon(s) || 'help', s.label, null, function () { self.pickStarter(s); }); })) : null,
        h('div', { class: 'hcard' },
          h('div', { class: 'hcard-t' }, icon('lock'), 'About this chat'),
          h('p', { class: 'help-about' }, c.appName + ' answers from this site and can book a meeting or pass your question to the team. Your chats are kept on this device' +
            (this.adapter.conversations ? ' and with the team' : '') + '.', privacy ? [' ', h('a', { href: privacy, target: '_blank', rel: 'noopener noreferrer' }, 'Privacy policy')] : null),
          last ? row('download', 'Download your last conversation', last.title || 'As a text file', function () { self.downloadTranscript(last.id); }) : null)));
  };

  // The conversation as a plain-text file to keep: who said what and when, with sources, choices, forms, times
  // and bookings written out.
  P.downloadTranscript = function (id) {
    var self = this, cv = this.store.conversations.filter(function (x) { return x.id === (id || this.activeId); }, this)[0];
    if (!cv) return;
    // A chat known only from the server's list holds its first question and a preview: its history comes first.
    if (cv.remote && this.adapter.conversation && !cv.loadedForTranscript) {
      this.adapter.conversation(cv.id).then(function (msgs) {
        if (self.destroyed) return;
        self.downloadTranscript.call(self, cv.id, msgs && msgs.length ? msgs : null);
      });
      return;
    }
    if (arguments[1]) cv = Object.assign({}, cv, { messages: arguments[1] });
    var name = this.cfg.appName, when = function (ts) { return ts ? new Date(ts).toLocaleString() : ''; };
    var lines = [name + ' conversation' + (cv.title ? ': ' + cv.title : ''), when(cv.createdAt), ''];
    cv.messages.forEach(function (m) {
      var parts = [];
      (m.blocks || []).forEach(function (b) {
        var st = b.state || {};
        if (b.type === 'text' && b.text) parts.push(plain(b.text));
        else if (b.type === 'buttons') {
          var opts = (b.options || []).filter(function (o) { return !o.url; }), urls = (b.options || []).filter(function (o) { return o.url; });
          var chose = st.selected ? ((b.options || []).filter(function (o) { return o.value === st.selected; })[0] || {}).label || st.selected : '';
          if (opts.length) parts.push('Options: ' + opts.map(function (o) { return o.label; }).join(' | ') + (chose ? ' (chose: ' + chose + ')' : ''));
          if (urls.length) parts.push('Links: ' + urls.map(function (o) { return o.label + ' <' + o.url + '>'; }).join(', '));
        } else if (b.type === 'confirmation') parts.push((b.title || 'Done') + (b.lines ? ': ' + b.lines.map(function (l) { return l && l.text != null ? l.text : l; }).join('; ') : ''));
        else if (b.type === 'card') parts.push([b.title, b.text].filter(Boolean).join(' - ') + (b.cta && b.cta.url ? ' <' + b.cta.url + '>' : ''));
        else if (b.type === 'lead_form') parts.push((b.title || 'Form') + (st.submitted ? ' (sent: ' + Object.keys(st.values || {}).map(function (k) { return st.values[k]; }).filter(Boolean).join(', ') + ')' : ' (not sent)'));
        else if (b.type === 'time_slots') parts.push((b.title || 'Times') + (st.selected ? ': chose ' + when(st.selected) : ': times offered'));
        else if (b.type === 'files') parts.push('Attached: ' + (b.files || []).map(function (f) { return f.name; }).join(', '));
        else if (b.type === 'error') parts.push('(error) ' + (b.text || ''));
        else if (b.type === 'ui_card') parts.push('(an answer card was shown here)');
      });
      if (parts.length) lines.push('[' + when(m.ts) + '] ' + (m.role === 'user' ? 'You' : name) + ':', parts.join('\n'), '');
    });
    var url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' }));
    var a = h('a', { href: url, download: (name + ' ' + new Date(cv.updatedAt || Date.now()).toISOString().slice(0, 10)).replace(/\s+/g, '-').toLowerCase() + '.txt', hidden: true });
    this.root.append(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    this.emit('transcript_download', { conversationId: cv.id });
  };

  // Brand colours Settings offers after the default and the site's own: each reads on light and dark.
  // deependhq.com's palette (marigold, think blue, navy night) and Champ Robin's original purple.
  var BRAND_SWATCHES = [['Purple', '#6B46E5'], ['Marigold', '#F4A62A'], ['Blue', '#4A7BF7'], ['Navy', '#0E1A33']];
  var TEXT_SIZES = [['s', 'Small'], ['m', 'Default'], ['l', 'Large']];

  // Everything a conversation says, lower-cased, for the Messages search: its title and every message's text.
  function searchText(cv) {
    var parts = [cv.title || ''];
    cv.messages.forEach(function (m) {
      (m.blocks || []).forEach(function (b) {
        if (b.text) parts.push(plain(b.text));
        if (b.title) parts.push(b.title);
        if (b.files) b.files.forEach(function (f) { parts.push(f.name); });
      });
    });
    return parts.join(' ').toLowerCase();
  }

  // The search field over the Messages list. Typing narrows the rows to chats containing every word (in the
  // title or any message); clear (or Escape) shows them all again. The words typed survive a re-render.
  P.messageSearch = function (rows, list) {
    var self = this;
    var none = h('p', { class: 'mnone', hidden: true }, 'No chats match your search.');
    list.append(none);
    var input = h('input', { class: 'msearch-q', type: 'search', placeholder: 'Search your chats', 'aria-label': 'Search your chats',
      autocomplete: 'off', spellcheck: 'false', value: this.msgQuery || '', oninput: filter, onkeydown: function (e) {
        if (e.key === 'Escape' && input.value) { e.stopPropagation(); input.value = ''; filter(); }
      } });
    var clear = h('button', { class: 'msearch-x', type: 'button', 'aria-label': 'Clear search', title: 'Clear search', html: ICON.close, onclick: function () {
      input.value = ''; filter(); input.focus();
    } });
    function filter() {
      var words = input.value.toLowerCase().split(/\s+/).filter(Boolean), shown = 0;
      self.msgQuery = input.value;
      rows.forEach(function (r) {
        var hit = words.every(function (w) { return r.text.indexOf(w) !== -1; });
        r.el.hidden = !hit;
        if (hit) shown++;
      });
      none.hidden = shown > 0;
      clear.hidden = !words.length;
    }
    filter();
    return h('div', { class: 'msearch-wrap' },
      h('label', { class: 'msearch' }, h('span', { class: 'msearch-i', html: ICON.search }), input, clear));
  };

  // Settings, in the conversation screen's style: back and the title on the left, size and close on the right,
  // then a live preview of the chat (it follows every choice) and cards: the appearance (light / dark /
  // device and the brand colour), the text size, reduce motion, and clearing the history.
  // In a wide window the preview stays in view on the left.
  // A question with two answers, in the widget's own style (the browser's confirm() can't be styled and names the
  // page's address). The safe answer is focused; Esc or a tap outside it is "no"; Tab stays inside; focus goes back.
  // With `input` it asks for a line of text instead and resolves to it (null when cancelled).
  P.confirmDialog = function (o) {
    var self = this, back = this.shadow.activeElement;
    if (this.dialogEl && this.dialogEl.isConnected) return Promise.resolve(o.input ? null : false);   // one question at a time
    return new Promise(function (resolve) {
      var done = false, tid = uid('cd'), field = null;
      function close(answer) {
        if (done) return;
        done = true;
        veil.remove();
        if (self.dialogEl === veil) self.dialogEl = null;
        self.syncInert();
        if (back && back.isConnected && back.focus) back.focus({ preventScroll: true }); else self.focusFirst();
        resolve(field ? (answer ? field.value : null) : answer);
      }
      var no = h('button', { class: 'cd-no', type: 'button', onclick: function () { close(false); } }, o.no || 'Cancel');
      var yes = h('button', { class: 'cd-yes' + (o.tone === 'primary' ? ' go' : ''), type: 'button', onclick: function () { close(true); } }, o.yes || 'OK');
      if (o.input) {
        field = h('input', { class: 'cd-in', type: 'text', maxlength: String(o.input.max || 200), 'aria-label': o.input.label || o.title, autocomplete: 'off' });
        field.value = o.input.value || '';
        field.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); close(true); } });   // not while an IME composes
      }
      // The card takes focus itself when its text is clicked, so keys still reach the dialog (not the widget behind it).
      var card = h('div', { class: 'cd-card' + (o.tone === 'primary' ? ' go' : ''), role: o.input ? 'dialog' : 'alertdialog', 'aria-modal': 'true', tabindex: '-1',
        'aria-labelledby': tid, 'aria-describedby': o.text ? tid + 'd' : null },
        h('span', { class: 'cd-ic' }, icon(o.icon || 'alert')),
        h('h3', { id: tid }, o.title),
        o.text ? h('p', { id: tid + 'd' }, o.text) : null,
        field,
        h('div', { class: 'cd-row' }, no, yes));
      var veil = h('div', { class: 'cd-veil', onclick: function (e) { if (e.target === veil) close(false); } }, card);
      var stops = [field, no, yes].filter(Boolean);
      veil.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(false); }
        else if (e.key === 'Tab') {
          e.preventDefault();
          var i = stops.indexOf(self.shadow.activeElement);
          stops[(i + (e.shiftKey ? stops.length - 1 : 1)) % stops.length].focus();
        }
      });
      self.dialogEl = veil;
      self.panel.append(veil);
      self.syncInert();
      requestAnimationFrame(function () {
        if (field) { field.focus({ preventScroll: true }); field.select(); } else no.focus({ preventScroll: true });
      });
    });
  };

  P.renderSettings = function () {
    var self = this, c = this.cfg;
    function schemeOpt(id, ico, label) {
      return h('button', { type: 'button', role: 'radio', 'aria-checked': String(self.scheme === id), onclick: function () { self.setScheme(id); } },
        icon(ico), label);
    }
    // A segmented control's pill slides from the previous choice to the new one, like the tabs.
    function segInd(key, ids, now) {
      var last = self.lastSeg || (self.lastSeg = {}), i = Math.max(0, ids.indexOf(now));
      var from = last[key] == null ? i : last[key];
      last[key] = i;
      var ind = h('span', { class: 'seg-ind', 'aria-hidden': 'true', style: '--x:' + from });
      if (from !== i) requestAnimationFrame(function () { requestAnimationFrame(function () { ind.style.setProperty('--x', i); }); });
      return ind;
    }

    var preview = h('div', { class: 'hcard sprev', 'aria-hidden': 'true' },
      h('div', { class: 'sp-screen' },
        h('span', { class: 'sp-mark' }, markBird(true)),
        h('span', { class: 'sp-user' }, 'Hi there.'),
        h('span', { class: 'sp-bot' }, h('span', { class: 'av mark mr' }, ringedBird()), h('span', null, 'Sure, I can help with that.')),
        h('span', { class: 'sp-box' }, h('span', { class: 'sp-ph' }, 'Message ' + c.appName), h('span', { class: 'sp-send', html: ICON.arrowRight }))),
      h('span', { class: 'sp-foot' }, 'Live preview', h('span', { class: 'sp-launch' }, bird())));

    // Default is the designed look (the plum Robin mark, purple accents); any other swatch colours the whole chat.
    var site = toHex(c.primaryColor);
    var swatches = [['Default', null]].concat(site ? [['Site colour', site]] : [], BRAND_SWATCHES.filter(function (sw) {
      return sw[1].toLowerCase() !== String(site).toLowerCase();
    }));
    var brandRow = h('div', { class: 'brand-row' },
      h('span', { class: 't' }, 'Brand colour'),
      h('div', { class: 'swatches', role: 'radiogroup', 'aria-label': 'Brand colour' }, swatches.map(function (sw) {
        var on = sw[1] ? String(self.brand).toLowerCase() === sw[1].toLowerCase() : !self.brand;
        return h('button', { class: 'sw' + (sw[1] ? '' : ' def'), type: 'button', role: 'radio', 'aria-checked': String(on), 'aria-label': sw[0], title: sw[0],
          style: sw[1] ? '--c:' + sw[1] + ';--ci:' + inkFor(sw[1]) : null, html: on ? ICON.check : null, onclick: function () { self.setBrand(sw[1]); } });
      })));

    var still = this.reduceMotion();
    return h('div', { class: 'view setv' + (this.settingsQuiet ? ' quiet' : '') },
      h('div', { class: 'chat-head' },
        h('div', { class: 'head-l' }, this.cbtn('back', 'Back', function () { self.go(self.settingsFrom || 'home'); }), h('h2', { class: 'head-title' }, 'Settings')),
        h('div', { class: 'head-r' }, this.stepper(), this.cbtn('close', 'Close chat', function () { self.close(); }))),
      h('div', { class: 'scroll settings' },
        preview,
        h('div', { class: 'hcard sset' },
          h('div', { class: 'hcard-t' }, icon('palette'), 'Appearance'),
          h('div', { class: 'seg', role: 'radiogroup', 'aria-label': 'Appearance' },
            segInd('scheme', ['light', 'dark', 'auto'], this.scheme), schemeOpt('light', 'sun', 'Light'), schemeOpt('dark', 'moon', 'Dark'), schemeOpt('auto', 'monitor', 'Device')),
          brandRow),
        h('div', { class: 'hcard sset' },
          h('div', { class: 'hcard-t' }, icon('type'), 'Text size'),
          h('div', { class: 'seg tsize', role: 'radiogroup', 'aria-label': 'Text size' },
            segInd('text', ['s', 'm', 'l'], this.textSize),
            TEXT_SIZES.map(function (t) {
              return h('button', { class: 'ts-' + t[0], type: 'button', role: 'radio', 'aria-checked': String(self.textSize === t[0]), 'aria-label': t[1], title: t[1],
                onclick: function () { self.setTextSize(t[0]); } }, 'Aa');
            }))),
        h('div', { class: 'hcard sset' },
          h('button', { class: 'srow', type: 'button', role: 'switch', 'aria-checked': String(still), onclick: function () { self.setReduceMotion(!still); } },
            h('span', { class: 'grow' }, h('span', { class: 't' }, 'Reduce motion'), h('span', { class: 's' }, 'The swallow stays still and loaders stop spinning')),
            h('span', { class: 'switch', 'aria-hidden': 'true' }))),
        h('div', { class: 'hcard sset' },
          h('div', { class: 'hcard-t' }, icon('lock'), 'Privacy'),
          h('button', { class: 'danger', type: 'button', onclick: function () {
            self.confirmDialog({ icon: 'trash', title: 'Clear conversation history?', text: 'This removes your chats from this device. It can’t be undone.',
              yes: 'Clear history', no: 'Keep chats' }).then(function (ok) { if (ok) self.reset(); });
          } },
            h('span', { class: 'dz-ic' }, icon('trash')),
            h('span', { class: 'grow' }, h('span', { class: 't' }, 'Clear conversation history'), h('span', { class: 's' }, 'Removes your chats from this device')),
            h('span', { class: 'chev', html: ICON.arrow })))));
  };

  // Conversation screen: a clean white canvas, a three-button
  // header (home, title menu, window menu), the thread, and the floating composer.
  P.renderThread = function () {
    var self = this, c = this.cfg, convo = this.active();
    this.threadEl = h('div', { class: 'thread', role: 'log', 'aria-live': 'polite' });
    var hasUser = convo.messages.length > 1 || convo.messages.some(function (m) { return m.role === 'user'; });
    this.starterRow = null;
    if (hasUser) {
      convo.messages.forEach(function (m) { self.threadEl.append(self.renderMessage(m, true)); });
    } else {
      // Idle: the stage at rest (the swallow gliding in its ring, the arc circling, a breathing glow and shadow),
      // a greeting and the quick starts, with plenty of white space. Gone once something is asked.
      this.starterRow = h('div', { class: 'idle' },
        robinStage({ state: 'idle', still: this.reduceMotion() }).el,
        h('h3', null, c.intro),
        h('p', null, 'Ask ' + c.appName + ' anything' + (c.starters.length ? ', or start with one of these.' : '.')),
        c.starters.length ? this.renderBlock({ type: 'buttons', options: c.starters.slice(0, 3), starter: true }, null) : null);
      this.threadEl.append(this.starterRow);
    }
    this.scrollEl = h('div', { class: 'scroll' }, this.threadEl);

    var title = h('button', { class: 'title-pill', type: 'button', 'aria-haspopup': 'menu', 'aria-expanded': 'false', title: 'Conversations',
      onclick: function () { self.toggleHeadMenu(title, 'convos'); } },
      this.presence(), h('span', null, c.appName), h('i', { html: ICON.chevronDown }));
    // Home and the title on the left; on the right every window control in view: wider view (900px and
    // up), the size chevrons (only the useful ones show), settings and close.
    this.chatEl = h('div', { class: 'view chat' },
      h('div', { class: 'chat-head' },
        h('div', { class: 'head-l' }, this.sideBtn(), this.cbtn('home', 'Home', function () { self.go('home'); }), title),
        h('div', { class: 'head-r' },
          this.wideBtn('cbtn'),
          this.stepper(),
          this.cbtn('gear', 'Settings', function () { self.openSettings(); }),
          this.cbtn('close', 'Close chat', function () { self.close(); }))),
      this.scrollEl,
      this.composer(function (text, files) { self.sendInput({ type: 'message', text: text }, text, files); }, c.placeholder),
      this.historySide());
    this.syncSide();
    return this.chatEl;
  };

  // The chat history beside the conversation, in the wide view only (on screens 1100px and up, where the
  // conversation keeps room to read): a hide button above "New conversation", then past chats by day. The
  // header's sidebar button brings it back; whether it is shown is remembered.
  P.historySide = function () {
    var self = this, groups = [], byName = {};
    var today = new Date(); today.setHours(0, 0, 0, 0);
    this.conversations().forEach(function (cv) {
      var g = cv.updatedAt >= today.getTime() ? 'Today' : cv.updatedAt >= today.getTime() - 6 * 864e5 ? 'This week' : 'Earlier';
      if (!byName[g]) groups.push(byName[g] = { name: g, items: [] });
      byName[g].items.push(cv);
    });
    var list = groups.length ? groups.map(function (g) {
      return [h('div', { class: 'side-h' }, g.name)].concat(g.items.map(function (cv) {
        return h('button', { class: 'side-item', type: 'button', 'aria-current': cv.id === self.activeId ? 'true' : null,
          onclick: function () { self.openThread(cv.id); } }, cv.title || 'Conversation');
      }));
    }) : h('p', { class: 'side-empty' }, 'Your conversations will show here.');
    return [
      h('aside', { class: 'side', 'aria-label': 'Chat history' },
        h('div', { class: 'side-top' },
          h('b', null, 'Chats'),
          h('button', { class: 'cbtn b-hide', type: 'button', 'aria-label': 'Hide chat history', title: 'Hide chat history', html: ICON.sidebar,
            onclick: function () { self.toggleSide(); } })),
        h('button', { class: 'side-new', type: 'button', onclick: function () { self.startConversation(); self.focusFirst(); } },
          h('span', { html: ICON.plus }), 'New conversation'),
        h('nav', { class: 'side-list' }, list))
    ];
  };

  // Redraws the history list in place, keeping its scroll position.
  P.syncHistory = function () {
    var old = this.chatEl && this.chatEl.querySelector('.side');
    if (!old) return;
    var list = old.querySelector('.side-list'), top = list ? list.scrollTop : 0, side = this.historySide()[0];
    old.replaceWith(side);
    side.querySelector('.side-list').scrollTop = top;
  };

  // The header's sidebar button, shown in the wide view while the history is hidden.
  P.sideBtn = function () {
    var self = this;
    return h('button', { class: 'cbtn b-side', type: 'button', 'aria-label': 'Show chat history', title: 'Show chat history', html: ICON.sidebar,
      onclick: function () { self.toggleSide(); } });
  };

  P.sideDocked = function () {
    return this.wide && this.mode === 'full' && !!(this.wideMq && this.wideMq.matches);
  };

  P.toggleSide = function () {
    if (!this.sideDocked()) return;
    var open = this.sideOpen = !this.sideOpen;
    this.store.sidebar = open;
    this.save();
    this.syncSide();
    var to = this.chatEl && this.chatEl.querySelector(open ? '.side-new' : '.b-side');
    if (to) to.focus();
  };

  P.syncSide = function () {
    var chat = this.chatEl;
    if (!chat) return;
    var can = this.sideDocked();
    chat.classList.toggle('can-side', can);
    chat.classList.toggle('docked', can && this.sideOpen);
    var btn = chat.querySelector('.b-side');
    if (btn) btn.setAttribute('aria-expanded', String(can && this.sideOpen));
  };

  // The conversations menu under the title: start a new conversation or switch to a recent one.
  P.toggleHeadMenu = function (anchor, kind) {
    var self = this, again = this.headPop && this.headPop.dataset.kind === kind;
    this.closeHeadMenu();
    if (again) return;
    function item(ic, label, fn, current) {
      return h('button', { type: 'button', role: 'menuitem', 'aria-current': current ? 'true' : null, onclick: function () { self.closeHeadMenu(); fn(); } },
        h('i', { html: ICON[ic] }), h('span', null, label));
    }
    var items = [item('plus', 'New conversation', function () { self.startConversation(); self.focusFirst(); })];
    var here = this.active();
    if (this.adapter.rename && here && here.messages.some(function (m) { return m.role === 'user'; })) {
      items.push(item('pen', 'Rename conversation', function () { self.renameActive(); }));
    }
    if (here && here.messages.some(function (m) { return m.role === 'user'; })) {
      items.push(item('download', 'Download transcript', function () { self.downloadTranscript(here.id); }));
    }
    var recent = this.conversations().filter(function (cv) { return cv.messages.some(function (m) { return m.role === 'user'; }); }).slice(0, 5);
    if (recent.length) items.push(h('hr'));
    recent.forEach(function (cv) {
      items.push(item('messages', cv.title || 'Conversation', function () { self.openThread(cv.id); }, cv.id === self.activeId));
    });
    items.push(h('hr'), item('help', 'Help & contact', function () { self.openHelp(); }),
      item('arrow', 'All conversations', function () { self.go('messages'); }));
    var pop = this.headPop = h('div', { class: 'hpop', role: 'menu', 'data-kind': kind }, items);
    pop.anchor = anchor;
    pop.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      e.preventDefault();
      var list = [].slice.call(pop.querySelectorAll('button'));
      var i = list.indexOf(self.shadow.activeElement), step = e.key === 'ArrowDown' ? 1 : -1;
      list[(i + step + list.length) % list.length].focus();
    });
    anchor.setAttribute('aria-expanded', 'true');
    this.chatEl.append(pop);
    pop.querySelector('button').focus();
  };

  P.closeHeadMenu = function () {
    var pop = this.headPop;
    if (!pop) return false;
    this.headPop = null;
    var hadFocus = pop.contains(this.shadow.activeElement);
    pop.anchor.setAttribute('aria-expanded', 'false');
    pop.remove();
    if (hadFocus && pop.anchor.isConnected) pop.anchor.focus();
    return true;
  };

  // The input: a large floating panel, text on top and the controls underneath ("+" menu and voice on the
  // left, send on the right; send turns into stop while a reply loads). onSend(text, files).
  P.composer = function (onSend, placeholder) {
    var self = this, c = this.cfg;
    var cx = this.cx = { placeholder: placeholder };
    var ta = cx.ta = h('textarea', { class: 'q', rows: '1', placeholder: placeholder, 'aria-label': placeholder, enterkeyhint: 'send' });
    ta.value = this.draft;
    if (ta.value) requestAnimationFrame(function () { if (ta.isConnected) grow(); });   // a restored draft at its full height
    var send = h('button', { class: 'send', type: 'submit', 'aria-label': 'Send message', title: 'Send', html: ICON.arrowRight });
    this.sendBtn = send;
    this.composerTa = ta;

    function grow() {
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
      self.draft = ta.value;
      self.syncSend();
    }
    cx.grow = grow;

    // `viaButton`: the send button doubles as stop while a reply loads; Enter never stops a reply.
    function submit(viaButton) {
      if (self.busyHere()) { if (viaButton) self.stopReply(); return; }
      if (self.dict) self.stopDictation(true);
      var text = ta.value.trim();
      var files = self.attachments.filter(function (a) { return !a.error; });
      if (!text && !files.length) return;
      self.attachments.forEach(function (a) { if (a.error && a.url) URL.revokeObjectURL(a.url); });
      self.attachments = [];
      ta.value = '';
      self.closePopovers();
      self.renderChips();
      grow();
      // The arrow flies off; restart the animation even on rapid sends.
      send.classList.remove('fly');
      void send.offsetWidth;
      send.classList.add('fly');
      setTimeout(function () { send.classList.remove('fly'); }, 550);
      onSend(text, files);
    }

    // "+" menu
    var items = [], fileInput = null, plusWrap = null;
    if (c.attachments) {
      fileInput = h('input', { type: 'file', multiple: true, hidden: true, accept: c.attachments.accept || null });
      fileInput.addEventListener('change', function () { self.addFiles(fileInput.files); fileInput.value = ''; });
      items.push(['clip', 'Attach a file', function () { fileInput.click(); }]);
    }
    if (c.emoji) items.push(['smile', 'Emoji', function () { self.openEmoji(); }]);
    if (this.backend && this.backend.gifs && this.adapter.gifs) items.push(['gif', 'GIF', function () { self.openGif(); }]);
    var serverEars = !!(this.backend && this.backend.sttServer && this.adapter.transcribe && global.MediaRecorder);
    if (c.dictation) items.push(['mic', 'Dictate', function () { SpeechRec ? self.startDictation() : self.recordDictation(); }, !SpeechRec && !serverEars]);
    if (items.length) {
      cx.plus = h('button', { class: 'cicon b-plus', type: 'button', 'aria-label': 'Attach a file, emoji or dictation', title: 'Add',
        'aria-haspopup': 'menu', 'aria-expanded': 'false', html: ICON.plus,
        onclick: function () {
          cx.menu.hidden ? self.openMenu() : self.closeMenu();
        } });
      cx.menu = h('div', { class: 'pmenu', role: 'menu', 'aria-label': 'Add to your message', hidden: true }, items.map(function (it) {
        return h('button', { type: 'button', role: 'menuitem', disabled: !!it[3], onclick: function () { self.closeMenu(); it[2](); } },
          h('span', { html: ICON[it[0]] }), it[1], it[3] ? h('small', null, 'Not in this browser') : null);
      }));
      cx.menu.addEventListener('keydown', function (e) {
        if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
        e.preventDefault();
        var list = [].slice.call(cx.menu.querySelectorAll('button:not(:disabled)'));
        var i = list.indexOf(self.shadow.activeElement), step = e.key === 'ArrowDown' ? 1 : -1;
        var next = list[(i + step + list.length) % list.length];
        if (next) next.focus();
      });
      plusWrap = cx.plusWrap = h('div', { class: 'plus-wrap' }, cx.plus, cx.menu);
    }

    // Secondary action beside "+": a spoken voice conversation (`voice: false` removes it).
    var speak = c.voice ? h('button', { class: 'cicon speak', type: 'button', disabled: !SpeechRec, html: ICON.wave,
      'aria-label': SpeechRec ? 'Start a voice conversation with ' + c.appName : 'Voice conversation needs Chrome, Edge or Safari',
      title: SpeechRec ? 'Voice conversation' : 'Voice needs Chrome, Edge or Safari',
      onclick: function () { self.startVoice(); } }) : null;

    // Recorder controls, visible only while dictating.
    cx.recTime = h('span', null, '0:00');
    var recCancel = h('button', { class: 'cicon recui', type: 'button', 'aria-label': 'Cancel dictation', title: 'Cancel', html: ICON.close,
      onclick: function () { self.stopDictation(false); } });
    var recMeter = h('span', { class: 'recmeter recui' }, h('span', { class: 'recdot', 'aria-hidden': 'true' }),
      h('span', { class: 'eq', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'), h('i')), cx.recTime);
    var recOk = h('button', { class: 'cicon recok recui', type: 'button', 'aria-label': 'Finish dictation', title: 'Done', html: ICON.check,
      onclick: function () { self.stopDictation(true); } });

    cx.attachEl = h('div', { class: 'attach' });
    var box = cx.box = h('form', { class: 'cbox', novalidate: true }, cx.attachEl, h('div', { class: 'tabox' }, ta),
      h('div', { class: 'cctl' }, fileInput, recCancel, plusWrap, speak, recMeter, h('span', { class: 'sp' }), send, recOk));

    ta.addEventListener('input', grow);
    ta.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
    });
    box.addEventListener('submit', function (e) { e.preventDefault(); submit(true); });
    if (c.attachments) {
      ta.addEventListener('paste', function (e) {
        var dt = e.clipboardData;
        if (dt && dt.files.length && !dt.getData('text')) { e.preventDefault(); self.addFiles(dt.files); }
      });
      box.addEventListener('dragover', function (e) { e.preventDefault(); box.classList.add('drop'); });
      box.addEventListener('dragleave', function () { box.classList.remove('drop'); });
      box.addEventListener('drop', function (e) {
        e.preventDefault();
        box.classList.remove('drop');
        if (e.dataTransfer && e.dataTransfer.files.length) self.addFiles(e.dataTransfer.files);
      });
    }

    cx.foot = h('div', { class: 'foot' });
    cx.el = h('div', { class: 'composer' }, box, cx.foot);
    this.resetFoot();
    this.renderChips();
    this.syncSend();
    return cx.el;
  };

  P.syncSend = function () {
    if (!this.sendBtn) return;
    var hasFiles = this.attachments.some(function (a) { return !a.error; });
    var send = this.sendBtn, stop = this.busyHere() && !!this.cx;
    send.disabled = stop ? false : !this.composerTa.value.trim() && !hasFiles;
    if (this.cx && this.cx.box) this.cx.box.classList.toggle('busy', this.typing);
    // While a reply loads, send becomes a dark stop button with a white square.
    if (send.classList.contains('stop') !== stop) {
      send.classList.toggle('stop', stop);
      send.innerHTML = stop ? ICON.stop : ICON.arrowRight;
      var label = stop ? 'Stop generating' : 'Send message';
      send.setAttribute('aria-label', label);
      send.title = stop ? 'Stop' : 'Send';
    }
  };

  P.resetFoot = function () {
    var cx = this.cx, c = this.cfg;
    if (!cx) return;
    cx.foot.className = 'foot';
    cx.foot.removeAttribute('role');
    // One short line: the privacy notice when there's a policy to link to, otherwise the AI note.
    cx.foot.innerHTML = c.privacyUrl && /^https?:\/\//.test(c.privacyUrl)
      ? '<span>By chatting with us, you agree to our <a href="' + esc(c.privacyUrl) + '" target="_blank" rel="noopener noreferrer">Privacy Policy</a></span>'
      : '<span>' + esc(c.disclaimer) + '</span>';
  };

  // A short message under the input (file too big, mic blocked, ...).
  P.note = function (text) {
    var self = this, cx = this.cx;
    if (!cx) return;
    clearTimeout(this.noteTimer);
    cx.foot.className = 'foot note';
    cx.foot.setAttribute('role', 'status');
    cx.foot.replaceChildren(icon('alert'), h('span', null, text));
    this.noteTimer = setTimeout(function () { self.resetFoot(); }, 4500);
  };

  P.closePopovers = function () {
    if (this.closeHeadMenu()) return true;
    var closed = this.closeMenu();
    closed = this.closeEmoji() || closed;
    if (closed && this.cx) this.cx.ta.focus();
    return closed;
  };

  P.openMenu = function () {
    var cx = this.cx;
    if (!cx || !cx.menu) return;
    this.closeEmoji();
    cx.menu.hidden = false;
    cx.plus.setAttribute('aria-expanded', 'true');
    var first = cx.menu.querySelector('button:not(:disabled)');
    if (first) first.focus();
  };

  P.closeMenu = function () {
    var cx = this.cx;
    if (!cx || !cx.menu || cx.menu.hidden) return false;
    cx.menu.hidden = true;
    cx.plus.setAttribute('aria-expanded', 'false');
    return true;
  };

  /* -- attachments -- */

  P.addFiles = function (list) {
    var self = this, rules = this.cfg.attachments;
    if (!rules || !list || !list.length) return;
    var max = rules.maxFiles || 5, maxMB = rules.maxSizeMB || 10;
    [].slice.call(list).forEach(function (file) {
      if (self.attachments.some(function (a) { return a.name === file.name && a.size === file.size && a.file && a.file.lastModified === file.lastModified; })) return;
      if (self.attachments.filter(function (a) { return !a.error; }).length >= max) { self.note('You can attach up to ' + max + ' files per message.'); return; }
      var err = file.size > maxMB * 1048576 ? 'Over ' + maxMB + ' MB' : !acceptOk(file, rules.accept) ? 'Type not supported' : null;
      self.attachments.push({ id: uid('f'), file: file, name: file.name, size: file.size, type: file.type || '', error: err,
        url: !err && /^image\//.test(file.type) ? URL.createObjectURL(file) : null });
    });
    this.emit('files_added', { count: list.length });
    if (this.attachments.some(function (a) { return !a.error; })) this.syncPresence('attaching', 1400);
    this.renderChips();
  };

  P.removeFile = function (id) {
    var self = this;
    var finish = function () {
      self.attachments = self.attachments.filter(function (a) {
        if (a.id === id && a.url) URL.revokeObjectURL(a.url);
        return a.id !== id;
      });
      self.renderChips();
      if (self.cx) self.cx.ta.focus();
    };
    // Shrink the chip out first, then drop it.
    var chip = this.cx && this.cx.attachEl.querySelector('[data-id="' + id + '"]');
    if (chip) { chip.classList.add('out'); setTimeout(finish, 160); } else finish();
  };

  P.renderChips = function () {
    var self = this, cx = this.cx;
    if (!cx) return;
    this.chipSeen = this.chipSeen || {};
    cx.attachEl.replaceChildren.apply(cx.attachEl, this.attachments.map(function (a) {
      var fresh = !self.chipSeen[a.id];   // only newly added chips pop in
      self.chipSeen[a.id] = true;
      return h('div', { class: 'achip' + (a.error ? ' err' : '') + (fresh ? ' new' : ''), 'data-id': a.id, title: a.error ? a.name + ': ' + a.error : a.name },
        a.url ? h('img', { src: a.url, alt: '' }) : h('span', { class: 'ext' }, fileExt(a.name)),
        h('span', { class: 'meta' }, h('span', { class: 'nm' }, a.name), h('span', { class: 'sz' }, a.error || fmtSize(a.size))),
        h('button', { class: 'x', type: 'button', 'aria-label': 'Remove ' + a.name, html: ICON.close, onclick: function () { self.removeFile(a.id); } }));
    }));
    this.syncSend();
  };

  /* -- emoji -- */

  P.openEmoji = function () {
    var self = this;
    // Asked for while the chat is closed: open the conversation and show it there.
    if (this.mode === 'hidden') { this.reopen = 'emoji'; this.startConversation(); return; }
    var cx = this.cx;
    if (!cx) return;
    if (cx.picker) { this.closeEmoji(); return; }
    var search = h('input', { type: 'search', placeholder: 'Search emoji', 'aria-label': 'Search emoji' });
    var grid = h('div', { class: 'egrid', role: 'group', 'aria-label': 'Emoji' });
    function draw() {
      var q = search.value.trim().toLowerCase();
      var list = EMOJI.filter(function (x) { return !q || x.k.indexOf(q) !== -1; });
      grid.replaceChildren.apply(grid, list.length ? list.map(function (x) {
        var name = x.k.split(' ')[0];
        return h('button', { type: 'button', title: name, 'aria-label': name, onclick: function () { self.insertText(x.e); } }, x.e);
      }) : [h('div', { class: 'eempty' }, 'No emoji match "' + search.value + '"')]);
    }
    search.addEventListener('input', draw);
    search.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      var first = grid.querySelector('button');
      if (first) first.click();
    });
    draw();
    cx.picker = h('div', { class: 'epick', role: 'dialog', 'aria-label': 'Emoji picker' }, search, grid);
    cx.el.insertBefore(cx.picker, cx.el.firstChild);
    search.focus();
    this.emit('emoji_open', {});
    this.syncPresence();
  };

  // GIFs from the backend's search (`/gifs`), in the emoji picker's place; choosing one sends it.
  P.openGif = function () {
    var self = this;
    if (this.mode === 'hidden') { this.reopen = 'gif'; this.startConversation(); return; }
    var cx = this.cx;
    if (!cx) return;
    if (cx.picker) { this.closeEmoji(); return; }
    var search = h('input', { type: 'search', placeholder: 'Search GIFs', 'aria-label': 'Search GIFs', maxlength: '60' });
    var grid = h('div', { class: 'egrid ggrid', role: 'group', 'aria-label': 'GIFs' }), timer = 0, asked = 0;
    function load() {
      var n = ++asked;
      self.adapter.gifs(cleanLine(search.value, 60)).then(function (items) {
        if (n !== asked) return;
        var list = items.filter(function (g) { return safeUrl(g.url) && /^https:/i.test(g.url); });
        grid.replaceChildren.apply(grid, list.length ? list.map(function (g) {
          var name = cleanLine(g.title, 80) || 'GIF';
          return h('button', { type: 'button', title: name, 'aria-label': name, onclick: function () { self.sendGif(g); } },
            h('img', { src: safeUrl(g.preview) || g.url, alt: '', loading: 'lazy' }));
        }) : [h('div', { class: 'eempty' }, 'No GIFs found')]);
      });
    }
    search.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(load, 300); });
    load();
    cx.picker = h('div', { class: 'epick gpick', role: 'dialog', 'aria-label': 'GIF picker' }, search, grid);
    cx.el.insertBefore(cx.picker, cx.el.firstChild);
    search.focus();
    this.emit('gif_open', {});
    this.syncPresence();
  };

  P.sendGif = function (g) {
    this.closeEmoji();
    var md = '[GIF](' + g.url + ')';
    this.sendInput({ type: 'message', text: md }, md);
  };

  // Dictation without the browser's speech recognition, when the backend transcribes (`/stt`): the first press
  // records, the second (or 30 s) stops, and the words go into the input.
  P.recordDictation = function () {
    var self = this;
    if (this.recording) { this.recording.stop(); return; }
    if (!navigator.mediaDevices || !global.MediaRecorder) { this.note('Dictation isn’t available in this browser.'); return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var chunks = [], rec = self.recording = new MediaRecorder(stream);
      var stopAt = setTimeout(function () { if (rec.state === 'recording') rec.stop(); }, 30000);
      rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = function () {
        clearTimeout(stopAt);
        self.recording = null;
        stream.getTracks().forEach(function (tr) { tr.stop(); });
        self.syncPresence();
        if (!chunks.length) return;
        self.note('Transcribing…');
        self.adapter.transcribe(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }), self.cfg.voiceLanguages[self.voiceLangIdx]).then(function (r) {
          var text = cleanText(r && r.text, 4000);
          if (text) { self.resetFoot(); self.insertText(text); } else self.note('Nothing was heard. Try again.');
        }, function () { self.note('Couldn’t transcribe that. Try again.'); });
      };
      rec.start();
      self.syncPresence();
      self.note('Recording… choose Dictate again to stop.');
    }, function () { self.note('Microphone permission was denied.'); });
  };

  P.closeEmoji = function () {
    var cx = this.cx;
    if (!cx || !cx.picker) return false;
    cx.picker.remove();
    cx.picker = null;
    this.syncPresence();
    return true;
  };

  // Inserts at the caret (or replaces the selection) and keeps the picker open for more.
  P.insertText = function (text) {
    var cx = this.cx;
    if (!cx) return;
    var ta = cx.ta, start = ta.selectionStart == null ? ta.value.length : ta.selectionStart;
    var end = ta.selectionEnd == null ? start : ta.selectionEnd;
    ta.setRangeText(text, start, end, 'end');
    cx.grow();
  };

  /* -- dictation: speech streams into the text field; nothing is sent until the visitor sends -- */

  P.voiceLang = function () {
    var code = this.cfg.voiceLanguages[this.voiceLangIdx] || 'auto';
    return code === 'auto' ? (navigator.language || 'en-US') : code;
  };

  P.startDictation = function () {
    var self = this, cx = this.cx;
    if (!SpeechRec || !cx || this.dict || this.call) return;
    var rec = new SpeechRec();
    rec.lang = this.voiceLang();
    rec.continuous = true;
    rec.interimResults = true;
    var d = this.dict = { rec: rec, base: cx.ta.value.replace(/\s+$/, ''), heard: '', started: Date.now(), cancelled: false };
    cx.box.classList.add('rec');
    cx.ta.placeholder = 'Listening…';
    rec.onresult = function (e) {
      if (d.cancelled || self.dict !== d || !self.cx) return;   // words arriving after Stop or a send don't come back
      var interim = '';
      for (var i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) d.heard += e.results[i][0].transcript;
        else interim += e.results[i][0].transcript;
      }
      self.cx.ta.value = [d.base, (d.heard + interim).trim()].filter(Boolean).join(' ');
      self.cx.grow();
    };
    rec.onerror = function (e) {
      if (e.error === 'no-speech' || e.error === 'aborted') return;
      self.stopDictation(true);
      self.note(voiceError(e.error));
    };
    rec.onend = function () { if (self.dict === d) self.stopDictation(true); };
    d.timer = setInterval(function () {
      var s = Math.floor((Date.now() - d.started) / 1000);
      if (self.cx) self.cx.recTime.textContent = Math.floor(s / 60) + ':' + ('0' + s % 60).slice(-2);
    }, 250);
    try { rec.start(); } catch (err) { this.stopDictation(true); return; }
    this.emit('dictation_start', { lang: rec.lang });
    this.syncPresence();
  };

  // keep=true leaves the transcript in the field; false restores what was typed before.
  P.stopDictation = function (keep) {
    var d = this.dict;
    if (!d) return;
    this.dict = null;
    clearInterval(d.timer);
    d.cancelled = !keep;
    d.rec.onend = d.rec.onerror = null;
    try { if (keep) d.rec.stop(); else d.rec.abort(); } catch (e) { /* already stopped */ }
    var cx = this.cx;
    if (cx) {
      if (!keep) cx.ta.value = d.base;
      cx.box.classList.remove('rec');
      cx.ta.placeholder = cx.placeholder;
      cx.recTime.textContent = '0:00';
      cx.grow();
      cx.ta.focus();
    }
    this.emit('dictation_end', { kept: !!keep });
    this.syncPresence();
  };

  /* -- voice conversation: listen -> send -> speak the reply -> listen, on a full-panel call screen -- */

  P.startVoice = function () {
    if (!SpeechRec || this.call) return;
    var self = this, c = this.cfg;
    this.stopReading();
    this.closePopovers();
    if (this.dict) this.stopDictation(true);
    if (!(this.view === 'thread' && this.active() && (this.mode === 'half' || this.mode === 'full'))) this.startConversation();

    var call = this.call = { started: Date.now(), muted: false, captions: true, state: 'listening' };
    // The stage in the call follows the real mic level when the meter is running.
    call.stage = robinStage({ state: 'listen', still: this.reduceMotion(), level: function () {
      return call.meter && self.voiceEl ? +(self.voiceEl.style.getPropertyValue('--lvl') || 0) : null;
    } });
    call.els = {
      time: h('span', { class: 'vtime' }, '00:00'),
      barTime: h('span', { class: 'vtime', 'aria-hidden': 'true' }, '00:00'),
      stat: h('div', { class: 'vstat', role: 'status' }, 'Listening…'),
      cap: h('div', { class: 'vcap', 'aria-live': 'polite' }),
      mute: h('button', { class: 'vbtn', type: 'button', 'aria-pressed': 'false', title: 'Mute', html: ICON.mic, onclick: function () { self.toggleMute(); } }),
      cc: h('button', { class: 'vbtn', type: 'button', 'aria-pressed': 'true', 'aria-label': 'Captions', title: 'Captions', html: ICON.cc, onclick: function () { self.toggleCaptions(); } }),
      lang: h('button', { class: 'vbtn', type: 'button', onclick: function () { self.cycleVoiceLang(); } })
    };
    this.voiceEl = h('div', { class: 'voice', role: 'dialog', 'aria-label': 'Voice conversation with ' + c.appName, 'data-state': 'listening' },
      h('div', { class: 'vhead' },
        h('span', { class: 'vt' }, icon('wave'), c.appName + ' · Voice'), h('span', { class: 'dot', 'aria-hidden': 'true' }), call.els.time,
        this.ibtn('chevronDown', 'Back to the chat (the call keeps going)', function () { self.minimiseVoice(); })),
      h('div', { class: 'vstage' },
        h('div', { class: 'vorb-wrap' },
          h('button', { class: 'vorb', type: 'button', 'aria-label': 'Interrupt', title: 'Tap to interrupt', onclick: function () { self.interruptVoice(); } }, call.stage.el)),
        call.els.stat, call.els.cap),
      h('div', { class: 'vctl' },
        call.els.mute,
        h('button', { class: 'vbtn end', type: 'button', 'aria-label': 'End call', title: 'End call', html: ICON.hangup, onclick: function () { self.endVoice(); } }),
        call.els.cc,
        call.els.lang));
    this.callbarEl = h('div', { class: 'callbar', role: 'status', hidden: true },
      icon('phone', 'cphone'), 'In a call', call.els.barTime, h('span', { class: 'sp' }),
      h('button', { type: 'button', onclick: function () { self.restoreVoice(); } }, 'Return'),
      h('button', { class: 'end', type: 'button', onclick: function () { self.endVoice(); } }, 'End'));
    this.panel.insertBefore(this.callbarEl, this.panel.querySelector('.view'));
    this.panel.append(this.voiceEl);
    this.syncVoiceLang();
    this.voiceState('listening');
    this.syncInert();

    call.timer = setInterval(function () {
      var s = Math.floor((Date.now() - call.started) / 1000);
      var t = ('0' + Math.floor(s / 60)).slice(-2) + ':' + ('0' + s % 60).slice(-2);
      call.els.time.textContent = t;
      call.els.barTime.textContent = t;
    }, 500);
    this.startMeter(call);
    this.listen();
    this.voiceEl.querySelector('.vbtn.end').focus();
    this.emit('voice_start', { lang: this.voiceLang() });
  };

  P.listen = function () {
    var self = this, call = this.call;
    if (!call) return;
    if (call.muted) { this.voiceState('muted'); return; }
    var rec = new SpeechRec();
    rec.lang = this.voiceLang();
    rec.interimResults = true;
    rec.continuous = false;
    call.rec = rec;
    call.heard = '';
    call.fatal = false;
    this.voiceState('listening');
    rec.onresult = function (e) {
      var t = '';
      for (var i = 0; i < e.results.length; i++) t += e.results[i][0].transcript;
      call.heard = t;
      self.caption('You', t);
    };
    rec.onerror = function (e) {
      if (e.error === 'no-speech' || e.error === 'aborted') return;
      call.fatal = true;
      self.voiceState('error', voiceError(e.error));
    };
    rec.onend = function () {
      if (self.call !== call || call.rec !== rec) return;
      call.rec = null;
      if (call.fatal || call.muted) return;
      var text = call.heard.trim();
      if (text) self.voiceTurn(text);
      else self.listen(); // silence: keep listening
    };
    try { rec.start(); } catch (err) { call.fatal = true; this.voiceState('error', voiceError('')); }
  };

  P.voiceTurn = function (text) {
    var self = this, call = this.call, convo = this.active() || this.startConversation(), asked = Date.now();
    this.voiceState('thinking');
    this.sendInput({ type: 'message', text: text, via: 'voice' }, text).then(function () {
      if (self.call !== call) return;
      var last = convo.messages[convo.messages.length - 1];
      var say = last && last.role === 'bot' && last.ts >= asked ? spokenText(last) : '';
      if (say) self.speak(say);
      else self.listen();
    });
  };

  P.speak = function (text) {
    var self = this, call = this.call, synth = global.speechSynthesis;
    this.caption(this.cfg.appName, text);
    if (this.serverVoice()) {
      this.voiceState('speaking');
      var token = call.voiceToken = {};
      this.adapter.speak(text).then(function (blob) {
        if (self.call !== call || call.voiceToken !== token) return;
        var audio = call.audio = new Audio(URL.createObjectURL(blob));
        audio.onended = audio.onerror = function () {
          if (self.call !== call || call.audio !== audio) return;
          call.audio = null;
          URL.revokeObjectURL(audio.src);
          self.listen();
        };
        return audio.play();
      }).catch(function () { if (self.call === call) self.listen(); });
      return;
    }
    if (!synth || !global.SpeechSynthesisUtterance) { this.listen(); return; }
    var u = new SpeechSynthesisUtterance(text);
    u.lang = this.voiceLang();
    u.rate = 1.03;
    var voice = pickVoice(u.lang);
    if (voice) u.voice = voice;
    call.utter = u;
    this.voiceState('speaking');
    u.onend = u.onerror = function () {
      if (self.call !== call || call.utter !== u) return;
      call.utter = null;
      self.listen();
    };
    synth.cancel();
    synth.speak(u);
  };

  P.interruptVoice = function () {
    var call = this.call;
    if (!call) return;
    if (call.state === 'speaking' && (call.audio || this.serverVoice())) {
      if (call.audio) { call.audio.pause(); URL.revokeObjectURL(call.audio.src); call.audio = null; }
      call.voiceToken = null;   // a reply still loading never plays
      this.listen();
    }
    else if (call.state === 'speaking' && global.speechSynthesis) global.speechSynthesis.cancel(); // onend resumes listening
    else if (call.state === 'error') this.listen();
  };

  P.voiceState = function (state, message) {
    var call = this.call;
    if (!call || !this.voiceEl) return;
    call.state = state;
    this.voiceEl.dataset.state = state;
    call.stage.set({ listening: 'listen', speaking: 'talk', thinking: 'thinking', muted: 'muted', error: 'error' }[state] || 'idle');
    call.els.stat.textContent = message || {
      listening: 'Listening…', thinking: 'Thinking…', speaking: 'Speaking · tap ' + this.cfg.appName + ' to interrupt', muted: 'Muted · tap the mic to talk'
    }[state] || '';
    var label = state === 'error' ? 'Try again' : call.muted ? 'Unmute microphone' : 'Mute microphone';
    call.els.mute.setAttribute('aria-pressed', String(call.muted));
    call.els.mute.setAttribute('aria-label', label);
    call.els.mute.title = label;
    call.els.mute.innerHTML = call.muted ? ICON.micOff : ICON.mic;
    this.syncPresence();
  };

  P.caption = function (who, text) {
    if (this.call) this.call.els.cap.replaceChildren(h('b', null, who), text);
  };

  P.toggleMute = function () {
    var call = this.call;
    if (!call) return;
    if (call.state === 'error') { call.muted = false; this.listen(); return; }
    call.muted = !call.muted;
    if (call.muted && call.rec) {
      var rec = call.rec;
      call.rec = null;
      try { rec.abort(); } catch (e) { /* already stopped */ }
    }
    if (call.muted) this.voiceState(call.state === 'listening' ? 'muted' : call.state);
    else if (call.state === 'muted') this.listen();
    else this.voiceState(call.state);
    this.emit('voice_mute', { muted: call.muted });
  };

  P.toggleCaptions = function () {
    var call = this.call;
    if (!call) return;
    call.captions = !call.captions;
    call.els.cap.hidden = !call.captions;
    call.els.cc.setAttribute('aria-pressed', String(call.captions));
  };

  P.cycleVoiceLang = function () {
    this.voiceLangIdx = (this.voiceLangIdx + 1) % this.cfg.voiceLanguages.length;
    this.syncVoiceLang();
    var call = this.call;
    if (call && call.state === 'listening' && call.rec) {
      var rec = call.rec;
      call.rec = null;
      try { rec.abort(); } catch (e) { /* already stopped */ }
      this.listen();
    }
  };

  P.syncVoiceLang = function () {
    var call = this.call;
    if (!call) return;
    var code = this.cfg.voiceLanguages[this.voiceLangIdx] || 'auto';
    var title = 'Speech language: ' + (code === 'auto' ? 'browser default (' + (navigator.language || 'en-US') + ')' : code);
    call.els.lang.textContent = code === 'auto' ? 'Auto' : code.slice(0, 2).toUpperCase();
    call.els.lang.title = title;
    call.els.lang.setAttribute('aria-label', title);
  };

  // While the call screen or the thinking layer covers the chat, what is under it can't take focus or clicks.
  P.syncInert = function () {
    var call = !!(this.voiceEl && !this.voiceEl.hidden), veil = !!(this.veil && this.veil.isConnected);
    var dialog = !!(this.dialogEl && this.dialogEl.isConnected);   // a question open: nothing behind it can be used
    this.panel.querySelectorAll(':scope>.view').forEach(function (v) { v.inert = call || veil || dialog; });
    if (this.callbarEl) this.callbarEl.inert = call || dialog;
  };

  P.minimiseVoice = function () {
    if (!this.call) return;
    this.voiceEl.hidden = true;
    this.callbarEl.hidden = false;
    this.syncInert();
    this.focusFirst();
  };

  P.restoreVoice = function () {
    if (!this.call) return;
    this.voiceEl.hidden = false;
    this.callbarEl.hidden = true;
    this.syncInert();
    this.voiceEl.querySelector('.vbtn.end').focus();
  };

  P.endVoice = function () {
    var call = this.call;
    if (!call) return;
    this.call = null;
    clearInterval(call.timer);
    if (call.rec) { call.rec.onend = null; try { call.rec.abort(); } catch (e) { /* already stopped */ } }
    if (call.audio) { call.audio.pause(); URL.revokeObjectURL(call.audio.src); call.audio = null; }
    if (global.speechSynthesis) global.speechSynthesis.cancel();
    this.stopMeter(call);
    if (this.voiceEl) this.voiceEl.remove();
    this.panel.querySelectorAll(':scope>.view').forEach(function (v) { v.inert = false; });
    if (this.callbarEl) this.callbarEl.remove();
    this.voiceEl = this.callbarEl = null;
    this.emit('voice_end', { seconds: Math.round((Date.now() - call.started) / 1000) });
    this.syncPresence();
    if (this.mode !== 'hidden') this.focusFirst();
  };

  // Mic level drives the orb's size while listening. Optional: the call works without it.
  P.startMeter = function (call) {
    var self = this, Ctx = global.AudioContext || global.webkitAudioContext;
    if (!Ctx || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      if (self.call !== call) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
      var ctx = new Ctx(), analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      var buf = new Uint8Array(analyser.fftSize);
      call.meter = { stream: stream, ctx: ctx };
      (function loop() {
        if (self.call !== call) return;
        analyser.getByteTimeDomainData(buf);
        var sum = 0;
        for (var i = 0; i < buf.length; i++) { var v = (buf[i] - 128) / 128; sum += v * v; }
        var lvl = call.state === 'listening' && !call.muted ? Math.min(1, Math.sqrt(sum / buf.length) * 5) : 0;
        if (self.voiceEl) self.voiceEl.style.setProperty('--lvl', lvl.toFixed(3));
        call.raf = requestAnimationFrame(loop);
      })();
    }).catch(function () { /* no level meter; the orb just stays still */ });
  };

  P.stopMeter = function (call) {
    cancelAnimationFrame(call.raf);
    if (!call.meter) return;
    call.meter.stream.getTracks().forEach(function (t) { t.stop(); });
    call.meter.ctx.close();
  };

  // `quiet` skips the entrance animation (messages that were already there when the thread opened).
  P.renderMessage = function (m, quiet) {
    var self = this, q = quiet ? ' quiet' : '';
    var col = h('div', { class: 'col' }, m.blocks.map(function (b) { return self.renderBlock(b, m); }));
    if (m.role === 'user') return h('div', { class: 'msg user' + q }, col);
    return h('div', { class: 'msg bot' + q }, this.botHead(m.ts), col, this.replyActions(m));
  };

  // Robin's answers open with a name line (mark, name, time); the content runs full width beneath it.
  P.botHead = function (ts) {
    return h('div', { class: 'ai-head' }, this.chatAvatar(), h('b', null, this.cfg.appName),
      h('time', null, new Date(ts || Date.now()).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })));
  };

  // Under each answer with text: copy, read aloud, and thumbs up / down (a `response_feedback` event).
  P.replyActions = function (m) {
    var self = this, up, down, why = h('div', { class: 'fb-slot' });
    var text = m.blocks.filter(function (b) { return b.type === 'text' && b.text; }).map(function (b) { return plain(b.text); }).join('\n\n');
    if (!text) return null;
    function act(ic, label, fn) {
      var b = h('button', { class: 'act', type: 'button', 'aria-label': label, title: label, html: ICON[ic], onclick: function () { fn(b); } });
      return b;
    }
    function rate(v) {
      m.feedback = m.feedback === v ? null : v;
      self.save();
      up.setAttribute('aria-pressed', String(m.feedback === 'up'));
      down.setAttribute('aria-pressed', String(m.feedback === 'down'));
      self.emit('response_feedback', { conversationId: self.activeId, messageId: m.id, value: m.feedback });
      if (self.adapter.feedback) self.adapter.feedback(m.ref, m.feedback, self.activeId);
      why.replaceChildren(m.feedback === 'down' ? self.feedbackForm(m, why) : '');
    }
    var copy = act('copy', 'Copy', function (b) {
      copyText(text).then(function () {
        b.innerHTML = ICON.check;
        b.classList.add('done');
        b.title = 'Copied';
        setTimeout(function () { b.innerHTML = ICON.copy; b.classList.remove('done'); b.title = 'Copy'; }, 1600);
      }, function () { self.note('Couldn’t copy that. Select the text instead.'); });
    });
    var read = (global.speechSynthesis && global.SpeechSynthesisUtterance) || this.serverVoice()
      ? act('volume', 'Read aloud', function (b) { self.readAloud(text, b); }) : null;
    up = act('thumbUp', 'Good response', function () { rate('up'); });
    down = act('thumbDown', 'Bad response', function () { rate('down'); });
    up.setAttribute('aria-pressed', String(m.feedback === 'up'));
    down.setAttribute('aria-pressed', String(m.feedback === 'down'));
    if (read) read.setAttribute('aria-pressed', 'false');
    return [h('div', { class: 'ai-actions' }, copy, read, up, down), why];
  };

  // After a thumbs-down: what went wrong (reasons and an optional note), sent with the rating.
  P.feedbackForm = function (m, slot) {
    var self = this, picked = [];
    var note = h('textarea', { class: 'fb-note', rows: '2', maxlength: '600', placeholder: 'Anything else? (optional)', 'aria-label': 'What went wrong' });
    var reasons = ['Not accurate', 'Didn’t answer my question', 'Not helpful', 'Too long'].map(function (r) {
      var c = h('button', { class: 'chip fb-chip', type: 'button', 'aria-pressed': 'false', onclick: function () {
        var i = picked.indexOf(r);
        if (i < 0) picked.push(r); else picked.splice(i, 1);
        c.setAttribute('aria-pressed', String(i < 0));
      } }, r);
      return c;
    });
    function send() {
      var text = cleanText([picked.join(', '), cleanText(note.value, 600)].filter(Boolean).join(': '), 1000);
      if (text) {
        m.feedbackNote = text;
        self.save();
        if (self.adapter.feedback && m.feedback === 'down') self.adapter.feedback(m.ref, 'down', self.activeId, text);
        self.emit('response_feedback', { conversationId: self.activeId, messageId: m.id, value: 'down', note: text });
      }
      var thanks = h('div', { class: 'fb-done', role: 'status' }, icon('check'), 'Thanks for the feedback');
      slot.replaceChildren(thanks);
      setTimeout(function () { if (thanks.parentNode === slot) slot.replaceChildren(); }, 2600);
    }
    var form = h('div', { class: 'fb-form', role: 'group', 'aria-label': 'What went wrong?' },
      h('div', { class: 'fb-t' }, 'What went wrong?'),
      h('div', { class: 'fb-chips' }, reasons), note,
      h('div', { class: 'fb-row' },
        h('button', { class: 'fb-skip', type: 'button', onclick: function () { slot.replaceChildren(); } }, 'Not now'),
        h('button', { class: 'fb-send', type: 'button', onclick: send }, 'Send')));
    requestAnimationFrame(function () { if (reasons[0].isConnected) reasons[0].focus({ preventScroll: true }); });
    return form;
  };

  // Reads an answer aloud with the browser's voice. Pressing it again, or another answer's, stops it.
  // The backend reads aloud itself when it has text-to-speech (`/tts`); otherwise the browser's voice.
  P.serverVoice = function () {
    return !!(this.backend && this.backend.ttsServer && this.adapter.speak && global.Audio);
  };

  P.readAloud = function (text, btn) {
    var again = this.readingBtn === btn, self = this;
    this.stopReading();
    if (again || this.call) return;
    if (this.serverVoice()) {
      var token = this.readToken = {};   // a press cut short never plays when its clip arrives late
      this.readingBtn = btn;
      btn.classList.add('on');
      btn.setAttribute('aria-pressed', 'true');
      this.syncPresence();
      this.adapter.speak(text).then(function (blob) {
        if (self.readToken !== token) return;
        var audio = self.readingAudio = new Audio(URL.createObjectURL(blob));
        audio.onended = audio.onerror = function () { if (self.readToken === token) self.stopReading(); };
        return audio.play();
      }).catch(function () { if (self.readToken === token) { self.stopReading(); self.note('Couldn’t read that aloud right now.'); } });
      return;
    }
    var u = new SpeechSynthesisUtterance(text);
    u.lang = document.documentElement.lang || 'en-US';
    var voice = pickVoice(u.lang);
    if (voice) u.voice = voice;
    u.onend = u.onerror = function () { if (self.readingBtn === btn) self.stopReading(); };
    this.readingBtn = btn;
    btn.classList.add('on');
    btn.setAttribute('aria-pressed', 'true');
    global.speechSynthesis.speak(u);
    this.syncPresence();
  };

  P.stopReading = function () {
    var btn = this.readingBtn;
    this.readToken = null;
    if (!btn) return;
    this.readingBtn = null;
    btn.classList.remove('on');
    btn.setAttribute('aria-pressed', 'false');
    if (this.readingAudio) { this.readingAudio.pause(); URL.revokeObjectURL(this.readingAudio.src); this.readingAudio = null; }
    if (global.speechSynthesis) global.speechSynthesis.cancel();
    this.syncPresence();
  };

  // Re-render one block in place after its state changes (form submitted, etc).
  P.refreshBlock = function (node, block, msg) {
    node.replaceWith(this.renderBlock(block, msg));
    this.save();
  };

  /* -- blocks (the OpenUI-renderable vocabulary) -- */

  P.renderBlock = function (b, msg) {
    var fn = this['block_' + b.type];
    return fn ? fn.call(this, b, msg) : this.block_text(b);
  };

  P.block_text = function (b) {
    return h('div', { class: 'bubble', html: rich(b.text) });
  };

  // An answer's card (deep-agent): a table, figures, steps or next-step buttons under the prose, drawn by the
  // server's own renderer as text only. Its buttons ask their label, or open a page the server allows.
  P.block_ui_card = function (b) {
    var self = this, host = h('div', { class: 'uic' });
    if (!b.program || !this.adapter.cardRenderer) return host;
    this.adapter.cardRenderer().then(function (m) {
      if (!m || !m.createCard) { host.remove(); return; }
      if (!self.cardCss) { self.cardCss = true; self.shadow.append(h('style', null, m.CSS)); }
      var ok = false;
      try {
      ok = m.createCard(host, {
        send: function (t) {
          t = cleanLine(t, 300);
          if (!t || self.busyHere() || /:\/\/|\S+@\S+\.\S+/.test(t)) return;
          self.emit('answer_card_button', { label: t });
          self.ask(t);
        },
        open: function (u) { var go = safeUrl(u); if (go) global.open(go, '_blank', 'noopener,noreferrer'); },
        onEvent: function (d) { self.emit('answer_card', d); }
      }).finish(b.program);
      } catch (e) { ok = false; }
      if (!ok) host.remove();
    });
    return host;
  };

  // Sent attachments. Image thumbnails show for this session; after a reload, a type badge.
  P.block_files = function (b) {
    var self = this;
    return h('div', { class: 'fchips' }, (b.files || []).map(function (f) {
      var url = self.previews[f.id];
      return h('div', { class: 'fchip', title: f.name },
        url ? h('img', { src: url, alt: '' }) : h('span', { class: 'ext' }, fileExt(f.name)),
        h('span', { class: 'meta' }, h('span', { class: 'nm' }, f.name), h('span', { class: 'sz' }, fmtSize(f.size || 0))));
    }));
  };

  P.block_buttons = function (b, msg) {
    var self = this, chosen = b.state && b.state.selected;
    var node = h('div', { class: 'chips' + (chosen ? ' picked' : '') }, (b.options || []).map(function (o) {
      var ic = optionIcon(o);
      return h('button', {
        class: 'chip' + (chosen === o.value ? ' on' : ''),
        type: 'button',
        disabled: !!chosen,
        onclick: function () {
          if (o.url) { var go = safeUrl(o.url); if (go) global.open(go, '_blank', 'noopener'); return; }
          if (b.starter) { self.pickStarter(o); return; }
          b.state = { selected: o.value };
          self.refreshBlock(node, b, msg);
          self.sendInput({ type: 'action', name: 'button', value: o.value, label: o.label }, o.label);
        }
      }, ic ? icon(ic, 'ci') : null, b.schedules
        ? [h('span', { class: 'sc-name' }, h('span', { class: 'sc-t' }, o.label), o.sub ? h('span', { class: 'sc-s' }, o.sub) : null),
          o.meta ? h('span', { class: 'sc-dur' }, o.meta) : null]
        : o.label);
    }));
    if (b.schedules) node.classList.add('sched');
    return node;
  };

  // Details form. Labels float above the field once it's in use; each field checks itself as you go (a tick
  // when it's right; a message, after you leave it or press submit, when it isn't); a bar fills as the
  // required fields are completed; Enter moves to the next field and submits from the last one.
  P.block_lead_form = function (b, msg) {
    var self = this;
    if (b.state && b.state.submitted) {
      var v = b.state.values;
      return h('div', { class: 'form' }, h('div', { class: 'done' },
        h('span', { class: 'tick draw', html: ICON.check }),
        h('div', null, h('div', { class: 't' }, 'Details sent'),
          h('div', { class: 's' }, [v.name, v.email, v.company].filter(Boolean).join(' · ')))));
    }
    var items = [];
    var fields = (b.fields || []).map(function (f, i) {
      var input = h('input', { name: f.name, type: f.type || 'text', autocomplete: f.autocomplete || 'on', required: !!f.required, value: f.value || '', placeholder: ' ' });
      var ic = f.icon || FIELD_ICONS[f.name] || (f.type === 'email' ? 'mail' : null);
      var field = h('label', { class: 'field fl', style: '--i:' + i },
        h('div', { class: 'inp' + (ic ? ' has-i' : '') }, ic ? icon(ic, 'fi') : null, input,
          h('span', { class: 'fl-label' }, f.label + (f.required ? '' : ' (optional)')),
          h('span', { class: 'fl-ok', html: ICON.check })),
        h('div', { class: 'err' }, icon('alert'), h('span', { class: 'msg-t' }, 'Required')));
      var it = { el: input, def: f, field: field, shown: false };
      items.push(it);
      input.addEventListener('input', function () { check(it); progress(); });
      input.addEventListener('blur', function () { if (input.value.trim()) { it.shown = true; check(it); } });
      input.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' || i === items.length - 1) return;
        e.preventDefault();
        items[i + 1].el.focus();
      });
      return field;
    });

    // 'ok', 'bad' or 'empty'; the error only shows once the visitor has left the field or tried to submit.
    function check(it, force) {
      var val = it.el.value.trim();
      var bad = (it.def.required && !val) || (it.def.type === 'email' && val && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(val));
      if (force) it.shown = true;
      it.field.toggleAttribute('data-ok', !!val && !bad);
      var showErr = bad && it.shown;
      if (showErr && force) { it.field.removeAttribute('data-err'); void it.field.offsetWidth; }   // replay the shake
      it.field.toggleAttribute('data-err', showErr);
      it.field.querySelector('.err .msg-t').textContent = val ? 'Enter a valid email, like name@company.com' : 'Required';
      return bad ? 'bad' : val ? 'ok' : 'empty';
    }

    var fill = h('i', { class: 'lf-fill' }), count = h('span', { class: 'lf-count' });
    var submit = h('button', { class: 'primary lf-submit', type: 'submit' }, b.submitLabel || 'Send', icon('arrowRight', 'pi'));
    function progress() {
      var req = items.filter(function (it) { return it.def.required; });
      var done = req.filter(function (it) { return it.field.hasAttribute('data-ok'); }).length;
      fill.style.transform = 'scaleX(' + (req.length ? done / req.length : 1) + ')';
      count.textContent = done + ' of ' + req.length;
      submit.classList.toggle('ready', done === req.length);
    }
    items.forEach(function (it) { if (it.el.value) check(it); });
    progress();

    var titleIcon = b.icon || FORM_ICONS[b.context && b.context.intent] || 'user';
    var node = h('form', { class: 'form lf', novalidate: true },
      h('div', { class: 'lf-head' },
        icon(titleIcon, 'hico'),
        h('div', { class: 'lf-titles' }, b.title ? h('h4', null, b.title) : null, b.hint ? h('p', { class: 'hint' }, b.hint) : null),
        count),
      b.summary ? h('div', { class: 'lf-sum' }, icon(b.summary.icon || 'calendar', 'si'),
        h('div', { class: 'grow' }, h('b', null, b.summary.title), b.summary.text ? h('span', null, b.summary.text) : null)) : null,
      h('div', { class: 'lf-bar' }, fill),
      h('div', { class: 'fields' }, fields),
      submit);

    node.addEventListener('submit', function (e) {
      e.preventDefault();
      var values = {}, firstBad = null;
      items.forEach(function (it) {
        if (check(it, true) === 'bad' && !firstBad) firstBad = it.el;
        values[it.def.name] = it.def.type === 'email' ? cleanLine(it.el.value, 200) : cleanText(it.el.value, it.def.max || 2000);
      });
      progress();
      if (firstBad) { firstBad.focus(); return; }
      b.state = { submitted: true, values: values };
      var keep = {};
      ['name', 'email', 'company'].forEach(function (k) { if (values[k]) keep[k] = values[k]; });
      self.store.visitor = Object.assign({}, self.store.visitor, keep);
      self.refreshBlock(node, b, msg);
      self.emit('lead_submitted', { values: values, context: b.context || null });
      self.sendInput({ type: 'action', name: 'submit_lead', data: { values: values, context: b.context || null } });
    });
    return node;
  };

  // Booking: day tiles with a navy marker that slides to the chosen day, times grouped into Morning /
  // Afternoon / Evening that slide in from the side you moved towards, and a footer that names the picked
  // time and enables "Book it". Picking a time doesn't redraw the grid, so the chosen pill just pops.
  P.block_time_slots = function (b, msg) {
    var self = this;
    var slots = (b.slots || []).map(function (s) { return new Date(s.start || s); }).filter(function (d) { return !isNaN(d); })
      .sort(function (a, z) { return a - z; });
    if (b.state && b.state.selected) {
      var picked = new Date(b.state.selected);
      return h('div', { class: 'form' }, h('div', { class: 'done' },
        h('span', { class: 'tick cal', html: ICON.calendar }),
        h('div', null, h('div', { class: 't' }, b.title || 'Meeting'),
          h('div', { class: 's' }, fmtDay.format(picked) + ' · ' + timeRange(picked, b.durationMinutes)))));
    }
    var byDay = {}, order = [];
    slots.forEach(function (d) {
      var key = d.toDateString();
      if (!byDay[key]) { byDay[key] = []; order.push(key); }
      byDay[key].push(d);
    });
    var dayIdx = 0, chosen = null;
    var marker = h('i', { class: 'sd-marker' });
    var days = order.map(function (k, i) {
      var d = byDay[k][0];
      return h('button', { class: 'sday', type: 'button', role: 'tab', 'aria-selected': String(i === 0), style: '--i:' + i, onclick: function () { showDay(i); } },
        h('span', { class: 'sd-dow' }, fmtDow.format(d)), h('span', { class: 'sd-num' }, fmtNum.format(d)), h('span', { class: 'sd-mon' }, fmtMon.format(d)));
    });
    var daysEl = h('div', { class: 'sdays', role: 'tablist', 'aria-label': 'Day', style: '--n:' + order.length }, marker, days);
    // More days than fit scroll sideways; arrows show at an edge with more beyond it.
    function nav(dir, label) {
      return h('button', { class: 'sd-nav ' + (dir < 0 ? 'l' : 'r'), type: 'button', tabindex: '-1', 'aria-label': label, html: ICON[dir < 0 ? 'back' : 'arrow'],
        onclick: function () { daysEl.scrollBy({ left: dir * daysEl.clientWidth * 0.8 }); } });
    }
    var dayStrip = h('div', { class: 'sdays-w' }, nav(-1, 'Earlier days'), daysEl, nav(1, 'Later days'));
    function edges() {
      dayStrip.toggleAttribute('data-l', daysEl.scrollLeft > 2);
      dayStrip.toggleAttribute('data-r', daysEl.scrollLeft + daysEl.clientWidth < daysEl.scrollWidth - 2);
    }
    daysEl.addEventListener('scroll', edges, { passive: true });
    requestAnimationFrame(edges);
    if (global.ResizeObserver) new ResizeObserver(edges).observe(daysEl);
    var times = h('div', { class: 'stimes' });
    var pickedEl = h('div', { class: 'spicked' });
    var confirmBtn = h('button', { class: 'primary sbook', type: 'button', disabled: true }, 'Book it', icon('arrowRight', 'pi'));

    function showDay(i, first) {
      var dir = i > dayIdx ? 'from-r' : i < dayIdx ? 'from-l' : '';
      dayIdx = i;
      daysEl.style.setProperty('--at', i);
      days.forEach(function (el, j) { el.setAttribute('aria-selected', String(j === i)); });
      var on = days[i], L = on.offsetLeft - 30, R = on.offsetLeft + on.offsetWidth + 30;   // keep the day clear of the arrows
      if (L < daysEl.scrollLeft) daysEl.scrollLeft = Math.max(0, L);
      else if (R > daysEl.scrollLeft + daysEl.clientWidth) daysEl.scrollLeft = R - daysEl.clientWidth;
      var groups = [['Morning', 0, 12], ['Afternoon', 12, 17], ['Evening', 17, 24]];
      var n = 0;
      times.className = 'stimes' + (first ? '' : ' ' + (dir || 'from-r'));
      void times.offsetWidth;   // restart the slide-in
      times.replaceChildren.apply(times, groups.map(function (g) {
        var list = (byDay[order[i]] || []).filter(function (d) { return d.getHours() >= g[1] && d.getHours() < g[2]; });
        if (!list.length) return null;
        return h('div', { class: 'sgroup' }, h('div', { class: 'sg-t' }, g[0]),
          h('div', { class: 'sgrid' }, list.map(function (d) {
            var on = !!chosen && chosen.getTime() === d.getTime();
            return h('button', { class: 'stime', type: 'button', 'aria-pressed': String(on), style: '--i:' + (n++), onclick: function () { pick(d, this); } },
              h('span', { class: 'st-check', html: ICON.check }), fmtTime.format(d));
          })));
      }).filter(Boolean));
    }

    function pick(d, btn) {
      chosen = d;
      times.querySelectorAll('.stime').forEach(function (el) { el.setAttribute('aria-pressed', String(el === btn)); });
      pickedEl.replaceChildren(h('span', { class: 'sp-in' }, icon('calendar', 'sp-i'),
        h('span', null, h('b', null, fmtDay.format(d)), ' · ' + timeRange(d, b.durationMinutes))));
      confirmBtn.disabled = false;
    }

    pickedEl.append(h('span', { class: 'sp-in sp-hint' }, 'Pick a time that suits you'));
    if (order.length) showDay(0, true);

    var node = h('div', { class: 'form sb' },
      h('div', { class: 'lf-head' },
        icon('calendar', 'hico'),
        h('div', { class: 'lf-titles' }, h('h4', null, b.title || 'Pick a time'),
          h('div', { class: 'meta-line', html: ICON.globe + esc((b.durationMinutes ? b.durationMinutes + ' min · ' : '') + tzName) }))),
      order.length ? [dayStrip, times, h('div', { class: 'sfoot' }, pickedEl, confirmBtn)]
        : h('p', { class: 'hint' }, 'No times are open right now.'));

    confirmBtn.addEventListener('click', function () {
      if (!chosen) return;
      var iso = chosen.toISOString();
      var label = fmtDay.format(chosen) + ' · ' + timeRange(chosen, b.durationMinutes);
      b.state = { selected: iso };
      self.refreshBlock(node, b, msg);
      self.emit('slot_selected', { start: iso, context: b.context || null });
      self.sendInput({ type: 'action', name: 'select_slot', data: { start: iso, durationMinutes: b.durationMinutes || null, context: b.context || null } }, label);
    });
    return node;
  };

  P.block_card = function (b) {
    var safeUrl = b.cta && /^https?:\/\//.test(b.cta.url) ? b.cta.url : null;
    var safeImg = b.image && /^https?:\/\//.test(b.image) ? b.image : null;
    return h('div', { class: 'info-card' },
      safeImg ? h('img', { src: safeImg, alt: '' }) : null,
      h('div', { class: 'in' },
        b.title ? h('h4', null, b.title) : null,
        b.text ? h('p', { html: rich(b.text) }) : null,
        safeUrl ? h('a', { class: 'link', href: safeUrl, target: '_blank', rel: 'noopener noreferrer' }, b.cta.label || 'Learn more', icon('arrowRight', 'pi')) : null));
  };

  // Confirmation: a green badge that bounces in and draws its tick, then sends out a ring and a burst of
  // small dots; the title beside it; and the details as rows, each with an icon tile, sliding in in turn.
  // Lines may be strings or { icon, text }.
  P.block_confirmation = function (b) {
    var dots = [];
    for (var i = 0; i < 8; i++) dots.push(h('i', { class: 'cf-dot', style: '--a:' + (i * 45 + 22) + 'deg' }));
    return h('div', { class: 'confirm' },
      h('div', { class: 'cf-head' },
        h('span', { class: 'cf-badge', 'aria-hidden': 'true' }, h('i', { class: 'cf-ring' }), dots, h('span', { class: 'tick draw', html: ICON.check })),
        h('div', { class: 't' }, b.title || 'Done')),
      b.lines ? h('ul', { class: 'cf-lines' }, b.lines.map(function (l) {
        var ic = l && l.icon && ICON[l.icon] ? l.icon : 'check';
        return h('li', null, h('span', { class: 'cf-ic' }, icon(ic)), h('span', null, l && l.text != null ? l.text : l));
      })) : null);
  };

  P.block_error = function (b, msg) {
    var self = this;
    var node = h('div', { class: 'bubble error' }, icon('alert', 'ei'), h('span', null, b.text || 'Something went wrong.'),
      b.retry && !(b.state && b.state.retried) ? h('button', { type: 'button', onclick: function () {
        b.state = { retried: true };
        self.refreshBlock(node, b, msg);
        var files = (msg && self.retryFiles[msg.id]) || [], input = Object.assign({}, b.retry);
        if (!files.length && input.attachments) {   // after a reload the files are gone: ask without them, and say so
          delete input.attachments;
          self.note('Attach the files again to send them; the question is sent without them.');
        }
        self.sendInput(input, null, files);
      } }, h('span', { html: ICON.refresh }), 'Retry') : null);
    return node;
  };

  /* ---------------------------------------------------------------- export */

  var instance = null, listeners = [];   // Robin.on handlers, kept for every instance init creates
  var Robin = {
    version: VERSION,
    init: function (config) {
      if (instance) instance.destroy();
      instance = new RobinWidget(config, listeners);
      return instance;
    },
    open: function (mode) { if (instance) instance.open(mode); },
    close: function () { if (instance) instance.close(); },
    toggle: function () { if (instance) instance.toggle(); },
    expand: function () { if (instance) instance.expand(); },
    collapse: function () { if (instance) instance.collapse(); },
    setWide: function (on) { if (instance) instance.setWide(on); },
    ask: function (text) { if (instance) instance.ask(text); },
    voice: function () { if (instance) instance.startVoice(); },
    endVoice: function () { if (instance) instance.endVoice(); },
    setTheme: function () {},   // retired: Robin always shows the swallow (kept so older embeds don't break)
    setScheme: function (s) { if (instance) instance.setScheme(s); },
    setBrand: function (color) { if (instance) instance.setBrand(color); },
    setTextSize: function (size) { if (instance) instance.setTextSize(size); },
    setReduceMotion: function (on) { if (instance) instance.setReduceMotion(on); },
    setToken: function (token) { if (instance) return instance.setToken(token); },
    on: function (type, fn) { listeners.push([type, fn]); if (instance) instance.on(type, fn); return Robin; },
    reset: function () { if (instance) instance.reset(); },
    destroy: function () { if (instance) { instance.destroy(); instance = null; } },
    get instance() { return instance; },
    HttpAdapter: HttpAdapter,
    DeepAgentAdapter: DeepAgentAdapter
  };
  global.Robin = Robin;

  // Auto-boot from `window.RobinSettings`, Intercom-style.
  if (global.RobinSettings && typeof global.RobinSettings === 'object' && !global.RobinSettings.nodeType) {
    var boot = function () { Robin.init(global.RobinSettings); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
  }
  return Robin;
});