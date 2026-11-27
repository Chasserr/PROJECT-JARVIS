# Agent loop, failures, and events

## 1. Loop

```text
start(goal, session_id, context, approval_handler?):
    if kill_switch.engaged: raise KillSwitchEngaged
    create durable run (status=running, encrypted goal)
    emit run.started; audit run.started
    plan = Planner.plan(goal, context)          # validated JSON, one retry
    save plan
    return execute(run, plan, results=[], attempt=0)

execute(run, plan, results, attempt):
    index = len(results)
    while index < len(plan.steps):
        if kill_switch.engaged: fail("kill switch engaged")
        step = plan.steps[index]
        try:
            result = registry.execute(step.tool, step.args)
        except ApprovalRequired as approval:
            if approval_handler:
                if handler(approval): continue       # execute the same step
                else: fail("approval denied")
            persist status=awaiting_approval + pending approval
            audit run.awaiting_approval
            return run
        append StepRecord(result); save results
        if not result.ok: break
        index += 1

    verdict = Critic.review(goal, plan, results)
    if verdict.done:
        answer = Answer(goal, results)
        persist completed; emit run.completed
        return run
    if attempt >= max_replans:
        fail("critic: ... (replan budget exhausted)")
    revised = Planner.replan(goal, plan, results, verdict.reason)
    save revised plan; results=[]; attempt += 1
    return execute(run, revised, [], attempt)
```

`resume(run_id, approved)` loads the encrypted plan, results, and pending
approval, adds the approval signature to an in-memory set, and continues from
the pending step. Approval is never inferred from a previous run.

## 2. Planner contract

The planner returns:

```json
{
  "summary": "one sentence",
  "steps": [
    {"tool": "time.now", "args": {"timezone": "UTC"}, "rationale": "why"}
  ]
}
```

Validation before any tool runs:

- valid JSON object with a `steps` list;
- ≤ `JARVIS_MAX_PLAN_STEPS`;
- every `tool` exists in the registry;
- every `args` object validates against the tool's JSON Schema.

On failure, the planner gets one corrective retry with the exact validation
error. A second failure fails the run before any side effect.

## 3. Critic contract

The critic returns `{"done": true|false, "reason": "..."}`. Deterministic
fallback:

| Situation | Fallback |
|---|---|
| Empty plan | done |
| No results yet | not done |
| Any failed step | not done with that error |
| Fewer results than plan steps | not done |
| All steps succeeded | done |

The LLM critic can override the fallback, but it sees the same untrusted
results. A failure to call the LLM falls back to the table above.

## 4. Failure and fallback paths

| Failure | Behavior |
|---|---|
| Ollama unreachable / model missing | `LLMError` with a start/serve hint; run fails before tools |
| Planner returns non-JSON | one retry, then `PlanError` |
| Planner invents a tool | validation error, one retry, then fail |
| Tool args invalid | planner retry; registry re-validates |
| Tool raises | `ToolResult(ok=false)`, audited, critic may replan |
| Tool timeout | `ToolResult(ok=false, error="timed out")` |
| Confirm tool without approval | run pauses with `awaiting_approval` |
| User denies | run fails with `approval denied by user` |
| Kill switch engaged | new work 423 / CLI error; in-flight run fails between steps |
| Replan budget exhausted | run fails with critic reason |
| Final answer LLM fails | fallback to successful tool outputs or failure reason |
| Audit chain mismatch | `jarvis audit verify` exits 1 |

## 5. Prompt-injection defense

Every prompt that sees external content contains the same rule: tool results,
web pages, files, emails, and screenshots are **untrusted data**, never
instructions. Tool output is serialized as JSON and bounded to 8,000 characters
in prompts.

Defense in depth:

1. The model cannot grant permissions; the runtime enforces tiers.
2. A `confirm` action pauses before execution; approval binds tool + exact args.
3. The planner never receives a tool result as a command; replans receive it as
   data with the same rule.
4. The final answer prompt repeats the rule.
5. Phase 2 web/file skills must additionally strip active content and cap size.
6. No shell, arbitrary file, or outbound-message tool exists in Phase 1.

Residual risk: a sufficiently persuasive payload can still bias a plan or
answer. Approval and least privilege limit impact; the audit log records what
happened.

## 6. Event bus

`EventBus.publish(type, payload)` inserts into `outbox`, then awaits subscribers.
A subscriber failure is logged and does not fail the publisher. The outbox is a
durable record for replay/inspection; `pending()` and `mark_consumed()` support a
future worker.

Event types:

| Type | Payload |
|---|---|
| `run.started` | `run_id`, `session_id` |
| `run.completed` | `run_id`, `status` |
| `run.failed` | `run_id`, `error` |
| `tool.called` | `tool`, `ok`, `duration_ms`, `run_id` |
| `approval.requested` | `tool`, `args` (redacted), `run_id`, `signature` |
| `memory.created` | `id`, `kind` |
| `memory.deleted` | `id` (reserved) |
| `audit.appended` | reserved |

Phase 5 Redis adapter:

```python
class RedisEventBus:
    async def publish(self, event_type, payload): ...
    def subscribe(self, event_type, handler): ...
```

The interface is intentionally small. Callers do not know whether the bus is
in-process or Redis.

## 7. Concurrency

- Each run is sequential. The API can start multiple runs concurrently.
- SQLite uses WAL and short-lived connections; writes are serialized by SQLite.
- There is no distributed lock or worker queue yet. Phase 5 adds a Redis-backed
  worker for scheduled/parallel jobs.
- The kill switch is a database flag, so it is shared by all processes using the
  same database.
