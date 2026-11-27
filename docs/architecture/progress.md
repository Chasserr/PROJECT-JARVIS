# Implementation progress

> **2026-11-27 — version control restored.** This workspace was an extracted ZIP
> copy with no `.git` directory, so history was lost and no change was
> revertable. `git init` was run and the untouched working tree was committed as
> the baseline (`chore: import existing JARVIS project into version control`,
> 143 tracked files). Secrets, the memory database and rollback backups remain
> untracked by `.gitignore`. Phase execution can now be tracked in commits again;
> this file stays as the narrative ledger.
>
> **Document paths referenced by handover notes do not exist.** The real files are:
>
> | Referenced | Actual |
> |---|---|
> | `docs/architecture/SYSTEM-ARCHITECTURE.md` | `docs/architecture/README.md` |
> | `docs/architecture/PHASE-PLAN.md` | `docs/architecture/phases.md` |
> | `docs/security/BUGHUNTER-INTEGRATION.md` | does not exist; see `docs/architecture/security.md` |

## Phase 2 — skills + starter toolset

Task list:

1. Schema v2: `notes`, `reminders` tables; encrypted stores.
2. Settings + `ToolContext` plumbing (`db`, `box`, skill/web/file settings).
3. Safe fetch helpers: SSRF guard, bounded HTML-to-text extraction.
4. Skill loader: `skills/<name>/manifest.json` + `skill.py`, duplicate and
   entry-path rejection, `requires_env` reporting.
5. Starter skills: `web.search`, `web.read`, `files.search`, `notes`,
   `reminders`.
6. Container/CLI wiring, docs, full-suite verification.

Ledger:

- Setup: no git repo → no worktree/commits. Ruling: use this file as the
  ledger and verify with the test suite after each task. Cost if wrong:
  changes are not individually revertable, only file-level.
- Phase 1 close-out: docs updated 28 → 29 tests; `build_llm` no longer raises
  at construction when the Anthropic key is missing, so `kill`/`status` stay
  usable. Suite: 29 passed, ruff clean.
- Task 1: complete. Schema v2 with `notes` and `reminders`; encrypted stores
  and models. `test_notes_reminders.py`: 3 passed.
- Task 2: complete. Skill/web/file settings, `ToolContext.db`/`box`, list
  result coercion. Suite still green.
- Task 3: complete. `net/safe_fetch.py` SSRF guard + bounded text extraction.
  `test_safe_fetch.py`: 16 passed.
- Task 4: complete. `skills/loader.py` with manifest validation, duplicate
  rejection, entry-path containment, `requires_env` reporting.
  `test_skill_loader.py`: 7 passed.
- Task 5: complete. 11 skill packages under `backend/skills/`:
  `web.search`, `web.read`, `files.search`, `notes.{create,list,update,delete}`,
  `reminders.{create,list,complete,delete}`. `test_skills.py`: 9 passed.
- Task 6: complete. Container loads skills from `JARVIS_SKILLS_DIR` or
  `backend/skills`; docs and `.env.example` updated. Suite: 64 passed, ruff
  clean. Live `jarvis tools`/`doctor` check pending Brave key.
- Ruling: `notes.delete` and `reminders.delete` are `dangerous: true` so a
  manifest cannot be silently upgraded to autonomous. Cost if wrong: an extra
  confirmation prompt.
- Ruling: missing `requires_env` values warn but do not block loading, so the
  rest of JARVIS stays usable without a Brave key. Cost if wrong: a skill is
  listed that fails at call time.

## 2026-11-27 — audit, version control, and documentation correction

Verified on this machine, not assumed:

- `pytest` in `backend/`: **67 passed**, exit 0. (Docs previously said 64, so
  the suite had already grown past the written record.)
- `nomic-embed-text` **is** installed, so vector recall is active and the
  Phase 2 "embedding model warning" is stale.
- Voice is implemented in the legacy runtime, not merely planned — see the
  corrected Phase 3 entry in [phases.md](phases.md).
- No services were listening on 8765/8766/8767 at audit time.
- The core still has **no specialist-agent layer**: `agent/` contains only
  planner, executor (`loop.py`) and critic. `llm/openjarvis.py` is a 53-line
  HTTP client, not an orchestrator. The 10-role agent team in the handover is
  **not implemented**.

Documentation corrected in this pass: `phases.md` (Phase 3 and Phase 4 status),
`architecture/README.md` (status line, voice row, test count), and the new
[INTEGRATION-STATUS.md](../INTEGRATION-STATUS.md) recording which external tools
are actually installed and working.

Ruling: doc-only changes, no code touched, so the suite was not re-run after the
edit. Cost if wrong: none — no executable path changed.

