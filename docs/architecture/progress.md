# Implementation progress

This workspace is not a git repository, so phase execution is tracked here
instead of in commits.

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
