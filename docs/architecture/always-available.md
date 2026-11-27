# Always-available JARVIS — gap analysis and plan

_Started 2026-11-27. This document is the plan the mission asked for before any
code was changed. It records what already exists, what is genuinely missing, and
the order in which the gaps get closed. Status lines are updated as work lands;
nothing here is marked done until a test or a live probe proves it._

## Rule used throughout

Every capability is reported from a runtime probe, never from a config flag or a
stored key. A feature with no backend is listed in `capabilities.UNIMPLEMENTED`
and shown as unavailable in the dashboard. A phone line, a PC bridge or an
integration that has no credentials reports `not_configured` with the exact
missing variable names.

## What the mission asks for vs. what exists

| Mission requirement | Current state on this machine | Gap |
| --- | --- | --- |
| Call JARVIS on a real number | `jarvis.telephony` gateway: Twilio signatures, TwiML, inbound/turn/poll flow, outbound Calls API, approval-gated `phone.call` tool | Needs a Twilio account, a number and a public HTTPS tunnel; no live call has been placed |
| Natural real-time voice conversation | Twilio speech recognition + `<Say>` TTS through `<Gather>`; the agent loop answers each turn | Barge-in and streaming audio are provider features not yet enabled; no local STT/TTS in the core |
| Conversation context across sessions | Core memory store + per-call transcript in `CallState` | Phone turns do not yet write durable memories; call transcripts are in-memory only |
| Connect JARVIS to the Windows PC remotely | Read-only `system.info` / `system.metrics` in the core; real mouse/keyboard only in the legacy `app.py` PC CONTROL runtime | Authenticated, approval-gated PC bridge is unbuilt (`desktop_control` stays in `UNIMPLEMENTED`) |
| Check whether the PC is online | Legacy `/api/health` on port 8765; core `/health` on 8767 | No remote reachability check with auth from outside the LAN |
| Execute approved computer tasks | `shell.run`, `files.write` (both `CONFIRM` + `dangerous`), real browser, vision | Launching applications and window control are not exposed to the core |
| Run PowerShell with permissions | `shell.run` allowlist accepts `python`, `pip-audit`, `pytest`, `node`, `npm`, `npx`, `git`, `ruff`, `echo`, `where` | `powershell` is deliberately not allowlisted; adding it needs a scoped, reviewed design |
| Monitor task execution and report results | Agent runs, planner/critic, audit log, `/agent/runs`, phone poll loop | Nothing missing structurally; voice reporting of long jobs is bounded by the call |
| Specialist agents integrated | 10 specialists + orchestrator, each role-scoped over the same loop, status from probes | Desktop and Creative remain `partial` (no control backend, no generation backend) |
| Delegate, monitor, handle failures, verify | `agent.delegate` with depth limit; critic agent; `spoken_result` reports failure honestly | No retry policy per specialist beyond the loop's replans |
| Email reading and drafting | IMAP source connector, `email.draft`, approval-gated `email.send` | No credentials configured; send path never exercised on this machine |
| Web research | `web.search` (Brave key needed), `web.read`, browser agent | Brave key absent, so research is `partial` |
| Long-term memory | Encrypted memory store, embeddings, memory agent | Working; not yet written from phone calls |
| PDF and document creation | `report.generate` writes Markdown | **No PDF writer**; mission explicitly asks for PDF |
| File uploads and downloads | `files.write` (text, bounded), connectors read files | No binary upload/download endpoint |
| Computer control | Legacy only | Not bridged to the core |
| Video editing | Nothing | No backend, no plan yet (`creative_gen` unimplemented) |
| Image generation | Nothing | No backend (`creative_gen` unimplemented) |
| Workflow automation | Visual Workflow Studio → `/workflow/runs`, real node execution | Working |
| Connected application management | `/connectors`, 8 sources, allowlist | Working; credentials missing for 4 sources |
| STT / TTS / VAD / interruptible voice | Legacy `app.py`: Kokoro TTS, faster-whisper STT, browser wake word | Core has no voice; phone path uses Twilio speech + `<Say>` |
| Authenticate phone and remote connections | Twilio HMAC-SHA1 signatures, caller allowlist, API bearer token | Remote PC bridge still to build |
| Never expose PC control publicly | PC control not exposed by the core at all | Correct today, and must stay true when the bridge lands |
| Approval for sensitive actions | `PermissionTier.CONFIRM` + `dangerous` on shell, file write, email send, report write, phone call | Working |
| Protect API keys | `SecretStr` settings, `.env`, scrubbed child environment | Working |
| Audit log of actions | Hash-chained audit log; telephony refusals and runs audited | Working |
| Never pretend a task succeeded | Tool results, probe-driven statuses, honest spoken outcomes | Working |

