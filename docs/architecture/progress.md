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
launcher replaces an open JARVIS window instead of focusing it and opens
`/?launch=<epoch-ms>`. A dashboard started from the scripts therefore always
loads the current stylesheet, with no manual hard refresh.

Ruling: CSS, response-header and launcher changes plus a new browser test file;
no backend application path was touched. Cost if wrong: the dashboard is no
longer cached at all, so each launch re-reads a few local files from disk.
