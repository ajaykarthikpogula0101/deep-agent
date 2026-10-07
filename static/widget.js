/* Embed for deependhq.com. Replaces widgo-gate.js.
 *   <script src="https://assistant.deependhq.com/static/widget.js" defer></script>
 *   optional: data-theme="dark|light|auto"  data-title="…"  data-subtitle="…"  data-suggestions="a|b|c"
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
  var LOGO = '<svg viewBox="0 0 22 22" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M1 7V1h6M15 1h6v6M21 15v6h-6M7 21H1v-6"/><circle cx="11" cy="11" r="3"/><path d="M11 4v3M11 15v3M4 11h3M15 11h3"/></svg>';

  // ---------------------------------------------------------------- proactive greeting: edit here
  var PROACTIVE = {
    enabled: !('noGreeting' in ds),
    delayMs: parseInt(ds.delay, 10) || 3000,               // how long after page load the bubble appears
    botName: 'Deep',
    title: 'Hi there 👋',
    question: 'What would you like help with?',
    // the bot's first message once the chat opens from the bubble or a quick reply
    message: '👋 Hi, you\'re speaking with Deep\'s AI assistant. Share as much detail as you can so I can give you the best answer.',
    quickReplies: ds.quickReplies ? ds.quickReplies.split('|').map(function (s) { return s.trim(); }).filter(Boolean)
      : ['Book a call with Deep', 'What is Deep working on?', 'Tell me about the companies'],
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
        el.setAttribute('theme', ds.theme || 'dark');
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
    'background:#F28C28', 'color:#1A1208', 'cursor:pointer', 'box-shadow:0 10px 30px rgba(0,0,0,.4)', 'padding:0'
  ].join(';');
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
      '.dh-pro{--bg:#0F0F10;--bg2:#1C1C1E;--line:#1F1F22;--line2:#2E2E32;--text:#F2F3F5;--muted:#8A8D93;--accent:#F28C28;--shadow:0 16px 48px rgba(0,0,0,.6)}',
      '.dh-pro[data-theme=light]{--bg:#FFFFFF;--bg2:#F1F2F4;--line:#E3E5E8;--line2:#CFD2D6;--text:#16171A;--muted:#6B7079;--shadow:0 14px 40px rgba(20,20,30,.18)}',
      '@media (prefers-color-scheme:light){.dh-pro[data-theme=auto]{--bg:#FFFFFF;--bg2:#F1F2F4;--line:#E3E5E8;--line2:#CFD2D6;--text:#16171A;--muted:#6B7079;--shadow:0 14px 40px rgba(20,20,30,.18)}}',
      '.dh-pro{position:fixed;z-index:2147482998;right:max(20px,env(safe-area-inset-right));bottom:calc(max(20px,env(safe-area-inset-bottom)) + 70px);display:flex;flex-direction:column;align-items:flex-end;gap:8px;max-width:min(340px,calc(100vw - 32px));font-family:inherit;font-size:14px;line-height:1.45;color:var(--text)}',
      '.dh-pro *{box-sizing:border-box;margin:0}',
      '.dh-pro-bubble{position:relative;display:flex;gap:12px;align-items:flex-start;width:100%;padding:14px 36px 12px 14px;background:var(--bg);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);cursor:pointer;text-align:left}',
      '.dh-pro-bubble:hover{border-color:var(--line2)}',
      '.dh-pro-avatar{flex:none;width:36px;height:36px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;color:#1A1208}',
      '.dh-pro-avatar svg{width:20px;height:20px}',
      '.dh-pro-title{font-weight:700;font-size:15px}',
      '.dh-pro-q{margin-top:2px;color:var(--text)}',
      '.dh-pro-meta{margin-top:6px;font-size:12px;color:var(--muted)}',
      '.dh-pro-x{position:absolute;top:8px;right:8px;width:26px;height:26px;border:0;border-radius:8px;background:transparent;color:var(--muted);font:18px/1 inherit;cursor:pointer}',
      '.dh-pro-x:hover{background:var(--bg2);color:var(--text)}',
      '.dh-pro-reply{align-self:flex-end;max-width:100%;padding:9px 14px;border:1px solid var(--line2);border-radius:999px;background:var(--bg);color:var(--text);font:inherit;font-size:14px;cursor:pointer;box-shadow:var(--shadow);text-align:left}',
      '.dh-pro-reply:hover{background:var(--bg2)}',
      '.dh-pro .dh-pro-in{opacity:0;transform:translateY(8px);animation:dh-pro-in .35s cubic-bezier(.16,1,.3,1) forwards}',
      '@keyframes dh-pro-in{to{opacity:1;transform:none}}',
      '.dh-pro.dh-pro-out{opacity:0;transform:translateY(6px);transition:opacity .2s,transform .2s;pointer-events:none}',
      '.dh-pro-badge{position:absolute;top:-4px;right:-4px;min-width:20px;height:20px;padding:0 6px;border-radius:999px;background:#E5484D;color:#fff;font:700 11px/20px system-ui,sans-serif;text-align:center;box-shadow:0 0 0 2px #0F0F10}',
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
    wrap.setAttribute('data-theme', ds.theme || 'dark');
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
        mount(true, PROACTIVE.message).then(function (el) { el.ask(label); }).catch(function () {});
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

  // tiny API for the site: window.deepAssistant.open() / .ask('…') / .greet()
  window.deepAssistant = {
    open: function () { return mount(true); },
    ask: function (text) { return mount(true).then(function (el) { el.ask(text); return el; }); },
    greet: function () { try { sessionStorage.removeItem(DISMISSED_KEY); } catch (e) {} showGreeting(); },
    config: PROACTIVE
  };
})();
