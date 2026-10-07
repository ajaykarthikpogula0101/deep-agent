// Real-browser check of the <deep-assistant> web component on the /demo host page (headless Edge/Chrome, DevTools
// protocol). Verifies the anonymous panel and the signed-in launcher against the running API.
//
//   node scripts/browser_check_widget.mjs http://127.0.0.1:8080 out_dir
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const BASE = process.argv[2] || "http://127.0.0.1:8080";
const OUT = process.argv[3] || ".";
const PORT = 9334;
const ENV = (() => { try { return readFileSync(new URL("../.env", import.meta.url), "utf8"); } catch { return ""; } })();
const TOKEN = (ENV.match(/^ADMIN_TOKEN=([^\s#]+)/m) || [])[1] || "";
const BROWSER = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(existsSync);
if (!BROWSER) { console.error("no Edge/Chrome found"); process.exit(1); }
mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const proc = spawn(BROWSER, [`--remote-debugging-port=${PORT}`, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required", "--window-size=1280,900", "--user-data-dir=" + join(OUT, "edge-profile"), "about:blank"], { stdio: "ignore" });
let ws, nextId = 1; const pending = new Map();
const call = (method, params = {}) => new Promise((resolve, reject) => { const id = nextId++; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params })); });
async function connect() {
  for (let i = 0; i < 40; i++) { try { const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); const page = list.find((t) => t.type === "page");
    if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise((r, e) => { ws.onopen = r; ws.onerror = e; }); break; } } catch {} await sleep(250); }
  if (!ws) throw new Error("could not attach to the browser");
  ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result); } };
  await call("Page.enable"); await call("Runtime.enable");
}
async function evaluate(expression) { const r = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r.result.value; }
async function waitFor(expression, timeoutMs = 20000, label = expression) { const t0 = Date.now(); while (Date.now() - t0 < timeoutMs) { try { if (await evaluate(expression)) return; } catch {} await sleep(250); } throw new Error("timed out waiting for " + label); }
async function shot(name) { const r = await call("Page.captureScreenshot", { format: "png" }); writeFileSync(join(OUT, name), Buffer.from(r.data, "base64")); console.log("saved", name); }
// helpers evaluated inside the page: $el(id) is the component, $sh(id) its shadow root
const P = (id, expr) => `(() => { const el = document.getElementById(${JSON.stringify(id)}); const sh = el.shadowRoot; return (${expr}); })()`;
async function ask(id, text) { await evaluate(P(id, `(el.ask(${JSON.stringify(text)}), true)`)); await sleep(500); await waitFor(P(id, "!el.busy"), 60000, "answer"); await sleep(400); }
async function lastBot(id) { return evaluate(P(id, `(() => { const rows = [...sh.querySelectorAll('.row.bot')]; const r = rows[rows.length - 1]; const m = r && r.querySelector('.msg');
  return { text: m ? m.innerText.slice(0, 300) : '', sources: [...(r ? r.querySelectorAll('.sources a') : [])].map(a => a.href), picker: !!(r && r.querySelector('.picker')), slots: (r ? r.querySelectorAll('.slots .btn') : []).length, hform: !!(r && r.querySelector('.hform')), tools: (r ? r.querySelectorAll('.tool') : []).length }; })()`)); }
