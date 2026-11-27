"""Critic: decide whether the goal is complete, with a deterministic fallback."""

from __future__ import annotations

import json

from pydantic import BaseModel

from ..llm.base import LLMClient, LLMError, Message, Role
from .models import Plan, StepRecord
from .prompts import CRITIC_SYSTEM, critic_user


class CriticVerdict(BaseModel):
    done: bool
    reason: str


class Critic:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def review(self, goal: str, plan: Plan, results: list[StepRecord]) -> CriticVerdict:
        fallback = _heuristic(plan, results)
        if not results:
            return fallback
        messages = [
            Message(role=Role.SYSTEM, content=CRITIC_SYSTEM),
            Message(role=Role.USER, content=critic_user(goal, plan, results)),
        ]
        try:
            response = await self._llm.complete(
                messages, json_mode=True, temperature=0.0, max_tokens=400
            )
        except LLMError:
            return fallback
        try:
            data = json.loads(response.text)
            verdict = CriticVerdict.model_validate(data)
        except Exception:
            return fallback
        # Never let the language model invent a truncation failure: web.read exposes
        # an explicit boolean. A page ending mid-sentence is not proof of truncation.
        if not verdict.done and "truncat" in verdict.reason.casefold():
            confirmed_truncation = any(
                record.tool == "web.read"
                and isinstance(record.output, dict)
                and record.output.get("truncated") is True
                for record in results
            )
            if not confirmed_truncation:
                return fallback
        # A failed step cannot be "done" unless the model gives a concrete reason.
        if not verdict.done and not verdict.reason.strip():
            verdict.reason = "goal is not fully answered"
        return verdict


def _heuristic(plan: Plan, results: list[StepRecord]) -> CriticVerdict:
    if not plan.steps:
        return CriticVerdict(done=True, reason="no tools required")
    if not results:
        return CriticVerdict(done=False, reason="plan has not run")
    failures = [record for record in results if not record.ok]
    if failures:
        return CriticVerdict(
            done=False, reason=f"step failed: {failures[0].error or 'unknown error'}"
        )
    if len(results) < len(plan.steps):
        return CriticVerdict(done=False, reason="plan is incomplete")
    return CriticVerdict(done=True, reason="all planned steps completed")
