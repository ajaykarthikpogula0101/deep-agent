// Black-box test of the render_email.mjs subprocess contract: one JSON line out, exit 0, policy outcomes.
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { EMAIL_EXAMPLE } from "../prompts.mjs";

const SCRIPT = fileURLToPath(new URL("../render_email.mjs", import.meta.url));
const HOSTS = ["deependhq.com", "www.deependhq.com", "scheduler.zoom.us"];
const PROG = EMAIL_EXAMPLE.split("```openui-lang\n")[1].split("\n```")[0];

function run(payload) {
  const p = spawnSync(process.execPath, [SCRIPT], { input: JSON.stringify(payload), encoding: "utf8",
    env: { ...process.env, OPENUI_TELEMETRY_DISABLED: "1", DO_NOT_TRACK: "1", NODE_ENV: "production" } });
  assert.equal(p.status, 0, "exit 0: " + p.stderr);
  const lines = p.stdout.split("\n").filter((l) => l.trim());
  assert.equal(lines.length, 1, "exactly one stdout line: " + p.stdout);
  return JSON.parse(lines[0]);
}
const render = (program, extra = {}) => run({ task: "render", program, subject: "s", preview_text: "29 Sep – 06 Oct 2026", lang: "en", allowed_hosts: HOSTS, max_chars: 150000, ...extra });

test("the example program renders", () => {
  const r = render("```openui-lang\n" + PROG + "\n```");
  assert.equal(r.ok, true);
  assert.equal(r.root, "EmailTemplate");
  assert.deepEqual(r.errors, []);
  assert.deepEqual(r.unresolved, []);
  assert.deepEqual(r.links, ["https://deependhq.com/admin"]);
  assert.ok(r.html.includes(">42<") && r.html.includes("Open the console") && r.html.includes('href="https://deependhq.com/admin"'));
  assert.ok(r.html.includes("29 Sep"));
  assert.equal(r.html_chars, r.html.length);
  assert.ok(r.statements >= 19 && r.ms >= 0);
});

test("a button to a foreign host is unsafe", () => {
  const r = render(PROG.replace("https://deependhq.com/admin", "https://evil.example/x"));
  assert.equal(r.ok, false); assert.equal(r.status, "unsafe"); assert.match(r.message, /evil\.example/);
});

test("EmailImage, EmailMarkdown and EmailLink are unsafe even on an allowed host", () => {
  const img = render(PROG + '\ni = EmailImage("https://deependhq.com/x.png", "alt")\nroot = EmailTemplate("s", "p", [h, i])');
  assert.equal(img.status, "unsafe"); assert.match(img.message, /EmailImage/);
  const md = render('root = EmailTemplate("s", "p", [m])\nm = EmailMarkdown("<img src=x>")');
  assert.equal(md.status, "unsafe"); assert.match(md.message, /EmailMarkdown/);
  const ln = render('root = EmailTemplate("s", "p", [l])\nl = EmailLink("x", "https://deependhq.com/x")');
  assert.equal(ln.status, "unsafe"); assert.match(ln.message, /EmailLink/);
});

test("a button colour that is not #hex is unsafe (CSS url() through backgroundColor)", () => {
  const r = render(PROG.replace('"#F28C28"', '"#fff;background-image:url(https:evil.com/p.gif)"'));
  assert.equal(r.ok, false); assert.equal(r.status, "unsafe"); assert.match(r.message, /colour not allowed/);
  assert.equal(render(PROG.replace('"#F28C28"', '"red"')).status, "unsafe");
  assert.equal(render(PROG.replace('"#F28C28"', '"#f28c28"')).ok, true);
});

test("http, userinfo and port are unsafe", () => {
  for (const u of ["http://deependhq.com/admin", "https://deependhq.com@evil.example/", "https://deependhq.com:8443/admin"]) {
    const r = render(PROG.replace("https://deependhq.com/admin", u));
    assert.equal(r.status, "unsafe", u);
  }
});

test("a non-EmailTemplate root and garbage are bad_program", () => {
  assert.equal(render('root = EmailHeading("x")').status, "bad_program");
  assert.equal(render("this is garbage").status, "bad_program");
  assert.equal(render("").status, "bad_program");
});

test("an unknown component in a child renders with an error entry (Python rejects it)", () => {
  const r = render(PROG.replace('EmailStatItem("42"', 'EmailStat("42"'));
  assert.equal(r.ok, true);
  assert.equal(r.errors[0].code, "unknown-component");
});

test("max_chars is honoured", () => {
  const r = render(PROG, { max_chars: 100 });
  assert.equal(r.status, "too_large");
});

test("the prompt task works with stdin closed after one write", () => {
  const r = run({ task: "prompt" });
  assert.equal(r.ok, true);
  assert.ok(r.prompt.startsWith("You write the weekly digest email") && r.chars === r.prompt.length && r.chars > 10000);
});

test("non-JSON stdin is a render_error line, not a crash", () => {
  const p = spawnSync(process.execPath, [SCRIPT], { input: "not json", encoding: "utf8" });
  assert.equal(p.status, 0);
  assert.equal(JSON.parse(p.stdout.trim()).status, "render_error");
});
