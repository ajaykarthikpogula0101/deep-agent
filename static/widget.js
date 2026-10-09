/* Embed for deependhq.com. Replaces widgo-gate.js.
 *   <script src="https://assistant.deependhq.com/static/widget.js" defer></script>
 *   optional: data-theme="light|dark|auto" (default light)  data-title="…"  data-subtitle="…"  data-suggestions="a|b|c"
 *             data-delay="3000" (ms before the greeting bubble appears)  data-quick-replies="a|b|c"
 *             (without data-quick-replies the chips are the most asked questions, from GET /widget-config)
 *             data-no-greeting (disable the proactive bubble entirely)
 *             data-tabs="home,messages,help"  data-shortcut="Book a call with Deep|https://scheduler.zoom.us/sreedeep"
 *             data-privacy="https://deependhq.com/privacy"
 *
 * Rules carried over from the site's own widgo-gate.js:
 *  - never auto-open, on any viewport (the greeting bubble is a nudge next to the button, not an open chat)
 *  - zero third-party bytes on first paint: this file is small and draws only the round launcher and, after a
 *    delay, the greeting card; the chat itself (static/deep-assistant.js, a dependency-free web component) is
 *    fetched when the visitor hovers or taps, or in idle time a few seconds after load
 *  - no cookies: session id in sessionStorage, visitor id in localStorage, both first-party on deependhq.com
 *  - no iframe: the chat renders in the page inside a Shadow DOM
 */
