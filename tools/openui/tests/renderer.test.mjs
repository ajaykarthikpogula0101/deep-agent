// static/deep-ui.js against the committed bundle: text-only rendering, the URL/label policy for buttons, the slot and
// value allowlists lang-core does not enforce, LIMITS, and createCard's state machine. Uses jsdom when it is installed
// (`npm ci` in tools/openui) and otherwise the fake document in tests/fakedom.mjs, so `node --test tests/` works in
// both cases. Both documents expose the same subset (textContent, querySelectorAll, classList, dataset).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const STATIC = new URL("../../../static/", import.meta.url);
const UI = await import(new URL("deep-ui.js", STATIC).href);
const { CSS, allowUrl, plan, renderTree, createCard } = UI;
const { createStreamingParser } = await import(new URL("vendor/openui-lang-core.min.mjs", STATIC).href);
const { LIBRARY, LIMITS, BOOK_URL } = await import(new URL("deep-ui-lib.mjs", STATIC).href);

let makeDoc, harness;
try { if (process.env.DEEP_UI_FAKEDOM) throw new Error("forced"); const { JSDOM } = await import("jsdom"); makeDoc = () => new JSDOM("<!doctype html><body></body>").window.document; harness = "jsdom"; }   // DEEP_UI_FAKEDOM=1 forces the fake document
catch { const { createFakeDocument } = await import("./fakedom.mjs"); makeDoc = createFakeDocument; harness = "fakedom"; }

const parse = (program) => createStreamingParser(LIBRARY.schema, "Card").set(program).root;
const tick = () => new Promise((r) => setTimeout(r, 80));   // createCard repaints on setTimeout(50) when there is no requestAnimationFrame
// a bot row like the widget's: .row.bot > .col > .msg(host)
function bubble(doc) {
  const row = doc.createElement("div"); row.className = "row bot"; const col = doc.createElement("div"); col.className = "col"; const msg = doc.createElement("div"); msg.className = "msg";
  row.appendChild(col); col.appendChild(msg); doc.body.appendChild(row); return { row, msg };
}
function render(program, hooks = {}) { const doc = makeDoc(); const host = doc.createElement("div"); const f = renderTree(parse(program), doc, hooks); if (f) host.appendChild(f); return { doc, host }; }
const texts = (host, sel) => Array.from(host.querySelectorAll(sel)).map((e) => e.textContent);

test(`harness: ${harness}`, () => { assert.ok(makeDoc().createElement("div")); });

test("source hygiene: deep-ui.js assigns no HTML strings; CSS has no animation", () => {
  const src = readFileSync(new URL("deep-ui.js", STATIC), "utf8");
  for (const bad of ["innerHTML", "insertAdjacentHTML", "outerHTML"]) assert.equal(src.includes(bad), false, bad);
  assert.equal(/animation/.test(CSS), false);
  assert.ok(CSS.includes(".ui-card") && CSS.includes(".msg.streaming:has(.ui-card)::after { display:none }"));
});

test("allowUrl: https on deependhq.com hosts (any path) or BOOK_URL exactly / with a / ? # suffix; everything else null", () => {
  for (const bad of ["javascript:alert(1)", "data:text/html,x", "http://deependhq.com/", "https://evil.example", "https://deependhq.com.evil.example/", "https://deependhq.com@evil.example/",
    "https://deependhq.com:8443/x", "https://scheduler.zoom.us/other", "https://scheduler.zoom.us/sreedeepx", "https://user:pw@deependhq.com/", "//deependhq.com/x", "deependhq.com/x", "", null, undefined, 42])
    assert.equal(allowUrl(bad), null, String(bad));
  assert.equal(allowUrl("https://www.deependhq.com/x?y=1"), "https://www.deependhq.com/x?y=1");
  assert.equal(allowUrl("https://deependhq.com"), "https://deependhq.com/");
  assert.equal(allowUrl("https://DEEPENDHQ.com/Company/Lake-B2B#top"), "https://deependhq.com/Company/Lake-B2B#top");
  assert.equal(allowUrl(BOOK_URL), BOOK_URL);
  assert.equal(allowUrl("https://scheduler.zoom.us/sreedeep/?x=1"), "https://scheduler.zoom.us/sreedeep/?x=1");
  assert.equal(allowUrl("https://scheduler.zoom.us/sreedeep?x=1"), "https://scheduler.zoom.us/sreedeep?x=1");
});

