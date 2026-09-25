#!/usr/bin/env bash
# Hashimori runtime demo — one-time setup on macOS/Linux.
#
#   ./demo/setup.sh                 # process-per-call hooks (simplest)
#   ./demo/setup.sh --fast          # resident server + curl hooks (~10x faster)
#   ./demo/setup.sh --judge FILE    # also enable the Jev judge; FILE holds TYPESAFE_API_KEY=...
#
# Creates demo/.venv, installs hashimori (editable) + pytest, compiles the
# runtime envelope from the design-time review, and writes the workspace's
# .claude/settings.json and .mcp.json with absolute paths.
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$DEMO_DIR")"
WS="$DEMO_DIR/workspace"
FAST=0
JUDGE_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fast) FAST=1; shift ;;
    --judge) JUDGE_FILE="$2"; shift 2 ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
done

echo "→ venv + install"
if [[ -n "${HASHIMORI_SETUP_OFFLINE:-}" ]]; then   # CI / air-gapped: reuse system packages
  python3 -m venv --system-site-packages "$DEMO_DIR/.venv"
  "$DEMO_DIR/.venv/bin/pip" install -q --no-deps --no-build-isolation -e "$REPO"
else
  python3 -m venv "$DEMO_DIR/.venv"
  "$DEMO_DIR/.venv/bin/pip" install -q --upgrade pip
  "$DEMO_DIR/.venv/bin/pip" install -q -e "$REPO"
  "$DEMO_DIR/.venv/bin/pip" install -q pytest || echo "   (pytest not installed — only needed to run the workspace's tests)"
fi
PY="$DEMO_DIR/.venv/bin/python"
HM="$DEMO_DIR/.venv/bin/hashimori"

echo "→ design-time review → runtime envelope"
mkdir -p "$WS/.hashimori" "$WS/.claude"
"$HM" envelope --rules "$REPO/rulepacks" --context "$DEMO_DIR/intake/coding-agent.json" \
  --out "$WS/.hashimori/envelope.json" > /dev/null
echo "   $WS/.hashimori/envelope.json"

ENV_PREFIX="HASHIMORI_HOME='$WS/.hashimori' HASHIMORI_ENVELOPE='$WS/.hashimori/envelope.json' HASHIMORI_ALLOW=grant"
if [[ -n "$JUDGE_FILE" ]]; then
  [[ -f "$JUDGE_FILE" ]] || { echo "judge file not found: $JUDGE_FILE"; exit 1; }
  ENV_PREFIX="set -a; . '$JUDGE_FILE'; set +a; HASHIMORI_JUDGE=jev $ENV_PREFIX"
  echo "→ judge enabled (key file: $JUDGE_FILE — never copied, never printed)"
fi

DENY_JSON='{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"hashimori: hook failed to run — failing closed"}}'

if [[ "$FAST" == 1 ]]; then
  PRE_CMD="curl -sf --max-time 5 -H 'content-type: application/json' --data-binary @- http://127.0.0.1:8787/pre || echo '$DENY_JSON'"
  POST_CMD="curl -sf --max-time 5 -H 'content-type: application/json' --data-binary @- http://127.0.0.1:8787/post > /dev/null || true"
  cat > "$DEMO_DIR/serve.sh" <<SERVE
#!/usr/bin/env bash
# Start the resident decision point for --fast hooks. Leave it running in its own terminal.
cd '$WS' && $ENV_PREFIX exec '$HM' serve --port 8787 --home '$WS/.hashimori' --envelope '$WS/.hashimori/envelope.json'
SERVE
  chmod +x "$DEMO_DIR/serve.sh"
  echo "→ fast mode: run ./demo/serve.sh in another terminal before starting claude"
else
  PRE_CMD="$ENV_PREFIX '$PY' -m hashimori.runtime.hook pre || echo '$DENY_JSON'"
  POST_CMD="$ENV_PREFIX '$PY' -m hashimori.runtime.hook post || true"
fi

"$PY" - "$WS" "$PRE_CMD" "$POST_CMD" "$PY" "$DEMO_DIR" <<'PYEOF'
import json, sys
ws, pre, post, py, demo = sys.argv[1:6]
settings = {
    "enableAllProjectMcpServers": True,
    "hooks": {
        "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": pre, "timeout": 30}]}],
        "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": post, "timeout": 30}]}],
    },
}
open(f"{ws}/.claude/settings.json", "w").write(json.dumps(settings, indent=2) + "\n")
mcp = open(f"{ws}/.mcp.json.template").read().replace("__PYTHON__", py).replace("__DEMO_DIR__", demo)
open(f"{ws}/.mcp.json", "w").write(mcp)
PYEOF
echo "→ wrote $WS/.claude/settings.json and $WS/.mcp.json"

"$HM" ledger reset --home "$WS/.hashimori" > /dev/null
rm -f "$WS/.hashimori/audit.jsonl" "$DEMO_DIR/chat-outbox.log"
echo
echo "Ready. Try:"
echo "  ./demo/replay.sh            # deterministic scenes, no agent needed"
echo "  cd demo/workspace && claude # live scenes — prompts in demo/SCENES.md"
