// Replaces lang-core's shared telemetry module (dist/shared-*.mjs) in the browser bundle: the PostHog key, the capture
// URL and the env gates never ship to visitors. Export names are the minified ones lang-core 0.4.1 imports
// (a = isTruthyEnv, i = isTelemetryDisabled, n = getPostHogConfig, o = normalizeProjectIdentity,
// r = isRuntimeTelemetryEnabled, t = TELEMETRY_REQUEST_TIMEOUT_MS); every gate answers "disabled".
export const a = () => false;
export const i = () => true;
export const n = () => null;
export const o = () => undefined;
export const r = () => false;
export const t = 0;
