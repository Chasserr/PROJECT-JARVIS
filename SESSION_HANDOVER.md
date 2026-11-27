# JARVIS — Session Handover

Last updated: 2026-11-27
Status: **voice-first assistant with real connectors, approval-gated actions, code/shell/browser
execution and a live visual interface.** Three agent capabilities remain honestly blocked
(dependency scanner, desktop control, creative generation) because no implementation exists.

Everything marked *Verified* below was executed on this machine during this session. Anything
not marked that way is a plan or an assumption. The work is committed locally in five logical
commits; the repository still has no remote, so nothing has been pushed.

---

## 1. Architecture (unchanged in shape)

| Layer | Runtime | Port | Role |
|---|---|---|---|
| Dashboard + legacy tools | `app.py` (Python `http.server`) | 8765 | Serves `web/`, PC control, camera, voice, Spotify, app catalogue |
| Agent core | `backend/` (`jarvis.cli serve`, FastAPI) | 8767 | Agent runs, tools, memory, audit, approvals, connectors |
| Model runtime | Ollama | 11434 | Local models, including the working vision model |
| Agent provider | OpenJarvis | 8000 | OpenAI-compatible chat backend for the planner |

The dashboard proxies to the core through `/api/core/*` (`core_request`, bearer token from
`backend/.env`). The dashboard serves `web/` from `ROOT/"web"` per request, so **frontend edits
are live without a restart**; backend edits need the core restarted (see §10).

One orchestrator (`AgentLoop`) plus ten specialists. Delegation is `agent.delegate`, which starts
a role-scoped run through the *same* loop, so specialists inherit audit, permission tiers,
approvals, encrypted memory, event bus and kill switch. Specialists cannot delegate
(`max_depth = 1`).

### New in this session: connectors and an action layer

```
web/ ── /api/core/connectors[/search] ─┐
                                      ├─ app.py proxy ─► core /api/v1/connectors
backend: ConnectorRegistry            ┘
   ├─ memory        (internal, no credentials)
   ├─ local_files   (needs JARVIS_FILE_SEARCH_ROOTS)
   ├─ project_repo  (needs JARVIS_PROJECT_ROOT)
   ├─ obsidian      (needs JARVIS_OBSIDIAN_VAULT)
   ├─ web           (needs JARVIS_BRAVE_API_KEY)
   ├─ github        (needs JARVIS_GITHUB_TOKEN)
   ├─ supabase      (needs URL + key + table allowlist)
   └─ email         (IMAP, needs host/user/password)
```

Every connector reports `connected` / `not_configured` / `error` from its own configuration, and
a fan-out search records a failure per source instead of losing the successful hits. Each hit
carries `source` + `locator` + `untrusted: true` for attribution.

---

## 2. Completed and Verified

### 2.1 Voice-first loop — Verified end to end

| Step | Evidence |
|---|---|
| TTS (Kokoro, `af_bella`, local) | `POST /api/voice/speak` → `200`, 602 444-byte WAV |
| STT (faster-whisper `tiny`, local) | `POST /api/voice/transcribe` on that exact WAV → `{"text": "Jarvis Voice loop verification. The quick brown fox jumps over the lazy dog.", "provider": "faster-whisper", "model": "tiny", "local": true}` |

Speech → audio → transcript round trip, no cloud service involved. The dashboard still drives the
conversation through `/api/core/chat` (streaming handled in `web/app.js`), so a spoken reply is
produced by the same core that answers typed messages.

### 2.2 Vision and camera — Verified

- `backend/src/jarvis/tools/vision.py`: `OllamaVision` client, image decoding (inline base64 or
  approved path), MIME sniffing, size limits, `probe_vision`.
- Tool `vision.analyze` (READ_ONLY) on the `research`, `browser`, `desktop`, `creative` roles.
- `POST /api/v1/vision/analyze` (core) and `POST /api/core/vision` (dashboard proxy).
- Proof real pixels reach the model: red circle → `A red circle`, blue square → `A dark blue
  square`, green triangle → `Green triangle`, no image → `No image provided.`
