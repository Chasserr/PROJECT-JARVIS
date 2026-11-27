"""JARVIS command line: ask, chat, memory, tools, audit, doctor, serve."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .agent.models import ApprovalRequest, RunResult, RunStatus
from .config import Settings
from .container import Container, build_container
from .llm.ollama import OllamaClient
from .memory.models import MemoryCreate, MemoryKind


def _print_result(result: RunResult) -> None:
    print(f"\nstatus: {result.status.value}")
    if result.answer:
        print(result.answer)
    if result.error:
        print(f"error: {result.error}", file=sys.stderr)
    if result.approval:
        print("approval required:")
        print(json.dumps(result.approval.model_dump(), indent=2, ensure_ascii=False))
    if result.steps:
        print("\nsteps:")
        for step in result.steps:
            mark = "ok" if step.ok else "FAIL"
            print(f"  [{mark}] {step.tool} ({step.duration_ms} ms)")
            if not step.ok and step.error:
                print(f"        {step.error}")


async def _approval_prompt(request: ApprovalRequest) -> bool:
    print("\n" + "=" * 60)
    print(f"APPROVAL REQUIRED: {request.tool}")
    print(f"permission: {request.permission}")
    print(f"arguments: {json.dumps(request.args, indent=2, ensure_ascii=False)}")
    print("=" * 60)
    answer = await asyncio.to_thread(input, "Approve this action? [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def _format_memory(memory: Any) -> str:
    score = f" score={memory.score:.3f}" if getattr(memory, "score", None) is not None else ""
    tags = f" tags={','.join(memory.tags)}" if memory.tags else ""
    return f"{memory.id}  [{memory.kind}]{score}{tags}\n  {memory.content}"


async def _cmd_ask(container: Container, goal: str) -> int:
    result = await container.agent.start(goal, session_id="cli", approval_handler=_approval_prompt)
    _print_result(result)
    return 0 if result.status is RunStatus.COMPLETED else 1


async def _cmd_chat(container: Container, session_id: str) -> int:
    print(f"JARVIS {__version__} — chat session '{session_id}'. Type /help or /exit.")
    while True:
        try:
            text = (await asyncio.to_thread(input, "\nyou> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            return 0
        if text == "/help":
            print(
                "/memory <query>  search memory\n/tools           list tools\n/exit            quit"
            )
            continue
        if text == "/tools":
            for manifest in container.registry.manifests():
                permission = container.registry.effective_permission(manifest).value
                print(f"  {manifest.name:24} {permission:12} {manifest.description}")
            continue
        if text.startswith("/memory "):
            results = await container.memory.search(text[8:].strip(), 5)
            print("\n\n".join(_format_memory(memory) for memory in results) or "no matches")
            continue

        episodes = container.memory.episodes(session_id, 8)
        context = "\n".join(f"{episode['role']}: {episode['content']}" for episode in episodes[-6:])
        container.memory.add_episode(session_id, "user", text)
        result = await container.agent.start(
            text,
            session_id=session_id,
            context=context,
            approval_handler=_approval_prompt,
        )
        _print_result(result)
        if result.answer:
            container.memory.add_episode(session_id, "assistant", result.answer)


async def _cmd_memory_add(container: Container, args: argparse.Namespace) -> int:
    memory = await container.memory.add(
        MemoryCreate(
            content=" ".join(args.content),
            kind=MemoryKind(args.kind),
            tags=args.tag or [],
        )
    )
    print(memory.model_dump_json(indent=2))
    return 0


async def _cmd_memory_search(container: Container, query: str, limit: int) -> int:
    results = await container.memory.search(query, limit)
    print("\n\n".join(_format_memory(memory) for memory in results) or "no matches")
    return 0


def _cmd_memory_list(container: Container, limit: int, kind: str | None) -> int:
    results = container.memory.list(limit, kind=kind)
    print("\n\n".join(_format_memory(memory) for memory in results) or "memory is empty")
    return 0


def _cmd_memory_delete(container: Container, memory_id: str, hard: bool, yes: bool) -> int:
    if not yes:
        prompt = "Permanently delete" if hard else "Forget"
        answer = input(f"{prompt} memory {memory_id}? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("cancelled")
            return 1
    deleted = container.memory.delete(memory_id, hard=hard)
    print("deleted" if deleted else "not found")
    return 0 if deleted else 1


def _cmd_tools(container: Container) -> int:
    for manifest in container.registry.manifests():
        permission = container.registry.effective_permission(manifest).value
        print(f"{manifest.name:24} {permission:12} {manifest.description}")
    return 0


def _cmd_audit_tail(container: Container, limit: int) -> int:
    for entry in container.audit.tail(limit):
        detail = json.dumps(entry.detail, ensure_ascii=False) if entry.detail else ""
        print(
            f"{entry.seq:5} {entry.actor:8} {entry.action:24} "
            f"{entry.outcome:8} {entry.tool or '-':20} {detail[:160]}"
        )
    return 0


def _cmd_audit_verify(container: Container) -> int:
    result = container.audit.verify()
    print(
        f"ok={result.ok} checked={result.checked} "
        f"first_bad_seq={result.first_bad_seq} message={result.message}"
    )
    return 0 if result.ok else 1


def _cmd_status(container: Container) -> int:
    kill = container.kill_switch.status()
    print(f"kill switch: {'ENGAGED' if kill.engaged else 'released'}")
    if kill.reason:
        print(f"  reason: {kill.reason}")
    print(f"database:    {'ok' if container.db.health() else 'error'}")
    print(f"memories:    {container.memory.count()}")
    print(f"tools:       {len(container.registry.manifests())}")
    print(f"provider:    {container.settings.llm_provider}")
    print(f"model:       {getattr(container.llm, 'model', '?')}")
    return 0


def _cmd_kill(container: Container, reason: str) -> int:
    status = container.kill_switch.engage(reason)
    container.audit.record(
        actor="cli",
        action="system.kill_switch.engaged",
        outcome="ok",
        detail={"reason": reason},
    )
    print(f"kill switch engaged: {status.reason}")
    return 0


def _cmd_release(container: Container) -> int:
    status = container.kill_switch.release()
    container.audit.record(actor="cli", action="system.kill_switch.released", outcome="ok")
    print(f"kill switch released (engaged={status.engaged})")
    return 0


async def _cmd_doctor(settings: Settings) -> int:
    failures = 0
    warnings = 0

    def ok(label: str, detail: str = "") -> None:
        print(f"[ok]   {label}{': ' + detail if detail else ''}")

    def warn(label: str, detail: str = "") -> None:
        nonlocal warnings
        warnings += 1
        print(f"[warn] {label}{': ' + detail if detail else ''}")

    def fail(label: str, detail: str = "") -> None:
        nonlocal failures
        failures += 1
        print(f"[fail] {label}{': ' + detail if detail else ''}")

    try:
        container = build_container(settings)
        ok("database", str(settings.db_path))
        ok("encryption key", str(settings.key_path))
        verification = container.audit.verify()
        if verification.ok:
            ok("audit chain", f"{verification.checked} entries")
        else:
            fail("audit chain", verification.message)
        ok("tools", f"{len(container.registry.manifests())} registered")
        kill = container.kill_switch.status()
        if kill.engaged:
            warn("kill switch engaged", kill.reason or "no reason recorded")
        else:
            ok("kill switch", "released")
    except Exception as exc:
        fail("startup", f"{type(exc).__name__}: {exc}")
        return 1

    if settings.llm_provider == "ollama":
        client = OllamaClient(settings.ollama_url, settings.ollama_model)
        try:
            models = await client.available_models()
        except Exception as exc:
            fail("ollama", str(exc))
        else:
            ok("ollama", settings.ollama_url)
            if settings.ollama_model in models:
                ok("chat model", settings.ollama_model)
            else:
                warn(
                    "chat model not installed",
                    f"{settings.ollama_model}; run `ollama pull {settings.ollama_model}`",
                )
            if settings.ollama_embed_model:
                installed_embedding_names = {name.split(":", 1)[0] for name in models}
                if settings.ollama_embed_model in models or settings.ollama_embed_model in installed_embedding_names:
                    ok("embedding model", settings.ollama_embed_model)
                else:
                    warn(
                        "embedding model not installed",
                        f"{settings.ollama_embed_model}; lexical search will be used",
                    )
    else:
        if settings.anthropic_api_key is None:
            fail("anthropic key", "JARVIS_ANTHROPIC_API_KEY is missing")
        elif not settings.allow_cloud:
            warn("cloud disabled", "set JARVIS_ALLOW_CLOUD=true to use Anthropic")
        else:
            ok("anthropic", settings.anthropic_model)

    if failures:
        print(f"\n{failures} failure(s), {warnings} warning(s)")
        return 1
    print(f"\nall critical checks passed ({warnings} warning(s))")
    return 0


def _cmd_serve(settings: Settings) -> int:
    import uvicorn

    from .api.app import create_app

    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
    return 0


def _cmd_init(settings: Settings, container: Container) -> int:
    print("JARVIS initialized")
    print(f"  data dir: {settings.data_dir}")
    print(f"  database: {settings.db_path}")
    print(f"  key:      {settings.key_path}")
    print(f"  provider: {settings.llm_provider} / {getattr(container.llm, 'model', '?')}")
    print(f"  tools:    {len(container.registry.manifests())}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="Local-first personal AI operating assistant.",
    )
    parser.add_argument("--version", action="version", version=f"JARVIS {__version__}")
    parser.add_argument("--data-dir", help="override JARVIS_DATA_DIR")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database and encryption key")
    sub.add_parser("doctor", help="check runtime, model, and audit health")
    sub.add_parser("status", help="show kill switch and runtime status")
    kill = sub.add_parser("kill", help="engage the global kill switch")
    kill.add_argument("--reason", default="manual stop")
    sub.add_parser("resume", help="release the global kill switch")

    ask = sub.add_parser("ask", help="run one goal through the agent")
    ask.add_argument("goal", nargs="+")

    chat = sub.add_parser("chat", help="interactive chat with memory context")
    chat.add_argument("--session", default="cli")

    serve = sub.add_parser("serve", help="start the HTTP API")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)

    memory = sub.add_parser("memory", help="manage long-term memory")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)
    memory_add = memory_sub.add_parser("add")
    memory_add.add_argument("content", nargs="+")
    memory_add.add_argument("--kind", default="fact", choices=["fact", "preference", "note"])
    memory_add.add_argument("--tag", action="append")
    memory_search = memory_sub.add_parser("search")
    memory_search.add_argument("query", nargs="+")
    memory_search.add_argument("--limit", type=int, default=10)
    memory_list = memory_sub.add_parser("list")
    memory_list.add_argument("--limit", type=int, default=50)
    memory_list.add_argument("--kind")
    memory_delete = memory_sub.add_parser("delete")
    memory_delete.add_argument("id")
    memory_delete.add_argument("--hard", action="store_true")
    memory_delete.add_argument("--yes", action="store_true")

    tools = sub.add_parser("tools", help="list registered tools")
    tools.add_argument("--json", action="store_true")

    audit = sub.add_parser("audit", help="inspect the audit log")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    audit_tail = audit_sub.add_parser("tail")
    audit_tail.add_argument("--limit", type=int, default=50)
    audit_sub.add_parser("verify")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = Settings()
    if args.data_dir:
        settings.data_dir = Path(args.data_dir)
        settings.database_path = None
    if args.command == "serve":
        if getattr(args, "host", None):
            settings.api_host = args.host
        if getattr(args, "port", None):
            settings.api_port = args.port
        return _cmd_serve(settings)

    try:
        if args.command == "doctor":
            return asyncio.run(_cmd_doctor(settings))
        container = build_container(settings)
        if args.command == "init":
            return _cmd_init(settings, container)
        if args.command == "status":
            return _cmd_status(container)
        if args.command == "kill":
            return _cmd_kill(container, args.reason)
        if args.command == "resume":
            return _cmd_release(container)
        if args.command == "ask":
            return asyncio.run(_cmd_ask(container, " ".join(args.goal)))
        if args.command == "chat":
            return asyncio.run(_cmd_chat(container, args.session))
        if args.command == "tools":
            if args.json:
                print(
                    json.dumps(
                        [
                            {
                                "name": manifest.name,
                                "description": manifest.description,
                                "permission": container.registry.effective_permission(
                                    manifest
                                ).value,
                                "input_schema": manifest.input_schema,
                            }
                            for manifest in container.registry.manifests()
                        ],
                        indent=2,
                    )
                )
                return 0
            return _cmd_tools(container)
        if args.command == "audit":
            if args.audit_command == "tail":
                return _cmd_audit_tail(container, args.limit)
            return _cmd_audit_verify(container)
        if args.command == "memory":
            if args.memory_command == "add":
                return asyncio.run(_cmd_memory_add(container, args))
            if args.memory_command == "search":
                return asyncio.run(_cmd_memory_search(container, " ".join(args.query), args.limit))
            if args.memory_command == "list":
                return _cmd_memory_list(container, args.limit, args.kind)
            return _cmd_memory_delete(container, args.id, args.hard, args.yes)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
