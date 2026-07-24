# CLAUDE.md — guide for Claude Code (and humans) working on Altitut CRM

This file orients an agent (or a new teammate) working in this repo. Read it before making
changes. For run/setup basics see [README.md](README.md).

## What this repo actually is

A listmonk fork, re-platformed. **The running app is `backend/` (Python FastAPI) +
`frontend/` (Vue 3), served together.** The original Go source (`cmd/`, `internal/`,
`models/`, `queries/`, `*.go`, `schema.sql`) is kept for reference only — do not edit it
expecting it to affect the running app. `queries/*.sql` and `schema.sql` are still the
source of truth for the DB schema and are useful when writing backend SQL.

## Architecture

- **Backend** — FastAPI app in `backend/app`. Entrypoint `app/main.py`; it seeds the admin
  user on startup and mounts the compiled frontend. All configuration is env-driven via
  Pydantic Settings in `app/config.py` — add new config there, never hard-code. One router
  per API area in `app/routers/`. DB access is async SQLAlchemy 2 + asyncpg (`app/db.py`).
- **Frontend** — Vue 3 `<script setup lang="ts">`, one view per admin page in
  `src/views/`. Oruga UI (Vue 3 successor to Buefy) themed with Bulma 1.0.
- **Serving** — `backend/Dockerfile.backend` is multi-stage: it builds the frontend, then
  bakes `dist/` into the Python image. So a frontend change needs an image rebuild
  (`docker compose up -d --build`) to show up in the Docker app; for fast iteration use the
  Vite dev server (`npm run dev`).

## Frontend gotchas (paid for in blood — don't regress these)

1. **Oruga registration (`src/main.ts`).** The default export of `@oruga-ui/oruga-next` is
   `createOruga()` with an **empty** component list — `app.use(Oruga, bulmaConfig)` registers
   **zero** components and every `<o-table>`/`<o-button>` renders as unstyled text. Use
   `app.use(createOruga(bulmaConfig, OrugaComponentPlugins))`.
2. **CSS load order (`src/main.ts`).** `main.css` → `bulma/css/bulma.min.css` →
   `@oruga-ui/theme-bulma/style.css` → `brand.css` (last). Bulma base **must** be imported
   or components are unstyled. `brand.css` loads last so its `:root` retint wins.
3. **Dark-mode lock.** Bulma 1.0 auto-flips to dark under
   `@media (prefers-color-scheme: dark)` on a plain `:root`, which broke the light shell.
   `brand.css` re-asserts the light `--bulma-scheme-*-l` values to lock light mode. If you
   add dark mode, do it deliberately — don't just delete the lock.
4. **Brand colors.** Altitut teal is set via Bulma CSS vars in `brand.css`
   (`--bulma-primary-h/s/l = 189deg/100%/21%`). Retint through those vars; don't scatter hex.
5. **Two design systems coexist.** `main.css` carries the custom shell (`.sidebar-*`, `.btn`,
   `.card` used by Layout/Login/NotFound); Bulma/Oruga style everything else. Load order
   manages the `.table`/`.modal`/`.pagination` class collisions — respect it.

## Conventions

- Backend: `ruff` + `mypy --strict` (config in `pyproject.toml`, line length 100). Tests with
  `pytest` (`backend/test_*.py`). New env/config → `app/config.py`.
- Frontend: `npm run lint`, `npm run type-check` (vue-tsc). Match existing view structure.
- Don't commit secrets. Default admin `listmonk`/`listmonk` is for local only.

---

## Claude Code tooling used to build this app

The app was built with Claude Code plus the skills/plugins below. **Install these so every
teammate works with the same tooling.** Skills and plugins live in your user-global
`~/.claude/` (they are not — and cannot be — checked into the repo), so each person installs
them once on their machine.

**Quick start:** run the bootstrap script, then install the plugins (slash commands it
prints):

```bash
bash scripts/claude-setup.sh          # macOS / Linux / Git Bash
powershell -File scripts/claude-setup.ps1   # Windows PowerShell
```

The details of each skill/plugin follow.

### Skills

| Skill | Source | Used for |
| ----- | ------ | -------- |
| **hallmark** | `https://github.com/Nutlope/hallmark.git` | The admin-UI redesign (Altitut retint + polish). A design skill that keeps generated UIs from looking generated. |

Install (clones into your user skills dir):

```bash
git clone https://github.com/Nutlope/hallmark.git ~/.claude/skills/hallmark
```

PowerShell (Windows):

```powershell
git clone https://github.com/Nutlope/hallmark.git "$env:USERPROFILE\.claude\skills\hallmark"
```

Then invoke it in a Claude Code session with `/hallmark` (e.g. `hallmark redesign <target>`,
`hallmark audit <target>`).

### Plugins

Installed via Claude Code slash commands. Add the marketplace, then install:

| Plugin | Marketplace | Purpose |
| ------ | ----------- | ------- |
| **ponytail** | `github:DietrichGebert/ponytail` | Enforces lean, no-over-engineering coding behavior. Active in every session. |
| **cloudflare** | `github:cloudflare/skills` | Cloudflare Workers/bindings/observability tooling (deploy/infra). |
| **figma** | `claude-plugins-official` (built-in marketplace) | Figma design ↔ code bridge (MCP). |

```text
# In a Claude Code session:
/plugin marketplace add DietrichGebert/ponytail
/plugin install ponytail@ponytail

/plugin marketplace add cloudflare/skills
/plugin install cloudflare@cloudflare

/plugin install figma@claude-plugins-official
```

Verify what you have with `/plugin` and `/skills`. The reference config this project was
built with:

```jsonc
// ~/.claude/settings.json  (excerpt — merge, don't overwrite your own)
{
  "enabledPlugins": {
    "ponytail@ponytail": true,
    "cloudflare@cloudflare": true,
    "figma@claude-plugins-official": true
  }
}
```

> Only **hallmark** (UI) and **ponytail** (coding discipline) shaped the current codebase
> directly. **cloudflare** and **figma** are installed for planned deploy/design work and are
> listed so the whole team's toolbox matches.
