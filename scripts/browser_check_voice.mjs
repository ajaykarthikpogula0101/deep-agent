// Real-browser check of speech input: each WAV clip is played into a headless Edge/Chrome as its microphone
// (--use-file-for-fake-audio-capture), then the widget's own recorder, endpointing and the server's /stt do the rest.
// Measures the character error rate of what lands in the composer (mic button) and in the voice call (first "you" line).
//
//   node scripts/browser_check_voice.mjs http://127.0.0.1:8089 out_dir clips_dir
//
// clips_dir holds <id>.wav (16 kHz mono, ~1 s of silence first and ~3 s after) and clips.json: [{id, lang, text, voice?}].
// Make them with tools/stt_bench/make_clips.py --wav. The server must have STT_PROVIDER=openai with a key.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const BASE = process.argv[2] || "http://127.0.0.1:8089";
const OUT = resolve(process.argv[3] || "voice-check");
const CLIPS = resolve(process.argv[4] || "clips");
const MAX_CER = Number(process.env.VOICE_MAX_CER || 0.25);
const BROWSER = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(existsSync);
if (!BROWSER) { console.error("no Edge/Chrome found"); process.exit(1); }
mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ONLY = (process.env.VOICE_ONLY || "").split(",").filter(Boolean);
const AUDIO = process.env.VOICE_AUDIO || "";  // JSON getUserMedia audio constraints to try instead of the widget's own
const clips = JSON.parse(readFileSync(join(CLIPS, "clips.json"), "utf8")).filter((c) => !ONLY.length || ONLY.includes(c.id));

function norm(s) { return (s || "").normalize("NFKC").toLowerCase().replace(/[\p{P}\p{S}\s]/gu, ""); }
function cer(ref, hyp) {
  const r = [...norm(ref)], h = [...norm(hyp)]; if (!r.length) return h.length ? 1 : 0;
  let prev = Array.from({ length: h.length + 1 }, (_, j) => j);
  for (let i = 1; i <= r.length; i++) { const cur = [i]; for (let j = 1; j <= h.length; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] === h[j - 1] ? 0 : 1)); prev = cur; }
  return Math.min(1, prev[h.length] / r.length);
}

async function session(wav, port, fn) {
  const profile = join(OUT, "edge-profile-" + port); rmSync(profile, { recursive: true, force: true });
  const proc = spawn(BROWSER, [`--remote-debugging-port=${port}`, "--headless=new", "--disable-gpu", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    `--use-file-for-fake-audio-capture=${wav}%noloop`, "--autoplay-policy=no-user-gesture-required", "--lang=en-US", "--window-size=1280,900", "--user-data-dir=" + profile, "about:blank"], { stdio: "ignore" });
  let ws = null, nextId = 1; const pending = new Map();
  const call = (method, params = {}) => new Promise((res, rej) => { const id = nextId++; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); });
  try {
    for (let i = 0; i < 60 && !ws; i++) { try { const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); const page = list.find((t) => t.type === "page");
      if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise((r, e) => { ws.onopen = r; ws.onerror = e; }); } } catch { ws = null; } if (!ws) await sleep(250); }
    if (!ws) throw new Error("could not attach to the browser");
    ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.rej(new Error(msg.error.message)) : p.res(msg.result); } };
    await call("Page.enable"); await call("Runtime.enable");
    const evaluate = async (expression) => { const r = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r.result.value; };
    const waitFor = async (expression, ms) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { const v = await evaluate(expression); if (v) return v; } catch {} await sleep(200); } return null; };
    return await fn({ call, evaluate, waitFor });
  } finally { try { ws && ws.close(); } catch {} proc.kill(); await sleep(400); rmSync(profile, { recursive: true, force: true }); }
}

