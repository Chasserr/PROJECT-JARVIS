# Phase plan

Status legend: **done**, **in progress**, **planned**, **blocked**.

## Phase 0 — architecture and plan — **done**

Deliverables:

- System diagram and component boundaries: [README.md](README.md)
- Data models and encryption: [data-models.md](data-models.md)
- API spec: [api.md](api.md)
- Skill manifest schema: [skill-manifest.md](skill-manifest.md)
- Agent loop, failures, events: [agent-loop.md](agent-loop.md)
- Config reference: [config.md](config.md)
- Security model: [security.md](security.md)

Acceptance: a builder can implement a phase without asking what a component
owns or where a secret lives.

## Phase 1 — core agent + CLI + memory — **done**

Built:

- Typed `Settings`, composition root, SQLite schema/WAL.
- AES-256-GCM `SecretBox`, encrypted memory/episodes/runs/audit detail.
- Hash-chained audit log with verification.
- Permission policy and `ToolRegistry` (schema, timeout, audit, events).
- Tools: `time.now`, `memory.save/search/list/forget`, `system.info`.
- Planner/executor/critic loop with durable runs, approval pause/resume,
  replanning, kill switch.
- CLI: `init`, `doctor`, `status`, `kill`, `resume`, `ask`, `chat`, `memory`,
  `tools`, `audit`, `serve`.
- FastAPI: health, tools, memory CRUD/search, runs, approvals, audit, system.
- 29 tests; ruff clean.

Verification evidence:

- `pytest`: 29 passed.
- `ruff check src tests`: clean.
- `jarvis doctor`: DB/key/audit/tools/Ollama/chat model pass; embedding model
  warning because `nomic-embed-text` is not installed.
- Live `jarvis ask "What time is it in UTC?"`: completed via `time.now`.
- Live `jarvis memory add` + `memory search "tea"`: lexical recall works.

Known gaps:

- No vector index; lexical fallback until `nomic-embed-text` is pulled.
- No dashboard/PWA, voice, scheduler, or external integrations.
- No Docker/Redis on this machine.
- No key rotation, OS keyring, TLS, or multi-user auth.
- No code/system/file/network tools yet (intentional).

## Phase 2 — tool/skill system + 5 starter skills — **complete**

Scope:

1. Skill loader: `skills/<name>/manifest.json` + `skill.py`; validate manifest,
   reject duplicate names, check `requires_env` names only.
2. `web.search` — Brave Search (key present); `read_only`; bounded results.
3. `web.read` — fetch a URL, strip scripts/active content, extract readable
   text, cap bytes; `read_only`; SSRF guard (block private/link-local hosts).
4. `files.search` — search an explicit allowlist of roots (Desktop, Documents,
   Downloads by default); no arbitrary path traversal; `read_only`.
5. `notes` — encrypted SQLite CRUD; `autonomous` for create/update, `confirm`
   for delete.
6. `reminders` — encrypted SQLite CRUD; `autonomous` create, `confirm` delete;
   scheduler arrives in Phase 5.

Acceptance:

- Each skill has a manifest, tests for success, invalid args, permission
  denial, timeout, and untrusted-output handling.
- `web.read` blocks `localhost`, RFC1918, link-local, and non-HTTP schemes.
- No skill can write outside its allowlisted roots.
- `jarvis tools` lists effective permissions.

Verification:

- 64 tests pass; `ruff check src tests` clean.
- `test_safe_fetch.py` covers 16 URL/extraction cases; `test_skill_loader.py`
  covers 7 loader cases; `test_skills.py` covers 9 skill behaviors.
- Notes and reminders encrypt fields at rest (ciphertext asserted in tests).

Gaps:

- `JARVIS_BRAVE_API_KEY` is unset, so `web.search` is registered but untested
  live.
- DNS rebinding is a residual SSRF risk: validation resolves the host, then
  httpx resolves again at connect time.
- `files.search` matches filenames only, not content.
- Reminder scheduling/notification is deferred to Phase 5.
- No `jarvis skills` command yet; `jarvis tools` shows loaded skills and
  effective permissions.

## Phase 3 — voice — **planned**

Scope:

