// Bundles @openuidev/lang-core for the browser into static/vendor/openui-lang-core.min.mjs (docs/UI_CARDS.md).
// Run from tools/openui after `npm ci`: `npm run build:vendor`. zod (only used by createLibrary/defineComponent,
// which the widget never calls) and ci-info (telemetry gate) are replaced by stubs so the bundle has no bare and
// no dynamic imports; lang-core's shared telemetry module (dist/shared-*.mjs: PostHog key, capture URL, env gates)
// is replaced by stubs/telemetry-stub.mjs so no key or endpoint ships to the browser. The build is deterministic:
// a second run gives no git diff.
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const noTelemetry = {
  name: "no-telemetry",
  setup(b) { b.onResolve({ filter: /[\\/]shared-[^\\/]+\.mjs$/ }, (args) => (args.importer.includes("@openuidev") ? { path: here("stubs/telemetry-stub.mjs") } : undefined)); },
};
await build({
  entryPoints: [here("node_modules/@openuidev/lang-core/dist/index.mjs")],
  bundle: true, format: "esm", platform: "browser", target: ["es2020"], minify: true,
  alias: { "zod/v4": here("stubs/zod-stub.mjs"), "zod/v4/core": here("stubs/zod-stub.mjs"), "ci-info": here("stubs/empty.mjs") },
  plugins: [noTelemetry],
  banner: { js: "/* @openuidev/lang-core 0.4.1 (MIT, Thesys Inc.) bundled for the browser by tools/openui/build_vendor.mjs; zod, ci-info and the telemetry module stubbed (createLibrary/defineComponent unavailable, no PostHog key); license: static/vendor/LICENSE-openui-lang-core.txt */" },
  outfile: here("../../static/vendor/openui-lang-core.min.mjs"), logLevel: "warning",
});
