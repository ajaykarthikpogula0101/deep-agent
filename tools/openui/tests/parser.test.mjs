// The committed browser bundle (static/vendor/openui-lang-core.min.mjs) parses the fixtures exactly as snapshotted and
// keeps every string verbatim: the renderer (static/deep-ui.js) is the only line of defence against markup, foreign
// URLs and wrong slot types, so this test pins what it must defend against. Run: `node --test tests/` in tools/openui.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";

const STATIC = new URL("../../../static/", import.meta.url);
const BUNDLE = new URL("vendor/openui-lang-core.min.mjs", STATIC);
const { createStreamingParser, evaluate } = await import(BUNDLE.href);
const { LIBRARY } = await import(new URL("deep-ui-lib.mjs", STATIC).href);
const FIX = fileURLToPath(new URL("fixtures/", import.meta.url));
const CTX = { getState: () => null, resolveRef: () => null };

// stream a program through set() in 7-char steps (the way the widget feeds 'ui chunk' events) and return the final result
function stream(src, step = 7) {
  const sp = createStreamingParser(LIBRARY.schema, "Card"); const seen = [];
  for (let i = step; i < src.length; i += step) seen.push(sp.set(src.slice(0, i)));
  const r = sp.set(src); seen.push(r); return { r, seen };
}
const snap = (r) => JSON.parse(JSON.stringify({ root: r.root, meta: { incomplete: r.meta.incomplete, unresolved: r.meta.unresolved, orphaned: r.meta.orphaned, statementCount: r.meta.statementCount, errors: r.meta.errors.map((e) => ({ code: e.code, statementId: e.statementId, path: e.path })) } }));
const fixture = (name) => readFileSync(FIX + name + ".openui", "utf8").replace(/\r\n/g, "\n").replace(/\n$/, "");

