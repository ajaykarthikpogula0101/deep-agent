/*
 * Answer cards for <deep-assistant> (docs/UI_CARDS.md): renders ONE openui-lang program (streamed by the server as
 * 'ui' SSE events) into a small card under the prose. Loaded lazily by deep-assistant.js on the first 'ui' event.
 *
 *   createCard(host, { send, open, onEvent, announce, doc }) -> { el, update(program), finish(program), destroy() }
 *   renderTree(root, doc, hooks) -> DocumentFragment | null        pure; textContent only, LIMITS applied
 *   plan(actionAst, label) -> {type:'ask', message} | {type:'open', url} | null
 *   allowUrl(u) -> normalised https URL or null                    deependhq.com hosts, or BOOK_URL exactly
 *   CSS                                                           injected once into the widget's shadow root
 *
 * Security model: the model's text (and anything planted in <sources>) can only ever become text nodes — no HTML string
 * is ever assigned in this file (a Node test greps for it); lang-core evaluates no code; @OpenUrl is allowlisted by allowUrl;
 * 'ask' buttons always send their own label (the @ToAssistant argument is ignored) and labels carrying an e-mail or a
 * '://' are not rendered, so a click can never inject a foreign address into the booking flow. lang-core does not
 * enforce slot types (a Button survives inside a Table cell, a Badge inside Steps.steps, objects where strings are
 * expected, unknown tones while partial), so every slot and value is re-checked here. No document/window access at
 * module top level: the Node tests pass a fake document.
 */
import { createStreamingParser, evaluate } from './vendor/openui-lang-core.min.mjs';
import { LIBRARY, LIMITS, ALLOWED_HOSTS, BOOK_URL } from './deep-ui-lib.mjs';

