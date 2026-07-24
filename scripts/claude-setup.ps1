# Installs the Claude Code skills this project uses. Run once per machine.
# Plugins can't be installed from a script - see the slash commands printed at the end.
$ErrorActionPreference = 'Stop'

$skillsDir = Join-Path $env:USERPROFILE '.claude\skills'
New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null

$hallmark = Join-Path $skillsDir 'hallmark'
if (Test-Path (Join-Path $hallmark '.git')) {
  Write-Host 'hallmark skill already present - pulling latest'
  git -C $hallmark pull --ff-only
} else {
  git clone https://github.com/Nutlope/hallmark.git $hallmark
}

Write-Host @'

Skills installed. Now install the plugins from a Claude Code session:

  /plugin marketplace add DietrichGebert/ponytail
  /plugin install ponytail@ponytail
  /plugin marketplace add cloudflare/skills
  /plugin install cloudflare@cloudflare
  /plugin install figma@claude-plugins-official

Verify with /plugin and /skills. See CLAUDE.md for details.
'@