- **Camera endpoint was broken and is now fixed.** `app.py` compared
  `raw.startswith(b"\\xff\\xd8")` (literal text) so `/api/camera/analyze` returned `415` for every
  frame. After the fix: `200` in 3.7 s, `{"description":"Red circle.","model":"qwen3.5:4b-8k"}`.

### 2.3 Data-source connectivity — Verified

`GET /api/core/connectors` on the live system:

| Source | State | Why |
|---|---|---|
| memory | **connected** | internal store |
| local_files | **connected** | `JARVIS_FILE_SEARCH_ROOTS` = Documents |
| project_repo | **connected** | `JARVIS_PROJECT_ROOT` = this repository |
| web | **connected** | Brave key configured |
| github | not_configured | `JARVIS_GITHUB_TOKEN` not set |
| supabase | not_configured | URL/key/tables not set |
| obsidian | not_configured | `JARVIS_OBSIDIAN_VAULT` not set |
| email | not_configured | IMAP host/user/password not set |

`POST /api/core/connectors/search {"query":"jarvis","limit":3}` → **22 attributed hits, 0 errors**
across `local_files` (5), `memory` (1), `project_repo` (8), `web` (8).

### 2.4 Action execution — Verified, with confirmation

| Tool | Tier | Verified result |
|---|---|---|
| `email.draft` | read-only | returns `status: draft`, `sent: false` |
| `email.send` | **confirm + dangerous** | unapproved call raises `ApprovalRequired`; approved call with no SMTP returns `SMTP is not configured` instead of pretending to send |
| `report.generate` | **confirm** | writes a real Markdown file under `data/reports/`, returns path and byte count |

`email.draft` validates addresses and caps recipients; `email.send` only ever runs after an
approval, and reports the SMTP failure honestly.

### 2.5 Code / shell / browser execution — Verified

New tools in `backend/src/jarvis/tools/execution.py`:

- **`shell.run`** (confirm + dangerous) — argv list only (never `shell=True`), allowlisted
  executables, cwd must be inside the project root, scrubbed environment (no `JARVIS_*` secrets),
  hard timeout, truncated output. Verified: `print(6*7)` → exit `0`, stdout `42`.
- **`files.write`** (confirm + dangerous) — writes only inside authorised roots, refuses `.git`,
  1 MB cap. Verified: wrote a real nested file and removed it afterwards.
- **`browser.open`** (read-only) — real headless Chromium via Playwright, host must be on
  `JARVIS_BROWSER_ALLOWED_DOMAINS`, private/loopback hosts refused. Verified:
  `https://example.com/` → `title: "Example Domain"` and real body text.

These are what flipped Engineer, Testing and Browser from `partial` to `connected`.

### 2.6 Dynamic visual interface — Verified in the browser

`web/viz.js` + `web/viz.css`, opened from the new **Visuals** rail button. Every mark comes from a
live request — there is no decorative animation.

- Agent constellation (SVG): orchestrator core plus 10 specialist nodes coloured by probe status,
  edges highlighted for the role of a live run.
- Tool surface: per-agent available-tool bars from `/api/core/tools`.
- Data sources: real connector states from `/api/core/connectors`.
- Recent runs: status chips and step counts from `/api/core/runs`.
- Runtime: provider, model, memory count, tool count, connected-source count from `/api/health`.

Rendered check in the local browser: 5 cards, 11 nodes, 8 sources, 11 bars, 30 tools, 4 live
sources, **no console errors and no failed requests**. Refreshes every 30 s only while open;
animations stop under `prefers-reduced-motion`.

### 2.7 Honest agent status — unchanged rule, now more agents qualify

- `backend/src/jarvis/capabilities.py` probes: Ollama, Brave, vision round-trip, **shell
  execution**, **writable root**, **Chromium launch**.
- A role is `connected` only when every allowlisted tool exists *and* every declared capability
  passes a live probe. Missing implementation is `partial`, never `connected`.