export const CSS = `
.ui-card { display:flex; flex-direction:column; gap:10px; margin-top:12px; padding:12px; border:1px solid var(--da-line); border-radius:var(--da-r-md); background:var(--da-subtle); font-size:13px; line-height:1.45 } .ui-card[data-ui-state="streaming"] { border-style:dashed }
.msg.streaming:has(.ui-card)::after { display:none }
.ui-card .ui-partial { opacity:.6 }
.ui-skel { height:9px; margin:4px 0; border-radius:6px; background:var(--da-line) } .ui-skel:nth-child(2) { width:85% } .ui-skel:nth-child(3) { width:55% }
.ui-head { display:flex; flex-direction:column; gap:2px } .ui-head b { font-size:14px; font-weight:650; letter-spacing:-.01em } .ui-head span { font-size:12px; color:var(--da-muted) }
.ui-stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(110px, 1fr)); gap:8px }
.ui-stat { padding:10px 12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-surface) } .ui-stat .v { display:block; font-size:18px; font-weight:700; letter-spacing:-.02em; color:var(--da-ink); font-variant-numeric:tabular-nums; overflow-wrap:anywhere } .ui-stat .l { display:block; margin-top:2px; font-size:11.5px; font-weight:600; color:var(--da-muted) } .ui-stat .n { display:block; margin-top:2px; font-size:11.5px; color:var(--da-muted) }
.ui-tablewrap { overflow-x:auto; border:1px solid var(--da-line); border-radius:12px; background:var(--da-surface) } .ui-table { width:100%; border-collapse:collapse; font-size:12.5px } .ui-table th, .ui-table td { padding:7px 10px; text-align:left; vertical-align:top; border-bottom:1px solid var(--da-line); overflow-wrap:break-word; hyphens:auto } .ui-table td:first-child { min-width:76px } .ui-table th { font-size:11.5px; font-weight:650; color:var(--da-muted); text-transform:uppercase; letter-spacing:.04em; background:var(--da-subtle) } .ui-table tr:last-child td { border-bottom:0 } .ui-table td:first-child { font-weight:600 } .ui-table caption { caption-side:bottom; padding:6px 10px; font-size:11.5px; color:var(--da-muted); text-align:left }
.ui-list { margin:0; padding-left:18px } .ui-list li { margin:2px 0 } .ui-list li::marker { color:var(--da-ink) }
.ui-kv { display:grid; grid-template-columns:max-content 1fr; gap:4px 12px; padding:10px 12px; border:1px solid var(--da-line); border-radius:12px; background:var(--da-surface) } .ui-kv span { color:var(--da-muted) } .ui-kv b { font-weight:600; overflow-wrap:anywhere }
.ui-steps { list-style:none; margin:0; padding:0; counter-reset:ui-step } .ui-steps .t { font-size:11.5px; font-weight:650; color:var(--da-muted); text-transform:uppercase; letter-spacing:.04em; margin-bottom:6px } .ui-step { position:relative; padding:0 0 10px 26px; counter-increment:ui-step } .ui-step::before { content:counter(ui-step); position:absolute; left:0; top:0; width:18px; height:18px; border-radius:50%; background:var(--da-lavender); color:var(--da-ink); font:650 10.5px/18px system-ui, sans-serif; text-align:center } .ui-step:not(:last-child)::after { content:""; position:absolute; left:8.5px; top:20px; bottom:0; width:1px; background:var(--da-line) } .ui-step b { display:block; font-weight:650 } .ui-step .when { display:block; font-size:11.5px; font-weight:600; color:var(--da-ink) } .ui-step span.d { display:block; color:var(--da-muted) }
.ui-chips { display:flex; flex-wrap:wrap; gap:6px } .ui-badge { display:inline-flex; align-items:center; min-height:24px; padding:2px 9px; border-radius:999px; background:var(--da-lavender); color:var(--da-ink); font-size:11.5px; font-weight:650 } .ui-badge.success { background:rgba(25,184,135,.14); color:var(--da-ok-text) } .ui-badge.warning { background:var(--da-danger-soft); color:var(--da-danger-text) } .ui-badge.info { background:var(--da-primary-soft); color:var(--da-ink) }
.ui-callout { display:flex; gap:8px; padding:9px 12px; border-left:3px solid var(--da-primary); border-radius:8px; background:var(--da-surface); color:var(--da-text) } .ui-callout svg { width:16px; height:16px; flex:none; margin-top:1px; color:var(--da-ink) } .ui-callout.success { border-left-color:var(--da-success) } .ui-callout.success svg { color:var(--da-success) } .ui-callout.warning { border-left-color:var(--da-danger); color:var(--da-danger-text) } .ui-callout.warning svg { color:var(--da-danger) }
.ui-actions { display:flex; flex-wrap:wrap; gap:6px; margin-top:2px } .ui-actions .ui-btn { min-height:32px; padding:4px 12px; font-size:12.5px }
`;

const CHILDREN = new Set(['Stat', 'Table', 'List', 'KeyValue', 'Steps', 'Badge', 'Callout', 'Actions']);
const BADGE_TONE = { neutral: '', success: 'success', warning: 'warning', info: 'info' };      // fixed maps: an unknown or
const CALLOUT_TONE = { info: '', success: 'success', warning: 'warning' };                   // partial value is never written raw
const EMAIL_RE = /[^\s@]+@[^\s@]+\.[^\s@]+/;
const SVG = 'http://www.w3.org/2000/svg';
const CTX = { getState: () => null, resolveRef: () => null };
const isEl = (n, type) => !!n && typeof n === 'object' && n.type === 'element' && (!type || n.typeName === type) && !!n.props && typeof n.props === 'object';
// Only strings and finite numbers become text; objects, arrays, elements and booleans where a string is expected are skipped.
const str = (v) => (typeof v === 'string' ? v.slice(0, LIMITS.str) : typeof v === 'number' && Number.isFinite(v) ? String(v) : null);

export function allowUrl(u) {
  let p; try { p = new URL(String(u)); } catch { return null; }
  if (p.protocol !== 'https:' || p.username || p.password || p.port) return null;
  if (ALLOWED_HOSTS.includes(p.hostname)) return p.href;                    // any path on our own site
  const h = p.href; if (h === BOOK_URL || h.startsWith(BOOK_URL + '/') || h.startsWith(BOOK_URL + '?') || h.startsWith(BOOK_URL + '#')) return h;
  return null;                                                              // javascript:, data:, http:, foreign hosts, other Zoom pages
}