## Phases

### Phase 1 — phone line (in progress, code landed)

Delivered in `backend/src/jarvis/telephony/`:

- `base.py` — `CallState`, `TelephonyError`, `TelephonyProvider` protocol, so a
  second vendor is an adapter rather than a rewrite.
- `twilio.py` — request signature (HMAC-SHA1, verified against Twilio's
  published example), TwiML builder with escaping, Calls REST API with the real
  error body surfaced.
- `gateway.py` — signature + caller-allowlist authorisation, greeting, turn
  delegation, poll loop with an honest give-up, outbound dialling in E.164.
- `routes.py` — public `/telephony/{voice,turn,poll}` webhooks (signature
  authenticated, no bearer token, `403` on refusal) and token-protected
  `/api/v1/telephony/{status,calls}`.
- `tool.py` — `phone.call`, `CONFIRM` + `dangerous`, so the agent can reach the
  user but never dial silently.
- `capabilities.probe_telephony` — verifies the Twilio account answers, not just
  that a token is present.

Still required before a real call can be demonstrated:

1. `JARVIS_TELEPHONY_PROVIDER=twilio`
2. `JARVIS_TWILIO_ACCOUNT_SID`, `JARVIS_TWILIO_AUTH_TOKEN`, `JARVIS_TWILIO_FROM_NUMBER`
3. A public HTTPS base URL in `JARVIS_TELEPHONY_PUBLIC_BASE_URL` (tunnel or
   reverse proxy; the core stays on loopback)
4. The caller's number in `JARVIS_TELEPHONY_ALLOWED_CALLERS`
5. Twilio console: voice webhook → `POST {base}/telephony/voice`

Costs: a Twilio number and per-minute call charges. Nothing else in this phase
is paid.

### Phase 2 — authenticated PC bridge

Goal: the phone can ask for an approved PC action and get the real result.

- A bridge process on the PC that dials *out* to the core over an authenticated
  channel, so no inbound port is opened. Reuse the legacy `app.py` control code
  behind an allowlist of verbs (`open_app`, `window_focus`, `screenshot`,
  `clipboard_read`, `type_text`, `key_press`).
- Every verb is `CONFIRM` + `dangerous`, audited, and reports a real exit state.
- `probe_runtime` gets a `desktop_control` probe that fails closed when the
  bridge is not connected; `UNIMPLEMENTED` loses the entry only then.

### Phase 3 — documents and files

- `document.pdf` tool: real PDF bytes written to the reports directory, with a
  test that parses the output back.
- Binary upload/download for the dashboard, bounded and root-confined.
- `report.generate` keeps writing Markdown; PDF is an additional format.

### Phase 4 — creative backends

- Image generation through a local model or an explicitly configured API; the
  Creative Agent stays `partial` until one is wired and probed.
- Video editing is scoped only after the image path exists; no placeholder.

### Phase 5 — voice in the core

- Move Kokoro TTS / faster-whisper STT out of the legacy runtime into a core
  voice service with VAD and barge-in, then let the phone path use local voice
  instead of provider speech where latency allows.

## Acceptance tests from the mission

| Test | Status |
| --- | --- |
| Call JARVIS from a phone | Blocked on Twilio credentials and a public URL; webhook flow tested locally |
| JARVIS answers with voice | TwiML + `<Say>` tested; not yet heard on a real call |
| Remote access to the PC agent | Not built (Phase 2) |
| Request a PC action by voice | Not built (Phase 2) |
| Delegate to specialist agents | Working and tested |
| Read and draft email | Implemented; blocked on IMAP/SMTP credentials |
| Create and deliver a PDF | Not built (Phase 3) |
| Remember conversation context | Memory store works; phone turns do not persist yet |
| Verify results of executed tasks | Working: tool results, critic, honest spoken outcomes |

## Test evidence for Phase 1

`backend/tests/test_telephony.py` — 21 tests, all passing, no network:

- Twilio's published signature vector, tampering and wrong-token rejection
- TwiML escaping, gather/redirect/hangup shape
- missing-setting reporting, empty caller allowlist treated as unconfigured
- `403` for bad signatures and unauthorised callers, `200` for an allowed caller
- a turn is delegated, then read back through the poll loop
- empty transcript re-prompts; slow run is abandoned; timed-out run says so
- `spoken_result` is honest for completed/approval/failed/cancelled
- outbound E.164 validation and the exact Twilio REST payload (mocked transport)
- `phone.call` is `CONFIRM` + `dangerous`
- `/api/v1/telephony/status` reports the configured state
- `probe_telephony` reports the unconfigured state truthfully