## 2026-11-27 — Agents rail button unusable (layout, not overlay)

Reported twice: an ordinary mouse click on the dashboard **Agents** rail button
did not open the specialist roster.

Root cause — two interacting defects in the `@media (max-width:850px)` block of
`web/openjarvis.css`:

1. `.rail-item span{display:none}` hid the only content of every rail button
   (they carry text labels, not icons), leaving eight blank squares.
2. `web/style.css` forces `.left-rail .rail-item{width:100%!important}`; once
   the rail switched to `flex-direction:row`, the eight buttons flex-shrank to
   roughly 18 px wide.

Measured at a 420 px viewport before the fix: button `18x42`, label
`display:none`. Playwright refused the element with "no visible area to click".
Overlay, stacking context, `pointer-events` and event propagation were each
checked and ruled out: `document.elementsFromPoint()` returned the button first,
and a capture-phase log showed a clean
`pointerdown -> mousedown -> focusin -> mouseup -> click` on `#railAgents`.

Fix: the responsive rule now keeps labels (`display:inline!important`) and sizes
each button with `width:auto`, `flex:0 0 auto`, `min-width:max-content` and
`min-height:40px`. It is written at matching specificity so it wins over
`style.css`'s forced width. `web/index.html` bumps the stylesheet cache-buster
to `openjarvis.css?v=20261127-agents-rail-1`.

Verification: real-mouse sweep over 17 viewport widths (320-1920). Labels
visible everywhere, targets 59-164 px wide, one physical click opens the panel
with all 11 agents and the close button hides it. Desktop layout is unchanged
(column rail, 164x58).

Regression tests: `backend/tests/test_dashboard_agents_panel.py` (9 cases) drives
the installed Chrome against a real HTTP server with a stubbed roster, so
Playwright hit-tests the button exactly as a user clicks it. They fail against
the old CSS and pass against the fix. Suite: **123 passed**.

Where `web/` is served from: `app.py` sets `ROOT = Path(__file__).resolve().parent`
and serves `ROOT/"web"`, so the dashboard always comes from the folder holding
`app.py`, never the process working directory. `restart-jarvis-server.ps1` and
`start-jarvis.bat` both run `app.py` from that same project folder, and only one
`openjarvis.css` exists on this machine, so the fix reaches the dashboard the
launchers open.

Stale assets: bumping the version string only helped browsers that had not
already cached the old URL, and `launch-jarvis-window.ps1` used to merely focus
an existing JARVIS window, so a window opened before the fix kept the old
stylesheet. The server now sends `Cache-Control: no-store, must-revalidate` on
every response that does not set its own policy (HTML, CSS, JS), and the
launcher closes the existing browser app window instead of focusing it. That
window is matched by class (`Chrome_WidgetWin_1`), owning process and the exact
title `JARVIS`, so consoles such as `JARVIS Core API` are never touched. A
dashboard started from the scripts therefore always loads the current
stylesheet, with no manual hard refresh.

Ruling: CSS, response-header and launcher changes plus a new browser test file;
no backend application path was touched. Cost if wrong: the dashboard is no
longer cached at all, so each launch re-reads a few local files from disk.

## 2026-11-27 — connectors, actions, execution, vision, Visuals and the scanner

Everything marked *verified* below was executed on this machine during the
session. Work is committed in logical units (`ed118c8` connectors, `ac9949e`
tools, `7d69fa5` agent status + API, `077a6f3` Visuals/Studio UI, `1ade1a1`
handover); the repository still has no remote, so nothing is pushed.

### Connectors — 8 read-only sources

`backend/src/jarvis/connectors/` (base, registry, internal, local, remote) plus
`tools/sources.py`. Sources: `memory`, `local_files`, `project_repo`,
`obsidian`, `web`, `github`, `supabase`, `email` (IMAP, read-only).

- Each connector reports `connected` / `not_configured` / `error` from its own
  configuration, so a missing token is never shown as a working source.
- Paths are resolved and checked against the authorised root; a symlink that
  escapes it is refused, and only known text suffixes are decoded.
- A fan-out search records a failure per source and keeps the successful hits,
  each tagged `source` + `locator` + `untrusted: true`.
- An empty `JARVIS_CONNECTOR_ALLOWLIST` means "no extra restriction"; a
  non-empty list restricts queries to those ids. Consent is never inferred from
  an empty list.

Verified: `/api/core/connectors` reported 4 connected (memory, local_files,
project_repo, web) and 4 `not_configured`; a search returned 22 attributed hits
with 0 errors across local_files (5), memory (1), project_repo (8), web (8).

### Actions — approval-gated side effects

