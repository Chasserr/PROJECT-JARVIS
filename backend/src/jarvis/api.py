from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from jarvis.agent.llm_planner import LLMCritic, LLMPlanner
from jarvis.agent.loop import Agent, ToolHandler
from jarvis.agent.policy import PolicyEngine
from jarvis.config import settings
from jarvis.events import EventBus
from jarvis.memory.store import MemoryStore
from jarvis.models import AgentTask, PermissionTier
from jarvis.providers.base import ChatProvider
from jarvis.providers.claude import ClaudeProvider
from jarvis.providers.openai_compatible import OpenAICompatibleProvider
from jarvis.providers.router import FallbackProvider
from jarvis.skills import (
    browser_control,
    bughunter,
    pc_control,
    security_scanner,
    voice_control,
    web_intelligence,
)
from jarvis.skills.manifest import load_skill_manifest
from jarvis.skills.raea import RaeaSkill, RaeaUnavailable
from jarvis.skills.windows_sandbox import run_restricted_worker

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = (Path(__file__).resolve().parents[2] / settings.database_path).resolve()
memory = MemoryStore(DB_PATH)
raea = RaeaSkill(PROJECT_ROOT)


def _provider() -> ChatProvider:
    local = OpenAICompatibleProvider(
        base_url=settings.local_base_url,
        api_key=settings.local_api_key,
        model=settings.local_model,
        name="ollama",
    )
    if (
        settings.provider.lower() == "claude"
        and settings.cloud_enabled
        and settings.claude_api_key.strip()
    ):
        claude = ClaudeProvider(
            api_key=settings.claude_api_key,
            model=settings.claude_model,
        )
        return FallbackProvider(claude, local)
    return local