function askPlan(label) {
  const t = typeof label === 'string' ? label : '';
  if (!t.trim() || t.length > LIMITS.ask || EMAIL_RE.test(t) || t.includes('://')) return null;
  return { type: 'ask', message: t };
}

// What a Button does when clicked. The first step that survives wins; 'ask' always carries the LABEL, never the
// @ToAssistant argument (one-click injection guard); 'open' only with an allowUrl() URL; @Set/@Run/@Reset and
// unknown steps are skipped. No action at all -> ask(label) under the same label rules.
export function plan(action, label) {
  if (action === undefined || action === null) return askPlan(label);
  let r; try { r = evaluate(action, CTX); } catch { return null; }
  const steps = r && Array.isArray(r.steps) ? r.steps : (r && typeof r === 'object' && r.type ? [r] : []);
  for (const s of steps) {
    if (!s || typeof s !== 'object') continue;
    if (s.type === 'continue_conversation') { const a = askPlan(label); if (a) return a; }
    else if (s.type === 'open_url') { const u = allowUrl(s.url); if (u) return { type: 'open', url: u }; }
  }
  return null;
}

// ---------------------------------------------------------------- pure DOM builder
export function renderTree(root, doc, hooks) {
  if (!isEl(root)) return null;
  doc = doc || globalThis.document; hooks = hooks || {};
  const frag = doc.createDocumentFragment();
  let nodes = 0;
  const budget = () => nodes++ < LIMITS.nodes;                             // every rendered element counts; beyond the cap nothing more is added
  const mk = (tag, cls, text) => { const e = doc.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; };
  const partial = (e, n) => { if (n.partial) e.classList.add('ui-partial'); return e; };

  const head = mk('div', 'ui-head'); head.appendChild(mk('b', '', str(root.props.title) || ''));
  const sub = str(root.props.subtitle); if (sub) head.appendChild(mk('span', '', sub));
  frag.appendChild(head); nodes++;

  const children = Array.isArray(root.props.children) ? root.props.children.filter((c) => isEl(c) && CHILDREN.has(c.typeName)) : [];
  let group = null, groupType = null, stats = 0, badges = 0;
  for (const n of children) {
    if (!budget()) break;
    if (n.typeName === 'Stat' || n.typeName === 'Badge') {                   // consecutive Stats -> tiles, consecutive Badges -> chips
      if (groupType !== n.typeName) { group = mk('div', n.typeName === 'Stat' ? 'ui-stats' : 'ui-chips'); groupType = n.typeName; frag.appendChild(group); }
      const e = n.typeName === 'Stat' ? (stats++ < LIMITS.stats ? stat(n) : null) : (badges++ < LIMITS.badges ? badge(n) : null);
      if (e) group.appendChild(e);
      continue;
    }
    group = null; groupType = null;
    const e = block(n, 2); if (e) frag.appendChild(e);
  }
  for (const g of Array.from(frag.childNodes)) if ((g.className === 'ui-stats' || g.className === 'ui-chips') && !g.childNodes.length) g.remove ? g.remove() : frag.removeChild(g);
  return frag;

  function stat(n) {
    const label = str(n.props.label), value = str(n.props.value); if (label === null || value === null) return null;
    const e = partial(mk('div', 'ui-stat'), n); e.appendChild(mk('span', 'v', value)); e.appendChild(mk('span', 'l', label));
    const note = str(n.props.note); if (note) e.appendChild(mk('span', 'n', note));
    return e;
  }
  function badge(n) {
    const label = str(n.props.label); if (label === null) return null;
    const tone = BADGE_TONE[n.props.tone] || '';
    return partial(mk('span', 'ui-badge' + (tone ? ' ' + tone : ''), label), n);
  }
  function block(n, depth) {
    if (depth > LIMITS.depth) return null;
    switch (n.typeName) {
      case 'Table': return table(n);
      case 'List': return list(n);
      case 'KeyValue': return keyValue(n);
      case 'Steps': return steps(n, depth);
      case 'Callout': return callout(n);
      case 'Actions': return actions(n, depth);
    }
    return null;
  }
  function table(n) {
    if (!Array.isArray(n.props.columns) || !Array.isArray(n.props.rows)) return null;
    const cols = n.props.columns.slice(0, LIMITS.cols).map(str).filter((c) => c !== null); if (!cols.length) return null;
    const wrap = partial(mk('div', 'ui-tablewrap'), n), t = mk('table', 'ui-table'); wrap.appendChild(t);
    const cap = str(n.props.caption); if (cap) t.appendChild(mk('caption', '', cap));
    const thead = mk('thead'), hr = mk('tr'); thead.appendChild(hr); t.appendChild(thead);
    for (const c of cols) hr.appendChild(mk('th', '', c));
    const tbody = mk('tbody'); t.appendChild(tbody);
    for (const row of n.props.rows.slice(0, LIMITS.rows)) {
      if (!Array.isArray(row) || !budget()) continue;
      const tr = mk('tr'); tbody.appendChild(tr);
      for (const cell of row.slice(0, cols.length)) tr.appendChild(mk('td', '', str(cell) || ''));   // a non-string cell stays empty so columns keep their alignment
    }
    return wrap;
  }
  function list(n) {
    if (!Array.isArray(n.props.items)) return null;
    const e = partial(mk(n.props.ordered === true ? 'ol' : 'ul', 'ui-list'), n);
    for (const it of n.props.items.slice(0, LIMITS.items)) { const s = str(it); if (s !== null && budget()) e.appendChild(mk('li', '', s)); }
    return e;
  }
  function keyValue(n) {
    if (!Array.isArray(n.props.pairs)) return null;
    const e = partial(mk('div', 'ui-kv'), n);
    for (const p of n.props.pairs.slice(0, LIMITS.pairs)) {
      if (!Array.isArray(p)) continue; const k = str(p[0]), v = str(p[1]); if (k === null || v === null || !budget()) continue;
      e.appendChild(mk('span', '', k)); e.appendChild(mk('b', '', v));
    }
    return e;
  }
  function steps(n, depth) {
    if (!Array.isArray(n.props.steps) || depth + 1 > LIMITS.depth) return null;
    const e = partial(mk('ol', 'ui-steps'), n);
    const title = str(n.props.title); if (title) e.appendChild(mk('div', 't', title));
    for (const s of n.props.steps.slice(0, LIMITS.steps)) {
      if (!isEl(s, 'Step')) continue; const t = str(s.props.title); if (t === null || !budget()) continue;   // only Step elements with a title
      const li = partial(mk('li', 'ui-step'), s); li.appendChild(mk('b', '', t));
      const when = str(s.props.when); if (when) li.appendChild(mk('span', 'when', when));
      const d = str(s.props.detail); if (d) li.appendChild(mk('span', 'd', d));
      e.appendChild(li);
    }
    return e;
  }
  function callout(n) {
    const text = str(n.props.text); if (text === null) return null;
    const tone = CALLOUT_TONE[n.props.tone] || '';
    const e = partial(mk('div', 'ui-callout' + (tone ? ' ' + tone : '')), n);
    const svg = doc.createElementNS(SVG, 'svg'); svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '2'); svg.setAttribute('stroke-linecap', 'round');
    const c = doc.createElementNS(SVG, 'circle'); c.setAttribute('cx', '12'); c.setAttribute('cy', '12'); c.setAttribute('r', '9'); svg.appendChild(c);
    const p = doc.createElementNS(SVG, 'path'); p.setAttribute('d', tone === 'success' ? 'M8.5 12.5l2.5 2.5 4.5-5' : 'M12 8v.5M12 11.5V16'); svg.appendChild(p);
    e.appendChild(svg); e.appendChild(mk('span', '', text));
    return e;
  }
  function actions(n, depth) {
    if (!Array.isArray(n.props.buttons) || depth + 1 > LIMITS.depth) return null;
    const e = partial(mk('div', 'ui-actions'), n); let primary = false;
    for (const b of n.props.buttons.slice(0, LIMITS.buttons)) {
      if (!isEl(b, 'Button')) continue; const label = str(b.props.label); if (label === null) continue;
      const p = plan(b.props.action, label); if (!p || !budget()) continue;   // disallowed URL / unsafe label -> not rendered at all
      const btn = partial(mk('button', 'btn sm ui-btn', label), b); btn.setAttribute('type', 'button'); btn.dataset.uiAction = p.type;
      if (p.type === 'ask' && !primary) { primary = true; btn.classList.add('primary'); }
      if (p.type === 'open') btn.dataset.uiUrl = p.url;
      btn.addEventListener('click', () => { if (p.type === 'ask') { if (hooks.send) hooks.send(p.message); } else if (hooks.open) hooks.open(p.url); });
      e.appendChild(btn);
    }
    return e.childNodes.length ? e : null;
  }
}

