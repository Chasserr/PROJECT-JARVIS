# HTTP API

Base URL: `http://127.0.0.1:8766`
Interactive docs: `/docs` (FastAPI/OpenAPI).

## Authentication

Authentication is optional for a loopback-only deployment. Set
`JARVIS_API_TOKEN` to require:

```http
Authorization: Bearer <token>
```

`/health` is unauthenticated. Every `/api/v1/*` route requires the token when
configured. Comparison is constant-time.

CORS is disabled by default. If you add a browser origin, set
`JARVIS_CORS_ORIGINS=https://your-origin` (comma-separated or JSON array).

## Rate limiting

`JARVIS_RATE_LIMIT_PER_MINUTE` (default 120, 0 disables) applies per client IP
to `/api/*`. Exceeding it returns `429` with `Retry-After`. This limiter is
in-memory; a Redis limiter is a Phase 5 replacement.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness, provider, model, DB, counts |
| GET | `/api/v1/tools` | Tool manifests + effective permission |
| GET | `/api/v1/system/status` | Kill switch, DB, memory/tool counts |
| POST | `/api/v1/system/kill?reason=` | Engage global kill switch |
| POST | `/api/v1/system/resume` | Release global kill switch |
| POST | `/api/v1/memory` | Create encrypted memory |
| GET | `/api/v1/memory` | List memories (`limit`, `kind`) |
| GET | `/api/v1/memory/search` | Semantic/lexical search (`q`, `limit`) |
| DELETE | `/api/v1/memory/{id}` | Soft delete (`hard=true` to purge) |
| POST | `/api/v1/agent/runs` | Start a run |
| GET | `/api/v1/agent/runs` | Recent runs (`limit`) |
| GET | `/api/v1/agent/runs/{id}` | Run state |
| POST | `/api/v1/agent/runs/{id}/approve` | Approve/deny a paused step |
| POST | `/api/v1/agent/runs/{id}/cancel` | Cancel a non-terminal run |
| GET | `/api/v1/audit` | Audit tail (`limit`) |
| GET | `/api/v1/audit/verify` | Verify the hash chain |

## Health

```json
{
  "status": "ok",
  "version": "0.1.0",
  "provider": "ollama",
  "model": "qwen3.5:2b",
  "database": true,
  "memory_count": 3,
  "tool_count": 6,
  "cloud_enabled": false
}
```

## Memory

Create:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8766/api/v1/memory `
  -ContentType application/json `
  -Body '{"content":"My favourite tea is jasmine","kind":"preference","tags":["tea"]}'
```

Search:

```powershell
Invoke-RestMethod "http://127.0.0.1:8766/api/v1/memory/search?q=tea&limit=5"
```

Delete:

```powershell
Invoke-RestMethod -Method Delete "http://127.0.0.1:8766/api/v1/memory/<id>?hard=false"
```

## Runs and approval

Start:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8766/api/v1/agent/runs `
  -ContentType application/json `
  -Body '{"goal":"What time is it in UTC?","session_id":"default"}'
```

If every step is allowed, the response is `200` with a `RunResult`.

If a step needs confirmation, the response is **`409 Conflict`** with the same
`RunResult` shape and `status: "awaiting_approval"`:

```json
{
  "run_id": "…",
  "status": "awaiting_approval",
  "goal": "Forget that memory",
  "plan": { "summary": "…", "steps": [ … ] },
  "steps": [],
  "approval": {
    "run_id": "…",
    "step_index": 0,
    "tool": "memory.forget",
    "args": { "id": "…" },
    "permission": "confirm",
    "signature": "sha256:…"
  },
  "error": null,
  "answer": null,
  "attempt": 0
}
```

Approve or deny:

```powershell
Invoke-RestMethod -Method Post `
  "http://127.0.0.1:8766/api/v1/agent/runs/<run_id>/approve" `
  -ContentType application/json -Body '{"approve":true}'
```

Approval binds the **tool name and exact canonical arguments**, not just the
run. The runtime re-executes only the paused step, then continues. Denying
marks the run failed.

If the kill switch is engaged, starting or resuming a run returns `423 Locked`.

## Audit

```powershell
Invoke-RestMethod "http://127.0.0.1:8766/api/v1/audit?limit=20"
Invoke-RestMethod "http://127.0.0.1:8766/api/v1/audit/verify"
```

Audit detail is decrypted for authorized callers. `verify` recomputes the
SHA-256 chain and reports the first bad `seq` if a row was edited.

## Errors

| Status | Meaning |
|---|---|
| 400 | Bad run state, unknown tool, invalid plan |
| 401 | Missing/invalid Bearer token |
| 404 | Memory or run not found |
| 409 | Human approval required |
| 422 | Request schema validation failed |
| 423 | Kill switch engaged |
| 429 | Rate limit exceeded |
| 502 | LLM provider error |
| 500 | Encryption failure |

Error body: `{"detail": "..."}`. Internal exception text is not returned for
unexpected failures.

## Security headers

All responses set `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and
`Cache-Control: no-store`.