def _skill_catalog() -> list[dict[str, Any]]:
    manifest_path = Path(settings.skill_manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = Path(__file__).resolve().parents[2] / manifest_path
    capabilities = frozenset({"raea"}) if raea.status().get("available") else frozenset()
    return load_skill_manifest(
        manifest_path,
        available_capabilities=capabilities,
    )


async def _probe_media(args: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(raea.probe_media, args["media_path"])


async def _render_composition(args: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(
        raea.render_composition, args["source_path"], args["output_name"]
    )


async def _search_memories(args: dict[str, Any]) -> dict[str, Any]:
    matches = await asyncio.to_thread(
        memory.search_memories, args["query"], limit=args.get("limit", 20)
    )
    return {"memories": matches}


def _build_agent() -> Agent:
    catalog = _skill_catalog()
    handlers: dict[str, ToolHandler] = {}
    permissions: dict[str, PermissionTier] = {}
    schemas: dict[str, set[str]] = {}
    argument_types: dict[str, dict[str, str]] = {}
    pc_handlers: dict[str, ToolHandler] = {
        "sandbox.text.stats": lambda args: asyncio.to_thread(
            run_restricted_worker, "text.stats", {"text": args["text"]}
        ),
        "memory.search": _search_memories,
        "security.scan_project": lambda _: asyncio.to_thread(
            security_scanner.scan_project, PROJECT_ROOT, PROJECT_ROOT / "data" / "security-reports"
        ),
        "bughunter.capabilities": lambda _: asyncio.to_thread(bughunter.capabilities),
        "bughunter.read_skill": lambda args: asyncio.to_thread(
            bughunter.read_skill, args["skill_name"]
        ),
        "bughunter.classify_url": lambda args: asyncio.to_thread(
            bughunter.classify_url, args["url"]
        ),
        "bughunter.local_audit": lambda _: asyncio.to_thread(bughunter.local_audit),
        "bughunter.surface_local": lambda _: asyncio.to_thread(bughunter.surface_local),
        "bughunter.triage_finding": lambda args: asyncio.to_thread(
            bughunter.triage_finding, args["finding_name"]
        ),
        "bughunter.draft_report": lambda args: asyncio.to_thread(
            bughunter.draft_report, args["finding_name"], args["platform"]
        ),
        "web.search": lambda args: web_intelligence.search_web(args["query"], args.get("limit", 5)),
        "web.read_page": lambda args: web_intelligence.read_page(args["url"]),
        "system.status": lambda _: asyncio.to_thread(pc_control.system_status),
        "desktop.windows": lambda _: asyncio.to_thread(pc_control.list_windows),
        "system.processes": lambda args: asyncio.to_thread(
            pc_control.running_processes, args["limit"]
        ),
        "apps.launch": lambda args: asyncio.to_thread(pc_control.launch_app, args["app"]),
        "apps.focus": lambda args: asyncio.to_thread(pc_control.focus_window, args["title"]),
        "apps.close": lambda args: asyncio.to_thread(pc_control.close_window, args["title"]),
        "files.list": lambda args: asyncio.to_thread(
            pc_control.list_user_files, args["path"], args.get("limit", 100)
        ),
        "files.search": lambda args: asyncio.to_thread(
            pc_control.search_user_files, args["query"], args["root"], args.get("limit", 50)
        ),
        "files.move": lambda args: asyncio.to_thread(
            pc_control.move_user_file, args["source"], args["destination"]
        ),
        "desktop.capture": lambda _: asyncio.to_thread(pc_control.capture_desktop),
        "desktop.click": lambda args: asyncio.to_thread(
            pc_control.click_desktop, args["x"], args["y"]
        ),
        "desktop.type_text": lambda args: asyncio.to_thread(
            pc_control.type_desktop_text, args["text"]
        ),
        "browser.open": lambda args: browser_control.run(browser_control.open_url, args["url"]),
        "browser.snapshot": lambda _: browser_control.run(browser_control.page_snapshot),
        "browser.click": lambda args: browser_control.run(browser_control.click_text, args["text"]),
        "browser.type_text": lambda args: browser_control.run(
            browser_control.type_text, args["text"]
        ),
        "browser.inspect_forms": lambda _: browser_control.run(browser_control.inspect_form_fields),
        "browser.fill_field": lambda args: browser_control.run(
            browser_control.fill_form_field, args["label"], args["value"]
        ),
        "browser.tabs": lambda _: browser_control.run(browser_control.list_tabs),
        "browser.new_tab": lambda args: browser_control.run(browser_control.new_tab, args["url"]),
        "browser.switch_tab": lambda args: browser_control.run(
            browser_control.switch_tab, args["index"]
        ),
        "browser.back": lambda _: browser_control.run(browser_control.navigate_history, "back"),
        "browser.forward": lambda _: browser_control.run(
            browser_control.navigate_history, "forward"
        ),
        "browser.reload": lambda _: browser_control.run(browser_control.navigate_history, "reload"),
        "browser.press_key": lambda args: browser_control.run(
            browser_control.press_key, args["key"]
        ),
        "voice.options": lambda _: asyncio.to_thread(voice_control.available_options),
        "voice.speak": lambda args: asyncio.to_thread(voice_control.speak, args["text"]),
        "voice.listen": lambda args: asyncio.to_thread(
            voice_control.listen,
            args["seconds"],
            args.get("language", "en-US"),
            args.get("device_index"),
        ),
        "voice.stop": lambda _: asyncio.to_thread(voice_control.stop_speaking),
    }
    for skill in catalog:
        skill_id = skill["skill_id"]
        schemas[skill_id] = set(skill["arguments"])
        argument_types[skill_id] = dict(skill["argument_types"])
        permissions[skill_id] = {
            "read_only": PermissionTier.READ_ONLY,
            "autonomous": PermissionTier.AUTONOMOUS,
            "confirm_before_act": PermissionTier.CONFIRM_BEFORE_ACT,
        }[skill["permission"]]
        if skill_id in pc_handlers:
            handlers[skill_id] = pc_handlers[skill_id]
        elif skill_id == "creative.raea.media_probe":
            handlers[skill_id] = _probe_media
        elif skill_id == "creative.raea.media_analyze":
            handlers[skill_id] = lambda args: asyncio.to_thread(
                raea.analyze_media, args["media_path"], args["analysis"]
            )
        elif skill_id == "creative.raea.media_trim":
            handlers[skill_id] = lambda args: asyncio.to_thread(
                raea.trim_media,
                args["media_path"],
                args["start_seconds"],
                args["end_seconds"],
                args["output_name"],
            )
        elif skill_id == "creative.raea.media_concat":
            handlers[skill_id] = lambda args: asyncio.to_thread(
                raea.concat_media, args["media_paths"], args["output_name"]
            )
        elif skill_id == "creative.raea.render":
            handlers[skill_id] = _render_composition
        if skill_id not in handlers:
            raise RuntimeError(f"Skill '{skill_id}' has no trusted handler registered in JARVIS.")
    provider = _provider()
    planner = LLMPlanner(provider, max_steps=settings.max_agent_steps, available_skills=catalog)
    critic = LLMCritic(provider)
    return Agent(
        planner,
        critic,
        handlers,
        PolicyEngine(permissions, kill_switch=settings.kill_switch),
        memory,
        EventBus(),
        max_steps=settings.max_agent_steps,
        max_retries_per_step=0,
        tool_schemas=schemas,
        tool_argument_types=argument_types,
        planner_timeout_seconds=settings.planner_timeout_seconds,
        tool_timeout_seconds=settings.tool_timeout_seconds,
        critic_timeout_seconds=settings.critic_timeout_seconds,
        max_concurrent_tools=settings.max_concurrent_tools,
    )


agent = _build_agent()


class MemoryInput(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    kind: str = Field(default="fact", max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=30)


class PlanInput(BaseModel):
    request: str = Field(min_length=1, max_length=8_000)


class AgentRunInput(BaseModel):
    request: str = Field(min_length=1, max_length=8_000)


class ApprovalInput(BaseModel):
    approved: bool


class VoiceSpeakInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice_name: str = Field(
        default="Microsoft Zira Desktop - English (United States)", min_length=1, max_length=128
    )


class VoiceListenInput(BaseModel):
    seconds: int = Field(default=6, ge=2, le=15)
    language: str | None = Field(
        default=None, min_length=2, max_length=16, pattern=r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$"
    )
    device_index: int | None = Field(default=None, ge=0)


class VoiceLanguageInput(BaseModel):
    language: str = Field(
        min_length=2, max_length=16, pattern=r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$"
    )


class MediaProbeInput(BaseModel):
    media_path: str = Field(min_length=1, max_length=2_000)


class RaeaRenderInput(BaseModel):
    source_path: str = Field(min_length=1, max_length=2_000)
    output_name: str = Field(min_length=1, max_length=100)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


app = FastAPI(title="JARVIS Core API", version="0.1.0", lifespan=lifespan)


@app.get("/api/v1/health")
async def health() -> dict[str, str | bool]:
    return {
        "app": "JARVIS",
        "status": "online",
        "provider": _provider().name,
        "cloud_enabled": settings.cloud_enabled,
        "kill_switch": settings.kill_switch,
    }


@app.get("/api/v1/skills")
async def list_skills() -> dict[str, Any]:
    catalog = _skill_catalog()
    return {"count": len(catalog), "skills": catalog}


@app.get("/api/v1/security/status")
async def security_status() -> dict[str, Any]:
    report = security_scanner.load_latest_report(PROJECT_ROOT / "data" / "security-reports")
    return {
        "skill_id": "security.scan_project",
        "available": True,
        "latest_report_available": report is not None,
        "latest_scan": (
            {"scan_id": report.get("scan_id"), "created_at": report.get("created_at"),
             "summary": report.get("summary")}
            if report else None
        ),
    }


@app.post("/api/v1/security/scan")
async def security_scan() -> dict[str, Any]:
    try:
        report = await asyncio.to_thread(
            security_scanner.scan_project, PROJECT_ROOT, PROJECT_ROOT / "data" / "security-reports"
        )
        memory.audit(
            actor="user", action="security.scan", resource="PROJECT-JARVIS",
            decision="completed", reason="Read-only local static security scan completed.",
            metadata={"scan_id": report["scan_id"], "summary": report["summary"]},
        )
        return report
    except (OSError, ValueError, RuntimeError) as exc:
        memory.audit(
            actor="system", action="security.scan", resource="PROJECT-JARVIS",
            decision="failed", reason=type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail=f"Security scan failed: {exc}") from exc


@app.get("/api/v1/security/report")
async def security_report() -> dict[str, Any]:
    report = security_scanner.load_latest_report(PROJECT_ROOT / "data" / "security-reports")
    if report is None:
        raise HTTPException(status_code=404, detail="No security report exists yet. Run a scan first.")
    return report


@app.post("/api/v1/agent/plan")
async def create_plan(item: PlanInput) -> dict[str, object]:
    provider = _provider()
    try:
        available_skills = _skill_catalog()
        steps = await LLMPlanner(
            provider, max_steps=settings.max_agent_steps, available_skills=available_skills
        ).plan(item.request, memory.list_memories(limit=20))
        return {
            "steps": [
                {
                    "description": step.description,
                    "tool": (
                        {"skill_id": step.tool.skill_id, "arguments": step.tool.arguments}
                        if step.tool
                        else None
                    ),
                }
                for step in steps
            ],
            "provider": provider.name,
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Planning unavailable: {exc}") from exc


@app.post("/api/v1/agent/run")
async def run_agent(item: AgentRunInput) -> dict[str, Any]:
    task = AgentTask(item.request)
    result = await agent.run(task)
    return _task_payload(result)


@app.get("/api/v1/agent/tasks")
async def list_agent_tasks(limit: int = 100) -> dict[str, Any]:
    try:
        tasks = agent.list_tasks(limit)
        return {"tasks": [_task_payload(task) for task in tasks]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/agent/tasks/{task_id}")
async def get_agent_task(task_id: str) -> dict[str, Any]:
    task = agent.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found in this running session.")
    return _task_payload(task)


@app.post("/api/v1/agent/tasks/{task_id}/cancel")
async def cancel_agent_task(task_id: str) -> dict[str, Any]:
    try:
        task = await agent.cancel_task(task_id)
        return _task_payload(task)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/agent/tasks/{task_id}/approval")
async def approve_agent_task(task_id: str, item: ApprovalInput) -> dict[str, Any]:
    try:
        task = await agent.approve(task_id, approved=item.approved)
        return _task_payload(task)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _task_payload(task: AgentTask) -> dict[str, Any]:
    return {
        "task_id": task.id,
        "request": task.request,
        "status": task.status.value,
        "steps": [
            {
                "description": step.description,
                "tool": (
                    {"skill_id": step.tool.skill_id, "arguments": step.tool.arguments}
                    if step.tool
                    else None
                ),
            }
            for step in task.steps
        ],
        "results": task.results,
        "error": task.error,
    }


@app.get("/api/v1/voice/options")
async def voice_options() -> dict[str, Any]:
    try:
        options = await asyncio.to_thread(voice_control.available_options)
        options["default_language"] = memory.get_setting("voice.language", "en-US")
        return options
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Voice options unavailable: {exc}") from exc


@app.get("/api/v1/voice/language")
async def get_voice_language() -> dict[str, Any]:
    try:
        options = await asyncio.to_thread(voice_control.available_options)
        available = [item["culture"] for item in options["recognition_languages"]]
        selected = memory.get_setting("voice.language", "en-US")
        if selected not in available and available:
            selected = available[0]
        return {"language": selected, "available_languages": available}
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Voice languages unavailable: {exc}") from exc


@app.put("/api/v1/voice/language")
async def set_voice_language(item: VoiceLanguageInput) -> dict[str, Any]:
    try:
        options = await asyncio.to_thread(voice_control.available_options)
        available = [entry["culture"] for entry in options["recognition_languages"]]
        selected = next((code for code in available if code.lower() == item.language.lower()), None)
        if selected is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "This Windows speech-recognition language is not installed.",
                    "available_languages": available,
                },
            )
        memory.set_setting("voice.language", selected)
        memory.audit(
            actor="user",
            action="voice.language.update",
            resource=selected,
            decision="allow",
            reason="User selected a supported voice language.",
        )
        return {"language": selected, "saved": True, "available_languages": available}
    except HTTPException:
        raise
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Voice language update failed: {exc}") from exc


@app.post("/api/v1/voice/speak")
async def voice_speak(item: VoiceSpeakInput) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(voice_control.speak, item.text, item.voice_name)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Voice output failed: {exc}") from exc


@app.post("/api/v1/voice/stop")
async def voice_stop() -> dict[str, bool]:
    try:
        return await asyncio.to_thread(voice_control.stop_speaking)
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Voice stop failed: {exc}") from exc


@app.post("/api/v1/voice/listen")
async def voice_listen(item: VoiceListenInput) -> dict[str, Any]:
    try:
        language = item.language or memory.get_setting("voice.language", "en-US")
        return await asyncio.to_thread(
            voice_control.listen, item.seconds, language, item.device_index
        )
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"Voice input failed: {exc}") from exc


@app.get("/api/v1/skills/raea/status")
async def raea_status() -> dict[str, object]:
    try:
        return {"skill_id": "creative.raea", **raea.status()}
    except (OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"raea status unavailable: {exc}") from exc


@app.post("/api/v1/skills/raea/media/probe")
async def raea_media_probe(item: MediaProbeInput) -> dict[str, object]:
    try:
        return {
            "skill_id": "creative.raea",
            "operation": "media_probe",
            **raea.probe_media(item.media_path),
        }
    except RaeaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/skills/raea/render")
async def raea_render(_: RaeaRenderInput) -> dict[str, object]:
    raise HTTPException(
        status_code=409,
        detail="Direct rendering is disabled. Use /api/v1/agent/run and approve the pending action.",
    )


@app.get("/api/v1/memory")
async def list_memory(limit: int = 100) -> dict[str, object]:
    try:
        return {"memories": memory.list_memories(limit=limit)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/memory")
async def add_memory(item: MemoryInput) -> dict[str, object]:
    try:
        saved = memory.add_memory(item.content, kind=item.kind, tags=item.tags)
        memory.audit(
            actor="user",
            action="memory.create",
            resource=saved["id"],
            decision="allow",
            reason="User explicitly saved a memory.",
        )
        return {"memory": saved}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/memory/{memory_id}")
async def delete_memory(memory_id: str) -> dict[str, bool]:
    deleted = memory.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found.")
    memory.audit(
        actor="user",
        action="memory.delete",
        resource=memory_id,
        decision="allow",
        reason="User explicitly deleted a memory.",
    )
    return {"deleted": True}
