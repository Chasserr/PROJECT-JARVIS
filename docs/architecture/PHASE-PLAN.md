# JARVIS Engineering Plan

## Phase 0 — Architecture and migration plan
- [x] Define component boundaries, data model, API outline, skill manifest, event bus, security and failure paths.
- [x] Preserve the existing app as a compatibility service.
- [x] Record migration decisions and runtime baseline.

## Phase 1 — Core agent, CLI and memory (foundation implemented)
- [x] Typed task, permission and configuration models.
- [x] Local asynchronous event bus.
- [x] SQLite memory CRUD and audit-event foundation.
- [x] Provider-neutral chat protocol, OpenAI-compatible local adapter, Claude Messages API adapter and local fallback router (live Claude verification awaits an API key).
- [x] LLM planner and critic contracts; bounded agent execution loop and permission gate.
- [x] CLI for saving, listing and deleting memories.
- [x] FastAPI health, memory and planning endpoints.
- [x] pytest, Ruff and Python compile checks.
- [x] Bounded per-step retries, resumable one-time approval, durable task history and safe restart recovery.
- [x] End-to-end live planner and agent verification with the local LM Studio provider after this maintenance pass.
- [x] Encrypt memory content at rest with Windows DPAPI; migrate legacy plaintext rows on initialization.
- [ ] Encrypt credentials and review other sensitive metadata; add authenticated remote access, rate limits and sandbox hardening.

## Phase 2 — Tool and skill system
- [x] Versioned JSON skill-manifest loading and validation; runtime capability gates hide unavailable integrations.
- [x] Initial in-process registry for Raea media probe, read-only media analysis (loudness, motion, cuts, freezes) and approval-gated composition render, with strict argument allowlists, permission tiers and audit integration.
- [x] Manifest entries are declarative only; every enabled skill must map to an explicit trusted in-code handler. Planner and executor validate declared argument JSON types.
- [ ] Full OS sandbox and broader permission/security review; a low-integrity restricted-token worker is integrated for the pure-data `sandbox.text.stats` skill, with verified restricted token, 256 MB process-memory cap, one-process Job Object limit, kill-on-job-close and hard execution deadline. AppContainer launch was tested but Python could not be started inside it on this host; filesystem read and network isolation are not yet enforced.
- [x] Starter skills: reminders/tasks in the legacy dashboard, memory search, filesystem search, web search/page reading with SSRF protections, Windows app/status control.
- [x] Negative tests for unknown skills, unexpected arguments and declined approvals; sensitive desktop/browser/file actions now require approval and the kill switch blocks all tool execution.
- [x] Initial adversarial tests cover hostile user requests, hostile saved-memory content, malicious model output and web-page trust instructions; string and array arguments have strict size caps.
- [ ] Expand adversarial coverage across every skill, redirect chains, browser content and cross-task memory poisoning.
- [x] Bounded planner, tool and critic execution timeouts; tool concurrency is capped and automatic tool retries are disabled to prevent duplicate side effects after ambiguous failures.
- [x] Cross-skill security matrix verifies every manifest skill, sensitive-action approvals, high-impact policy defaults, kill-switch denial and rejection of runtime-code manifest fields.

## Phase 3 — Voice and browser workflows
- [x] Initial local Windows SAPI speech output and user-initiated bounded speech recognition.
- [x] Windows voice and installed speech-recognition language discovery; bounded dictation can select an installed culture and rejects unavailable languages, exposed through the core voice-options API.
- [x] Dedicated Playwright browser with navigation, tabs, snapshots, safe keyboard allowlist, non-sensitive form inspection/filling and protected actions.
- [ ] openWakeWord, Whisper STT and streaming TTS provider adapters.
- [x] Per-task cancellation API and cooperative stop between agent actions; an already-running tool is allowed to finish safely, while pending protected approvals can be cancelled without execution.
- [x] Windows audio endpoint discovery exposed through voice.options, including selectable PortAudio device indices.
- [x] Fifine microphone selected as JARVIS's only exposed microphone; Iriun and Camo are hidden from JARVIS (Windows drivers/apps remain installed).
- [x] Echo Dot selected for JARVIS speech output through per-device audio playback.
- [x] Voice playback interruption via POST /api/v1/voice/stop and the autonomous voice.stop skill; endpoint verified against the live core API.
- [x] User-facing language settings API with persisted recognition-language preference, installed-language validation and audit event; verified live with en-US.
- [ ] English baseline; evaluate Twi support with measured model quality before claiming support.

## Phase 4 — Dashboard
- [ ] Next.js + TypeScript + Tailwind HUD.
- [ ] Live task/event stream, permissions, logs, memory editor and resource telemetry.
- [ ] PWA installability and mobile regression against existing mobile dashboard.

## Phase 5 — Automation and integrations
- [ ] Scheduler, event triggers and routines.
- [ ] Calendar/email/notes/task providers, messaging, Home Assistant/MQTT, finance and briefing integrations.
- [x] Initial Raea creative-engine bridge verified for media metadata/analysis, approval-gated clip trimming/concatenation and composition rendering; broader timeline/export workflows remain open.
- [ ] Outbound and financial actions always require confirmation.

## Phase 6 — Security, reliability and deployment
- [x] Windows DPAPI encryption for memory content and migration of legacy plaintext memory rows.
- [x] Agent kill switch enforced by the policy gate; consequential desktop, browser and file actions require explicit approval.
- [ ] Encrypt credentials and sensitive metadata; complete audit review, rate limits, authenticated remote access and sandbox hardening.
- [ ] Docker Compose, optional Redis and vector store.
- [x] Current backend baseline: 101 pytest tests, Ruff, strict mypy and compileall all pass; maintenance notes documented.
- [ ] Full Playwright end-to-end suite, recovery expansion, security audit and deployment docs.

## Delivery rule
At the end of every phase: execute tests, report verified capabilities, list gaps, then continue unless a credential, external account, hardware permission or product decision blocks progress. Never report a planned integration as working.
