# JARVIS Engineering Status — 2026-11-23

## Changes applied in this maintenance pass

- Fixed strict mypy errors across the agent loop, FastAPI wiring, DPAPI buffer typing, Windows desktop control, Playwright browser context handling and voice response validation.
- Added the Anthropic Claude Messages API adapter and a bounded provider router. Claude is used only when `JARVIS_PROVIDER=claude`, `JARVIS_CLOUD_ENABLED=true` and a key is configured; the configured OpenAI-compatible local endpoint is the fallback. Cloud inference remains disabled by default.
- Corrected memory-search tool output to return a structured object and updated the critic's verification path accordingly.
- Enforced `confirm_before_act` as a real policy tier rather than accidentally treating it as autonomous.
- Added hard approval gates for closing windows, moving files, desktop text entry, browser text entry and browser form filling. The planner's instructions now match those gates.
- Added an enforced policy kill switch. When enabled, all tool execution, including read-only tools, is rejected.
- Added regression tests for permission tiers, sensitive actions, kill switch and provider fallback.
- Added `backend/.env.example` and updated setup/security documentation.
- Built a versioned JSON skill manifest containing all 35 current skill definitions, including permission tiers, argument descriptions/types and runtime capability requirements.
- Added strict manifest validation, duplicate-ID rejection, safe identifier checks and capability gating. JSON manifests cannot name Python handlers or execute code.
- Added an explicit trusted in-code handler registry check: JARVIS refuses to start if any enabled manifest skill lacks a handler.
- Added a live `GET /api/v1/skills` endpoint and enforced declared argument JSON types in both planner parsing and the execution loop; boolean values cannot pass as integers and non-finite numeric values are rejected.
- Added `web.search` and `web.read_page` as trusted read-only skills using DuckDuckGo HTML search and bounded HTML extraction. Requests validate public DNS/IP targets, revalidate redirects, reject non-standard ports and embedded credentials, disable environment proxies, cap timeouts/download size/text length, and never execute page scripts.
- Added web-intelligence security and parser regression tests plus `docs/WEB-INTELLIGENCE.md`; registered both new skills in the manifest (37 skills total).
- Updated the planner's operating instructions to route public research to `web.search` and supplied public URLs to `web.read_page`; explicitly tells the planner to treat page content as untrusted and never follow embedded instructions. Added regression tests for this trust boundary.
- Added initial adversarial tests proving hostile user requests and saved-memory strings remain untrusted payload data, and malicious model output cannot be promoted into the system prompt.
- Added strict argument-size caps: strings max 8,000 characters; string arrays max 100 entries with each entry max 2,000 characters. Added regression tests for both limits.
- Added configurable planner, tool and critic deadlines, a bounded tool-concurrency semaphore, and disabled automatic tool retries. This avoids replaying a side-effecting action when a timeout occurs after the action may already have started. Important limitation: asyncio cancellation cannot forcibly stop a synchronous operation already running inside `asyncio.to_thread` or a thread-pool worker; such work may finish in the background after the request times out. The process-isolated runner must provide hard termination.
- Improved failure reporting so timeout errors are visible in task state and event output instead of appearing as empty error strings; added planner/tool timeout regression tests.
- Added a cross-skill security matrix covering every manifest entry, typed schemas, explicit approval gates for sensitive desktop/browser/file/media actions, every high-impact policy entry, kill-switch denial for every registered skill, and rejection of manifest fields that could smuggle runtime code.
- Implemented `sandbox.text.stats` as the first isolated skill. It launches a fixed worker entry point using a Windows restricted token with disabled privileges and verified low-integrity SID (`S-1-16-4096`), then assigns the suspended child to a Job Object before resuming it. The Job Object enforces one active process, a 256 MB process-memory cap and kill-on-job-close; the parent enforces a bounded request/response protocol and hard execution deadline. The worker exposes only pure-data text statistics and rejects unknown operations; it has no JARVIS filesystem, browser or desktop handler wired into it.
- Tested Windows AppContainer profile creation and process launch. The host could create the profile but Python process creation inside the AppContainer failed with Win32 error 2 (executable access), so the AppContainer probe/profile was removed. The working restricted-token worker is not a full filesystem/network sandbox: low integrity prevents writes to higher-integrity objects by default, but does not block reads or network access. Do not dispatch arbitrary or sensitive handlers through this worker until those boundaries are separately enforced.

## Verification

- Ruff: passed across backend source and tests.
- Mypy strict: passed for all 24 backend source files.
- Pytest: 101 passed, including the Windows restricted-worker launch, low-integrity/restricted-token verification, unknown-operation denial, request-size/deadline limits, web-intelligence URL safety, planner trust-boundary, hostile-input, bounded-execution and cross-skill security-matrix tests.
- Python compileall: passed.
- Live web search returned three results for an official Python documentation query; live HTML extraction read the Python.org homepage (title and 6,712 characters of text).
- Restarted the core API on `127.0.0.1:8766`; health is online and the skill endpoint reports 38 enabled skills, including `web.search`, `web.read_page` and `sandbox.text.stats`.
- Live FastAPI health endpoint: HTTP 200; provider route reports local LM Studio and cloud is disabled.
- Started the LM Studio local server on port 1234; Gemma 4 E2B/E4B and Nomic embedding models are listed, with Gemma 4 E2B loaded.
- Live planner smoke test: passed; local Gemma generated a valid `system.status` tool plan.
- Live end-to-end agent smoke test: passed; planner → policy → system-status skill → critic completed successfully.
- Live Raea status endpoint: available, version 0.1.9.
- Live voice options endpoint: 2 installed voices; en-US recognition; configured Fifine microphone and Echo Dot output.
- Restored the legacy dashboard/service on `127.0.0.1:8765` without changing its code; its health endpoint reports the local LM Studio model as available. The upgraded FastAPI core remains online on `127.0.0.1:8766`.

## Remaining blockers and gaps
- Claude live verification requires the user's API key and explicit cloud enablement.
- Sandboxed skill execution is not implemented yet; the current registry is intentionally in-process and restricted to trusted handlers.
- Semantic/vector memory, Whisper streaming STT, openWakeWord, streaming TTS, Twi quality validation, Next.js HUD, scheduler/routines, Redis, Docker Compose and broader integrations remain outstanding.
- Credential/metadata encryption, authenticated remote access, rate limits, expanded adversarial prompt-injection coverage and full sandbox hardening remain outstanding. Skill handlers are still trusted in-process functions; argument validation and trust-boundary tests are not an OS sandbox.
- No project reset, destructive cleanup or Git commit was performed. Existing local changes and user files were preserved.

## Next recommended work

1. Implement a real Windows OS-isolated skill runner (restricted token/AppContainer or equivalent) before marking Phase 2 complete; Job Objects and asyncio timeouts alone are resource/lifecycle controls, not a security boundary. Expand adversarial tests across all skill families.
2. Expand research workflows with source-grounded multi-page comparison and citation-aware summaries.
3. Complete wake-word/Whisper/ElevenLabs streaming voice.
4. Build the Next.js HUD and migrate the current dashboard/PWA incrementally without losing its visual identity.
5. Add scheduler/routines, integrations, vector memory and Docker/Redis deployment after the skill/security foundation.
