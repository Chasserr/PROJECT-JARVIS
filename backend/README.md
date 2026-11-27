# JARVIS backend

Local-first personal AI operating assistant. Phase 1 provides the core agent,
typed tool registry, encrypted memory, audit log, HTTP API, and CLI. Voice,
dashboard, automation, and external integrations are later phases.

## Requirements

- Python 3.12+ (this machine runs 3.15)
- Ollama for the default local model (`qwen3.5:2b`), or an Anthropic API key
- No Docker/Redis required for Phase 1

## Quick start

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
jarvis init
jarvis doctor
jarvis ask "What time is it in UTC?"
```

Run the API:

```powershell
jarvis serve
# Default: http://127.0.0.1:8766
```

The integrated desktop launcher uses loopback port `8767` and a locally generated bearer token in the ignored `backend/.env` file. Its authenticated `POST /api/v1/chat` endpoint provides local-model chat with encrypted core-memory recall. The desktop server proxies ordinary chat to this endpoint; the legacy PC-control runtime remains separate until its approval flow is integrated. Do not expose either local service to a LAN or public network.

Run the checks:

```powershell
pytest
ruff check src tests
```

## Configuration

All settings use the `JARVIS_` prefix and can live in `backend/.env`. See
`.env.example` and [docs/architecture/06-config.md](../docs/architecture/06-config.md).

The encryption key is generated at `data/master.key` on first run unless
`JARVIS_MASTER_KEY` is set. Back it up: losing it makes existing memory and
audit details unreadable.

## Security defaults

- API binds `127.0.0.1`; set `JARVIS_API_TOKEN` before exposing it through a tunnel.
- Tools have `read_only`, `confirm`, or `autonomous` permission tiers.
- Confirming actions pause the run and return HTTP 409 with an approval request.
- Memory, run state, episodes, and audit details are AES-256-GCM encrypted.
- Audit entries are SHA-256 hash-chained and verifiable with `jarvis audit verify`.
- Tool output is framed as untrusted data in every planner, critic, and answer prompt.

## Current limits

- Vector recall uses Ollama embeddings when `nomic-embed-text` is installed;
  otherwise it falls back to lexical scoring. There is no ANN index yet.
- Redis and Docker Compose are deferred until Docker is available; the event bus
  is in-process with a durable SQLite outbox.
- Phase 2 ships 17 tools: `time.now`, `memory.*`, `system.info`, plus
  `web.search`, `web.read`, `files.search`, `notes.*`, and `reminders.*`.
- `web.search` needs `JARVIS_BRAVE_API_KEY`; without it the skill loads but
  fails when called.
- `files.search` only reads under `JARVIS_FILE_SEARCH_ROOTS`, or Desktop,
  Documents, and Downloads when unset. It never writes.
- `web.read` blocks loopback, private, link-local, and non-HTTP URLs, strips
  scripts/styles, and caps bytes and characters. DNS rebinding remains a
  documented residual risk.
- Reminders are stored and listed; the scheduler that fires them arrives in
  Phase 5.
