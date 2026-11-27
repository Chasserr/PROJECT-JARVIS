# JARVIS architecture

Status: **Phases 0–2 complete**; Phase 3 voice core shipped in the legacy desktop
runtime (not yet in the core); Phases 4–6 planned.
Last updated: 2026-11-27.

## 1. Intent

JARVIS is a local-first, voice-and-text personal AI operating assistant. It
plans multi-step work, calls typed tools, remembers durable facts, and asks for
human approval before destructive, financial, or outbound actions.

Design principles:

1. **Local by default.** The API binds loopback, the default model is local
   Ollama, and cloud providers require two explicit opt-ins.
2. **Least privilege.** Every tool declares a permission tier. The runtime, not
   the model, enforces it.
3. **Untrusted content stays data.** Web pages, files, emails, screenshots, and
   tool output are never treated as instructions.
4. **Everything important is inspectable.** Runs, tool calls, approvals, and
   memory changes are audited. Audit details are encrypted and hash-chained.
5. **No fake integrations.** A tool exists only when it has a real
   implementation, schema, timeout, and test.

## 2. Stack: requested vs. implemented

| Layer | Requested | Implemented now | Why |
|---|---|---|---|
| Core | Python 3.12 + FastAPI + asyncio | Python 3.12+ syntax, runs on 3.15; FastAPI 0.165, uvicorn 0.54 | 3.15 is the installed runtime; wheels verified |
| UI | Next.js + TypeScript + Tailwind | Phase 4 | Phase 1 is API + CLI first |
| LLM | Claude primary, Ollama fallback | Provider interface; Ollama `qwen3.5:2b` default; Anthropic client ready | No `ANTHROPIC_API_KEY` on this machine; local-first default |
| Memory | SQLite + Chroma/pgvector, encrypted | SQLite + AES-256-GCM; Ollama embeddings; lexical fallback | Chroma may lag 3.15; pgvector needs Postgres/Docker |
| Voice | openWakeWord + Whisper + Piper/ElevenLabs | Kokoro TTS + faster-whisper STT shipped in the legacy `app.py` runtime | Local-only path already works; wake word is still browser SpeechRecognition, and the core has no voice yet |
| Queue | Redis + Docker Compose | In-process async bus + SQLite durable outbox; Redis adapter Phase 5 | Docker and Redis are not installed |
| Deployment | Docker Compose | Local venv now; Compose authored but not runnable here | Docker absent |

These are deliberate substitutions, not silent omissions. Each has an adapter
seam so the requested component can replace it without rewriting callers.

## 3. System diagram

```
┌──────────────────────────────┐      ┌──────────────────────────────┐
│ CLI (`jarvis ask/chat/...`)   │      │ Next.js HUD + PWA (Phase 4)  │
└──────────────┬───────────────┘      └──────────────┬───────────────┘
               │                                     │ HTTP + optional Bearer
               └──────────────────┬──────────────────┘
                                  ▼
                       ┌─────────────────────┐
                       │ FastAPI (`/api/v1`) │
                       │ auth, schemas, CORS │
                       └──────────┬──────────┘
                                  ▼
                       ┌─────────────────────┐
                       │ AgentLoop           │
                       │ planner → executor  │
                       │        → critic     │
                       └───┬─────────┬───────┘
                           │         │
             ┌─────────────▼──┐   ┌──▼──────────────────┐
             │ ToolRegistry   │   │ MemoryStore         │
             │ schema + tier  │   │ encrypted facts     │
             │ timeout + audit│   │ + episodes + search │
             └───────┬────────┘   └──────────┬──────────┘
                     │                       │
        ┌────────────▼───────────┐  ┌────────▼─────────────┐
        │ Built-in tools / skills│  │ SQLite (WAL)         │
        │ time, memory, system   │  │ memories, runs,      │
        │ Phase 2: web, files... │  │ audit, outbox        │
        └────────────────────────┘  └────────┬─────────────┘
                                             │
                                  ┌──────────▼──────────┐
                                  │ SecretBox AES-256-GCM│
                                  │ key: env or file     │
                                  └─────────────────────┘

Cross-cutting: AuditLog (hash chain), EventBus (SQLite outbox), Settings.
```

## 4. A run, end to end

1. A caller submits `POST /api/v1/agent/runs` or runs `jarvis ask`.
2. The runtime rejects the request if the global kill switch is engaged.
3. `AgentLoop` creates a durable run row and emits `run.started`.
4. `Planner` sends the goal plus the real tool specs to the LLM in JSON mode.
5. The plan is validated against the registry: known tool, JSON Schema args,
   step limit. Invalid plans get one corrective retry.
6. `ToolRegistry` validates args again, resolves the effective permission tier,
   applies a timeout, and executes. Every call is audited and emits
   `tool.called`.
7. A `confirm` tool raises `ApprovalRequired`. The run is persisted as
   `awaiting_approval`; the API returns HTTP 409 with the exact tool, args,
   permission, and signature. The CLI prompts in the terminal.
