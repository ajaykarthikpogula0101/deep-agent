// A tiny fake document for renderer.test.mjs, used when jsdom is not installed (plain `node --test` before `npm ci`).
// It implements only what static/deep-ui.js and the test touch: createElement/createElementNS/createDocumentFragment,
// textContent (get/set), className/classList/dataset/attributes, appendChild/replaceChildren/remove, closest and a
// small selector engine (tag, #id, .class, [attr], [attr=value], compound, descendant and child combinators, lists).
// There is deliberately no innerHTML: text set through textContent can never become markup here either.
class Node {
  constructor(doc) { this.ownerDocument = doc; this.parentNode = null; this.childNodes = []; }
  get children() { return this.childNodes.filter((n) => n instanceof Element); }
  get firstChild() { return this.childNodes[0] || null; }
  get firstElementChild() { return this.children[0] || null; }
  appendChild(n) {
    if (n instanceof Fragment) { const kids = n.childNodes.splice(0); for (const c of kids) { c.parentNode = null; this.appendChild(c); } return n; }
    if (n.parentNode) n.parentNode.removeChild(n);
    n.parentNode = this; this.childNodes.push(n); return n;
  }
  removeChild(n) { const i = this.childNodes.indexOf(n); if (i < 0) throw new Error('not a child'); this.childNodes.splice(i, 1); n.parentNode = null; return n; }
  replaceChildren(...nodes) { for (const c of this.childNodes.splice(0)) c.parentNode = null; for (const n of nodes) this.appendChild(n); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(''); }
  set textContent(v) { this.replaceChildren(); if (v !== '' && v !== null && v !== undefined) this.appendChild(new Text(this.ownerDocument, String(v))); }
  *descendants() { for (const c of this.childNodes) { if (c instanceof Element) { yield c; yield* c.descendants(); } } }
  querySelectorAll(sel) { const list = parseSelector(sel); const out = []; for (const e of this.descendants()) if (list.some((s) => matchesComplex(e, s, this))) out.push(e); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
class Text extends Node { constructor(doc, data) { super(doc); this.data = data; this.nodeType = 3; } get textContent() { return this.data; } set textContent(v) { this.data = String(v); } }
class Fragment extends Node { constructor(doc) { super(doc); this.nodeType = 11; } }
class Element extends Node {
  constructor(doc, tag, ns) {
    super(doc); this.nodeType = 1; this.localName = tag.toLowerCase(); this.tagName = ns ? tag : tag.toUpperCase(); this.namespaceURI = ns || 'http://www.w3.org/1999/xhtml';
    this.attributes = new Map(); this._listeners = new Map();
    const self = this;
    this.classList = {
      add(...c) { const s = new Set(self.className.split(/\s+/).filter(Boolean)); c.forEach((x) => s.add(x)); self.className = [...s].join(' '); },
      remove(...c) { const s = new Set(self.className.split(/\s+/).filter(Boolean)); c.forEach((x) => s.delete(x)); self.className = [...s].join(' '); },
      contains(c) { return self.className.split(/\s+/).includes(c); },
      toggle(c, f) { const on = f === undefined ? !this.contains(c) : !!f; on ? this.add(c) : this.remove(c); return on; },
    };
    this.dataset = new Proxy({}, {   // data-* attributes, camelCase <-> kebab-case like the real DOMStringMap
      get: (_, k) => (typeof k === 'string' ? self.attributes.get('data-' + kebab(k)) : undefined),
      set: (_, k, v) => { self.attributes.set('data-' + kebab(k), String(v)); return true; },
      has: (_, k) => self.attributes.has('data-' + kebab(k)),
      deleteProperty: (_, k) => { self.attributes.delete('data-' + kebab(k)); return true; },
      ownKeys: () => [...self.attributes.keys()].filter((k) => k.startsWith('data-')).map((k) => camel(k.slice(5))),
      getOwnPropertyDescriptor: () => ({ enumerable: true, configurable: true }),
    });
  }
  get className() { return this.attributes.get('class') || ''; } set className(v) { this.attributes.set('class', String(v)); }
  get id() { return this.attributes.get('id') || ''; } set id(v) { this.attributes.set('id', String(v)); }
  setAttribute(k, v) { this.attributes.set(String(k), String(v)); } getAttribute(k) { return this.attributes.has(k) ? this.attributes.get(k) : null; }
  hasAttribute(k) { return this.attributes.has(k); } removeAttribute(k) { this.attributes.delete(k); }
  addEventListener(t, f) { if (!this._listeners.has(t)) this._listeners.set(t, []); this._listeners.get(t).push(f); }
  removeEventListener(t, f) { const l = this._listeners.get(t) || []; const i = l.indexOf(f); if (i >= 0) l.splice(i, 1); }
  dispatchEvent(ev) { for (const f of this._listeners.get(ev.type) || []) f.call(this, ev); if (typeof this['on' + ev.type] === 'function') this['on' + ev.type](ev); return true; }
  click() { this.dispatchEvent({ type: 'click', target: this, preventDefault() {}, stopPropagation() {} }); }
  matches(sel) { return parseSelector(sel).some((s) => matchesComplex(this, s, null)); }
  closest(sel) { for (let e = this; e; e = e.parentNode) if (e instanceof Element && e.matches(sel)) return e; return null; }
  get isConnected() { let e = this; while (e.parentNode) e = e.parentNode; return e === this.ownerDocument.body || e === this.ownerDocument; }
}
const kebab = (s) => s.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase());
const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());

