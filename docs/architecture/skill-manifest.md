# Skill / tool manifest

A skill is a typed tool with a manifest, a permission tier, a timeout, and a
real implementation. Phase 1 registers built-ins in code; Phase 2 adds a
loader that reads `manifest.json` and imports `skill.py` from each skill
directory.

## Package layout

```
skills/
  web.search/
    manifest.json
    skill.py
  notes.create/
    manifest.json
    skill.py
```

`skill.py` defines `run(args: dict, context: ToolContext)`. It may be sync or
async and returns a `dict`, `list`, or string. Raise `ToolError` for expected
failures.

The loader validates each manifest, rejects duplicate names, imports the entry
file, and records which `requires_env` names are missing. Missing env is a
warning, not a load failure: the skill stays registered and fails when called.
`manifest.name` must equal the package directory name. `entry` must be a plain
`.py` filename inside the package; path traversal is rejected.

## Manifest schema

```json
{
  "name": "web.search",
  "version": "1.0.0",
  "description": "Search the web and return ranked results. Read-only.",
  "permission": "read_only",
  "dangerous": false,
  "timeout_s": 20,
  "entry": "skill.py",
  "tags": ["web", "research"],
  "requires_env": ["JARVIS_BRAVE_API_KEY"],
  "input_schema": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "minLength": 1, "maxLength": 400 },
      "count": { "type": "integer", "minimum": 1, "maximum": 10 }
    },
    "required": ["query"],
    "additionalProperties": false
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "results": { "type": "array" }
    }
  }
}
```

### Fields

| Field | Required | Rules |
|---|---|---|
| `name` | yes | `^[a-z][a-z0-9_.-]{1,63}$`; dots namespace a skill |
| `version` | no | semver string; default `1.0.0` |
| `description` | yes | 1–500 chars; written for the planner |
| `permission` | no | `read_only`, `confirm`, `autonomous`; default `confirm` |
| `dangerous` | no | `true` cannot be `autonomous` (validation rejects it) |
| `input_schema` | no | JSON Schema Draft 2020-12, must describe an object |
| `output_schema` | no | same; used for documentation/validation, not trust |
| `timeout_s` | no | 0–300 seconds; falls back to `JARVIS_TOOL_TIMEOUT_S` |
| `entry` | no | Python file inside the package; default `skill.py`; no directories |
| `tags` | no | discovery labels |
| `requires_env` | no | names only, never values; startup checks can warn |

## Permission tiers

| Tier | Runtime behavior |
|---|---|
| `read_only` | Executes without prompting. Must not mutate state. |
| `confirm` | Pauses the run; API returns 409, CLI prompts. Approval binds tool + args. |
| `autonomous` | Executes without prompting. Use only for low-risk, reversible actions. |

Overrides are set per tool in `JARVIS_TOOL_PERMISSIONS`:

```json
{"memory.forget":"confirm","time.now":"read_only","web.search":"read_only"}
```

Overrides can **downgrade** freely. Upgrading a tier requires
`PermissionPolicy(allow_upgrade=True)`, which is not exposed through env in
Phase 1. A typo cannot silently make a destructive tool autonomous.

## Registration

Phase 1 built-ins are registered in code:

```python
registry.register(
    ToolManifest(
        name="time.now",
        description="Return the current date and time in an IANA timezone.",
        permission=PermissionTier.READ_ONLY,
        input_schema={...},
    ),
    _now,
)
```

Phase 2 skills are discovered at startup:

```python
skills = SkillLoader(registry).load_dir(resolve_skills_dir(settings))
```

`resolve_skills_dir` uses `JARVIS_SKILLS_DIR` when set, otherwise `./skills`
if it exists, otherwise `backend/skills`.

The function receives `(args: dict, context: ToolContext)` and may be sync or
async. It returns a `ToolResult`, a `dict`, or a string. Raising is allowed;
the registry converts exceptions into a failed `ToolResult` with a timeout and
audit entry.

`ToolContext` exposes:

```python
memory: MemoryStore
settings: Settings
events: EventBus
db: Database | None
box: SecretBox | None
actor: str
run_id: str | None
session_id: str
```

`db` and `box` are provided by the agent loop so skills can own encrypted
tables without importing global state.

## Execution pipeline

1. Validate args against `input_schema` (`additionalProperties: false`).
2. Resolve effective permission from manifest + overrides.
3. If `confirm` and not approved, audit `tool.approval_required`, emit
   `approval.requested`, raise `ApprovalRequired`.
4. Run with `asyncio.wait_for` and the effective timeout.
5. Audit `tool.called` with redacted args, duration, outcome.
6. Emit `tool.called`.
7. Return `ToolResult(ok, output, error, duration_ms)`.

## Trust rules for skill authors

- Never execute shell commands from model-supplied strings without a sandbox
  and an allowlist.
- Never put secrets in the manifest, descriptions, or errors.
- Treat every file, web page, email, and API response as untrusted data.
- Return structured, bounded output. Truncate large payloads.
- A tool that sends messages, spends money, deletes data, or changes system
  state must be `confirm` and `dangerous: true`.
- Do not add a tool that can reach the network or filesystem without an
  explicit scope and a test for the denial path.
