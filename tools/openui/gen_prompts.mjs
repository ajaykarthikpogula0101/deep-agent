// tools/openui/gen_prompts.mjs — writes the two committed prompt texts (npm run gen:prompts):
//   app/rag/ui_cards_prompt.txt   lang-core generateSystemPrompt(LIBRARY from static/deep-ui-lib.mjs, CHAT_PROMPT_OPTIONS)
//   tools/openui/email_prompt.txt @openuidev/react-email emailLibrary.prompt(EMAIL_PROMPT_OPTIONS)
// Both pass through trim(): the stock "Hoisting & Streaming" lecture and the "charts / forms" rule do not apply to
// our libraries, and the email prompt drops the picsum.photos image advice (images are forbidden anyway).
// Python never runs this: it reads the committed files. tests/lib.test.mjs regenerates and diffs (drift test),
// so a bump of lang-core or react-email that changes the stock sections shows up as a failing test, not in production.
import { generateSystemPrompt } from "@openuidev/lang-core";
import { emailLibrary } from "@openuidev/react-email";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { CHAT_PROMPT_OPTIONS, EMAIL_PROMPT_OPTIONS } from "./prompts.mjs";

export const CHAT_PROMPT_FILE = new URL("../../app/rag/ui_cards_prompt.txt", import.meta.url);
export const EMAIL_PROMPT_FILE = new URL("./email_prompt.txt", import.meta.url);

export function trim(p) {  // deterministic post-processing of lang-core's output; byte-stable across runs
  p = p.replace(/## Hoisting & Streaming \(CRITICAL\)[\s\S]*?(?=\n## )/, "");
  p = p.replace(/## Important Rules\n- Choose components that best represent the content[^\n]*\n/, "");
  return p.replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

export async function chatPrompt() {  // lazy import: the widget owns static/deep-ui-lib.mjs (single source of truth)
  const { LIBRARY } = await import("../../static/deep-ui-lib.mjs");
  return trim(generateSystemPrompt({ library: LIBRARY, promptOptions: CHAT_PROMPT_OPTIONS }));
}

export function emailPrompt() {
  const raw = emailLibrary.prompt(EMAIL_PROMPT_OPTIONS);
  return trim(raw.split("\n").filter((ln) => !ln.includes("picsum.photos")).join("\n"));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const chat = await chatPrompt();
  writeFileSync(CHAT_PROMPT_FILE, chat);
  const mail = emailPrompt();
  writeFileSync(EMAIL_PROMPT_FILE, mail);
  console.log(`ui_cards_prompt.txt ${chat.length} chars, email_prompt.txt ${mail.length} chars`);
}