(function () {
  var script = document.currentScript;
  var ORIGIN = (script && script.src) ? new URL(script.src).origin : '';
  if (!ORIGIN || document.querySelector('deep-assistant') || document.getElementById('dh-assistant-btn')) return;
  var ds = (script && script.dataset) || {};
  var VER = (function () { try { return new URL(script.src).searchParams.get('v') || ''; } catch (e) { return ''; } })();
  var LOGO = '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" aria-hidden="true"><path d="M12 3.5c4.97 0 9 3.36 9 7.5s-4.03 7.5-9 7.5c-.9 0-1.77-.11-2.6-.32L5 20l.95-3.4C4.13 15.24 3 13.22 3 11c0-4.14 4.03-7.5 9-7.5z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M12 7.2l.95 2.65 2.65.95-2.65.95L12 14.4l-.95-2.65-2.65-.95 2.65-.95z" fill="currentColor"/></svg>';
  var BOOK_RE = /\b(book|schedule|meeting|appointment|demo call|call with)\b/i;  // quick replies like these open the booking flow
  var THEME = ds.theme || 'light';

  // ---------------------------------------------------------------- proactive greeting: edit here
  var PROACTIVE = {
    enabled: !('noGreeting' in ds),
    delayMs: parseInt(ds.delay, 10) || 3000,               // how long after page load the bubble appears
    botName: 'Deep',
    title: 'Hi! I\'m Deep 👋',
    question: 'Exploring LakeB2B\'s data solutions? I can answer questions or book you a meeting.',
    // optional intro line for the chat's welcome screen; empty keeps the component's default copy
    message: '',
    quickReplies: ds.quickReplies ? ds.quickReplies.split('|').map(function (s) { return s.trim(); }).filter(Boolean)
      : ['Book a meeting', 'What data solutions does LakeB2B offer?', 'What is LakeB2B?'],
    unread: 1,
  };
  var DISMISSED_KEY = 'dh_greeting_dismissed';   // sessionStorage: once dismissed or opened, not again this session

  var loading = null;
  function load() {
    if (!loading) loading = import(ORIGIN + '/static/deep-assistant.js' + (VER ? '?v=' + encodeURIComponent(VER) : '')).catch(function (e) { loading = null; throw e; });
    return loading;
  }
  function mount(open, greeting) {
    return load().then(function () {
      var el = document.querySelector('deep-assistant');
      if (!el) {
        el = document.createElement('deep-assistant');
        el.setAttribute('api', ORIGIN);
        el.setAttribute('mode', 'launcher');
        el.setAttribute('theme', THEME);
        if (ds.title) el.setAttribute('title', ds.title);
        if (ds.subtitle) el.setAttribute('subtitle', ds.subtitle);
        if (ds.suggestions) el.setAttribute('suggestions', ds.suggestions);
        if (ds.tabs) el.setAttribute('tabs', ds.tabs);
        if (ds.shortcut) el.setAttribute('shortcut', ds.shortcut);
        if (ds.privacy) el.setAttribute('privacy-url', ds.privacy);
        if (greeting) el.setAttribute('greeting', greeting);
        document.body.appendChild(el);
      }
      if (open) el.setAttribute('open', '');
      dismiss();
      var b = document.getElementById('dh-assistant-btn');
      if (b) b.remove();  // the component draws its own launcher from here on
      return el;
    });
  }

  // ---------------------------------------------------------------- round launcher + unread badge
  var btn = document.createElement('button');
  btn.id = 'dh-assistant-btn';
  btn.type = 'button';
  btn.innerHTML = LOGO + '<span class="dh-pro-badge" hidden aria-hidden="true"></span>';
  btn.setAttribute('aria-label', 'Ask the site assistant');
  btn.style.cssText = [
    'position:fixed', 'right:max(20px, env(safe-area-inset-right))', 'bottom:max(20px, env(safe-area-inset-bottom))',
    'width:56px', 'height:56px', 'border:0', 'border-radius:50%', 'z-index:2147483000', 'display:flex', 'align-items:center', 'justify-content:center',
    'background:linear-gradient(145deg,#7466FF 0%,#5546F7 55%,#3E31D4 100%)', 'color:#FFFFFF', 'cursor:pointer', 'padding:0', 'margin:0',
    'box-shadow:0 12px 28px -10px rgba(85,70,247,.65),0 2px 6px rgba(21,27,50,.18)', 'transition:transform .18s cubic-bezier(.2,.8,.2,1)'
  ].join(';');
  btn.addEventListener('mouseenter', function () { btn.style.transform = 'translateY(-2px)'; });
  btn.addEventListener('mouseleave', function () { btn.style.transform = ''; });
  btn.addEventListener('mouseenter', function () { load().catch(function () {}); });
  btn.addEventListener('focus', function () { load().catch(function () {}); });
  btn.addEventListener('click', function () {
    btn.disabled = true; btn.style.opacity = '.6';
    mount(true, shown ? PROACTIVE.message : null).catch(function () { btn.disabled = false; btn.style.opacity = ''; });
  });
  document.body.appendChild(btn);
  var badge = btn.querySelector('.dh-pro-badge');

  // ---------------------------------------------------------------- greeting card + quick replies
  var shown = false, wrap = null, timeTimer = null, shownAt = 0;
  function dismissed() { try { return sessionStorage.getItem(DISMISSED_KEY) === '1'; } catch (e) { return false; } }
  function dismiss() {
    try { sessionStorage.setItem(DISMISSED_KEY, '1'); } catch (e) {}
    if (wrap) { wrap.classList.add('dh-pro-out'); var w = wrap; wrap = null; setTimeout(function () { w.remove(); }, 250); }
    if (timeTimer) { clearInterval(timeTimer); timeTimer = null; }
    badge.hidden = true; shown = false;
  }
  function relTime() {
    var s = Math.round((Date.now() - shownAt) / 1000);
    return s < 60 ? 'just now' : s < 3600 ? Math.round(s / 60) + ' min ago' : Math.round(s / 3600) + ' h ago';
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function injectStyles() {
    if (document.getElementById('dh-pro-style')) return;
    var st = document.createElement('style'); st.id = 'dh-pro-style';
    st.textContent = [
      // Indigo Dream tokens (same as the chat component); inherited text styles are reset so the host page cannot leak in
      '.dh-pro{--bg:#FFFFFF;--bg2:#F0F2F9;--line:#E4E7F2;--line2:#CDD2E3;--text:#151B32;--muted:#68718A;--accent:#5546F7;--lav:#EEECFF;--shadow:0 18px 44px -14px rgba(21,27,50,.28),0 0 0 1px rgba(21,27,50,.04)}',
      '.dh-pro[data-theme=dark]{--bg:#171C33;--bg2:#1E2441;--line:#2A3152;--line2:#3A4268;--text:#ECEEF8;--muted:#9BA3C0;--lav:#26234F;--shadow:0 18px 44px -14px rgba(0,0,0,.7)}',
      '@media (prefers-color-scheme:dark){.dh-pro[data-theme=auto]{--bg:#171C33;--bg2:#1E2441;--line:#2A3152;--line2:#3A4268;--text:#ECEEF8;--muted:#9BA3C0;--lav:#26234F;--shadow:0 18px 44px -14px rgba(0,0,0,.7)}}',
      '.dh-pro{position:fixed;z-index:2147482998;right:max(20px,env(safe-area-inset-right));bottom:calc(max(20px,env(safe-area-inset-bottom)) + 70px);display:flex;flex-direction:column;align-items:flex-end;gap:8px;max-width:min(330px,calc(100vw - 32px));font-family:"Inter",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:14px;font-weight:400;line-height:1.45;letter-spacing:normal;text-transform:none;text-align:left;color:var(--text);-webkit-font-smoothing:antialiased}',
      '.dh-pro *{box-sizing:border-box;margin:0}',
      '.dh-pro-bubble{position:relative;display:flex;gap:12px;align-items:flex-start;width:100%;padding:14px 38px 12px 14px;background:var(--bg);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);cursor:pointer;text-align:left}',
      '.dh-pro-bubble:hover{border-color:var(--line2)}',
      '.dh-pro-bubble:focus-visible,.dh-pro-reply:focus-visible,.dh-pro-x:focus-visible{outline:2px solid var(--accent);outline-offset:2px}',
      '.dh-pro-avatar{flex:none;width:36px;height:36px;border-radius:12px;background:linear-gradient(145deg,#7466FF,#5546F7 55%,#3E31D4);display:flex;align-items:center;justify-content:center;color:#fff}',
      '.dh-pro-avatar svg{width:20px;height:20px}',
      '.dh-pro-title{font-weight:700;font-size:15px;letter-spacing:-.01em}',
      '.dh-pro-q{margin-top:2px;color:var(--text)}',
      '.dh-pro-meta{margin-top:6px;font-size:12px;color:var(--muted)}',
      '.dh-pro-x{position:absolute;top:8px;right:8px;width:26px;height:26px;padding:0;border:0;border-radius:8px;background:transparent;color:var(--muted);font:18px/1 system-ui,sans-serif;cursor:pointer}',
      '.dh-pro-x:hover{background:var(--bg2);color:var(--text)}',
      '.dh-pro-reply{align-self:flex-end;max-width:100%;padding:8px 14px;border:1px solid var(--line);border-radius:999px;background:var(--bg);color:var(--accent);font:inherit;font-size:13.5px;font-weight:600;cursor:pointer;box-shadow:var(--shadow);text-align:left}',
      '.dh-pro-reply:hover{background:var(--lav);border-color:var(--accent)}',
      '.dh-pro .dh-pro-in{opacity:0;transform:translateY(8px);animation:dh-pro-in .35s cubic-bezier(.16,1,.3,1) forwards}',
      '@keyframes dh-pro-in{to{opacity:1;transform:none}}',
      '.dh-pro.dh-pro-out{opacity:0;transform:translateY(6px);transition:opacity .2s,transform .2s;pointer-events:none}',
      '.dh-pro-badge{position:absolute;top:-4px;right:-4px;min-width:20px;height:20px;padding:0 6px;border-radius:999px;background:#D6345B;color:#fff;font:700 11px/20px system-ui,sans-serif;text-align:center;box-shadow:0 0 0 2px #fff}',
      '@media (prefers-reduced-motion:reduce){.dh-pro .dh-pro-in{animation:none;opacity:1;transform:none}.dh-pro.dh-pro-out{transition:none}}',
      '@media (max-width:480px){.dh-pro{max-width:calc(100vw - 32px)}.dh-pro-bubble{padding:12px 34px 10px 12px}}',
    ].join('\n');
    document.head.appendChild(st);
  }
  // smart quick replies: the questions visitors ask most (server, 1.5 s budget), else the fixed list above
  function smartReplies() {
    if (ds.quickReplies || typeof fetch !== 'function') return Promise.resolve(PROACTIVE.quickReplies);
    var ctrl = (typeof AbortController === 'function') ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 1500);
    return fetch(ORIGIN + '/widget-config', ctrl ? { signal: ctrl.signal } : undefined)
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (c) { clearTimeout(timer); return (c && c.suggestions && c.suggestions.length) ? c.suggestions : PROACTIVE.quickReplies; })
      .catch(function () { clearTimeout(timer); return PROACTIVE.quickReplies; });
  }
  function showGreeting() {
    if (!PROACTIVE.enabled || shown || dismissed() || document.querySelector('deep-assistant') || !document.getElementById('dh-assistant-btn')) return;
    smartReplies().then(function (replies) { PROACTIVE.quickReplies = replies; renderGreeting(); });
  }
  function renderGreeting() {
    if (!PROACTIVE.enabled || shown || dismissed() || document.querySelector('deep-assistant') || !document.getElementById('dh-assistant-btn')) return;
    injectStyles();
    shown = true; shownAt = Date.now();
    wrap = document.createElement('div');
    wrap.className = 'dh-pro';
    wrap.setAttribute('data-theme', THEME);
    wrap.setAttribute('role', 'region');
    wrap.setAttribute('aria-label', PROACTIVE.botName + ' greeting');
    var bubble = document.createElement('div');
    bubble.className = 'dh-pro-bubble dh-pro-in';
    bubble.setAttribute('role', 'button'); bubble.tabIndex = 0;
    bubble.innerHTML =
      '<div class="dh-pro-avatar" aria-hidden="true">' + LOGO + '</div>' +
      '<div><div class="dh-pro-title">' + esc(PROACTIVE.title) + '</div><div class="dh-pro-q">' + esc(PROACTIVE.question) + '</div>' +
      '<div class="dh-pro-meta"><span class="dh-pro-name">' + esc(PROACTIVE.botName) + '</span> • <span class="dh-pro-time">just now</span></div></div>' +
      '<button class="dh-pro-x" type="button" aria-label="Dismiss">×</button>';
    var openFromBubble = function () { bubble.style.pointerEvents = 'none'; mount(true, PROACTIVE.message).catch(function () { bubble.style.pointerEvents = ''; }); };
    bubble.addEventListener('click', function (e) { if (e.target.closest('.dh-pro-x')) return; openFromBubble(); });
    bubble.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openFromBubble(); } });
    bubble.querySelector('.dh-pro-x').addEventListener('click', function (e) { e.stopPropagation(); dismiss(); });
    wrap.appendChild(bubble);
    PROACTIVE.quickReplies.slice(0, 4).forEach(function (label, i) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'dh-pro-reply dh-pro-in'; b.textContent = label;
      b.style.animationDelay = (120 + i * 90) + 'ms';
      b.addEventListener('click', function () {
        wrap && wrap.querySelectorAll('button, .dh-pro-bubble').forEach(function (x) { x.style.pointerEvents = 'none'; });
        mount(true, PROACTIVE.message).then(function (el) { if (BOOK_RE.test(label) && el.startBooking) el.startBooking(null, label); else el.ask(label); }).catch(function () {});
      });
      wrap.appendChild(b);
    });
    document.body.appendChild(wrap);
    badge.textContent = String(PROACTIVE.unread); badge.hidden = false;
    timeTimer = setInterval(function () { var t = wrap && wrap.querySelector('.dh-pro-time'); if (t) t.textContent = relTime(); }, 30000);
    load().catch(function () {});  // the visitor is likely to tap now: have the chat ready
  }
  if (PROACTIVE.enabled && !dismissed()) setTimeout(showGreeting, PROACTIVE.delayMs);

  // warm the cache after the page is idle, so the first tap opens instantly
  var warm = function () { load().catch(function () {}); };
  if ('requestIdleCallback' in window) requestIdleCallback(warm, { timeout: 6000 }); else setTimeout(warm, 4000);

  // tiny API for the site: window.deepAssistant.open() / .ask('…') / .book() / .greet()
  window.deepAssistant = {
    open: function () { return mount(true); },
    ask: function (text) { return mount(true).then(function (el) { el.ask(text); return el; }); },
    book: function (callType) { return mount(true).then(function (el) { el.book(callType || null); return el; }); },
    greet: function () { try { sessionStorage.removeItem(DISMISSED_KEY); } catch (e) {} showGreeting(); },
    config: PROACTIVE
  };
})();