test("plan: ask carries the LABEL (the @ToAssistant argument is ignored); open only through allowUrl; label rules", () => {
  const b = (src) => parse('root = Card("t", [a])\na = Actions([b])\nb = ' + src).props.children[0].props.buttons[0];
  assert.deepEqual(plan(undefined, "What does Lake B2B sell?"), { type: "ask", message: "What does Lake B2B sell?" });
  assert.deepEqual(plan(b('Button("Tell me", Action([@ToAssistant("x", "ctx")]))').props.action, "Tell me"), { type: "ask", message: "Tell me" });
  assert.deepEqual(plan(b('Button("Go", Action([@OpenUrl("https://deependhq.com/x")]))').props.action, "Go"), { type: "open", url: "https://deependhq.com/x" });
  assert.deepEqual(plan(b('Button("Go", @OpenUrl("https://scheduler.zoom.us/sreedeep"))').props.action, "Go"), { type: "open", url: BOOK_URL }, "bare step without Action([...])");
  assert.deepEqual(plan(b('Button("Go", Action([@Set($x, 1), @OpenUrl("https://deependhq.com/y")]))').props.action, "Go"), { type: "open", url: "https://deependhq.com/y" }, "@Set skipped, next step wins");
  assert.equal(plan(b('Button("Go", Action([@OpenUrl("javascript:alert(1)")]))').props.action, "Go"), null);
  assert.equal(plan(b('Button("Go", Action([@OpenUrl("https://evil.example")]))').props.action, "Go"), null);
  assert.equal(plan(b('Button("Go", Action([@Set($x, 1)]))').props.action, "Go"), null, "no surviving step");
  assert.equal(plan(undefined, "my email is a@b.co"), null); assert.equal(plan(undefined, "see https://evil.example"), null);
  assert.equal(plan(undefined, ""), null); assert.equal(plan(undefined, "   "), null); assert.equal(plan(undefined, "x".repeat(LIMITS.ask + 1)), null);
  assert.deepEqual(plan(undefined, "x".repeat(LIMITS.ask)), { type: "ask", message: "x".repeat(LIMITS.ask) });
  assert.equal(plan(b('Button("a@b.co", Action([@ToAssistant("fine")]))').props.action, "a@b.co"), null, "ask refused for an e-mail label even with an explicit @ToAssistant");
  assert.equal(plan({ k: "Garbage" }, "x"), null, "evaluate throwing -> null");
});

test("renderTree: every model string is a text node, never markup", () => {
  const { host } = render('root = Card("Card test <b>x</b>", [s, c, t], "\\"><script>alert(1)</script>")\ns = Stat("Companies", "3", "<img src=x onerror=alert(1)>")\nc = Callout("javascript:alert(1)")\nt = Table(["<th>"], [["<td onclick=x>"]])');
  const b = host.querySelector(".ui-head b");
  assert.equal(b.textContent, "Card test <b>x</b>"); assert.equal(b.children.length, 0);
  assert.equal(host.querySelector(".ui-head span").textContent, '"><script>alert(1)</script>');
  assert.ok(host.querySelector(".ui-stat .n").textContent.includes("<img"));
  assert.equal(host.querySelectorAll("img, script").length, 0);
  assert.equal(host.querySelector(".ui-callout span").textContent, "javascript:alert(1)");
  assert.equal(host.querySelector(".ui-table th").textContent, "<th>"); assert.equal(host.querySelector(".ui-table td").textContent, "<td onclick=x>");
});

