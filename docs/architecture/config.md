# Configuration reference

All settings use the `JARVIS_` prefix. Put them in `backend/.env` or the process
environment. Empty secret values are treated as unset.

## Core

| Variable | Default | Notes |
|---|---|---|
| `JARVIS_ENVIRONMENT` | `dev` | `dev`, `test`, `prod` |
| `JARVIS_DATA_DIR` | `./data` | Database and key live here |
| `JARVIS_DATABASE_PATH` | `<data>/jarvis.sqlite3` | Override DB path |
| `JARVIS_MASTER_KEY` | unset | 32 raw bytes or base64; preferred for prod |
| `JARVIS_MASTER_KEY_FILE` | `<data>/master.key` | Generated on first use |
| `JARVIS_LOG_LEVEL` | `INFO` | uvicorn/application level |

Generate a key:

```powershell
python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
```

## LLM

| Variable | Default | Notes |
|---|---|---|
| `JARVIS_LLM_PROVIDER` | `ollama` | `ollama` or `anthropic` |
| `JARVIS_OLLAMA_URL` | `http://127.0.0.1:11434` | Native API |
| `JARVIS_OLLAMA_MODEL` | `qwen3.5:2b` | Chat/planning model |
| `JARVIS_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Empty disables embeddings |
| `JARVIS_OLLAMA_THINK` | `false` | Disable thinking traces for JSON planning |
| `JARVIS_ANTHROPIC_API_KEY` | unset | Required for Anthropic |
| `JARVIS_ANTHROPIC_MODEL` | `claude-sonnet-4-5` | |
| `JARVIS_ALLOW_CLOUD` | `false` | Second opt-in for Anthropic |

Local-only example:

```dotenv
JARVIS_LLM_PROVIDER=ollama
JARVIS_OLLAMA_MODEL=qwen3.5:2b
JARVIS_ALLOW_CLOUD=false
```

Cloud example (explicit):

```dotenv
JARVIS_LLM_PROVIDER=anthropic
JARVIS_ANTHROPIC_API_KEY=sk-ant-...
JARVIS_ALLOW_CLOUD=true
```

## Agent limits

| Variable | Default | Notes |
|---|---|---|
| `JARVIS_MAX_PLAN_STEPS` | `12` | 1–50 |
| `JARVIS_MAX_REPLANS` | `2` | 0–5 |
| `JARVIS_TOOL_TIMEOUT_S` | `30` | Per-tool fallback; manifest may override |

## API

| Variable | Default | Notes |
|---|---|---|
| `JARVIS_API_HOST` | `127.0.0.1` | Keep loopback unless you add TLS/auth |
| `JARVIS_API_PORT` | `8766` | |
| `JARVIS_API_TOKEN` | unset | Bearer token; required before tunneling |
| `JARVIS_CORS_ORIGINS` | empty | Comma-separated or JSON array |
| `JARVIS_RATE_LIMIT_PER_MINUTE` | `120` | Per client IP; 0 disables |

## Permissions

`JARVIS_TOOL_PERMISSIONS` is a JSON object mapping tool name to
`read_only`, `confirm`, or `autonomous`:

```dotenv
JARVIS_TOOL_PERMISSIONS={"time.now":"read_only","memory.forget":"confirm"}
```

Overrides can lower a tier. Raising a tier requires `allow_upgrade=True` in
`PermissionPolicy`, which is not exposed as an env var in Phase 1.

## Skills, web, and files

| Variable | Default | Notes |
|---|---|---|
| `JARVIS_SKILLS_DIR` | `backend/skills` | Directory of `<name>/manifest.json` packages |
| `JARVIS_BRAVE_API_KEY` | unset | Required by `web.search` |
| `JARVIS_WEB_SEARCH_RESULTS` | `5` | 1–10 results per search |
| `JARVIS_WEB_READ_MAX_BYTES` | `1000000` | Hard download cap |
| `JARVIS_WEB_READ_MAX_CHARS` | `20000` | Text returned to the model |
| `JARVIS_WEB_READ_TIMEOUT_S` | `15` | Connect/read timeout |
| `JARVIS_FILE_SEARCH_ROOTS` | empty | Comma-separated paths or JSON array; empty = Desktop, Documents, Downloads |
| `JARVIS_FILE_SEARCH_MAX_RESULTS` | `20` | 1–200 |
| `JARVIS_FILE_SEARCH_MAX_ENTRIES` | `20000` | Walk budget per search |

`web.read` validates every URL and redirect hop. It rejects non-HTTP schemes,
embedded credentials, loopback, private, link-local, multicast, reserved, and
known metadata hostnames. `files.search` resolves each hit and requires it to
stay under an allowlisted root; it is read-only.

## CLI overrides

```powershell
jarvis --data-dir C:\jarvis-data status
jarvis serve --host 127.0.0.1 --port 8766
```

`--data-dir` resets the derived database path; `--host`/`--port` only affect
`serve`.

## Files and permissions

- `data/master.key` — generated, base64, 32 bytes. Back it up.
- `data/jarvis.sqlite3` — encrypted fields inside a normal SQLite file.
- `.env` — never commit. `.gitignore` excludes it.

The key is not stored in the database. Copying the database without the key
leaves encrypted content unreadable.

## Operational checks

```powershell
jarvis doctor
jarvis status
jarvis audit verify
```

`doctor` checks the DB, key, audit chain, tool count, kill switch, Ollama
reachability, and whether the configured chat/embedding models are installed.