// ---------------------------------------------------------------- the streaming card under a bot bubble
export function createCard(host, { send, open, onEvent, announce, doc = globalThis.document } = {}) {
  const hooks = { send, open };
  const emit = (d) => { try { if (onEvent) onEvent(d); } catch {} };
  const el = doc.createElement('div'); el.className = 'ui-card card'; el.dataset.uiState = 'streaming';
  for (let i = 0; i < 3; i++) el.appendChild(Object.assign(doc.createElement('div'), { className: 'ui-skel' }));
  host.appendChild(el);                                                      // last child of .msg: _setText re-appends it on every token re-render
  const parser = createStreamingParser(LIBRARY.schema, 'Card');
  let result = null, timer = null, closed = false;
  const hasRaf = typeof globalThis.requestAnimationFrame === 'function';                      // repaint coalesced per frame (setTimeout fallback in Node)
  const raf = hasRaf ? (f) => globalThis.requestAnimationFrame(f) : (f) => setTimeout(f, 50);
  const cancel = () => { if (timer === null) return; if (hasRaf) globalThis.cancelAnimationFrame(timer); else clearTimeout(timer); timer = null; };
  const paint = () => { timer = null; if (closed || !result || !result.root) return; const f = renderTree(result.root, doc, hooks); if (f) el.replaceChildren(f); };
  const api = {
    el,
    update(program) {
      if (closed) return;
      try {
        if (typeof program !== 'string' || program.length > LIMITS.program) return api.destroy();
        result = parser.set(program);
        if (timer === null) timer = raf(paint);
      } catch { api.destroy(); }
    },
    finish(program) {
      if (closed) return false;
      try {
        if (typeof program !== 'string' || program.length > LIMITS.program) { api.destroy(); return false; }
        result = parser.set(program);
        if (!result.root || result.root.typeName !== 'Card') { api.destroy(); return false; }   // other errors (excess-args at root…) keep the card
        cancel(); paint();
        for (const p of Array.from(el.querySelectorAll('.ui-partial'))) p.classList.remove('ui-partial');
        el.dataset.uiState = 'done'; el.dataset.uiStatements = String(result.meta && result.meta.statementCount || 0); el.dataset.uiRoot = 'Card';
        emit({ state: 'rendered', statements: Number(el.dataset.uiStatements) });
        try { if (announce) announce(str(result.root.props.title) || 'Answer card'); } catch {}
        return true;
      } catch { api.destroy(); return false; }
    },
    destroy() {
      if (closed) return; cancel(); closed = true;
      try { el.remove(); } catch {}
      try {
        if (!host.querySelector('.bk.card, .hform, .ui-card')) { host.classList.remove('hascard'); const row = host.closest && host.closest('.row'); if (row) row.classList.remove('wide'); }
      } catch {}
      emit({ state: 'dropped' });
    },
  };
  return api;
}