// ---- selectors: "a b > c.d[x=y], .e" -> [[{comb, compound}...], ...]
const cache = new Map();
function parseSelector(sel) {
  if (cache.has(sel)) return cache.get(sel);
  const list = String(sel).split(',').map((part) => {
    const tokens = part.trim().match(/>|\s+|[^\s>]+/g) || []; const seq = []; let comb = ' ';
    for (const t of tokens) { if (t === '>') comb = '>'; else if (/^\s+$/.test(t)) { if (comb !== '>') comb = ' '; } else { seq.push({ comb, compound: parseCompound(t) }); comb = ' '; } }
    return seq;
  });
  cache.set(sel, list); return list;
}
function parseCompound(t) {
  const c = { tag: null, id: null, classes: [], attrs: [] }; const re = /([a-zA-Z][\w-]*|\*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:=("[^"]*"|'[^']*'|[^\]]*))?\]/g; let m;
  while ((m = re.exec(t))) { if (m[1]) c.tag = m[1] === '*' ? null : m[1].toLowerCase(); else if (m[2]) c.id = m[2]; else if (m[3]) c.classes.push(m[3]); else if (m[4]) c.attrs.push({ name: m[4], value: m[5] === undefined ? null : m[5].replace(/^["']|["']$/g, '') }); }
  return c;
}
function matchesCompound(e, c) {
  if (c.tag && e.localName !== c.tag) return false;
  if (c.id && e.id !== c.id) return false;
  if (c.classes.some((k) => !e.classList.contains(k))) return false;
  return c.attrs.every((a) => e.hasAttribute(a.name) && (a.value === null || e.getAttribute(a.name) === a.value));
}
function matchesComplex(e, seq, scope) {
  let i = seq.length - 1; if (!matchesCompound(e, seq[i].compound)) return false;
  let cur = e;
  while (--i >= 0) {
    const comb = seq[i + 1].comb; const c = seq[i].compound;
    if (comb === '>') { cur = cur.parentNode; if (!(cur instanceof Element) || cur === scope || !matchesCompound(cur, c)) return false; }
    else { cur = cur.parentNode; while (cur instanceof Element && cur !== scope && !matchesCompound(cur, c)) cur = cur.parentNode; if (!(cur instanceof Element) || cur === scope) return false; }
  }
  return true;
}

export function createFakeDocument() {
  const doc = {
    createElement(tag) { return new Element(doc, tag); },
    createElementNS(ns, tag) { return new Element(doc, tag, ns); },
    createDocumentFragment() { return new Fragment(doc); },
    createTextNode(t) { return new Text(doc, t); },
  };
  doc.body = new Element(doc, 'body');
  doc.querySelectorAll = (s) => doc.body.querySelectorAll(s); doc.querySelector = (s) => doc.body.querySelector(s);
  return doc;
}