`tools/actions.py`: `email.draft` (read-only), `email.send` and
`report.generate` (`CONFIRM`, `dangerous`).

Verified: draft returned `sent: false`; an unapproved `email.send` raised
`ApprovalRequired`; the approved call with no SMTP configured returned
"SMTP is not configured" instead of claiming success; `report.generate` wrote a
real Markdown file and returned its path and byte count.

### Execution — bounded shell, file write, real browser

`tools/execution.py`:

- `shell.run` — argv list only, allowlisted executables, cwd inside the project
  root, scrubbed environment (no `JARVIS_*` secrets), hard timeout. Verified:
  `print(6*7)` → exit `0`, stdout `42`.
- `files.write` — authorised roots only, refuses `.git`, 1 MB cap. Verified with
  a real nested file.
- `browser.open` — headless Chromium, host must be on
  `JARVIS_BROWSER_ALLOWED_DOMAINS`, private/loopback hosts refused. Verified:
  `https://example.com/` → title `Example Domain` and real body text.

These are not a sandbox: an allowlisted interpreter is still powerful, and the
approval prompt showing exact argv is the real control.

### Vision — verified with real pixels

`tools/vision.py`, tool `vision.analyze`, `/api/v1/vision/analyze` and
`/api/core/vision`. Three different images produced three different correct
answers, and a request without an image answered "No image provided."

Camera path was broken: `app.py` compared the base64 bytes against the literal
text `b"\xff\xd8"`, so `/api/camera/analyze` returned 415 for every frame.
After the fix: 200 in 3.7 s with a real description.

### Visuals panel

`web/viz.js` + `web/viz.css`, opened from the new `#railVisuals` button. Every
mark comes from a live request (agents, tools, sources, runs, health) and an
endpoint that cannot be read is listed as unavailable rather than invented.
Browser check: 5 cards, 11 constellation nodes, 8 sources, 11 bars, 30 tools,
4 live sources, no console errors, no failed requests.

### Dependency scanner — Security Agent unblocked

`tools/scanner.py` adds `security.scan` (read-only) and
`capabilities.probe_scanner`; `pip-audit` and `pip` joined the shell allowlist
(`npm` was already there) and `scanner_timeout_s` bounds the audit.

- `pip-audit` runs as `python -m pip_audit -f json` so it audits the interpreter
  JARVIS itself uses.
- `npm audit --json` runs when a `package-lock.json` exists in the project root,
  `web/` or `frontend/`.
- Four states stay distinct: `ran`, `not_applicable`, `unavailable`, `failed`.
  Exit code 1 with JSON means *vulnerabilities found and the scan completed*, so
  it is `ran`, not a failure. An empty stdout is not treated as an empty report.
- pip-audit advisories carry no severity field, so they are counted as
  `unknown`; npm's real severities are kept.
- `scanner` left `UNIMPLEMENTED`; the probe only passes when a real audit ran
  and parsed.

Verified on this machine (pip-audit 2.10.1 installed into `backend/.venv`):
the probe returned `{"available": true, "packages": 78, "vulnerabilities": 0}`,
the live `/api/core/agents` reported `security: connected`, and the roster moved
to **9 connected / 2 partial** (desktop control, creative generation). A real
`pip-audit -r` run against a pinned old release confirmed the finding shape
(`id`, `fix_versions`, `aliases`, `description`).

`npm audit` is implemented and unit-tested against npm's documented JSON, but it
reports `not_applicable` in this repository because no npm project exists — that
is the honest state, not a passing scan.

### Verification and rulings

- `pytest` in `backend/`: **181 passed** (13 new scanner tests).
- `ruff check src tests`: only the pre-existing `SIM112` at
  `tools/builtin.py:97`.
- Ruling: `security.scan` is `READ_ONLY` rather than `CONFIRM`. It runs two
  fixed audit commands and writes nothing; the arbitrary-command risk stays
  behind `shell.run`, which does pause for approval. Cost if wrong: an agent can
  trigger a network audit without asking.
- Ruling: the probe requires a successful Python audit only. Requiring npm here
  would keep a working capability marked partial for lack of a JavaScript
  project. Cost if wrong: an environment without pip-audit stays `partial`, which
  is the truthful result.
- Review pass for this commit series removed only dead weight (an unused
  `_host_of` helper, redundant `getattr` fallbacks, an unused container field and
  parameter, a dead `viz.js` branch, and an allowlist comment that contradicted
  behaviour).

Known stale text, recorded rather than silently edited: `architecture/README.md`
still says "No shell execution, arbitrary file access, or network tool exists in
Phase 1" and quotes 67 tests; both predate this session.
