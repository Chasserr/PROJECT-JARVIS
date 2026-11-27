# Integration status — verified 2026-11-27

This file records what was **actually checked on this machine**, not what a
configuration file claims. Three states are distinguished:

- **Working** — exercised and observed doing its job.
- **Configured** — present in config or on disk, but not exercised end to end.
- **Absent** — not installed; nothing to verify.

Machine context: Windows, Python 3.15.0, Node v24.22.1, git 2.56.0, Ollama
0.40.18. Ollama models present: `qwen3.5:4b`, `qwen3.5:4b-8k`, `qwen3.5:2b`,
`qwen2.5-coder:7b`, `nomic-embed-text`, `gpt-oss:20b`, `glm-5.3-flash:cloud`.

## Development tooling

| Integration | State | Evidence |
|---|---|---|
| OpenCode | **Working** — v2.4.1 | `opencode --version`. (Handover notes said 2.3.2; it has been upgraded.) |
| OpenCode **Superpowers** plugin | **Working** | `loading plugin id=superpowers@git+https://github.com/obra/superpowers.git` in `~/.local/share/opencode/log/opencode.log`, most recently 2026-11-27. 15 skills present on disk under the cached package (`brainstorming`, `test-driven-development`, `systematic-debugging`, `writing-plans`, `verification-before-completion`, and others). |
| OpenCode DCP plugin (`@tarquinen/opencode-dcp`) | **Working** | `loading plugin id=@tarquinen/opencode-dcp` in the same log. |
| OpenCode MCP: `context7`, `playwright`, `chrome-devtools`, `rea` | **Configured, not exercised** | Declared in `~/.config/opencode/opencode.jsonc` and visible in `opencode debug config`. No MCP call was made in this audit. |
| Hermes Agent | **Working** — v0.23.4 | `hermes.exe --version` → `Hermes Agent v0.23.4 (2026.9.24) · stable`, installed from git at `C:\Users\Mesha\AppData\Local\hermes\hermes-agent`. Not wired into JARVIS. |
| OpenClaw | **Working** — 2026.11.10 (6ea542f) | `openclaw --version`. `~/.openclaw/jarvis-team/` holds 9 agent dirs (`architect`, `designer`, `developer`, `devops`, `coordinator`, `qa`, `researcher`, `reviewer`, `writer`). Not wired into JARVIS. |
| Claude Code | **Working** — v2.1.332 | `claude --version`. No JARVIS integration exists. |
| Muse Code | **Absent** | `muse` not on PATH; no Muse install found under the home directory. Not evaluated. |
| GitHub | **Not connected** | `gh` CLI not installed; the repository had no `.git` at all before this session and still has **no git remote** configured. |

## Creative and knowledge

| Integration | State | Evidence |
|---|---|---|
| Raea creative engine | **Configured, not exercised** | `rea-agents` installed globally; `rea` MCP server declared in `opencode.jsonc` with Ghidra/JADX/WABT paths. No JARVIS connector. |
| Obsidian | **Present on machine, not integrated** | Vault at `C:\Users\Mesha\Documents\Obsidian Vault`; `%APPDATA%\obsidian\obsidian.json` exists. JARVIS source contains only a static dashboard tool card, no connector. |
| APEX AI dashboard | **Present on machine, not integrated** | `C:\Users\Mesha\Desktop\APEX AI` with `start_apex.bat` / `stop_apex.bat`. Separate application; JARVIS has no code path to it. |
| Supabase | **Not connected** | `supabase` CLI not installed; no Supabase reference in JARVIS source. |

## JARVIS internal capabilities

| Capability | State | Evidence |
|---|---|---|
| Core agent loop (plan → execute → critic) | **Working** | `backend/src/jarvis/agent/` (`planner.py`, `loop.py`, `critic.py`); 67 tests pass. |
| Encrypted memory, audit chain, kill switch, approval pause/resume | **Working** | `security/` modules; covered by `test_crypto.py`, `test_audit.py`, `test_permissions.py`, `test_agent.py`. |
| Tool/skill layer (17 tools, 11 skill packages) | **Working** | `backend/skills/*/manifest.json`; `test_skills.py`, `test_skill_loader.py`. |
| Local voice (Kokoro TTS + faster-whisper STT) | **Working in the legacy runtime** | `app.py` `/api/voice/{status,speak,transcribe}`; live smoke test recorded in [LOCAL_VOICE_PIPELINE.md](LOCAL_VOICE_PIPELINE.md). Not implemented in the FastAPI core. |
| **Specialist agent team (10 roles)** | **Not implemented** | `agent/` has no orchestrator and no role registry. `llm/openjarvis.py` is a 53-line HTTP client. |
| **Dashboard ↔ agent execution** | **Not implemented** | `web/tools-agents.js` renders a hardcoded agent list; only "JARVIS Core" is marked Connected and the rest are "Not verified" / "Not registered". Its own UI text states execution is disabled until a real backend integration is registered. |
| pocket-tts | **Absent** | `pip show pocket-tts` → not found. Not installed, not evaluated. |

## What this means for the handover

1. The OpenCode/Superpowers item is **already working**; it did not need
   completing, only verifying. Its configuration is split across
   `opencode.json` (model/provider) and `opencode.jsonc` (plugins/MCP); OpenCode
   merges both, so this is a readability issue, not a defect.
2. Hermes and OpenClaw are both installed and functional **as separate tools**.
   Neither is connected to JARVIS — that work is genuinely outstanding.
3. The largest real gap is the **10-role specialist agent architecture** and its
   dashboard integration. Neither exists in code.
4. Nothing in this audit was changed by assumption. Items marked "configured,
   not exercised" were not tested and must not be reported as working.
