#!/usr/bin/env bash
# One command: turns ../.env.production into the Worker's APP_ENV secret, then builds the image and deploys.
#   bash deploy.sh            deploy to Cloudflare (needs Docker running and `wrangler login`)
#   bash deploy.sh --dry-run  validate the config and bundle only
set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE="../.env.production"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE"; exit 1; }
SECRETS="$(mktemp)"; trap 'rm -f "$SECRETS"' EXIT
python3 - "$ENV_FILE" "$SECRETS" "${1:-}" <<'PY'
import json, sys
env = {}
for line in open(sys.argv[1]):
    if line.startswith("#") or "=" not in line: continue
    k, v = line.split("=", 1)
    v = v.split(" #")[0].strip()
    if v: env[k.strip()] = v
for need in () if sys.argv[3] == "--dry-run" else ("LLM_API_KEY", "ADMIN_TOKEN", "LINK_SECRET"):
    if need not in env: sys.exit(f"{need} is empty in .env.production")
json.dump({"APP_ENV": json.dumps(env)}, open(sys.argv[2], "w"))
PY
[ -d node_modules ] || npm install --no-audit --no-fund
npx wrangler deploy --secrets-file "$SECRETS" "$@"
