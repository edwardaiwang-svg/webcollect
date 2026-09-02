#!/usr/bin/env bash
# webcollect bootstrap — idempotent; gets a fresh machine/session to parity.
# Usage: ./install.sh [--with-permissions]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WITH_PERMS=0
[ "${1:-}" = "--with-permissions" ] && WITH_PERMS=1
cd "$REPO_DIR"

say() { printf "\033[1m== %s\033[0m\n" "$*"; }

# 1. preflight ---------------------------------------------------------------
say "preflight"
for t in git uv jq; do command -v "$t" >/dev/null || { echo "missing required tool: $t"; exit 1; }; done
command -v brew >/dev/null || echo "  (brew not found; install duckdb manually if needed)"

# 2. venv + deps -------------------------------------------------------------
say "python env (uv, 3.12)"
[ -d "$REPO_DIR/.venv" ] || uv venv --python 3.12 "$REPO_DIR/.venv"
if [ -f "$REPO_DIR/uv.lock" ]; then
  uv pip sync --python "$REPO_DIR/.venv/bin/python" "$REPO_DIR/uv.lock"
else
  uv pip install --python "$REPO_DIR/.venv/bin/python" \
    duckdb sqlite-vec tiktoken pydantic datasketch numpy rank-bm25 rapidfuzz \
    praw httpx beautifulsoup4 selectolax pyyaml openpyxl sentence-transformers scikit-learn
fi

# 3. duckdb CLI --------------------------------------------------------------
say "duckdb CLI"
command -v duckdb >/dev/null || { command -v brew >/dev/null && brew install duckdb || echo "  install duckdb manually"; }

# 4. symlink skills into ~/.claude/skills ------------------------------------
say "skills -> ~/.claude/skills (symlink)"
mkdir -p "$HOME/.claude/skills"
for d in "$REPO_DIR"/skills/*/; do
  name="$(basename "$d")"
  ln -sfn "$d" "$HOME/.claude/skills/$name"
  echo "  linked $name"
done

# 5. merge MCP defs into ~/.claude.json (never clobber) -----------------------
say "MCP servers -> ~/.claude.json (jq merge)"
CJ="$HOME/.claude.json"
if [ -f "$CJ" ]; then
  cp "$CJ" "$CJ.bak.$(date +%s)"
  jq --slurpfile m "$REPO_DIR/mcp/servers.json" \
     '.mcpServers = ((.mcpServers // {}) * (($m[0] // {}) | with_entries(select(.key|startswith("_")|not))))' \
     "$CJ" > "$CJ.tmp" && mv "$CJ.tmp" "$CJ"
  echo "  merged (backup: $CJ.bak.*)"
else
  echo "  ~/.claude.json absent; skipped"
fi

# 6. optional: auto-approve read-only pipeline commands ----------------------
if [ "$WITH_PERMS" = "1" ]; then
  say "permissions allowlist -> ~/.claude/settings.local.json"
  SL="$HOME/.claude/settings.local.json"
  [ -f "$SL" ] || echo '{}' > "$SL"
  cp "$SL" "$SL.bak.$(date +%s)"
  jq '.permissions.allow = ((.permissions.allow // []) + [
        "Bash(.venv/bin/python cli.py:*)",
        "Bash(duckdb:*)"
      ] | unique)' "$SL" > "$SL.tmp" && mv "$SL.tmp" "$SL"
  echo "  added (backup: $SL.bak.*)"
fi

# 7. secrets -----------------------------------------------------------------
say "secrets"
[ -f "$REPO_DIR/.env" ] || { cp "$REPO_DIR/env.example" "$REPO_DIR/.env"; echo "  created .env from example — fill REDDIT_* / optional keys"; }

# 8. selftest (the gate) -----------------------------------------------------
say "selftest"
HF_HUB_DISABLE_PROGRESS_BARS=1 TOKENIZERS_PARALLELISM=false \
  "$REPO_DIR/.venv/bin/python" "$REPO_DIR/lib/db.py" --selftest

say "done — open any project, run claude; skills are auto-discovered."
