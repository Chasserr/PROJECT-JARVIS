"""Modular data-source connectors.

``build_connector_registry`` is the only place that decides which sources exist.
The allowlist decides which of them the user has authorised, so a connector can
be installed and still honestly report ``not_configured``.
"""

from __future__ import annotations

from ..config import Settings
from ..memory.store import MemoryStore
from ..notes.store import NoteStore
from .base import Connector, SourceError, SourceHit, SourceState, SourceStatus
from .internal import MemoryConnector
from .local import LocalFilesConnector, ObsidianConnector, ProjectRepoConnector
from .registry import ConnectorRegistry
from .remote import EmailConnector, GitHubConnector, SupabaseConnector, WebConnector


def build_connector_registry(
    settings: Settings,
    *,
    memory: MemoryStore,
    notes: NoteStore,
) -> ConnectorRegistry:
    registry = ConnectorRegistry(
        allowlist=settings.connector_allowlist or None,
        timeout_s=settings.connector_timeout_s,
        max_results=settings.connector_max_results,
    )
    registry.register(MemoryConnector(memory, notes))
    registry.register(LocalFilesConnector(settings))
    registry.register(ProjectRepoConnector(settings))
    registry.register(ObsidianConnector(settings))
    registry.register(WebConnector(settings))
    registry.register(GitHubConnector(settings))
    registry.register(SupabaseConnector(settings))
    registry.register(EmailConnector(settings))
    return registry


__all__ = [
    "Connector",
    "ConnectorRegistry",
    "SourceError",
    "SourceHit",
    "SourceState",
    "SourceStatus",
    "build_connector_registry",
]