let failures = 0; const check = (c, label) => { console.log((c ? "PASS " : "FAIL ") + label); if (!c) failures++; };
try {
  await connect();
  const DEMO = await (await fetch(`${BASE}/demo/token`)).json(); const DEMO_EMAIL = DEMO.email || "ada@lovelace.org";
  await call("Page.navigate", { url: `${BASE}/demo` });
  await waitFor("customElements.get('deep-assistant') && document.getElementById('panel').shadowRoot && document.getElementById('panel').shadowRoot.querySelector('.chip')", 20000, "component to render");
  check(await evaluate(P("panel", "sh.querySelectorAll('.log .chip').length")) === 3, "panel renders the default suggestion chips");
  await evaluate(P("panel", "(el.setAttribute('theme', 'dark'), true)")); await sleep(100);  // the demo page sets theme=auto; the spec's dark look is what we verify
  check(await evaluate(P("launcher", "sh.querySelectorAll('.log .chip').length")) === 3, "launcher renders custom suggestions from the attribute");
  check(await evaluate("getComputedStyle(document.getElementById('panel').shadowRoot.querySelector('.panel')).fontFamily.includes('system-ui')"), "component inherits the host app's font");
  await waitFor(P("panel", "el._online === true"), 10000, "health check"); check(true, "health check passes inside the component");
  // new interface: no subtitle/meta bar, bubbles, more-menu, composer with Speak/send toggle, privacy footer
  check(await evaluate(P("panel", "!sh.querySelector('.readouts') && sh.querySelector('.brand .sub').textContent === 'Deep can also help directly' && getComputedStyle(sh.querySelector('.panel')).backgroundColor === 'rgb(0, 0, 0)'")), "restyle: black panel, subtitle 'Deep can also help directly', no meta bar");
  check(await evaluate(P("panel", "(() => { const m = sh.querySelector('.row.bot .msg'); return getComputedStyle(m).borderTopLeftRadius === '20px' && getComputedStyle(m).backgroundColor === 'rgb(28, 28, 30)' && /Deep • AI Agent • /.test(sh.querySelector('.row.bot .meta').textContent); })()")), "restyle: bot bubble 20px / #1C1C1E with 'Deep • AI Agent • time' meta line");
  check(await evaluate(P("panel", "/you're speaking with Deep's AI assistant/.test(sh.querySelector('.row.bot .msg').textContent)")), "greeting: generic first message for anonymous visitors");
  await evaluate(P("panel", "(sh.querySelector('.more').click(), true)")); await sleep(150);
  check(await evaluate(P("panel", "sh.querySelector('.menu').classList.contains('open') && [...sh.querySelectorAll('.menu button span')].map(s => s.textContent).join('|') === 'Switch theme|Download transcript|New chat'")), "header: ⋯ menu with Switch theme, Download transcript, New chat");
  await evaluate(P("panel", "(sh.querySelector('.menu button[data-act=theme]').click(), true)")); await sleep(150);
  check(await evaluate(P("panel", "el.getAttribute('theme') === 'light' && getComputedStyle(sh.querySelector('.panel')).backgroundColor === 'rgb(255, 255, 255)'")), "menu: Switch theme flips to light");
  await evaluate(P("panel", "(el.setAttribute('theme', 'dark'), true)"));
  check(await evaluate(P("panel", "!sh.querySelector('.speak').hidden && sh.querySelector('.send').hidden && !!sh.querySelector('.b-clip') && !!sh.querySelector('.b-emoji') && !!sh.querySelector('.b-mic')")), "composer: paperclip, emoji, mic and 'Speak to Deep' shown when empty");
  await evaluate(P("panel", "(sh.querySelector('.q').value = 'hello', sh.querySelector('.q').dispatchEvent(new Event('input')), true)"));
  check(await evaluate(P("panel", "sh.querySelector('.speak').hidden && !sh.querySelector('.send').hidden")), "composer: typed text swaps 'Speak to Deep' for the orange send arrow");
  await evaluate(P("panel", "(sh.querySelector('.b-emoji').click(), true)")); await sleep(100);
  await evaluate(P("panel", "(() => { const s = sh.querySelector('.pop-emoji .search'); s.value = 'rocket'; s.dispatchEvent(new Event('input')); sh.querySelector('.egrid button').click(); return true; })()"));
  check(await evaluate(P("panel", "sh.querySelector('.q').value === 'hello🚀'")), "emoji: search 'rocket' and insert at the cursor");
  await evaluate(P("panel", "(sh.querySelector('.q').value = '', sh.querySelector('.q').dispatchEvent(new Event('input')), true)"));
  check(await evaluate(P("panel", "/agree to our/.test(sh.querySelector('.foot').textContent) && /deependhq\\.com\\/privacy/.test(sh.querySelector('.foot a').href)")), "footer: privacy line with the configured link");
  await evaluate(P("panel", "(sh.querySelector('.b-gif').click(), true)")); await sleep(600);
  check(await evaluate(P("panel", "sh.querySelector('.pop-gif').classList.contains('open') && /not enabled/.test(sh.querySelector('.pop-gif .empty').textContent)")), "gif: button present; picker explains GIFs are not enabled without a key");
  await evaluate(P("panel", "(el._closePops(), true)"));
  await evaluate(P("panel", "(sh.querySelector('.speak').click(), true)")); await sleep(300);
  await sleep(900);
  check(await evaluate(P("panel", "sh.querySelector('.voice').classList.contains('open') && /Listening|Thinking|not available|denied|Could not/.test(sh.querySelector('.vstatus').textContent) && !!sh.querySelector('.v-mute') && !!sh.querySelector('.v-end')")), "voice: 'Speak to Deep' opens the call view with status, mute and end");
  const vc = await evaluate(P("panel", "(() => { const r = (sel) => sh.querySelector(sel).getBoundingClientRect(); const e = r('.v-end'), m = r('.v-mute'); const cs = getComputedStyle(sh.querySelector('.v-end')); return { endW: Math.round(e.width), endH: Math.round(e.height), muteW: Math.round(m.width), radius: cs.borderRadius, bg: cs.backgroundColor, endText: [...sh.querySelector('.v-end').childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim() + (sh.querySelector('.v-end .tip') ? '' : 'NO-TIP'), canvas: !!sh.querySelector('.vorb canvas') && !sh.querySelector('.vorb canvas').hidden, header: sh.querySelector('.vhead b').textContent, timer: sh.querySelector('.vtimer').textContent, live: !!sh.querySelector('.vhead .live'), state: el._voice && el._voice.state, orb: !!(el._voice && el._voice.orb), meter: !!(el._voice && el._voice.meter), ccOn: sh.querySelector('.v-cc').getAttribute('aria-pressed'), st: sh.querySelector('.st .stt').textContent }; })()"));
  check(vc.endW === 56 && vc.endH === 56 && vc.muteW === 56 && vc.radius === '50%' && /229, 72, 77/.test(vc.bg) && vc.endText === '', `voice: round 56px mute and red hang-up buttons, no wrapped text (end text: "${vc.endText}")`);
  check(vc.canvas && vc.orb && vc.meter, "voice: canvas orb running with the audio meter attached");
  check(vc.header === 'ask deep >_' && /^\d\d:\d\d$/.test(vc.timer) && vc.live, `voice: header strip with live dot and timer (${vc.timer})`);
  check(vc.st === 'In a call', "voice: header status reads 'In a call'");
  await evaluate(P("panel", "(sh.querySelector('.v-mute').click(), true)")); await sleep(500);
  const mu = await evaluate(P("panel", "({ muted: sh.querySelector('.voice').classList.contains('muted'), on: sh.querySelector('.v-mute').classList.contains('on'), st: sh.querySelector('.vstatus').textContent, state: el._voice.state, badge: getComputedStyle(sh.querySelector('.vmute-badge')).display })"));
  check(mu.muted && mu.on && mu.st === 'Muted' && mu.state === 'muted' && mu.badge === 'block', "voice: mute turns the button white, shows the muted badge and greys the orb");
  await evaluate(P("panel", "(sh.querySelector('.v-mute').click(), true)")); await sleep(300);
  await evaluate(P("panel", "(sh.querySelector('.v-min').click(), true)")); await sleep(200);
  check(await evaluate(P("panel", "!sh.querySelector('.voice').classList.contains('open') && sh.querySelector('.vpill').classList.contains('show') && !!el._voice")), "voice: minimize returns to chat with the call still going (pill shown)");
  await evaluate(P("panel", "(sh.querySelector('.vpill').click(), true)")); await sleep(200);
  check(await evaluate(P("panel", "sh.querySelector('.voice').classList.contains('open')")), "voice: the pill reopens the call view");
  await shot("widget_voice.png"); await sleep(800);
  await evaluate(P("panel", "(sh.querySelector('.v-end').click(), true)")); await sleep(700);
  await waitFor(P("panel", "!sh.querySelector('.voice').classList.contains('open') && !el._voice"), 5000, "call view to close"); await sleep(200);
  const endst = await evaluate(P("panel", "JSON.stringify({ card: sh.querySelector('.callcard') ? sh.querySelector('.callcard').textContent : null, rows: sh.querySelectorAll('.row').length, lastRow: (sh.querySelector('.log').lastElementChild || {}).className })"));
  check(/Voice call · \d+s/.test(endst), "voice: End call collapses the view and leaves a 'Voice call · Ns' summary card: " + endst);
  check(await evaluate(P("panel", "sh.querySelector('.st .stt').textContent === 'Online' && sh.querySelector('.orb-mini') && !sh.querySelector('.orb-mini').classList.contains('call')")), "header: status back to Online, mini orb idle");
  // attachment: a text file uploaded through the composer, then a question answered from it
  const tmpTxt = join(OUT, "brief.txt"); writeFileSync(tmpTxt, "Internal brief: Lake B2B is evaluating EU fintech data for a client called Nordwind Pay.");
  const inputObj = await call("Runtime.evaluate", { expression: "document.getElementById('panel').shadowRoot.querySelector('.file')" });
  await call("DOM.setFileInputFiles", { objectId: inputObj.result.objectId, files: [tmpTxt] });
  await waitFor(P("panel", "sh.querySelector('.achip') && /KB|B$/.test(sh.querySelector('.achip .sz').textContent)"), 15000, "upload chip");
  check(await evaluate(P("panel", "sh.querySelector('.achip .nm').textContent === 'brief.txt' && !sh.querySelector('.send').hidden")), "attachment: chip shows the file name and size, send enabled");
  await ask("panel", "Which client is named in my file?");
  const fb = await lastBot("panel");
  check(/Nordwind/i.test(fb.text), "attachment: the answer uses the uploaded file's contents: " + fb.text.slice(0, 70).replace(/\n/g, " ") + "…");
  check(await evaluate(P("panel", "/📎/.test([...sh.querySelectorAll('.row.user .msg')].pop().textContent) && !sh.querySelector('.achip')")), "attachment: shown in the user bubble, chip cleared after sending");

  await ask("panel", "What does Lake B2B do?");
  let b = await lastBot("panel");
  check(/Lake B2B/i.test(b.text) && b.text.length > 60, "anonymous panel streams an answer: " + b.text.slice(0, 60).replace(/\n/g, " ") + "…");
  check(b.sources.some((u) => u.includes("/company/lake-b2b")), "sources list links to the Lake B2B page");
  const ag = await evaluate(P("panel", "(() => { const rows = [...sh.querySelectorAll('.row.bot')]; const r = rows[rows.length - 1]; const w = r.querySelector('.worked'); const steps = r.querySelector('.steps'); if (w) w.click(); return { worked: w ? w.textContent : '', steps: steps ? [...steps.querySelectorAll('span')].map(x => x.textContent) : [], ctx: r.querySelector('.ctx') ? r.querySelector('.ctx').textContent : '', metaIn: r.querySelector('.meta').classList.contains('in'), toolsIn: !!r.querySelector('.tools.in'), activity: !!r.querySelector('.activity'), skel: r.querySelector('.msg').classList.contains('skel'), streaming: r.querySelector('.msg').classList.contains('streaming') }; })()"));
  check(/^Worked for \d+(\.\d)?s · \d sources?$/.test(ag.worked) && !ag.activity && !ag.skel && !ag.streaming, `agent: activity row collapsed into '${ag.worked}'`);
  check(ag.steps.includes('Thinking') && ag.steps.includes('Searching deependhq.com') && ag.steps.some(x => /^Reading \d sources?$/.test(x)) && ag.steps.includes('Writing') && ag.steps.includes('Done'), `agent: real backend steps listed (${ag.steps.join(' → ')})`);
  check(/^Using \d sources? from deependhq\.com$/.test(ag.ctx), `agent: context chip '${ag.ctx}'`);
  check(ag.metaIn && ag.toolsIn, "agent: meta line and action icons revealed with the stagger classes");

  check(b.tools >= 3, "thumbs and copy tools rendered");
  check(await evaluate("document.getElementById('events').textContent.includes('panel  answer')"), "host page received the deep-assistant:answer event");
  await shot("widget_panel.png");

  // ---- Messages screen: list, reopen, read state, new chat, tabs
  check(await evaluate(P("panel", "sh.querySelectorAll('.tabs .tab').length")) === 3 && await evaluate(P("panel", "sh.querySelector('.tab[data-tab=home]').classList.contains('on')")), "tabs: Home, Messages, Help with Home active");
  const firstSid = await evaluate(P("panel", "el.sessionId"));
  await evaluate(P("panel", "(sh.querySelector('.tab[data-tab=messages]').click(), true)"));
  await waitFor(P("panel", "sh.querySelectorAll('.mlist .convo').length >= 1"), 10000, "conversation list");
  check(await evaluate(P("panel", "sh.querySelector('.vtitle').textContent")) === "Messages" && await evaluate(P("panel", "!sh.querySelector('.view-chat').offsetParent")), "messages: header reads 'Messages', chat view hidden");
  check(await evaluate(P("panel", "/scheduler\\.zoom\\.us/.test(sh.querySelector('.shortcut').href)")), "messages: shortcut card links to the booking page");
  let rows = await evaluate(P("panel", "[...sh.querySelectorAll('.mlist .convo')].map(b => ({ sid: b.dataset.sid, name: b.querySelector('.n').textContent, preview: b.querySelector('.p').textContent, time: b.querySelector('.time').textContent, unread: !!b.querySelector('.dot') }))"));
  check(rows.length >= 1 && rows[0].sid === firstSid && /Nordwind|Lake B2B/i.test(rows[0].preview) && /^(now|\d+m)$/.test(rows[0].time) && !rows[0].unread, `messages: row shows bot name, last-message preview and relative time (${rows[0].time}), read`);
  check(await evaluate(P("panel", "sh.querySelector('.tab[data-tab=messages] .badge').hidden")), "messages: no unread badge after reading");
  await evaluate(P("panel", "(sh.querySelector('.fab').click(), true)")); await sleep(300);
  check(await evaluate(P("panel", "el.view === 'chat' && el.sessionId !== " + JSON.stringify(firstSid) + " && sh.querySelectorAll('.log .chip').length === 3")), "messages: 'Ask a question' starts a new conversation with the greeting and quick replies");
  await ask("panel", "Which companies are in Champions Group?");
  const secondSid = await evaluate(P("panel", "el.sessionId"));
  await evaluate(P("panel", "(sh.querySelector('.tab[data-tab=messages]').click(), true)"));
  await waitFor(P("panel", "sh.querySelectorAll('.mlist .convo').length >= 2"), 10000, "two conversations");
  rows = await evaluate(P("panel", "[...sh.querySelectorAll('.mlist .convo')].map(b => b.dataset.sid)"));
  check(rows[0] === secondSid && rows[1] === firstSid, "messages: newest conversation first");
  // titles: generated in the background after the first exchange; rows show title + preview, grouped under "Today"
  const vidP = await evaluate(P("panel", "el._vid"));
  let titled = null; for (let i = 0; i < 20 && !titled; i++) { const d = await (await fetch(`${BASE}/conversations`, { headers: { "X-Visitor-Id": vidP, Origin: BASE } })).json(); const c = d.items.find((x) => x.session_id === firstSid); if (c && c.title_source === "auto") titled = c; else await sleep(1000); }
  check(!!titled && titled.title.split(" ").length <= 8 && !/^What does Lake B2B do\?$/.test(titled.title), `titles: auto title generated for the first conversation: "${titled && titled.title}"`);
  await evaluate(P("panel", "(el.showView('chat'), el.showView('messages'), true)")); await waitFor(P("panel", "sh.querySelectorAll('.mlist .convo').length >= 2"), 10000, "list again");
  const row0 = await evaluate(P("panel", `(() => { const b = sh.querySelector('.convo[data-sid=${JSON.stringify(firstSid)}]'); const n = b.querySelector('.n'), p = b.querySelector('.p'); const cs = getComputedStyle(n); return { title: n.textContent, preview: p.textContent, weight: cs.fontWeight, size: cs.fontSize, nowrap: cs.whiteSpace === 'nowrap' && cs.textOverflow === 'ellipsis', group: sh.querySelector('.mgroup') && sh.querySelector('.mgroup').textContent, avatar: Math.round(b.querySelector('.avatar').getBoundingClientRect().width), overflow: sh.querySelector('.mlist').scrollWidth > sh.querySelector('.mlist').clientWidth, timeRight: b.querySelector('.time').getBoundingClientRect().left > n.getBoundingClientRect().right - 1 }; })()`));
  check(row0.title === (titled && titled.title) && !/deep >_/.test(row0.title) && row0.preview.length > 0, "messages: row shows the generated title, not the bot name, with a preview line");
  check(row0.weight >= 600 && row0.size === "14px" && row0.nowrap && row0.avatar === 32 && row0.group === "Today" && !row0.overflow && row0.timeRight, `messages: 14px semibold one-line title, 32px avatar, grouped under Today, time in its own column, no horizontal overflow`);
  await evaluate(P("panel", "(() => { const s = sh.querySelector('.msearch'); s.value = 'zzzz-no-match'; s.dispatchEvent(new Event('input')); return true; })()")); await sleep(150);
  check(await evaluate(P("panel", "sh.querySelectorAll('.mlist .convo').length === 0 && /match/.test(sh.querySelector('.mempty').textContent)")), "messages: search filters the list");
  await evaluate(P("panel", "(() => { const s = sh.querySelector('.msearch'); s.value = ''; s.dispatchEvent(new Event('input')); return true; })()")); await sleep(150);
  await evaluate(P("panel", `(sh.querySelector('.convo[data-sid=${JSON.stringify(firstSid)}] .more2').click(), true)`)); await sleep(150);
  await evaluate(P("panel", "(() => { const f = sh.querySelector('.rename'); f.querySelector('input').value = 'My Lake B2B notes'; f.requestSubmit(); return true; })()")); await sleep(800);
  check(await evaluate(P("panel", `sh.querySelector('.convo[data-sid=${JSON.stringify(firstSid)}] .n').textContent === 'My Lake B2B notes'`)), "messages: rename via the row menu is saved and shown");
  check(await evaluate(P("panel", "(() => { const l = sh.querySelector('.mlist'); return parseInt(getComputedStyle(l).paddingBottom) >= 64 && Math.round(sh.querySelector('.fab').getBoundingClientRect().height) === 40; })()")), "messages: list bottom padding clears the 40px Ask button");
  await shot("widget_messages.png");
  await evaluate(P("panel", `(sh.querySelector('.convo[data-sid=${JSON.stringify(firstSid)}]').click(), true)`));
  await waitFor(P("panel", "el.view === 'chat' && el.sessionId === " + JSON.stringify(firstSid)), 10000, "reopen first conversation");
  check(await evaluate(P("panel", "sh.querySelectorAll('.row.user').length === 2 && [...sh.querySelectorAll('.row.user .msg')].some(m => /Lake B2B/i.test(m.textContent)) && sh.querySelectorAll('.row.bot .tool').length >= 3 && !sh.querySelector('.back').hidden")), "messages: reopened conversation shows its full history with tools and a back button");
  await evaluate(P("panel", "(sh.querySelector('.back').click(), true)")); await sleep(300);
  check(await evaluate(P("panel", "el.view === 'messages'")), "messages: back button returns to the list");
  const unreadNow = await (await fetch(`${BASE}/conversations`, { headers: { "X-Visitor-Id": await evaluate(P("panel", "el._vid")), Origin: BASE } })).json();
  check(unreadNow.unread_conversations === 0, "messages: API reports no unread conversations after both were read");
  await evaluate(P("panel", "(sh.querySelector('.tab[data-tab=help]').click(), true)")); await sleep(200);
  check(await evaluate(P("panel", "sh.querySelector('.vtitle').textContent === 'Help' && sh.querySelectorAll('.help .btn').length >= 2")), "help tab: actions rendered");
  // capability cards (starts a new chat, so it runs after the Messages checks)
  const caps = await evaluate(P("panel", "(() => { el.newChat(); const c = [...sh.querySelectorAll('.caps .cap')].map(x => x.textContent.trim()); return { n: c.length, c, st: sh.querySelector('.st .stt').textContent, orb: !!sh.querySelector('.orb-mini') }; })()"));
  check(caps.n === 4 && caps.c[1] === "Books calls on Deep's calendar" && caps.c[3] === 'Voice conversation', `agent: four capability cards in the empty chat (${caps.c.join(' | ')})`);
  check(caps.st === 'Online' && caps.orb, "header: mini orb avatar with 'Online' status");
  await evaluate(P("panel", "(sh.querySelector('.caps .cap').click(), true)")); await sleep(300);
  const live = await evaluate(P("panel", "(() => { const rows = [...sh.querySelectorAll('.row.bot')]; const r = rows[rows.length - 1]; return { activity: !!r.querySelector('.activity'), lbl: r.querySelector('.activity .lbl') ? r.querySelector('.activity .lbl').textContent : '', skel: r.querySelector('.msg').classList.contains('skel'), busy: sh.querySelector('.cbox').classList.contains('busy'), st: sh.querySelector('.st .stt').textContent, work: sh.querySelector('.orb-mini').classList.contains('work'), caps: !!sh.querySelector('.caps-row') }; })()"));
  check(live.activity && live.lbl && live.skel && live.busy && live.st === 'Working…' && live.work && !live.caps, `agent: while working: activity '${live.lbl}', skeleton bubble, glowing composer, header 'Working…'`);
  await shot("widget_working.png");
  await waitFor(P("panel", "!el.busy"), 60000, "capability answer"); await sleep(400);

  await evaluate(P("panel", "(sh.querySelector('.tab[data-tab=home]').click(), true)")); await sleep(200);

  // signed-in launcher: token from /demo/token, identity visible, booking skips name/email
  await waitFor(P("launcher", "el.getAttribute('token')"), 10000, "demo token"); await sleep(600);
  const me = await evaluate(P("launcher", "el._me"));
  check(me && me.signed_in === true && me.email === DEMO_EMAIL, `launcher identifies the signed-in user (${me && me.name})`);
  await evaluate("(document.getElementById('open').click(), true)"); await sleep(300);
  check(await evaluate("document.getElementById('launcher').hasAttribute('open')"), "launcher opens from the host page");
  // clean up: the demo address may hold test bookings from earlier runs (the per-email cap would refuse a new one)
  try { const bl = await (await fetch(`${BASE}/admin/bookings?days=60`, { headers: { "X-Admin-Token": TOKEN } })).json(); for (const b of bl.items.filter((x) => x.email === DEMO_EMAIL && ["confirmed", "pending_zoom"].includes(x.status))) await fetch(`${BASE}/admin/bookings/${b.id}/cancel`, { method: "POST", headers: { "X-Admin-Token": TOKEN } }); } catch {}
  await ask("launcher", "I want to book a meeting with Deep");
  b = await lastBot("launcher"); check(b.picker, "booking: call-type cards rendered");
  check(await evaluate(P("launcher", "sh.querySelectorAll('.picker .ctype').length === 3 && /min · with Deep/.test(sh.querySelector('.picker .ctype').textContent)")), "booking: three call types with duration and description");
  check(!/\d{1,2}:\d{2}/.test(b.text), "booking: the model did not list times in text");
  await evaluate(P("launcher", "(sh.querySelector('.picker .ctype').click(), true)")); await waitFor(P("launcher", "!!sh.querySelector('.avail .date')"), 30000, "availability grid"); await sleep(400);
  const grid = await evaluate(P("launcher", "(() => { const a = sh.querySelector('.avail'); return { dates: a.querySelectorAll('.date').length, offDates: a.querySelectorAll('.date.off').length, open: a.querySelectorAll('.time:not(.off)').length, off: a.querySelectorAll('.time.off').length, offLabel: a.querySelector('.time.off') ? a.querySelector('.time.off').textContent : '', tz: (a.querySelector('.tzn') || {}).textContent || '', onDate: !!a.querySelector('.date.on') }; })()"));
  check(grid.dates >= 14 && grid.onDate, `booking: ${grid.dates} date chips, first open day selected`);
  check(grid.open >= 1, `booking: ${grid.open} open times in the grid`);
  check(grid.off >= 1 && /Not available/.test(grid.offLabel), `booking: ${grid.off} taken times greyed and labelled 'Not available'`);
  check(grid.offDates >= 1, `booking: ${grid.offDates} days without open slots greyed out`);
  check(/^Times shown in \S+/.test(grid.tz), "booking: timezone note under the grid");
  await evaluate(P("launcher", "(sh.querySelector('.avail .time:not(.off)').click(), true)")); await sleep(300);
  check(await evaluate(P("launcher", "sh.querySelector('.bform input[name=email]').hidden && sh.querySelector('.bform input[name=email]').value === " + JSON.stringify(DEMO_EMAIL))), "booking: details form prefills and hides the verified email");
  await evaluate(P("launcher", "(sh.querySelector('.bform textarea').value = 'browser test booking', sh.querySelector('.bform input[name=company]').value = 'Lovelace Analytical Engines', sh.querySelector('.bform button[type=submit]').click(), true)")); await sleep(300);
  check(await evaluate(P("launcher", "!!sh.querySelector('.bsum') && /Confirm booking/.test(sh.querySelector('.bsum').textContent) && /Nothing is booked until you confirm/.test(sh.querySelector('.bsum').textContent)")), "booking: summary card with call, time, duration and 'Confirm booking'");
  await shot("widget_booking_summary.png");
  await evaluate(P("launcher", "(sh.querySelector('.bsum [data-confirm]').click(), true)")); await waitFor(P("launcher", "!!sh.querySelector('.booked')"), 60000, "booking result"); await sleep(300);
  const booked = await evaluate(P("launcher", "(() => { const b = sh.querySelector('.booked'); return { text: b.textContent, ics: !!b.querySelector('a[download]'), zoom: !!b.querySelector('a.primary') }; })()"));
  check(/booked with Deep|One last step on Zoom/.test(booked.text) && booked.ics && booked.zoom, "booking: success card with Zoom button, Add to calendar and email note: " + booked.text.slice(0, 60).replace(/\n/g, " "));
  const hist = await evaluate(P("launcher", "el._history[el._history.length - 1].content"));
  check(/^(Booking confirmed|Time held):/.test(hist), "booking: the model's history records the confirmation line");
  await shot("widget_launcher.png");
  const bk = await fetch(`${BASE}/admin/bookings?days=1`, { headers: { "X-Admin-Token": TOKEN } });
  if (bk.ok) { const d = await bk.json(); const mine = d.items.find((x) => x.notes === "browser test booking"); check(!!mine && ["confirmed", "pending_zoom"].includes(mine.status) && !!mine.start_utc, `booking: stored in the bookings table (${mine && mine.method})`); }
  else check(false, "admin bookings reachable");
  try { const bl = await (await fetch(`${BASE}/admin/bookings?days=1`, { headers: { "X-Admin-Token": TOKEN } })).json(); const mine = bl.items.find((x) => x.notes === "browser test booking" && x.status !== "cancelled"); if (mine) { const c = await fetch(`${BASE}/admin/bookings/${mine.id}/cancel`, { method: "POST", headers: { "X-Admin-Token": TOKEN } }); check(c.ok, "booking: test booking cancelled again (admin cancel endpoint)"); } } catch { check(false, "booking: cleanup"); }

  await ask("launcher", "Can I talk to a real person?");
  b = await lastBot("launcher"); check(b.hform, "hand-over form rendered");
  check(await evaluate(P("launcher", "sh.querySelector('.hform input[name=email]').hidden && sh.querySelector('.hform input[name=email]').value === " + JSON.stringify(DEMO_EMAIL))), "hand-over form hides and prefills the verified email");

  const sid = await evaluate(P("launcher", "el.sessionId"));
  const r = await fetch(`${BASE}/admin/sessions?days=1&limit=50`, { headers: { "X-Admin-Token": TOKEN } });
  if (r.ok) { const d = await r.json(); const s = d.items.find((x) => x.session_id === sid); check(s && s.user_email === DEMO_EMAIL, "session row carries the signed-in user"); }
  else check(false, "admin sessions reachable");

  // ---- the public-site path: one script tag (widget.js) -> launcher button -> component mounted on first tap
  await call("Page.navigate", { url: `${BASE}/site` });
  await waitFor("document.readyState === 'complete' && !!document.getElementById('dh-assistant-btn')", 20000, "embed page");
  check(await evaluate("!document.querySelector('deep-assistant') && !!document.getElementById('dh-assistant-btn') && !document.querySelector('.dh-pro')"), "site embed: only the launcher button exists before the first tap (no greeting yet)");

  // proactive greeting bubble + quick replies (data-delay=800 on the test page)
  await waitFor("!!document.querySelector('.dh-pro .dh-pro-bubble')", 10000, "greeting bubble");
  check(await evaluate("document.querySelectorAll('.dh-pro .dh-pro-reply').length") === 3, "greeting: three quick-reply pills under the bubble");
  check(await evaluate("document.querySelector('.dh-pro-title').textContent.includes('Hi there') && /just now/.test(document.querySelector('.dh-pro-meta').textContent) && /deep/i.test(document.querySelector('.dh-pro-name').textContent)"), "greeting: title, question and 'bot • just now' line");
  check(await evaluate("(() => { const b = document.querySelector('#dh-assistant-btn .dh-pro-badge'); return !b.hidden && b.textContent === '1'; })()"), "greeting: unread badge '1' on the launcher");
  check(await evaluate("(() => { const r = document.querySelector('.dh-pro').getBoundingClientRect(); return r.right <= innerWidth && r.bottom <= innerHeight && r.left >= 0; })()"), "greeting: bubble stays inside the viewport");
  await sleep(600); await shot("site_bubble.png");
  await evaluate("(document.querySelector('.dh-pro-x').click(), true)"); await sleep(400);
  check(await evaluate("!document.querySelector('.dh-pro') && document.querySelector('#dh-assistant-btn .dh-pro-badge').hidden && sessionStorage.getItem('dh_greeting_dismissed') === '1'"), "greeting: × dismisses it, clears the badge and remembers for the session");
  await call("Page.reload", {}); await waitFor("document.readyState === 'complete' && !!document.getElementById('dh-assistant-btn')", 20000, "embed page reload"); await sleep(1500);
  check(await evaluate("!document.querySelector('.dh-pro')"), "greeting: not shown again after dismissal in this session");
  // bring it back and take a quick reply (drop any transcript the earlier /demo run left on this origin first)
  await evaluate("(Object.keys(sessionStorage).filter(k => k.startsWith('da:')).forEach(k => sessionStorage.removeItem(k)), window.deepAssistant.greet(), true)");
  await waitFor("!!document.querySelector('.dh-pro .dh-pro-reply')", 5000, "greeting again");
  const label = await evaluate("document.querySelector('.dh-pro .dh-pro-reply').textContent");
  await evaluate("(document.querySelector('.dh-pro .dh-pro-reply').click(), true)");
  await waitFor("document.querySelector('deep-assistant') && document.querySelector('deep-assistant').hasAttribute('open') && document.querySelector('deep-assistant').shadowRoot.querySelectorAll('.row.user').length >= 1", 20000, "quick reply opens the chat");
  await sleep(500);
  const first = await evaluate("document.querySelector('deep-assistant').shadowRoot.querySelector('.row.bot .msg').innerText");
  const userMsg = await evaluate("document.querySelector('deep-assistant').shadowRoot.querySelector('.row.user .msg').innerText");
  check(/speaking with Deep's AI assistant/.test(first), "quick reply: greeting is the bot's first message");
  check(userMsg === label, `quick reply: '${label}' sent as the visitor's first message`);
  check(await evaluate("!document.querySelector('.dh-pro') && !document.getElementById('dh-assistant-btn')"), "quick reply: bubble, pills and badge are gone once the chat is open");
  await waitFor("!document.querySelector('deep-assistant').busy", 60000, "quick reply answer"); await sleep(300);
  check(await evaluate("[...document.querySelector('deep-assistant').shadowRoot.querySelectorAll('.row.bot .msg')].pop().innerText.length > 40"), "quick reply: answer streamed through the normal flow");
  await shot("site_greeting.png");
  // fresh page for the plain launcher path
  await evaluate("(sessionStorage.clear(), true)");
  await call("Page.navigate", { url: `${BASE}/site?plain=1` });
  await waitFor("document.readyState === 'complete' && !!document.getElementById('dh-assistant-btn')", 20000, "embed page");
  await evaluate("(document.getElementById('dh-assistant-btn').click(), true)");
  await waitFor("document.querySelector('deep-assistant') && document.querySelector('deep-assistant').hasAttribute('open') && document.querySelector('deep-assistant').shadowRoot.querySelector('.row')", 20000, "component mount on tap");
  check(await evaluate("!document.getElementById('dh-assistant-btn') && document.querySelector('deep-assistant').getAttribute('mode') === 'launcher'"), "site embed: component mounted in launcher mode, bootstrap button removed");
  check(await evaluate("getComputedStyle(document.querySelector('deep-assistant').shadowRoot.querySelector('.panel')).fontFamily.includes('Georgia')"), "site embed: chat inherits the site's font (no iframe)");
  await evaluate("(document.querySelector('deep-assistant').reset(), true)"); await sleep(300);  // a transcript from /demo may have been restored (same origin)
  await evaluate("(window.deepAssistant.ask('What does Lake B2B do?'), true)"); await sleep(600);
  await waitFor("!document.querySelector('deep-assistant').busy", 60000, "answer on the site embed"); await sleep(300);
  const t = await evaluate("[...document.querySelector('deep-assistant').shadowRoot.querySelectorAll('.row.bot .msg')].pop().innerText.slice(0, 120)");
  check(/Lake B2B/i.test(t), "site embed: window.deepAssistant.ask() produced an answer: " + t.slice(0, 60).replace(/\n/g, " ") + "…");
  await shot("site_embed.png");
} catch (e) { console.error("ERROR", e.stack || e.message); failures++; try { await shot("widget_error.png"); } catch {} }
finally { try { ws && ws.close(); } catch {} proc.kill(); await sleep(300); }  // let the socket close before exiting
console.log(failures ? `${failures} check(s) failed` : "all widget checks passed");
process.exit(failures ? 1 : 0);
