// Stub for zod/v4 and zod/v4/core in the browser bundle: lang-core only touches zod inside createLibrary()/
// defineComponent(), which a hand-written LibrarySpec (static/deep-ui-lib.mjs) never calls.
export function object() { throw new Error("zod stubbed out: createLibrary() is not available in this build"); } export function registry() { return { add() {}, get() { return undefined; } }; } export function toJSONSchema() { throw new Error("zod stubbed out"); }
