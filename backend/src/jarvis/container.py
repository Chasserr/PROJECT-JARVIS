"""Composition root. One place wires settings, storage, security, tools, and agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .agent.critic import Critic
from .agent.loop import AgentLoop
from .agent.planner import Planner
from .agent.team import AgentTeam
from .config import Settings
from .connectors import ConnectorRegistry, build_connector_registry
from .db import Database
from .events import EventBus
from .llm.base import LLMClient
from .llm.factory import build_llm
from .memory.embeddings import EmbeddingProvider, OllamaEmbeddings
from .memory.store import MemoryStore
from .notes.store import NoteStore
from .security.audit import AuditLog
from .security.crypto import SecretBox
from .security.kill_switch import KillSwitch
from .security.permissions import PermissionPolicy
from .skills.loader import LoadedSkill, SkillLoader
from .tools.actions import register_action_tools
from .tools.agent_tools import register_agent_tools
from .tools.builtin import build_builtin_registry
from .tools.execution import register_execution_tools
from .tools.registry import ToolRegistry
from .tools.scanner import register_scanner_tool
from .tools.sources import register_source_tools
from .tools.vision import register_vision_tool

UNSET = object()
log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    db: Database
    box: SecretBox
    audit: AuditLog
    events: EventBus
    memory: MemoryStore
    registry: ToolRegistry
    llm: LLMClient
    planner: Planner
    critic: Critic
    agent: AgentLoop
    kill_switch: KillSwitch
    team: AgentTeam | None = None
    skills: list[LoadedSkill] = field(default_factory=list)
    connectors: ConnectorRegistry | None = None


def resolve_skills_dir(settings: Settings) -> Path:
    if settings.skills_dir is not None:
        return Path(settings.skills_dir)
    local = Path.cwd() / "skills"
    if local.is_dir():
        return local
    return Path(__file__).resolve().parents[2] / "skills"


def build_container(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    embeddings: EmbeddingProvider | None | object = UNSET,
) -> Container:
    settings = settings or Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.initialize()
    box = SecretBox.from_settings(settings)
    audit = AuditLog(db, box)
    events = EventBus(db)
    kill_switch = KillSwitch(db)

    if embeddings is UNSET:
        if settings.ollama_embed_model:
            embeddings = OllamaEmbeddings(settings.ollama_url, settings.ollama_embed_model)
        else:
            embeddings = None
    memory = MemoryStore(db, box, embeddings if embeddings is not None else None)  # type: ignore[arg-type]
    policy = PermissionPolicy(settings.tool_permissions)
    registry = build_builtin_registry(policy=policy, audit=audit, events=events, settings=settings)
    register_vision_tool(registry)
    register_action_tools(registry)
    register_execution_tools(registry)
    register_scanner_tool(registry)
    notes = NoteStore(db, box)
    connectors = build_connector_registry(settings, memory=memory, notes=notes)
    register_source_tools(registry, connectors)
    loaded_skills = SkillLoader(registry).load_dir(resolve_skills_dir(settings))
    for skill in loaded_skills:
        if skill.missing_env:
            log.warning(
                "skill %s is missing env vars: %s", skill.name, ", ".join(skill.missing_env)
            )
    client = llm or build_llm(settings)
    team = AgentTeam(registry)
    register_agent_tools(registry)
    planner = Planner(client, registry, settings)
    critic = Critic(client)
    agent = AgentLoop(
        db=db,
        box=box,
        memory=memory,
        registry=registry,
        llm=client,
        planner=planner,
        critic=critic,
        events=events,
        audit=audit,
        settings=settings,
        kill_switch=kill_switch,
        team=team,
    )
    return Container(
        settings=settings,
        db=db,
        box=box,
        audit=audit,
        events=events,
        memory=memory,
        registry=registry,
        llm=client,
        planner=planner,
        critic=critic,
        agent=agent,
        kill_switch=kill_switch,
        team=team,
        skills=loaded_skills,
        connectors=connectors,
    )
