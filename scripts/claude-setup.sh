#!/usr/bin/env bash
# Installs the Claude Code skills this project uses. Run once per machine.
# Plugins can't be installed from a script — see the slash commands printed at the end.
set -euo pipefail

SKILLS_DIR="${HOME}/.claude/skills"
mkdir -p "$SKILLS_DIR"

if [ -d "$SKILLS_DIR/hallmark/.git" ]; then
  echo "hallmark skill already present — pulling latest"
  git -C "$SKILLS_DIR/hallmark" pull --ff-only
else
  git clone https://github.com/Nutlope/hallmark.git "$SKILLS_DIR/hallmark"
fi

cat <<'EOF'

Skills installed. Now install the plugins from a Claude Code session:

  /plugin marketplace add DietrichGebert/ponytail
  /plugin install ponytail@ponytail
  /plugin marketplace add cloudflare/skills
  /plugin install cloudflare@cloudflare
  /plugin install figma@claude-plugins-official

Verify with /plugin and /skills. See CLAUDE.md for details.
EOF
