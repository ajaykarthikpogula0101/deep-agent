// tools/openui/render_email.mjs — renders ONE openui-lang program (the model-composed weekly digest) to email HTML.
// Called by app/digest_rich.py as a subprocess: one JSON object on stdin, exactly one JSON line on stdout, exit 0
// whenever a line was written (also for ok:false); exit 1 only on an uncaught crash (Python treats "no JSON line"
// as render_error). Contract (docs/AUTOMATIONS.md §6):
//   stdin : {"task":"render","program":"<openui-lang, fences tolerated>","subject":"...","preview_text":"...","lang":"en",
//            "allowed_hosts":["deependhq.com","www.deependhq.com","scheduler.zoom.us"],"max_chars":150000}
//         | {"task":"prompt"}
//   stdout: {"ok":true,"html":"...","root":"EmailTemplate","statements":19,"errors":[],"unresolved":[],"orphaned":[],
//            "links":["https://deependhq.com/admin"],"html_chars":10455,"ms":499}
//         | {"ok":true,"prompt":"...","chars":<n>}
//         | {"ok":false,"status":"bad_program"|"unsafe"|"too_large"|"render_error","message":"..."}
// Policy (enforced here on the parsed tree AND, text-based, in Python before the call): no image/link/markdown-style
// components (EmailMarkdown renders raw HTML, EmailLink/EmailImage carry arbitrary URLs), every href/src/url prop must
// be https on an allowed host with no userinfo and no port, and every *Color prop must be a #hex value (react-email
// writes it into a style attribute, where `url(...)` would fetch a remote image). Python then requires errors == []
// (an unresolved reference is dropped by the parser, counted and logged) and a content check (sane_html) on the HTML.
import React from "react";
import { Renderer, createParser } from "@openuidev/react-lang";
import { emailLibrary } from "@openuidev/react-email";
import { render } from "@react-email/render";
import { Html, Head, Body, Preview } from "@react-email/components";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

export const FORBIDDEN = /Markdown|Link|Image|Avatar|Social|Header|Footer|Product|Pricing|Testimonial|Survey|Bento|Code|Checkout|Review|Article|Feature|NavLink/;

export function stripFences(text) {
  return String(text || "").replace(/^\s*```[^\n]*\n/, "").replace(/\n```\s*$/, "").trim();
}

export function linkOk(v, allowedHosts) {
  try {
    const u = new URL(v);
    return u.protocol === "https:" && u.username === "" && u.password === "" && u.port === "" && allowedHosts.includes(u.hostname);
  } catch {
    return false;
  }
}

export const HEX_COLOUR = /^#[0-9a-f]{3,8}$/i;

export function policy(root, allowedHosts) {  // walk the whole element tree: forbidden components, disallowed links, non-hex colours
  const links = [], problems = [];
  const walk = (n) => {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) { n.forEach(walk); return; }
    if (n.type === "element") {
      if (FORBIDDEN.test(n.typeName)) problems.push("component not allowed: " + n.typeName);
      for (const [k, v] of Object.entries(n.props || {})) {
        if (/^(href|src|url)$/i.test(k) && typeof v === "string") { links.push(v); if (!linkOk(v, allowedHosts)) problems.push("link not allowed: " + v); }
        if (/colou?r$/i.test(k) && typeof v === "string" && !HEX_COLOUR.test(v)) problems.push("colour not allowed: " + v);   // a colour prop lands in style="": no url(), no injection
        walk(v);
      }
    }
  };
  walk(root);
  return { links, problems };
}

export async function renderTask(p) {
  const t0 = Date.now();
  const program = stripFences(p.program);
  const res = createParser(emailLibrary.toJSONSchema()).parse(program);
  if (!res.root || res.root.typeName !== "EmailTemplate") return { ok: false, status: "bad_program", message: "root is " + (res.root ? res.root.typeName : "null") };
  const rootErr = (res.meta.errors || []).find((e) => e.statementId === "root");
  if (rootErr) return { ok: false, status: "bad_program", message: rootErr.message };
  const pol = policy(res.root, Array.isArray(p.allowed_hosts) ? p.allowed_hosts : []);
  if (pol.problems.length) return { ok: false, status: "unsafe", message: pol.problems.join("; ") };
  const el = React.createElement(Html, { lang: p.lang || "en" }, React.createElement(Head), React.createElement(Preview, null, p.preview_text || ""),
    React.createElement(Body, { style: { background: "#f3f4f6", margin: 0 } }, React.createElement(Renderer, { response: program, library: emailLibrary, isStreaming: false })));
  const html = await render(el, { pretty: false });
  const max = Number(p.max_chars) > 0 ? Number(p.max_chars) : 150000;
  if (html.length > max) return { ok: false, status: "too_large", message: String(html.length) };
  return { ok: true, html, root: res.root.typeName, statements: res.meta.statementCount, errors: res.meta.errors || [], unresolved: res.meta.unresolved || [],
           orphaned: res.meta.orphaned || [], links: pol.links, html_chars: html.length, ms: Date.now() - t0 };
}

async function main() {
  let raw = "";
  for await (const c of process.stdin) raw += c;
  let out;
  try {
    const p = JSON.parse(raw || "{}");
    if (p.task === "prompt") {
      const { emailPrompt } = await import("./gen_prompts.mjs");
      const prompt = emailPrompt();
      out = { ok: true, prompt, chars: prompt.length };
    } else {
      out = await renderTask(p);
    }
  } catch (e) {
    out = { ok: false, status: "render_error", message: String((e && e.message) || e).slice(0, 300) };
  }
  process.stdout.write(JSON.stringify(out) + "\n", () => process.exit(0));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