- Wake word: openWakeWord (or a documented alternative) with a configurable
  model path; no always-on cloud.
- STT: faster-whisper/Whisper local; streaming partials; English first.
- TTS: Piper local default; ElevenLabs optional (key present).
- Interrupt/barge-in: stop playback and capture a new utterance.
- Multilingual: English + Twi best-effort. Twi STT/TTS quality is a known
  limitation; fall back to text and state the limitation.
- Voice approval prompts for `confirm` tools, with a spoken "no" default.

Acceptance:

- End-to-end "wake → speak → transcript → agent → spoken answer".
- Interrupt stops audio within 300 ms.
- Voice approval cannot silently approve a `confirm` action.
- Mic permission and device selection documented.

Blocked/decision: Twi voice data/quality. Default: ship English, expose Twi as
best-effort with a clear fallback.

## Phase 4 — dashboard + PWA — **planned**

Scope:

- Next.js 15 App Router + TypeScript + Tailwind.
- HUD: agent status, active run/steps, memory, logs, resource use, tool
  permissions, conversation history, kill switch, approval inbox.
- PWA: installable, mobile layout, offline shell; no fake data.
- Live updates via SSE or WebSocket; typed API client.
- Playwright E2E for run, approval, memory edit/delete, kill switch.

Acceptance:

- Dashboard reflects real backend state and survives refresh.
- Approval action is explicit and shows tool + args.
- Playwright passes against a local backend.
- Lighthouse/PWA install check documented.

## Phase 5 — automation + integrations — **planned**

Scope:

- Scheduler and routines ("good morning" chain), event triggers, interrupt
  budget for proactivity.
- Calendar/email (OAuth), smart home (MQTT/Home Assistant), Telegram/WhatsApp,
  finance tracker, daily briefing/news, vision (camera/screen OCR/description).
- Redis event bus/worker when Docker is available; Compose stack.
- Per-feature cloud toggles.

Acceptance:

- Every integration has a real credential path, permission tier, rate limit,
  audit entry, and failure mode.
- Routines are idempotent and cancellable.
- Proactivity respects a user-set budget and quiet hours.
- No integration ships with a mocked success path.

Blocked/decision: OAuth apps, Telegram/WhatsApp credentials, MQTT broker,
camera access. Default: implement local-first pieces and leave credential-gated
integrations disabled with a clear setup message.

## Phase 6 — hardening, tests, Docker, docs — **planned**

Scope:

- Sandboxed code execution (Job Objects/container, filesystem allowlist,
  network policy, CPU/memory/time limits) before any code/system skill ships.
- Key rotation/re-encryption, OS keyring/vault, TLS guidance, audit anchoring,
  retention/backup tooling.
- Redis rate limits, dependency/container scanning, CI, coverage, mypy/pyright.
- Docker Compose (backend + Redis + optional Postgres/pgvector + frontend).
- Full docs, threat-model review per integration.

Acceptance:

- `docker compose up` works on a machine with Docker.
- Sandbox escape tests and denial-path tests pass.
- Backup/restore and key-rotation drills documented.
- CI runs lint, types, unit, and Playwright tests.

Blocked: Docker is not installed on this machine. Compose files can be authored
and validated statically, but not run here.

## Decisions needed (ask once, with defaults)

| Decision | Default if no answer |
|---|---|
| Anthropic key for cloud planning | Stay on local Ollama |
| Pull `nomic-embed-text` (~274 MB) | Lexical search; warn in doctor |
| Google/Microsoft OAuth for calendar/email | Skip; local notes/reminders first |
| Telegram/WhatsApp credentials | Skip; no outbound messaging |
| MQTT/Home Assistant broker | Skip; no smart-home control |
| Twi voice data | English first; Twi best-effort |
| Camera/mic permissions | Ask at Phase 3/5 runtime, not now |

## Definition of done for every phase

1. Code is typed, modular, and has no placeholder success paths.
2. Tests cover success, denial, timeout, and malformed input.
3. `pytest` and `ruff` pass.
4. Security review: permission tier, secrets, audit, injection, kill switch.
5. Docs updated: config, API/manifest, failure modes, known gaps.
6. A live smoke test demonstrates the phase's main path.