### 2.8 Workflow Studio can return Home — Verified

`#wsHome` ("← Home") in the Studio top bar, shared `closeStudio()` with the original close control,
Escape closes, rail resets to Chat. The old close button rendered blank because `index.html` holds
mojibake glyphs, which is why the new control is text-labelled.

---

## 3. Agent status — measured, not declared

`GET /api/core/agents` on the live system (probes cached 300 s):

| # | Agent | Status | Reason if partial |
|---|---|---|---|
| 1 | Chief Orchestrator | **connected** | |
| 2 | Software Engineer | **connected** | shell + file-write probes pass |
| 3 | Research Agent | **connected** | Brave probe answered |
| 4 | Security Agent | partial | no dependency/vulnerability scanner |
| 5 | Testing Agent | **connected** | shell probe passes |
| 6 | Browser Agent | **connected** | Chromium launch probe passes |
| 7 | Desktop Agent | partial | mouse/keyboard control lives only in the legacy runtime |
| 8 | Creative Agent | partial | no image/video generation backend |
| 9 | Memory Agent | **connected** | |
| 10 | Critic Agent | **connected** | |
| 11 | Documentation Agent | **connected** | |

8 connected / 3 partial (previously 5 / 6).

---

## 4. Tests

`backend/.venv/Scripts/python.exe -m pytest` → **168 passed**.

New this session:

- `backend/tests/test_connectors.py` — filename vs content search, text-only reads, root-escape
  refusal, binary refusal, `node_modules` skipping, Obsidian tags, failure isolation, attribution
  filtering, allowlist denial, "nothing authorised" note.
- `backend/tests/test_actions.py` — draft never claims to send, address validation, approval
  required before any side effect, missing-SMTP honesty, report file contents and byte count.
- `backend/tests/test_execution.py` — allowlisted command runs, approval required, unlisted
  command refused, cwd escape refused, file write inside root, escape and `.git` refused, private
  host blocked, un-allowlisted domain refused, new tools present on the right roles.
- `backend/tests/test_api.py` — `/api/v1/connectors` real states, `/api/v1/connectors/search`
  attributed and untrusted-marked hits.
- `backend/tests/test_vision.py` — updated: `code_edit`/`shell`/`browser_automation` are no longer
  declared unimplemented.

Lint: `ruff check src tests` → only the pre-existing `SIM112 SystemDrive` at
`backend/src/jarvis/tools/builtin.py:97`.

---

## 5. Files changed

New:
- `backend/src/jarvis/connectors/{__init__,base,registry,internal,local,remote}.py`
- `backend/src/jarvis/tools/{sources,actions,execution,vision}.py`
- `backend/src/jarvis/capabilities.py`
- `backend/tests/{test_connectors,test_actions,test_execution,test_vision}.py`
- `web/viz.js`, `web/viz.css`

Modified:
- `backend/src/jarvis/config.py` — connector, email, shell, browsing and report settings
- `backend/src/jarvis/container.py` — build connectors, register action/execution/source tools
- `backend/src/jarvis/agent/team.py` — new tools on engineer/research/security/testing/browser/creative
- `backend/src/jarvis/api/app.py` + `schemas.py` — `/connectors`, `/connectors/search`, `/connectors/read`
- `backend/tests/conftest.py` — probes off in tests
- `backend/tests/test_api.py`, `backend/tests/test_dashboard_agents_panel.py` — new endpoints, Visuals rail label
- `app.py` — camera magic-byte fix, `/api/core/vision`, `/api/core/connectors[/search]`
- `web/index.html` — Visuals rail button, `viz.css`/`viz.js` tags, Studio Home button
- `web/workflow-studio.js`, `web/workflow-studio.css` — Studio Home/Escape close
- `web/tools-agents.js` — render probe-derived `status`/`status_detail`
- `.gitignore` — ignore `/data/` (database, master key, generated reports)

