// Drive the chat page in headless Edge/Chrome over the DevTools protocol, wait for each answer to finish
// streaming, and save screenshots. Verifies the real front end against the running API.
//
//   node scripts/browser_check.mjs http://127.0.0.1:8080 out_dir
//
// Needs Node 22+ (global WebSocket) and Microsoft Edge or Google Chrome installed.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const ENV = (() => { try { return readFileSync(new URL("../.env", import.meta.url), "utf8"); } catch { return ""; } })();
const envVal = (k) => { const m = ENV.match(new RegExp(`^${k}=([^\\s#]+)`, "m")); return m ? m[1] : ""; };
const TOKEN = envVal("ADMIN_TOKEN");
// visitor emails are real now: use a plus-address of the configured mailbox so test mail lands in your own inbox
const SMTP_USER = envVal("SMTP_USER");
const TEST_EMAIL = /@gmail\.com$/i.test(SMTP_USER) ? SMTP_USER.replace("@", "+browsertest@") : "browser-test@lovelace.org";

const BASE = process.argv[2] || "http://127.0.0.1:8080";
const OUT = process.argv[3] || ".";
const PORT = 9333;
const BROWSER = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
].find(existsSync);
if (!BROWSER) { console.error("no Edge/Chrome found"); process.exit(1); }
mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const proc = spawn(BROWSER, [`--remote-debugging-port=${PORT}`, "--headless=new", "--disable-gpu", "--hide-scrollbars",
  "--window-size=1184,820", "--user-data-dir=" + join(OUT, "edge-profile"), "about:blank"], { stdio: "ignore" });

let ws, nextId = 1; const pending = new Map();
function call(method, params = {}) {
  return new Promise((resolve, reject) => { const id = nextId++; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params })); });
}
async function connect() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise((r, e) => { ws.onopen = r; ws.onerror = e; }); break; }
    } catch {}
    await sleep(250);
  }
  if (!ws) throw new Error("could not attach to the browser");
  ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result); } };
  await call("Page.enable"); await call("Runtime.enable");
}
async function evaluate(expression) { const r = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.text); return r.result.value; }
async function waitIdle(timeoutMs = 60000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) { if (await evaluate("!document.body.classList.contains('busy')")) return true; await sleep(300); }
  return false;
}
async function shot(name) { const r = await call("Page.captureScreenshot", { format: "png" }); writeFileSync(join(OUT, name), Buffer.from(r.data, "base64")); console.log("saved", name); }
async function waitFor(expression, timeoutMs = 20000, label = expression) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) { try { if (await evaluate(expression)) return; } catch {} await sleep(200); }
  throw new Error("timed out waiting for " + label);
}
async function goto(url, ready = "typeof send === 'function'") { await call("Page.navigate", { url }); await waitFor(`document.readyState === 'complete' && (${ready})`, 20000, "page load"); await sleep(800); }
// fire-and-forget: send() returns a promise that only settles when the answer is complete, so never await it here
async function fire(text) { await evaluate(`(setTimeout(() => send(${JSON.stringify(text)}), 0), true)`); await sleep(500); }
async function ask(text) { await fire(text); const ok = await waitIdle(); if (!ok) throw new Error("answer did not finish in time"); await sleep(400); }
async function lastBot() { return evaluate("(() => { const rows = [...document.querySelectorAll('.row.bot')]; const r = rows[rows.length - 1]; const m = r && r.querySelector('.msg'); return { text: m ? m.innerText.slice(0, 400) : '', sources: [...(r ? r.querySelectorAll('.sources a') : [])].map(a => a.href), picker: !!(r && r.querySelector('.picker')), slots: (r ? r.querySelectorAll('.slots .btn') : []).length, tools: (r ? r.querySelectorAll('.tool') : []).length }; })()");
}

