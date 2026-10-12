# static/vendor

Third-party code served to the browser. Nothing here is edited by hand.

## openui-lang-core.min.mjs

`@openuidev/lang-core` 0.4.1 (MIT, Thesys Inc.; licence text in `LICENSE-openui-lang-core.txt`), the parser and
action evaluator for openui-lang, bundled as one ES module for the answer cards (`static/deep-ui.js`,
docs/UI_CARDS.md). Built by `tools/openui/build_vendor.mjs` (esbuild 0.25.12, `format: esm`, `platform: browser`,
`target: es2020`, minified) with three stubs: `zod/v4` + `zod/v4/core` -> `tools/openui/stubs/zod-stub.mjs` (lang-core
only touches zod inside `createLibrary`/`defineComponent`, which the widget never calls; both throw in this build),
`ci-info` -> `tools/openui/stubs/empty.mjs`, and lang-core's shared telemetry module (`dist/shared-*.mjs`) ->
`tools/openui/stubs/telemetry-stub.mjs`, so the PostHog key and capture URL are not in the file and every telemetry
gate answers "disabled" (`tools/openui/tests/parser.test.mjs` asserts no `phc_` key is present). The bundle has no bare
and no dynamic imports. Current size: 78,952 bytes.

Rebuild (from the repo root; the result must give no git diff unless the package was bumped):

```
cd tools\openui
$env:OPENUI_TELEMETRY_DISABLED="1"; $env:DO_NOT_TRACK="1"; npm ci
npm run build:vendor
```

The exact command the committed file was produced with: `node build_vendor.mjs` run inside `tools/openui` with
`node_modules/@openuidev/lang-core@0.4.1` installed (Node 24.19, esbuild 0.25.12); `tools/openui/tests/parser.test.mjs`
exercises the committed file and records its size.
