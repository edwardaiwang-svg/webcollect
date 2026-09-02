#!/usr/bin/env bash
# Remove webcollect skill symlinks. Config backups (*.bak.<ts>) are left in place.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for d in "$REPO_DIR"/skills/*/; do
  name="$(basename "$d")"
  link="$HOME/.claude/skills/$name"
  if [ -L "$link" ]; then rm "$link"; echo "removed symlink $name"; fi
done
echo "Done. ~/.claude.json and settings backups (*.bak.*) were NOT auto-restored;"
echo "restore manually if needed. The venv + corpora under \$CORPUS_ROOT are untouched."