test("renderTree: DOM map of the suite fixture (stats, chips, table, buttons with data attributes, primary on the first ask)", () => {
  const { host } = render(readFileSync(new URL("fixtures/example-companies.openui", import.meta.url), "utf8").replace(/\r\n/g, "\n") + 'bd = Badge("Live", "success")\nn = Stat("Companies", 3)\n');
  assert.deepEqual(texts(host, ".ui-table thead th"), ["Company", "Focus"]);
  assert.equal(host.querySelectorAll(".ui-table tbody tr").length, 3); assert.deepEqual(texts(host, ".ui-table tbody tr td"), ["Lake B2B", "B2B data", "Ampliz", "Healthcare data", "Champions Accelerator", "Venture studio"]);
  const btns = Array.from(host.querySelectorAll(".ui-actions .ui-btn"));
  assert.equal(btns.length, 2);
  assert.equal(btns[0].dataset.uiAction, "ask"); assert.ok(btns[0].classList.contains("primary")); assert.equal(btns[0].textContent, "What does Lake B2B sell?"); assert.equal(btns[0].getAttribute("type"), "button");
  assert.equal(btns[1].dataset.uiAction, "open"); assert.equal(btns[1].dataset.uiUrl, "https://deependhq.com/company/lake-b2b"); assert.ok(!btns[1].classList.contains("primary"));
  assert.ok(btns[0].classList.contains("btn") && btns[0].classList.contains("sm") && btns[0].classList.contains("ui-btn"));
  const { host: h2 } = render('root = Card("t", [s1, s2, b1, b2, l, k, st, c])\ns1 = Stat("A", "1")\ns2 = Stat("B", 2, "note")\nb1 = Badge("x")\nb2 = Badge("y", "info")\nl = List(["i1", "i2"], true)\nk = KeyValue([["k", "v"]])\nst = Steps([Step("one", "day 1", "detail")], "Phases")\nc = Callout("takeaway", "success")');
  assert.equal(h2.querySelectorAll(".ui-stats").length, 1); assert.deepEqual(texts(h2, ".ui-stats .ui-stat .v"), ["1", "2"]); assert.deepEqual(texts(h2, ".ui-stat .l"), ["A", "B"]); assert.deepEqual(texts(h2, ".ui-stat .n"), ["note"]);
  assert.equal(h2.querySelectorAll(".ui-chips").length, 1); assert.deepEqual(texts(h2, ".ui-chips .ui-badge"), ["x", "y"]); assert.ok(h2.querySelectorAll(".ui-badge")[1].classList.contains("info"));
  assert.equal(h2.querySelector("ol.ui-list") && h2.querySelectorAll("ol.ui-list li").length, 2);
  assert.deepEqual(texts(h2, ".ui-kv span"), ["k"]); assert.deepEqual(texts(h2, ".ui-kv b"), ["v"]);
  assert.equal(h2.querySelector("ol.ui-steps .t").textContent, "Phases"); assert.equal(h2.querySelector(".ui-step b").textContent, "one"); assert.equal(h2.querySelector(".ui-step .when").textContent, "day 1"); assert.equal(h2.querySelector(".ui-step span.d").textContent, "detail");
  assert.ok(h2.querySelector(".ui-callout").classList.contains("success")); assert.equal(h2.querySelectorAll(".ui-callout svg").length, 1); assert.equal(h2.querySelector(".ui-callout span").textContent, "takeaway");
});

test("renderTree: buttons with a disallowed URL or an unsafe label are not rendered; clicks call the hooks with the label / the URL", () => {
  const sent = [], opened = [];
  const { host } = render('root = Card("t", [a])\na = Actions([b1, b2, b3, b4, b5, b6])\nb1 = Button("Bad link", Action([@OpenUrl("javascript:alert(1)")]))\nb2 = Button("Foreign", Action([@OpenUrl("https://evil.example/x")]))\nb3 = Button("Other zoom", Action([@OpenUrl("https://scheduler.zoom.us/other")]))\nb4 = Button("my email is a@b.co")\nb5 = Button("Ask me", Action([@ToAssistant("injected text", "ctx")]))\nb6 = Button("Open", Action([@OpenUrl("https://deependhq.com/company/lake-b2b")]))',
    { send: (t) => sent.push(t), open: (u) => opened.push(u) });
  const btns = Array.from(host.querySelectorAll(".ui-btn"));
  assert.deepEqual(btns.map((b) => b.textContent), ["Ask me", "Open"]);
  btns[0].click(); btns[1].click();
  assert.deepEqual(sent, ["Ask me"], "the label, not the @ToAssistant argument"); assert.deepEqual(opened, ["https://deependhq.com/company/lake-b2b"]);
  const { host: h2 } = render('root = Card("t", [a])\na = Actions([Button("x", Action([@OpenUrl("https://evil.example")]))])');
  assert.equal(h2.querySelector(".ui-actions"), null, "an Actions row with no surviving button is not rendered");
});

