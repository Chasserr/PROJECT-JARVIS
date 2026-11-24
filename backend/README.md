# JARVIS Core Backend

This is the new modular backend, built alongside the existing Windows assistant. Do not remove the root `app.py` or legacy `web/` dashboard during migration.

## Runtime
- Python 3.12+ (the current PC has Python 3.13 and 3.15; 3.13 is used for development until 3.12 is installed).
- Install: `py -3.13 -m pip install -e ".[dev]"`
- Configuration: copy `.env.example` to `.env` and edit only the settings you need. Keep `JARVIS_CLOUD_ENABLED=false` unless you explicitly want cloud inference. The root `.gitignore` excludes `.env`.
- Run API: `py -3.13 -m uvicorn jarvis.api:app --app-dir src --host 127.0.0.1 --port 8766`
- CLI: `py -3.13 -m jarvis.cli --db ..\data\jarvis-core.sqlite3 memories` (from this directory with package installed).

## Current milestone
- Phase 1: typed task/permission models, local async event bus, SQLite memory/audit store with Windows DPAPI-protected memory content, provider-neutral FastAPI API, CLI and tests.
- AI routing: when `JARVIS_PROVIDER=claude`, `JARVIS_CLOUD_ENABLED=true` and `JARVIS_CLAUDE_API_KEY` is configured, Claude is primary and the configured OpenAI-compatible local endpoint is the fallback. Cloud calls remain disabled by default. Set `JARVIS_LOCAL_BASE_URL` to an Ollama OpenAI-compatible endpoint to use Ollama as the fallback; the default endpoint is LM Studio.
- Agent execution: registered Raea media-probe and read-only media-analysis handlers (loudness, motion, cuts, freezes), plus composition-render (confirmation required); strict argument allowlists; bounded tool retries; one-time approval/resume; audit events.
- Skill registry: `backend/config/skills.json` is a versioned declarative manifest. Startup validates unique IDs, permission tiers, argument names and JSON types, and capability requirements. The manifest cannot import or execute handlers; each skill must map to a trusted in-code handler. Inspect enabled skills with `GET /api/v1/skills`.
- Planner and executor both validate argument keys and types before a handler can run.
- Agent API: `POST /api/v1/agent/run`, `GET /api/v1/agent/tasks/{task_id}`, and `POST /api/v1/agent/tasks/{task_id}/approval` with `{\"approved\": true|false}`.
- Planner uses a JSON repair/validation retry for small-model formatting errors. The critic retries and has a narrow fallback only when every registered process result explicitly reports exit code 0.
- Task plans, results and status are persisted in SQLite. Interrupted tasks are marked failed on restart and never automatically replayed. The versioned skill manifest is loaded from `config/skills.json` by default; override with `JARVIS_SKILL_MANIFEST_PATH`.

## Security status
- Memory `content` is encrypted at rest with Windows DPAPI, bound to the current Windows user. Legacy plaintext memory rows are migrated on startup.
- SQLite connections are explicitly closed after each operation.
- DPAPI protects memory content only; tags, audit metadata, credentials and other database fields are not encrypted. Do not store API credentials in SQLite; supply secrets through ignored `.env` files or Windows environment variables.
- The API binds to loopback by default. Authenticated remote access, full rate limiting and sandbox execution are not complete. Do not expose this service to a LAN, Tailscale or public network.


## Phase 3 desktop and browser controls

The Windows control layer now includes:
- Primary desktop screenshot capture via MSS (saved under `backend/data/screenshots`).
- Coordinate-based desktop click and focused-field text entry via PyAutoGUI. Both require explicit one-time approval through the agent workflow.
- A dedicated visible Playwright Chromium profile under `backend/data/browser-profile`.
- Browser navigation to explicit HTTP/HTTPS URLs, current-page text snapshots, exact-text clicks, and focused-field entry.
- Browser click, text entry and form filling require explicit approval; navigation is restricted to HTTP/HTTPS URLs. Closing windows and moving files also require explicit approval.

The browser controller uses a single-worker executor because Playwright's synchronous API is thread-affine. Browser profile data is local to this PC. Do not enter passwords, payment details, or other secrets through planner-generated text-entry actions.

Desktop screenshots may contain private information. They are saved locally and should be treated as sensitive files. The API remains bound to loopback; do not expose it to a network without authentication and additional security controls.


## Voice and workflow capabilities

Windows voice I/O is now available locally:
- `POST /api/v1/voice/speak` uses the selected installed Windows SAPI voice by default; an optional ElevenLabs voice is available when the API key is configured and that voice is explicitly selected.
- `POST /api/v1/voice/listen` captures a user-initiated, bounded microphone session (2-15 seconds) and transcribes English with the installed Windows System.Speech recognizer.
- Agent skills `voice.speak` and `voice.listen` expose the same actions to the planner.
- There is no always-on microphone or wake-word listener. Listening happens only when explicitly requested.

Browser workflows now support tab listing, new tabs, switching tabs, back/forward/reload, a limited keyboard shortcut allowlist, and visible form-field inspection. Filling one non-sensitive field by exact label or placeholder requires approval; password, file and button controls are excluded, and the fill skill never submits a form. Keyboard actions still require agent approval. The browser remains isolated in JARVIS's own Chromium profile.

Raea media analysis is available through `creative.raea.media_analyze` for loudness, motion, shot cuts and frozen frames. These operations are read-only. Basic editing is also available: `creative.raea.media_trim` creates a new trimmed MP4, and `creative.raea.media_concat` joins 2-20 clips in order. Both require approval, write only into `backend/data/raea-output`, and refuse to overwrite existing outputs. Composition rendering remains approval-gated.

Memory search decrypts and scans saved memories in-process, so the database does not gain a plaintext content index. Search ranks memories by the number of matching query terms. This is a simple local retrieval layer, not yet semantic/vector search.


## Durable agent task history and restart recovery

Agent tasks are now stored in the local SQLite database. The API exposes:
- `GET /api/v1/agent/tasks?limit=100` for recent task history.
- `GET /api/v1/agent/tasks/{task_id}` for a saved task.
- Task plans, completed step results, errors and final status are persisted as the task runs.

On backend restart, tasks that were pending, running or awaiting approval are marked failed with an interruption warning. JARVIS deliberately does not automatically replay an in-flight action or restore an old approval, because the last external action may already have happened. Review the recorded results before retrying.
