# Data models

SQLite is the source of truth. WAL mode is enabled; each operation uses a
short-lived connection so asyncio tasks never share a connection across
threads. `PRAGMA user_version = 2`.

## 1. Tables

### `memories`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `kind` | TEXT | `fact`, `preference`, `note`, `episode` |
| `content` | BLOB | AES-256-GCM, context `memory` |
| `tags` | TEXT | JSON array |
| `source` | TEXT | `user`, `api`, `agent` |
| `embedding` | BLOB | float32 array, native endian |
| `embedding_model` | TEXT | model identity; vectors from another model are ignored |
| `created_at`, `updated_at` | REAL | Unix seconds |
| `deleted_at` | REAL | soft-delete marker |

Index: `(deleted_at, updated_at DESC)`.

### `notes`

User-authored notes, encrypted at the field level.

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `title` | BLOB | AES-256-GCM, context `note` |
| `body` | BLOB | AES-256-GCM, context `note` |
| `tags` | BLOB | encrypted JSON array |
| `source` | TEXT | `user`, `api`, `agent` |
| `created_at`, `updated_at` | REAL | Unix seconds |
| `deleted_at` | REAL | soft-delete marker |

Index: `(deleted_at, updated_at DESC)`. Hard delete removes the row; soft
delete only sets `deleted_at`.

### `reminders`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `text` | BLOB | AES-256-GCM, context `reminder` |
| `due_at` | REAL | Unix seconds; null means unscheduled |
| `status` | TEXT | `pending` or `done` |
| `created_at`, `updated_at` | REAL | |
| `deleted_at` | REAL | soft-delete marker |

Index: `(deleted_at, status, due_at)`. `ReminderStore.due()` returns pending
reminders whose `due_at <= now`; firing them is Phase 5.

### `episodes`

Short-term conversation history, also encrypted.

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `session_id` | TEXT | CLI/API session |
| `role` | TEXT | `user`, `assistant` |
| `content` | BLOB | AES-256-GCM, context `episode` |
| `created_at` | REAL | Unix seconds |
| `meta` | TEXT | JSON object |

Index: `(session_id, created_at)`.

### `runs`

Durable agent runs. Every state transition is persisted so approval can resume
in a new process.

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `session_id` | TEXT | |
| `goal` | TEXT | encrypted, context `run` |
| `status` | TEXT | `running`, `awaiting_approval`, `completed`, `failed`, `cancelled` |
| `plan` | TEXT | encrypted JSON `Plan` |
| `results` | TEXT | encrypted JSON list of `StepRecord` |
| `answer` | TEXT | encrypted final answer |
| `error` | TEXT | encrypted failure reason |
| `attempt` | INTEGER | replan count |
| `pending` | TEXT | encrypted `ApprovalRequest` |
| `created_at`, `updated_at` | REAL | |

### `audit`

Append-only. `seq` is the ordering key.

| Column | Type | Notes |
|---|---|---|
| `seq` | INTEGER PK AUTOINCREMENT | |
| `id` | TEXT UNIQUE | UUID |
| `ts` | REAL | Unix seconds |
| `actor` | TEXT | `user`, `api`, `agent`, `test` |
| `action` | TEXT | e.g. `tool.called`, `run.completed` |
| `tool` | TEXT | nullable |
| `permission` | TEXT | effective tier |
| `outcome` | TEXT | `ok`, `error`, `pending` |
| `detail` | BLOB | encrypted JSON, context `audit` |
| `prev_hash` | TEXT | previous `entry_hash` or 64 zeros |
| `entry_hash` | TEXT | SHA-256 of the canonical entry |

Hash material:

```
ts(6dp)|actor|action|tool|permission|outcome|sha256(detail_cipher)|prev_hash
```

### `outbox`

Durable event log used by the in-process bus.

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `type` | TEXT | event type |
| `payload` | TEXT | JSON, redacted before publishing |
| `created_at` | REAL | |
| `consumed` | INTEGER | 0/1 |

Index: `(consumed, created_at)`.

## 2. Pydantic models

### Memory

```python
class Memory(BaseModel):
    id: str
    kind: str
    content: str
    tags: list[str]
    source: str
    created_at: float
    updated_at: float
    score: float | None
```

`MemoryCreate` enforces non-blank content (≤20,000 chars), a known kind, and
≤20 cleaned tags.

### Notes and reminders

```python
class NoteCreate(BaseModel):
    title: str = ""          # ≤200
    body: str                # 1..20,000
    tags: list[str] = []     # ≤20 tags, each ≤40 chars

class Note(NoteCreate):
    id: str
    source: str
    created_at: float
    updated_at: float

class ReminderCreate(BaseModel):
    text: str                # 1..2,000
    due_at: float | None

class Reminder(ReminderCreate):
    id: str
    status: str              # pending | done
    created_at: float
    updated_at: float
```

`NoteUpdate` makes title, body, and tags optional. Soft delete is the default;
`hard=True` removes the row.

### Agent

```python
class PlanStep(BaseModel):
    tool: str
    args: dict[str, Any]
    rationale: str

class Plan(BaseModel):
    summary: str
    steps: list[PlanStep]

class StepRecord(BaseModel):
    index: int
    tool: str
    args: dict[str, Any]
    ok: bool
    output: Any
    error: str | None
    duration_ms: int

class ApprovalRequest(BaseModel):
    run_id: str
    step_index: int
    tool: str
    args: dict[str, Any]
    permission: str
    signature: str  # sha256("tool:" + canonical JSON args)

class RunResult(BaseModel):
    run_id: str
    status: RunStatus
    goal: str
    answer: str | None
    plan: Plan | None
    steps: list[StepRecord]
    error: str | None
    approval: ApprovalRequest | None
    attempt: int
```

### LLM

`Message(role, content, name?, tool_call_id?)`, `ToolCall(id, name, arguments)`,
`LLMResponse(text, tool_calls, model, raw)`.

## 3. Encryption

`SecretBox` uses AES-256-GCM with a fresh 96-bit nonce per value. Ciphertext
layout is `b"J1" + nonce + ciphertext_and_tag`. The associated data is a
context label, so a memory ciphertext cannot be decrypted as a run.

Key resolution order:

1. `JARVIS_MASTER_KEY` (32 raw bytes or base64).
2. `JARVIS_MASTER_KEY_FILE`.
3. `data/master.key`, generated on first use (base64, chmod 600 where supported).

Losing the key makes encrypted content unrecoverable. Back it up separately from
the database.

## 4. Vector recall

- Embeddings are float32 arrays stored in `memories.embedding`.
- `embedding_model` is stored with each vector. A query vector is only compared
  with vectors from the same model.
- Score = `0.75 * cosine + 0.25 * lexical_overlap` when a vector is available;
  otherwise lexical overlap alone.
- The current scan is O(n) over live memories. Phase 5 adds an ANN index
  (sqlite-vec, Chroma, or pgvector) behind the same `MemoryStore` interface.

## 5. Retention and deletion

- `memory.delete(id)` is a soft delete by default; `hard=true` removes the row.
- Audit rows are append-only. There is no delete API in Phase 1.
- Runs are never automatically purged. A retention job is a Phase 6 item.
- The database is not encrypted as a whole; individual sensitive fields are.
  Full-database encryption (SQLCipher) is an option, not a Phase 1 dependency.
