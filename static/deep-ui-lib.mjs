// Answer cards (docs/UI_CARDS.md): the single source of truth for the openui-lang library the model writes and the
// widget renders. Imported by static/deep-ui.js (browser), tools/openui/gen_prompts.mjs (prompt text) and the Node
// tests; served as application/javascript. Key order matters: positional arguments map to the key order of
// schema.$defs[Name].properties. Keep in sync with app/rag/ui_cards_prompt.txt (regenerate with npm run gen:prompts).
export const LIBRARY = {
  "id": "deep-answer-cards",
  "root": "Card",
  "components": {
    "Card":     { "signature": "Card(title: string, children: (Stat | Table | List | KeyValue | Steps | Badge | Callout | Actions)[], subtitle?: string)", "description": "The card; always the root. Title: 2-6 words naming what the card shows. Children render top to bottom" },
    "Stat":     { "signature": "Stat(label: string, value: string, note?: string)", "description": "One headline number or short value (\"3 companies\", \"day 338\"); several Stats in a row become tiles" },
    "Table":    { "signature": "Table(columns: string[], rows: string[][], caption?: string)", "description": "Compare things side by side; each row is an array aligned to columns, first column is the row name" },
    "List":     { "signature": "List(items: string[], ordered?: boolean)", "description": "Short bullet items; ordered=true for a ranking" },
    "KeyValue": { "signature": "KeyValue(pairs: string[][])", "description": "Fact sheet about one thing as [label, value] pairs" },
    "Steps":    { "signature": "Steps(steps: Step[], title?: string)", "description": "A sequence in order: how-it-works steps, phases, dated journey entries" },
    "Step":     { "signature": "Step(title: string, when?: string, detail?: string)", "description": "One step or journey entry; when = its day and date label such as \"day 338 · 2026-10-04\"" },
    "Badge":    { "signature": "Badge(label: string, tone?: \"neutral\" | \"success\" | \"warning\" | \"info\")", "description": "Small status or tag pill (\"B2B data\", \"live\"); several Badges in a row become a chip row" },
    "Callout":  { "signature": "Callout(text: string, tone?: \"info\" | \"success\" | \"warning\")", "description": "One highlighted sentence: the takeaway, a caveat, or who this fits" },
    "Actions":  { "signature": "Actions(buttons: Button[])", "description": "A row of 1-3 next-step buttons, always the last child" },
    "Button":   { "signature": "Button(label: string, action?: ActionExpression)", "description": "A next step; without an action it sends its label to the assistant as the visitor's next message" }
  },
  "componentGroups": [
    { "name": "Card", "components": ["Card"], "notes": ["root = Card(...) is always the first line."] },
    { "name": "Content", "components": ["Stat", "Table", "List", "KeyValue", "Steps", "Step", "Badge", "Callout"] },
    { "name": "Next steps", "components": ["Actions", "Button"] }
  ],
  "schema": {
    "$defs": {
      "Card":     { "properties": { "title": { "type": "string" }, "children": { "type": "array", "items": { "anyOf": [ { "$ref": "#/$defs/Stat" }, { "$ref": "#/$defs/Table" }, { "$ref": "#/$defs/List" }, { "$ref": "#/$defs/KeyValue" }, { "$ref": "#/$defs/Steps" }, { "$ref": "#/$defs/Badge" }, { "$ref": "#/$defs/Callout" }, { "$ref": "#/$defs/Actions" } ] } }, "subtitle": { "type": "string" } }, "required": ["title", "children"] },
      "Stat":     { "properties": { "label": { "type": "string" }, "value": { "anyOf": [ { "type": "string" }, { "type": "number" } ] }, "note": { "type": "string" } }, "required": ["label", "value"] },
      "Table":    { "properties": { "columns": { "type": "array", "items": { "type": "string" } }, "rows": { "type": "array", "items": { "type": "array" } }, "caption": { "type": "string" } }, "required": ["columns", "rows"] },
      "List":     { "properties": { "items": { "type": "array", "items": { "type": "string" } }, "ordered": { "type": "boolean" } }, "required": ["items"] },
      "KeyValue": { "properties": { "pairs": { "type": "array", "items": { "type": "array" } } }, "required": ["pairs"] },
      "Steps":    { "properties": { "steps": { "type": "array", "items": { "$ref": "#/$defs/Step" } }, "title": { "type": "string" } }, "required": ["steps"] },
      "Step":     { "properties": { "title": { "type": "string" }, "when": { "type": "string" }, "detail": { "type": "string" } }, "required": ["title"] },
      "Badge":    { "properties": { "label": { "type": "string" }, "tone": { "type": "string", "enum": ["neutral", "success", "warning", "info"] } }, "required": ["label"] },
      "Callout":  { "properties": { "text": { "type": "string" }, "tone": { "type": "string", "enum": ["info", "success", "warning"] } }, "required": ["text"] },
      "Actions":  { "properties": { "buttons": { "type": "array", "items": { "$ref": "#/$defs/Button" } } }, "required": ["buttons"] },
      "Button":   { "properties": { "label": { "type": "string" }, "action": {} }, "required": ["label"] }
    },
    "properties": { "Card": { "$ref": "#/$defs/Card" }, "Stat": { "$ref": "#/$defs/Stat" }, "Table": { "$ref": "#/$defs/Table" }, "List": { "$ref": "#/$defs/List" }, "KeyValue": { "$ref": "#/$defs/KeyValue" }, "Steps": { "$ref": "#/$defs/Steps" }, "Step": { "$ref": "#/$defs/Step" }, "Badge": { "$ref": "#/$defs/Badge" }, "Callout": { "$ref": "#/$defs/Callout" }, "Actions": { "$ref": "#/$defs/Actions" }, "Button": { "$ref": "#/$defs/Button" } }
  }
};
// Renderer caps (beyond a cap the extra entries are dropped, never the card) and the URL policy for @OpenUrl buttons.
export const LIMITS = { program: 4000, rows: 60, cols: 8, items: 40, pairs: 40, steps: 40, buttons: 6, stats: 8, badges: 12, str: 500, nodes: 200, depth: 4, ask: 300 };
export const ALLOWED_HOSTS = ['deependhq.com', 'www.deependhq.com'];      // any https path on these hosts
export const BOOK_URL = 'https://scheduler.zoom.us/sreedeep';             // exact URL (or BOOK_URL + '/' | '?' | '#' …); keep equal to DEFAULT_SHORTCUT in deep-assistant.js:28 and ZOOM_BOOKING_BASE