let failures = 0;
const check = (cond, label) => { console.log((cond ? "PASS " : "FAIL ") + label); if (!cond) failures++; };
try {
  await connect();
  await goto(`${BASE}/legacy`);
  check(await evaluate("document.querySelectorAll('.chip').length") === 4, "empty state shows four suggestion chips");
  check(await evaluate("document.getElementById('live').textContent.includes('ready')"), "health check reports ready");

  await ask("What does Lake B2B do?");
  let b = await lastBot();
  check(/Lake B2B/i.test(b.text) && b.text.length > 60, "answer streamed into the bubble: " + b.text.slice(0, 70).replace(/\n/g, " ") + "…");
  check(b.sources.some((u) => u.includes("/company/lake-b2b")), "sources list links to the Lake B2B page");
  check(!/https?:\/\//.test(b.text) && !/source\s*:/i.test(b.text), "no URLs or 'Source:' lines inside the answer text");
  check(await evaluate("document.querySelectorAll('.row.bot:last-of-type .msg a.cite, .row.bot:last-of-type .msg sup.cite').length") >= 1, "citation markers rendered in the answer");
  check(b.tools >= 1, "copy tool present under the answer");
  check(await evaluate("document.querySelectorAll('.chip').length") === 0, "suggestion chips removed after first send");
  await shot("live_answer.png");

  await ask("I want to book a meeting with Deep");
  b = await lastBot();
  check(b.picker, "call-type selector rendered under the reply");
  check(!/Discovery Call \(15 min\)/.test(b.text), "model did not list the call types as text");
  await evaluate("document.querySelector('.picker .btn').click()"); await sleep(400); await waitIdle(); await sleep(400);
  b = await lastBot();
  check(b.slots === 3, "three slot buttons rendered after choosing the discovery call");
  await shot("live_booking.png");

  // transcript survives a reload
  const before = await evaluate("document.querySelectorAll('.row').length");
  await goto(`${BASE}/legacy`);
  const after = await evaluate("document.querySelectorAll('.row').length");
  check(after >= before - 1 && after >= 4, `transcript restored after reload (${after} rows)`);

  // stop generation
  await fire("Tell me about every company in Champions Group in detail"); await sleep(600);
  await evaluate("(stop(), true)"); await sleep(800);
  check(await evaluate("!document.body.classList.contains('busy')"), "stop button cancels generation");

  // theme toggle + new conversation
  await evaluate("document.getElementById('theme').click()");
  check(await evaluate("document.documentElement.dataset.theme") === "light", "theme toggles to light");
  await shot("live_light.png");
  await evaluate("document.getElementById('reset').click()"); await sleep(300);
  check(await evaluate("document.querySelectorAll('.chip').length") === 4, "new conversation resets to the empty state");

  // ---- Fin-style layer: feedback, custom answers, hand-over, refusal offer, admin console
  const admin = async (path, opts = {}) => { const r = await fetch(`${BASE}${path}`, { ...opts, headers: { "X-Admin-Token": TOKEN, "Content-Type": "application/json", ...(opts.headers || {}) } }); if (!r.ok) throw new Error(`${path} -> ${r.status}`); return r.json(); };
  const sid = await evaluate("SESSION");
  const lastAssistant = async () => { const t = await admin(`/admin/conversations/${sid}`); return t.messages.filter((m) => m.role === "assistant").pop(); };

  await ask("What does Lake B2B do?");
  await evaluate("(document.querySelector('.row.bot:last-of-type .thumb').click(), true)"); await sleep(900);
  check(await evaluate("!!document.querySelector('.row.bot:last-of-type .thumb.on')"), "thumbs-up marks the answer as rated");
  let la = await lastAssistant();
  check(la && la.feedback === 1 && la.outcome === "answered", `feedback stored in the inbox (outcome ${la && la.outcome})`);

  const ca = await admin("/admin/custom-answers", { method: "POST", body: JSON.stringify({ question: "What are your office hours?", answer: "Deep's team works 9 to 6 IST, Monday to Friday.", link: "https://deependhq.com/now" }) });
  try {
    await ask("when are your office hours?");
    b = await lastBot();
    check(/9 to 6 IST/.test(b.text), "custom answer served verbatim");
    la = await lastAssistant();
    check(la && la.outcome === "custom", "inbox records the turn as a custom answer");
  } finally { await admin(`/admin/custom-answers/${ca.id}`, { method: "DELETE" }); }

  await ask("What's the weather in Paris today?");
  check(await evaluate("[...document.querySelectorAll('.row.bot:last-of-type .handoff .btn')].some(b => /Ask Deep directly/.test(b.textContent))"), "refusal offers 'Ask Deep directly'");
  la = await lastAssistant();
  check(la && la.outcome === "refused", "inbox records the refusal");

  await ask("Can I talk to a real person?");
  check(await evaluate("!!document.querySelector('.row.bot:last-of-type .hform')"), "asking for a human renders the hand-over form");
  await evaluate(`(() => { const f = document.querySelector('.row.bot:last-of-type .hform'); f.elements['name'].value = 'Browser Test'; f.elements['email'].value = ${JSON.stringify(TEST_EMAIL)}; f.elements['message'].value = 'Automated hand-over check, please ignore.'; f.requestSubmit(); return true; })()`);
  await waitFor("/Sent\\. Deep will reply/.test(document.querySelector('.row.bot:last-of-type .hform')?.textContent || '')", 20000, "hand-over confirmation");
  check(true, "hand-over form submits and confirms");
  const tx = await admin(`/admin/conversations/${sid}`);
  check(tx.leads.some((l) => l.status === "handover" && l.email === TEST_EMAIL), "hand-over stored as a lead on the session");
  const tpl = await admin("/admin/email-templates");
  check(/Thank you for booking with LakeB2B/.test(tpl.previews.visitor_booking.subject), "visitor subject renders the brand from the call type");
  const gaps = await admin("/admin/gaps?days=1");
  check(gaps.unanswered.some((u) => /weather in paris/.test(u.question)), "unanswered question appears in gaps");
  const met = await admin("/admin/metrics?days=1");
  check(met.conversations >= 1 && met.csat.up >= 1 && met.handovers >= 1, `metrics: ${met.conversations} conversations, csat up ${met.csat.up}, hand-overs ${met.handovers}`);
  await shot("live_handover.png");

  await goto(`${BASE}/admin`, "typeof load === 'function'");
  await evaluate(`(document.getElementById('token').value = ${JSON.stringify(TOKEN)}, document.getElementById('go').click(), true)`);
  await waitFor("/updated/.test(document.getElementById('status').textContent)", 20000, "admin console load");
  check(await evaluate("document.querySelectorAll('#tiles .tile').length") === 8, "admin overview shows eight metric tiles");
  check(await evaluate("document.querySelectorAll('#convo-list tr.click').length") >= 1, "admin lists conversations");
  await shot("admin_overview.png");
  await evaluate("(document.querySelector('nav button[data-pane=\"gaps\"]').click(), true)"); await sleep(300); await shot("admin_gaps.png");
  await evaluate("(document.querySelector('nav button[data-pane=\"convos\"]').click(), document.querySelector('#convo-list tr.click').click(), true)"); await sleep(1200); await shot("admin_transcript.png");
  await evaluate("(document.querySelector('nav button[data-pane=\"answers\"]').click(), true)"); await sleep(300); await shot("admin_answers.png");
  await evaluate("(document.querySelector('nav button[data-pane=\"emails\"]').click(), true)"); await sleep(300);
  check(await evaluate("document.getElementById('pv-visitor_booking').textContent.includes('Thank you for booking with')"), "emails tab shows the live preview");
  await shot("admin_emails.png");

  await goto(`${BASE}/legacy`);
  await call("Emulation.setDeviceMetricsOverride", { width: 420, height: 860, deviceScaleFactor: 1, mobile: true });
  await evaluate("document.getElementById('theme').click()"); await sleep(200);
  await ask("Which companies are in Champions Group?");
  await shot("live_phone.png");
} catch (e) {
  console.error("ERROR", e.stack || e.message); failures++;
  try { await shot("live_error.png"); } catch {}
} finally {
  try { ws && ws.close(); } catch {}
  proc.kill();
}
console.log(failures ? `${failures} check(s) failed` : "all checks passed");
process.exit(failures ? 1 : 0);