test("renderTree: slot and value allowlists (lang-core does not enforce them)", () => {
  const { host } = render('root = Card("t", [st, tb, kv, s1, s2, l, x, a])\nst = Steps([Step("ok", "d1"), Badge("not a step"), Step("")], "T")\ntb = Table(["A", "B"], [["r1", Button("hidden")], [{a: 1}, [1, 2]], "not a row", ["r3", "c3"]])\nkv = KeyValue([["k", {a: 1}], ["k2", "v2"]])\ns1 = Stat("x", {a: 1})\ns2 = Stat("y", 7)\nl = List(["a", {b: 1}, 3, "c"])\nx = Button("stray button as a child")\na = Actions([Badge("not a button"), Button("fine")])');
  assert.deepEqual(texts(host, ".ui-step b"), ["ok", ""], "only Step elements render (an empty title is still a string)");
  assert.equal(host.querySelectorAll(".ui-step").length, 2);
  assert.equal(host.querySelectorAll(".ui-table tbody tr").length, 3); assert.deepEqual(texts(host, ".ui-table tbody td"), ["r1", "", "", "", "r3", "c3"], "non-string cells stay empty, non-array rows are skipped");
  assert.equal(host.querySelectorAll(".ui-table button").length, 0, "a Button inside a cell is not rendered");
  assert.deepEqual(texts(host, ".ui-kv span"), ["k2"]); assert.deepEqual(texts(host, ".ui-kv b"), ["v2"]);
  assert.deepEqual(texts(host, ".ui-stat .v"), ["7"], "Stat with an object value is skipped; a number renders");
  assert.deepEqual(texts(host, ".ui-list li"), ["a", "c"], "lang-core already drops non-string items here; the renderer would too");
  assert.equal(host.textContent.includes("stray button"), false, "a Button directly under Card is not a valid child");
  assert.deepEqual(texts(host, ".ui-btn"), ["fine"]);
  assert.equal(host.textContent.includes("[object"), false);
});

test("renderTree: tone comes from a fixed map (a partial / unknown value never reaches className); partial nodes get ui-partial", () => {
  const node = (tone, partial) => ({ type: "element", typeName: "Card", props: { title: "t", children: [{ type: "element", typeName: "Badge", props: { label: "x", tone }, partial }, { type: "element", typeName: "Callout", props: { text: "c", tone }, partial: false }] }, partial: false });
  const doc = makeDoc(); const host = doc.createElement("div"); host.appendChild(renderTree(node("x hidden btn", true), doc));
  assert.equal(host.querySelector(".ui-badge").className, "ui-badge ui-partial"); assert.equal(host.querySelector(".ui-callout").className, "ui-callout");
  const h2 = doc.createElement("div"); h2.appendChild(renderTree(node("warning", false), doc));
  assert.equal(h2.querySelector(".ui-badge").className, "ui-badge warning"); assert.equal(h2.querySelector(".ui-callout").className, "ui-callout warning");
  const h3 = doc.createElement("div"); h3.appendChild(renderTree(node("neutral", false), doc));
  assert.equal(h3.querySelector(".ui-badge").className, "ui-badge");
  assert.equal(renderTree(null, doc), null); assert.equal(renderTree({ type: "element", typeName: "Card", props: { children: [] }, partial: true }, doc).childNodes.length, 1, "root without a title: empty head only");
});

test("renderTree: LIMITS drop the extra entries, never the card; long strings are truncated", () => {
  const rows = Array.from({ length: 100 }, (_, i) => `["r${i}", "v"]`).join(", ");
  const btns = Array.from({ length: 10 }, (_, i) => `Button("b${i}")`).join(", ");
  const stats = Array.from({ length: 12 }, (_, i) => `Stat("s${i}", "${i}")`).join(", ");
  const cols = Array.from({ length: 12 }, (_, i) => `"c${i}"`).join(", ");
  const { host } = render(`root = Card("t", [${stats}, tb, a, l, big])\ntb = Table([${cols}], [${rows}])\na = Actions([${btns}])\nl = List([${Array.from({ length: 50 }, (_, i) => `"i${i}"`).join(", ")}])\nbig = Callout("${"y".repeat(700)}")`);
  assert.equal(host.querySelectorAll(".ui-table tbody tr").length, LIMITS.rows);
  assert.equal(host.querySelectorAll(".ui-table thead th").length, LIMITS.cols);
  assert.equal(host.querySelectorAll(".ui-btn").length, LIMITS.buttons);
  assert.equal(host.querySelectorAll(".ui-stat").length, LIMITS.stats);
  assert.equal(host.querySelectorAll(".ui-list li").length, LIMITS.items);
  assert.equal(host.querySelector(".ui-callout span").textContent.length, LIMITS.str);
  assert.ok(host.querySelector(".ui-head b"), "the card itself survives");
});

