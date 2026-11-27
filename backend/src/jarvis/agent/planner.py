"""Planner: ask the model for a JSON plan, validate it, and retry malformed output."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from ..config import Settings
from ..llm.base import LLMClient, LLMError, Message, Role
from ..tools.registry import ToolRegistry, ToolValidationError
from .models import Plan, PlanStep, StepRecord
from .prompts import PLANNER_SYSTEM, planner_user, replanner_user


class PlanError(RuntimeError):
    pass


class Planner:
    def __init__(self, llm: LLMClient, registry: ToolRegistry, settings: Settings) -> None:
        self._llm = llm
        self._registry = registry
        self._settings = settings

    async def plan(
        self,
        goal: str,
        context: str = "",
        *,
        tools: list[dict[str, Any]] | None = None,
        persona: str | None = None,
    ) -> Plan:
        """Build a plan. ``tools`` narrows the tool list to a specialist's scope."""
        specs = self._registry.specs() if tools is None else tools
        prompt = planner_user(goal, specs, self._settings.max_plan_steps, context)
        return await self._request(prompt, specs, persona)

    async def replan(
        self,
        goal: str,
        previous: Plan,
        results: list[StepRecord],
        critique: str,
        context: str = "",
        *,
        tools: list[dict[str, Any]] | None = None,
        persona: str | None = None,
    ) -> Plan:
        specs = self._registry.specs() if tools is None else tools
        prompt = replanner_user(
            goal,
            specs,
            previous,
            results,
            critique,
            self._settings.max_plan_steps,
            context,
        )
        return await self._request(prompt, specs, persona)

    async def _request(
        self,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        persona: str | None = None,
    ) -> Plan:
        system = PLANNER_SYSTEM
        if persona:
            system = f"{PLANNER_SYSTEM}\n\nRole assignment:\n{persona}"
        messages = [
            Message(role=Role.SYSTEM, content=system),
            Message(role=Role.USER, content=prompt),
        ]
        last_error = "planner returned no plan"
        # Small local models can occasionally return valid JSON with an incomplete
        # shape. Give them one additional repair attempt, with a deterministic
        # temperature and an explicit schema reminder; never silently accept a
        # malformed/empty plan as a successful run.
        for attempt in range(3):
            try:
                response = await self._llm.complete(
                    messages, json_mode=True, temperature=0.0, max_tokens=2000
                )
            except LLMError as exc:
                raise PlanError(str(exc)) from exc
            try:
                plan = self._parse(response.text)
                self._validate(plan, tools)
                return plan
            except (PlanError, ToolValidationError) as exc:
                last_error = str(exc)
                messages.append(Message(role=Role.ASSISTANT, content=response.text))
                messages.append(
                    Message(
                        role=Role.USER,
                        content=(
                            f"Attempt {attempt + 1} of 3 failed: {last_error}.\n"
                            "Return one valid JSON object only. It MUST contain both keys: "
                            "\"summary\" (a short string) and \"steps\" (an array). "
                            "Each step must contain \"tool\", \"args\", and \"rationale\". "
                            "If no tool is needed, use \"steps\": []. Never omit the steps key. "
                            "Use only the exact registered tool names and argument schemas."
                        ),
                    )
                )
        raise PlanError(last_error)

    def _parse(self, text: str) -> Plan:
        text = (text or "").strip()
        if not text:
            raise PlanError("planner returned empty output")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = _extract_json_object(text)
        if not isinstance(data, dict):
            raise PlanError("planner output must be a JSON object")
        if "steps" not in data:
            raise PlanError("planner output is missing 'steps'")
        if not isinstance(data["steps"], list):
            raise PlanError("'steps' must be a list")
        try:
            return Plan.model_validate(data)
        except Exception as exc:
            raise PlanError(f"invalid plan shape: {exc}") from exc

    def _validate(self, plan: Plan, tools: list[dict[str, Any]] | None = None) -> None:
        if len(plan.steps) > self._settings.max_plan_steps:
            raise PlanError(
                f"plan has {len(plan.steps)} steps; limit is {self._settings.max_plan_steps}"
            )
        scope = {item["name"] for item in tools} if tools is not None else None
        for index, step in enumerate(plan.steps):
            if scope is not None and step.tool not in scope:
                raise PlanError(
                    f"step {index + 1} uses '{step.tool}', which is outside this agent's scope"
                )
            if not self._registry.has(step.tool):
                raise PlanError(f"step {index + 1} uses unknown tool '{step.tool}'")
            tool = self._registry.get(step.tool)
            errors = sorted(
                Draft202012Validator(tool.manifest.input_schema).iter_errors(step.args),
                key=lambda error: list(error.path),
            )
            if errors:
                first = errors[0]
                path = ".".join(str(part) for part in first.path) or "<root>"
                raise PlanError(
                    f"step {index + 1} ({step.tool}) has invalid args at {path}: {first.message}"
                )


def _extract_json_object(text: str) -> Any:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
            return value
        except json.JSONDecodeError:
            continue
    raise PlanError("planner output did not contain valid JSON")


def plan_from_steps(summary: str, steps: list[PlanStep]) -> Plan:
    return Plan(summary=summary, steps=steps)