const P = (expr) => `(() => { const el = document.getElementById('panel'); const sh = el.shadowRoot; return (${expr}); })()`;
async function open(t) {
  await t.call("Page.navigate", { url: `${BASE}/demo` });
  await t.waitFor("customElements.get('deep-assistant') && document.getElementById('panel').shadowRoot && document.getElementById('panel').shadowRoot.querySelector('.welcome .act')", 20000);
  await t.evaluate("(localStorage.setItem('dh_voice_lang', 'auto'), true)");
  if (AUDIO) await t.evaluate(P(`(el._audioConstraints = ${AUDIO}, true)`));
  await t.waitFor(P("el._cfg && el._cfg.stt === 'server'"), 15000);  // the server's settings are in (before that the widget would use browser recognition)
}

let failures = 0, port = 9460; const rows = [];
const check = (c, label) => { console.log((c ? "PASS " : "FAIL ") + label); if (!c) failures++; };
try {
  const cfg = await (await fetch(`${BASE}/widget-config`)).json();
  if (cfg.stt !== "server") { console.error("the server under test does not use server speech-to-text (stt=" + cfg.stt + ")"); process.exit(2); }
  for (const c of clips) {
    const wav = join(CLIPS, c.id + ".wav");
    // 1. composer mic: tap, speak, the widget stops by itself after the pause and fills the input
    const dict = await session(wav, port++, async (t) => {
      await open(t);
      const t0 = Date.now(); await t.evaluate(P("(sh.querySelector('.b-mic').click(), true)"));
      const got = await t.waitFor(P("(() => { const v = el.$q.value.trim(); const lab = sh.querySelector('.rec .rlabel').textContent; return v ? { v } : (/didn't|couldn't|Could not|denied/.test(lab) ? { v: '', lab } : null); })()"), 45000);
      return { text: got ? got.v : "", note: got && got.lab ? got.lab : (got ? "" : "timeout"), ms: Date.now() - t0, lang: await t.evaluate(P("el._lastLang")) };
    });
    const e1 = cer(c.text, dict.text); rows.push({ id: c.id, mode: "mic", cer: e1, ...dict });
    check(c.text ? e1 <= MAX_CER : !dict.text, `mic   ${c.id.padEnd(14)} CER ${(100 * e1).toFixed(0).padStart(3)}%  ${(dict.ms / 1000).toFixed(1)}s  [${dict.lang || "-"}] ${dict.text.slice(0, 70) || dict.note}`);
    if (!c.voice) continue;
    // 2. voice call: the first thing heard becomes the visitor's line (the call is ended before the answer is spoken)
    const call = await session(wav, port++, async (t) => {
      await open(t);
      const t0 = Date.now(); await t.evaluate(P("(el.startVoice(), true)"));
      const line = await t.waitFor(P("el._voice && el._voice.lines.length ? el._voice.lines[0].text : (el._voice && /failed|denied|Could not/.test(sh.querySelector('.vstatus').textContent) ? '#' + sh.querySelector('.vstatus').textContent : null)"), 45000);
      const ms = Date.now() - t0; await t.evaluate(P("(el.stopVoice(), true)")).catch(() => {});
      return { text: line && !line.startsWith("#") ? line : "", note: line && line.startsWith("#") ? line.slice(1) : (line ? "" : "timeout"), ms };
    });
    const e2 = cer(c.text, call.text); rows.push({ id: c.id, mode: "call", cer: e2, ...call });
    check(e2 <= MAX_CER, `call  ${c.id.padEnd(14)} CER ${(100 * e2).toFixed(0).padStart(3)}%  ${(call.ms / 1000).toFixed(1)}s  ${call.text.slice(0, 70) || call.note}`);
  }
} catch (e) { console.error(e); failures++; }
writeFileSync(join(OUT, "voice_results.json"), JSON.stringify(rows, null, 1));
const speech = rows.filter((r) => clips.find((c) => c.id === r.id).text);
console.log(`\nmean CER ${(100 * speech.reduce((a, r) => a + r.cer, 0) / Math.max(1, speech.length)).toFixed(1)}% over ${speech.length} spoken runs`);
console.log(failures ? `${failures} check(s) failed` : "all voice checks passed");
process.exit(failures ? 1 : 0);