test("createCard: streaming -> done, data attributes, events, announce, hascard/wide bookkeeping", async () => {
  const doc = makeDoc(); const { row, msg } = bubble(doc); const events = [], said = [];
  msg.classList.add("hascard"); row.classList.add("wide");   // as _onUi does before createCard
  const c = createCard(msg, { send() {}, open() {}, onEvent: (d) => events.push(d), announce: (t) => said.push(t), doc });
  assert.equal(c.el.dataset.uiState, "streaming"); assert.equal(c.el.className, "ui-card card"); assert.equal(c.el.querySelectorAll(".ui-skel").length, 3); assert.equal(msg.querySelector(".ui-card"), c.el);
  const full = readFileSync(new URL("fixtures/example-journey.openui", import.meta.url), "utf8").replace(/\r\n/g, "\n").replace(/\n$/, "");
  c.update(full.slice(0, 30)); await tick();
  assert.equal(c.el.querySelectorAll(".ui-skel").length, 3, "no root yet: skeleton bars stay");
  c.update(full.slice(0, 40)); await tick();
  assert.equal(c.el.dataset.uiState, "streaming"); assert.ok(c.el.querySelector(".ui-head b"), "partial program paints a head"); assert.equal(c.el.querySelectorAll(".ui-skel").length, 0);
  c.update(full.slice(0, 80)); c.update(full.slice(0, 120)); await tick();
  assert.ok(c.finish(full));
  assert.equal(c.el.dataset.uiState, "done"); assert.equal(c.el.dataset.uiStatements, "7"); assert.equal(c.el.dataset.uiRoot, "Card");
  assert.equal(c.el.querySelectorAll(".ui-partial").length, 0);
  assert.deepEqual(texts(c.el, ".ui-stat .v"), ["338"]); assert.equal(c.el.querySelectorAll(".ui-step").length, 2);
  assert.deepEqual(events, [{ state: "rendered", statements: 7 }]); assert.deepEqual(said, ["Latest journey entries"]);
  assert.ok(msg.classList.contains("hascard") && row.classList.contains("wide"));
  c.destroy();
  assert.equal(msg.querySelector(".ui-card"), null); assert.equal(events[1].state, "dropped");
  assert.ok(!msg.classList.contains("hascard") && !row.classList.contains("wide"), "no other card in the bubble: classes removed");
  c.destroy(); assert.equal(events.length, 2, "destroy is idempotent");
  assert.equal(c.finish(full), false, "finish after destroy");
});

test("createCard: finish() fails only for no root / root not Card / over LIMITS.program; excess-args at root keeps the card; other cards keep hascard", async () => {
  const cases = [["garbage text", false], ['t = Table(["a"], [["b"]])\nroot = t', false], ['root = Table(["a"], [["b"]])', false], ['root = Card("t", [s])\ns = Stat("a", "1")\n' + "# ".repeat(2100), false], ['root = Card("t", [s], "sub", "extra")\ns = Stat("Days", "1")', true]];
  for (const [program, ok] of cases) {
    const doc = makeDoc(); const { msg } = bubble(doc); const events = [];
    const c = createCard(msg, { onEvent: (d) => events.push(d), doc });
    assert.equal(c.finish(program), ok, program.slice(0, 40));
    assert.equal(!!msg.querySelector(".ui-card"), ok); assert.equal(events[events.length - 1].state, ok ? "rendered" : "dropped");
  }
  const doc = makeDoc(); const { row, msg } = bubble(doc); msg.classList.add("hascard"); row.classList.add("wide");
  const other = doc.createElement("div"); other.className = "bk card"; msg.appendChild(other);
  const c = createCard(msg, { doc }); c.update("x".repeat(LIMITS.program + 1));
  assert.equal(msg.querySelector(".ui-card"), null, "update over the cap destroys"); assert.ok(msg.classList.contains("hascard") && row.classList.contains("wide"), "the booking card still needs the wide bubble");
});

test("createCard: a renderer throw destroys the card instead of leaking", () => {
  const doc = makeDoc(); const { msg } = bubble(doc); const events = [];
  const c = createCard(msg, { onEvent: (d) => events.push(d), doc });
  assert.equal(c.finish(123), false); assert.equal(msg.querySelector(".ui-card"), null); assert.deepEqual(events, [{ state: "dropped" }]);
});
