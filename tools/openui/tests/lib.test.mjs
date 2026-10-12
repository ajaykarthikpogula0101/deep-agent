// Drift test: the committed prompt texts must equal a live generation (a bumped lang-core / react-email that changes
// the stock sections fails here, never silently in production), and the chat examples must parse cleanly.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createStreamingParser } from "@openuidev/lang-core";
import { chatPrompt, emailPrompt, CHAT_PROMPT_FILE, EMAIL_PROMPT_FILE } from "../gen_prompts.mjs";
import { CHAT_EXAMPLES } from "../prompts.mjs";

test("app/rag/ui_cards_prompt.txt equals the generator output byte for byte", async () => {
  const live = await chatPrompt();
  assert.equal(readFileSync(CHAT_PROMPT_FILE, "utf8"), live);
  assert.ok(live.startsWith("ANSWER CARD (optional)") && live.endsWith("\n") && !live.endsWith("\n\n"));
  for (const bad of ["## Hoisting", "Query(", "$binding", "charts for trends"]) assert.ok(!live.includes(bad), bad);
  for (const good of ["@ToAssistant", "@OpenUrl", "any @ToAssistant argument is ignored"]) assert.ok(live.includes(good), good);
});

test("tools/openui/email_prompt.txt equals the generator output byte for byte", () => {
  const live = emailPrompt();
  assert.equal(readFileSync(EMAIL_PROMPT_FILE, "utf8"), live);
  assert.ok(live.startsWith("You write the weekly digest email"));
  for (const bad of ["## Hoisting", "picsum.photos", "charts for trends"]) assert.ok(!live.includes(bad), bad);
  assert.ok(live.includes("Never EmailMarkdown, EmailLink or images"));
});

test("both chat examples parse with no errors and no orphans", async () => {
  const { LIBRARY } = await import("../../../static/deep-ui-lib.mjs");
  for (const ex of CHAT_EXAMPLES) {
    const prog = ex.split("```openui-lang\n")[1].split("\n```")[0];
    const sp = createStreamingParser(LIBRARY.schema, "Card");
    let r;
    for (let i = 7; i < prog.length; i += 7) r = sp.set(prog.slice(0, i));
    r = sp.set(prog);
    assert.equal(r.root && r.root.typeName, "Card");
    assert.deepEqual(r.meta.errors, []);
    assert.deepEqual(r.meta.orphaned, []);
  }
});