Review pass before committing removed only dead weight: the unused `_host_of` helper in
`connectors/remote.py`, `getattr(...)` fallbacks for settings and notes that are typed and always
present, the unused `Container.notes` field, an unused parameter on `_safe_env`, a dead branch in
`viz.js`, and an `allowlist` comment in `config.py` that contradicted the implemented behaviour.
No behaviour or user-visible output changed; the suite was re-run afterwards.

Configuration added to `backend/.env` (values are not secrets and are not reproduced here):
`JARVIS_PROJECT_ROOT`, `JARVIS_BROWSER_ALLOWED_DOMAINS=["example.com","en.wikipedia.org","github.com"]`.
List settings in `.env` must be JSON arrays — pydantic-settings parses them as JSON before
validators run, and a comma-separated value stops the core from starting.

---

## 6. Remaining work and blockers

1. **Creative generation** — no image or video backend is installed, so the Creative Agent stays
   `partial` by design. Choosing one (and its credentials) is a user decision.
2. **Security scanner** — no dependency/vulnerability scanner is wired in. `shell.run` could drive
   `pip-audit`/`npm audit` if that were added to the allowlist, but the reporting layer does not
   exist yet.
3. **Desktop control in the core** — mouse/keyboard control still lives only in the legacy
   `app.py` PC CONTROL runtime. Bridging it needs an approval-gated RPC and a kill path.
4. **Credentials not supplied**, so these paths are implemented but not exercised against a live
   service: `email.send` (SMTP), `email` connector (IMAP), `github`, `supabase`, `obsidian`.
   Each reports `not_configured` instead of failing silently.
5. **`shell.run` is not a true sandbox.** It is an allowlist + approval + cwd containment + env
   scrubbing, but an allowlisted interpreter (`python`, `node`) can still do broad things. The
   approval prompt, which shows exact argv, is the real control. Do not raise these tools to
   `autonomous`.
6. **Dev-tool audit** — OpenCode, Claude Code, OpenClaw, Obsidian, Apex, Raea, Hermes, Pocket TTS,
   Muse Code, GitHub and Supabase installations were still not audited.
7. **`/api/health`** on 8765 does not include `agent_core`, and its `lm_studio` flag is stale. The
   Visuals panel therefore counts tools from `/api/core/tools` instead.
8. **Mobile page** (`web/mobile.html`) has not been updated for the Visuals panel.
9. **No remote is configured**, so the five commits exist only on this PC. Add a remote and push
   only when that is explicitly agreed.

---

## 7. Next steps

1. Keep committing in logical units and never rewrite published history.
2. Supply credentials for one remote source at a time (GitHub is cheapest) and confirm the
   connector flips from `not_configured` to `connected` with a real query.
3. Add `pip-audit`/`npm audit` to the shell allowlist and build the scanner summary to unblock the
   Security Agent.
4. Decide the creative-generation backend before claiming that capability.
5. Re-run `pytest` and `ruff` before any commit.

---

## 8. Reproducing the verification

```bash
# backend suite
cd backend && ./.venv/Scripts/python.exe -m pytest

# restart on current code (a healthy core is NOT reloaded automatically)
netstat -ano | grep ":8767 " | grep LISTENING   # kill that PID
powershell -File ./restart-jarvis-server.ps1
```

```bash
# connectors (through the dashboard proxy, which carries the token)
curl -s http://127.0.0.1:8765/api/core/connectors
curl -s -X POST -H "Content-Type: application/json" \
     -d '{"query":"jarvis","limit":3}' \
     http://127.0.0.1:8765/api/core/connectors/search

# voice round trip
curl -s -o /tmp/probe.wav -X POST -H "Content-Type: application/json" \
     -d '{"text":"Jarvis voice loop verification."}' http://127.0.0.1:8765/api/voice/speak
curl -s -X POST -F "audio=@/tmp/probe.wav;filename=probe.wav" \
     http://127.0.0.1:8765/api/voice/transcribe
```

Vision check: build any PNG, base64 it, `POST /api/v1/vision/analyze` with
`{"image_base64": "...", "prompt": "What is this?"}`. To confirm the model really sees, send three
different images and require three different correct answers.