test("bundle: ES module with no bare or dynamic imports, banner present, size recorded", (t) => {
  const src = readFileSync(BUNDLE, "utf8");
  assert.equal((src.match(/from"[a-z@][^"]*"/g) || []).length, 0, "bare imports");
  assert.equal((src.match(/import\(/g) || []).length, 0, "dynamic imports");
  assert.ok(src.startsWith("/* @openuidev/lang-core 0.4.1 (MIT, Thesys Inc.) bundled for the browser by tools/openui/build_vendor.mjs"));
  assert.equal((src.match(/phc_[A-Za-z0-9]{20,}|cloudfront\.net\/capture/g) || []).length, 0, "telemetry key / capture URL stubbed out");
  const size = statSync(BUNDLE).size; t.diagnostic(`bundle size ${size} bytes`);
  assert.ok(size > 40_000 && size < 200_000, "size " + size);
  assert.equal(typeof createStreamingParser, "function"); assert.equal(typeof evaluate, "function");
});

test("fixtures: 7-char streaming of every *.openui gives the snapshotted *.tree.json", () => {
  const names = readdirSync(FIX).filter((f) => f.endsWith(".openui")).map((f) => f.replace(/\.openui$/, ""));
  assert.ok(names.length >= 8, "fixtures present");
  for (const name of names) {
    const expected = JSON.parse(readFileSync(FIX + name + ".tree.json", "utf8"));
    assert.deepEqual(snap(stream(fixture(name)).r), expected, name);
  }
});

test("fixtures: the two prompt examples parse cleanly (no errors, no orphans)", () => {
  for (const name of ["example-companies", "example-journey"]) {
    const { r } = stream(fixture(name));
    assert.equal(r.root.typeName, "Card", name); assert.deepEqual(r.meta.errors, [], name); assert.deepEqual(r.meta.orphaned, [], name); assert.deepEqual(r.meta.unresolved, [], name);
  }
});

test("XSS strings survive verbatim; orphans are dropped; evaluate returns javascript: URLs untouched", () => {
  const { r } = stream(fixture("xss-orphan-number"));
  assert.equal(r.root.props.title, "Card test <b>x</b>");
  assert.equal(r.root.props.subtitle, '"><script>alert(1)</script>');
  const [s, k, c, a] = r.root.props.children;
  assert.equal(s.typeName, "Stat"); assert.equal(s.props.value, 3, "numbers stay numbers"); assert.equal(s.props.note, "<img src=x onerror=alert(1)>");
  assert.deepEqual(k.props.pairs, [["Sells", "B2B data"], ["Since", 2004]]);
  assert.equal(c.props.text, "javascript:alert(1)"); assert.equal(c.props.tone, "warning");
  assert.deepEqual(r.meta.orphaned.sort(), ["e", "orphan"], "unreferenced statements are dropped, not rendered");
  assert.equal(r.root.props.children.length, 4);
  const [b1, b2] = a.props.buttons;
  assert.deepEqual(evaluate(b1.props.action, CTX), { steps: [{ type: "open_url", url: "javascript:alert(1)" }] }, "lang-core does not allowlist: the renderer must");
  assert.deepEqual(evaluate(b2.props.action, CTX), { steps: [{ type: "continue_conversation", message: "ignored message", context: "ctx" }] });
});

test("an unknown component referenced from root is dropped with unknown-component", () => {
  const { r } = stream('root = Card("t", [s, e])\ns = Stat("a", "1")\ne = Evil("x")');
  assert.equal(r.root.typeName, "Card");
  assert.ok(r.meta.errors.some((e) => e.code === "unknown-component"), JSON.stringify(r.meta.errors));
  assert.deepEqual(r.root.props.children.map((c) => c.typeName), ["Stat"]);
});

test("slot types are NOT enforced by lang-core (the renderer filters): excess args at root, Badge in steps, Button in a cell, object Stat value", () => {
  let r = stream(fixture("excess-args-root")).r;
  assert.equal(r.root.typeName, "Card", "root kept despite excess-args"); assert.deepEqual(r.meta.errors.map((e) => e.code + "@" + e.statementId), ["excess-args@root"]);
  r = stream(fixture("badge-in-steps")).r;
  assert.deepEqual(r.root.props.children[0].props.steps.map((s) => (s && s.typeName) || typeof s), ["Step", "Badge", "Step"], "Badge survives inside Steps.steps; the plain string is dropped by validation");
  r = stream(fixture("button-in-cell")).r;
  const rows = r.root.props.children[0].props.rows;
  assert.equal(rows[0][1].typeName, "Button", "a Button element survives inside a Table cell"); assert.deepEqual(rows[1], [{ a: 1 }, [1, 2]]);
  assert.deepEqual(r.root.props.children[1].props.pairs, [["Sells", { a: 1 }], ["Ok", "fine"]]);
  r = stream(fixture("stat-object")).r;
  assert.deepEqual(r.root.props.children[0].props.value, { a: 1 }, "Stat.value anyOf is unchecked");
  assert.equal(r.root.props.children[2].props.tone, undefined, "a wrong enum value is dropped once complete…");
  const mid = stream('root = Card("t", [bd])\nbd = Badge("x", "x hidden btn")').seen.filter((x) => x.root && x.root.props.children[0] && typeof x.root.props.children[0].props.tone === "string");
  assert.ok(mid.length > 0, "…but while streaming (partial) a non-enum tone string is present on the node");
  assert.ok(mid.some((x) => x.root.props.children[0].partial), "and the node is marked partial");
});

test("bare @OpenUrl without Action([...]) evaluates to a single step; @Set is a step the renderer must skip", () => {
  const { r } = stream(fixture("bare-openurl"));
  const [b1, b2] = r.root.props.children[0].props.buttons;
  assert.deepEqual(evaluate(b1.props.action, CTX), { type: "open_url", url: "https://scheduler.zoom.us/sreedeep" });
  const p = evaluate(b2.props.action, CTX);
  assert.equal(p.steps.length, 2); assert.equal(p.steps[0].type, "set"); assert.deepEqual(p.steps[1], { type: "open_url", url: "https://www.deependhq.com/x?y=1" });
});

test("set() replaces: a shrinking program re-parses from scratch", () => {
  const sp = createStreamingParser(LIBRARY.schema, "Card");
  sp.set('root = Card("t", [l])\nl = List(["a", "b"])');
  const r = sp.set('root = Card("t", [l])\nl = List(["c"])');
  assert.deepEqual(r.root.props.children[0].props.items, ["c"]);
});