8. `resume(approved=true)` executes only that approved step, then continues.
9. `Critic` reviews the results. If incomplete and budget remains, `Planner`
   replans with the critique. Otherwise the run completes or fails.
10. `Answer` is generated from the goal and results. Run state is encrypted at
    rest; `run.completed` or `run.failed` is emitted.

## 5. Folder tree

```
PROJECT-JARVIS-main/
├─ app.py, web/, *.ps1, *.bat          # legacy app, untouched during migration
├─ backend/
│  ├─ pyproject.toml
│  ├─ .env.example
│  ├─ README.md
│  ├─ src/jarvis/
│  │  ├─ config.py                     # typed JARVIS_* settings
│  │  ├─ container.py                  # composition root
│  │  ├─ db.py                         # SQLite schema + connections
│  │  ├─ events.py                     # EventBus + durable outbox
│  │  ├─ cli.py                        # ask/chat/memory/tools/audit/doctor/serve
│  │  ├─ agent/
│  │  │  ├─ models.py                  # Plan, StepRecord, RunResult, Approval
│  │  │  ├─ prompts.py                 # injection-resistant prompts
│  │  │  ├─ planner.py                 # JSON plan + validation + retry
│  │  │  ├─ critic.py                  # completion review + fallback
│  │  │  └─ loop.py                    # durable execute/replan/approve loop
│  │  ├─ api/
│  │  │  ├─ app.py                     # FastAPI factory, auth, routes
│  │  │  ├─ ratelimit.py               # per-IP sliding window
│  │  │  └─ schemas.py
│  │  ├─ llm/
│  │  │  ├─ base.py                    # provider-neutral messages/response
│  │  │  ├─ ollama.py                  # native /api/chat
│  │  │  ├─ anthropic.py               # Messages API, cloud opt-in
│  │  │  └─ factory.py
│  │  ├─ memory/
│  │  │  ├─ models.py                  # Memory, float32 vectors, cosine
│  │  │  ├─ embeddings.py              # Ollama embeddings
│  │  │  └─ store.py                   # encrypted CRUD/search/episodes
│  │  ├─ security/
│  │  │  ├─ crypto.py                  # AES-256-GCM SecretBox
│  │  │  ├─ audit.py                   # encrypted, hash-chained log
│  │  │  ├─ kill_switch.py             # persistent global stop
│  │  │  └─ permissions.py             # read_only/confirm/autonomous
│  │  ├─ net/
│  │  │  └─ safe_fetch.py              # SSRF guard + bounded text extraction
│  │  ├─ notes/                        # encrypted note store/models
│  │  ├─ reminders/                    # encrypted reminder store/models
│  │  ├─ skills/
│  │  │  ├─ loader.py                  # manifest + entry validation
│  │  │  ├─ web_search.py              # Brave client
│  │  │  ├─ web_read.py                # safe URL reader
│  │  │  ├─ files.py                   # allowlisted filename search
│  │  │  ├─ notes_tools.py
│  │  │  └─ reminders_tools.py
│  │  └─ tools/
│  │     ├─ manifest.py                # schema + permission boundary
│  │     ├─ registry.py                # validation, timeout, audit, events
│  │     └─ builtin.py                 # time, memory.*, system.info
│  ├─ skills/                          # 11 skill packages (manifest + skill.py)
│  └─ tests/                           # 67 passing tests
├─ docs/architecture/                  # this Phase 0 set
├─ frontend/                           # Phase 4 (Next.js)
└─ docker-compose.yml                  # Phase 6 (not runnable without Docker)
```

## 6. Security invariants

- API binds `127.0.0.1`; optional Bearer token with constant-time comparison.
- No wildcard CORS. CORS is disabled unless explicitly configured.
- Every tool has a manifest, JSON Schema, timeout, and permission tier.
- `dangerous: true` cannot be autonomous (manifest validation rejects it).
- Permission overrides can downgrade freely; upgrades require an explicit flag.
- `confirm` actions pause the run. The approval signature binds tool + exact args.
- A persistent global kill switch blocks new runs/resumes and is checked between
  steps; the API returns 423 while engaged.
- `/api/*` is rate-limited per client IP (in-memory in Phase 1).
- Memory, episodes, run state, and audit details use AES-256-GCM with unique
  nonces and authenticated context labels (`memory`, `episode`, `run`, `audit`).
- Audit entries form a SHA-256 hash chain; `jarvis audit verify` detects edits.
- Prompts label tool output as untrusted data. The planner never sees tool output
  as instructions; the critic and answer prompts repeat the rule.
- Secrets come from env or the key file; args are redacted in audit details.
- No shell execution, arbitrary file access, or network tool exists in Phase 1.

See [security.md](security.md) for the threat model and residual risks.

## 7. Non-goals for Phase 1

- Voice wake word, STT, TTS.
- Dashboard/PWA.
- Scheduled jobs, routines, proactivity.
- WhatsApp/Telegram, smart home, email/calendar.
- Code execution and system control (these need a sandbox and a separate
  permission design before they can be safe).
- Multi-user accounts. Phase 1 is a single local operator.
