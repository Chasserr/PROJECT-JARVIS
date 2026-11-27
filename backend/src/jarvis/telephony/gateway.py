"""Call flow: verify, greet, listen, delegate, report.

The gateway speaks only what it can support. A run that needs approval is read
back as needing approval, a failed run is read back as failed, and a run that
outlives the call is left in the desktop console rather than guessed at.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ..config import Settings
from .base import CallState, TelephonyError, TelephonyProvider
from .twilio import TwilioProvider, twiml_response

Runner = Callable[[str], Awaitable[dict[str, Any]]]
AuditHook = Callable[[str, str, dict[str, Any]], None]

_CALL_LIMIT = 200
_NUMBER_RE = re.compile(r"[^0-9+]")
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def normalise_number(value: str) -> str:
    """Keep digits and a leading plus so +1 (555) 010-9999 matches +15550109999."""
    return _NUMBER_RE.sub("", value or "")


def build_provider(settings: Settings) -> TelephonyProvider | None:
    if settings.telephony_provider == "twilio":
        return TwilioProvider(settings)
    return None


def spoken_result(result: Mapping[str, Any]) -> str:
    """Turn one agent run into one honest sentence to read aloud."""
    status = str(result.get("status") or "")
    if status == "completed":
        answer = " ".join(str(result.get("answer") or "").split())
        return answer[:1200] or "The task completed, but there was no answer to read back."
    if status == "awaiting_approval":
        return "That needs your approval in the desktop console before I can go ahead."
    if status in {"cancelled", "canceled"}:
        return "That run was cancelled."
    error = " ".join(str(result.get("error") or status or "unknown error").split())
    return f"That did not complete: {error[:400]}"


class VoiceGateway:
    """Provider-independent inbound/outbound call handling."""

    def __init__(
        self,
        settings: Settings,
        *,
        runner: Runner,
        provider: TelephonyProvider | None = None,
        audit: AuditHook | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider if provider is not None else build_provider(settings)
        self._runner = runner
        self._audit = audit
        self._calls: dict[str, CallState] = {}

    # -- state -----------------------------------------------------------
    def missing_settings(self) -> list[str]:
        if self.provider is None:
            return ["JARVIS_TELEPHONY_PROVIDER"]
        missing = list(self.provider.missing_settings())
        if not self.settings.telephony_allowed_callers:
            missing.append("JARVIS_TELEPHONY_ALLOWED_CALLERS")
        return missing

    def status(self) -> dict[str, Any]:
        missing = self.missing_settings()
        return {
            "configured": not missing,
            "provider": self.provider.name if self.provider is not None else "none",
            "missing": missing,
            "voice": self.settings.telephony_voice,
            "language": self.settings.telephony_language,
            "authorised_callers": len(self.settings.telephony_allowed_callers),
            "active_calls": len(self._calls),
        }

    def calls(self) -> list[dict[str, Any]]:
        return [state.as_dict() for state in self._calls.values()]

    def public_url(self, path: str) -> str:
        base = (self.settings.telephony_public_base_url or "").rstrip("/")
        return base + path if base else path

    def _emit(self, action: str, outcome: str, detail: dict[str, Any]) -> None:
        if self._audit is not None:
            self._audit(action, outcome, detail)

    def record_refusal(self, action: str, reason: str) -> None:
        """Audit a refused webhook without leaking the reason to the caller."""
        self._emit(action, "error", {"reason": reason[:300]})

    def _remember(self, state: CallState) -> None:
        self._calls[state.sid] = state
        while len(self._calls) > _CALL_LIMIT:
            oldest = min(self._calls.values(), key=lambda item: item.started_at)
            self._calls.pop(oldest.sid, None)

    # -- inbound ---------------------------------------------------------
    def authorise(
        self, *, url: str, params: Mapping[str, str], signature: str
    ) -> None:
        """Refuse anything that is not a signed request from an allowed caller."""
        if self.provider is None:
            raise TelephonyError("no telephony provider is configured")
        missing = self.missing_settings()
        if missing:
            raise TelephonyError("telephony is not configured: " + ", ".join(missing))
        if not self.provider.verify_signature(url, params, signature):
            raise TelephonyError("invalid telephony request signature")
        caller = normalise_number(params.get("From", ""))
        allowed = {normalise_number(item) for item in self.settings.telephony_allowed_callers}
        if not caller or caller not in allowed:
            raise TelephonyError("caller is not authorised")

    def _twiml(self, **kwargs: Any) -> str:
        options: dict[str, Any] = {
            "voice": self.settings.telephony_voice,
            "language": self.settings.telephony_language,
            "speech_timeout": self.settings.telephony_speech_timeout_s,
        }
        options.update(kwargs)
        return twiml_response(**options)

    def inbound(self, params: Mapping[str, str]) -> str:
        caller = params.get("From", "")
        sid = params.get("CallSid") or f"local-{int(time.time() * 1000)}"
        self._remember(CallState(sid=sid, caller=caller, status="listening"))
        self._emit("telephony.call.received", "ok", {"call_sid": sid, "caller": caller})
        return self._twiml(
            prompt=self.settings.telephony_greeting,
            gather_action=self.public_url("/telephony/turn"),
        )

    # -- conversation ----------------------------------------------------
    def turn(self, params: Mapping[str, str]) -> str:
        sid = params.get("CallSid", "")
        state = self._calls.get(sid)
        if state is None:
            return self._twiml(say="This call is no longer active.", hangup=True)
        if state.task is not None and not state.task.done():
            return self._twiml(
                say="I am still working on the previous request.",
                redirect=self.public_url("/telephony/poll"),
            )
        speech = " ".join((params.get("SpeechResult") or "").split())
        if not speech:
            return self._twiml(
                prompt="I did not catch that. Please say it again.",
                gather_action=self.public_url("/telephony/turn"),
            )
        state.transcript.append(speech)
        state.status = "working"
        state.polls = 0
        state.reply = ""
        state.task = asyncio.create_task(self._run(state, speech))
        self._emit(
            "telephony.turn.received", "ok", {"call_sid": sid, "chars": len(speech)}
        )
        return self._twiml(say="One moment.", redirect=self.public_url("/telephony/poll"))

    async def _run(self, state: CallState, speech: str) -> None:
        try:
            result = await asyncio.wait_for(
                self._runner(speech), timeout=self.settings.telephony_turn_timeout_s
            )
        except TimeoutError:
            state.status = "timed_out"
            state.reply = (
                "That took longer than I can hold the call. The result will be in the "
                "desktop console."
            )
            self._emit("telephony.run.timed_out", "error", {"call_sid": state.sid})
            return
        except Exception as exc:  # noqa: BLE001 - spoken back as state
            state.status = "failed"
            state.reply = f"That failed: {type(exc).__name__}."
            self._emit(
                "telephony.run.failed",
                "error",
                {"call_sid": state.sid, "error": f"{type(exc).__name__}: {exc}"[:300]},
            )
            return
        state.run_id = str(result.get("id") or result.get("run_id") or "") or None
        state.reply = spoken_result(result)
        state.status = "done"
        self._emit(
            "telephony.run.completed",
            "ok",
            {"call_sid": state.sid, "run_id": state.run_id, "status": result.get("status")},
        )

    def poll(self, params: Mapping[str, str]) -> str:
        sid = params.get("CallSid", "")
        state = self._calls.get(sid)
        if state is None:
            return self._twiml(say="This call is no longer active.", hangup=True)
        if state.task is not None and not state.task.done():
            state.polls += 1
            if state.polls > self.settings.telephony_max_polls:
                state.status = "abandoned"
                return self._twiml(
                    say=(
                        "This is taking longer than the call allows. I will leave the "
                        "result in the desktop console. Goodbye."
                    ),
                    hangup=True,
                )
            return self._twiml(
                pause=self.settings.telephony_poll_seconds,
                redirect=self.public_url("/telephony/poll"),
            )
        reply = state.reply or "I have no result to read back."
        state.task = None
        state.polls = 0
        state.status = "listening"
        return self._twiml(
            prompt=reply,
            gather_action=self.public_url("/telephony/turn"),
        )

    # -- outbound --------------------------------------------------------
    async def outbound(self, *, to: str, message: str = "") -> dict[str, Any]:
        provider = self.provider
        missing = self.missing_settings()
        if provider is None or missing:
            raise TelephonyError(
                "telephony is not configured: "
                + ", ".join(missing or ["JARVIS_TELEPHONY_PROVIDER"])
            )
        number = normalise_number(to)
        if not _E164_RE.match(number):
            raise TelephonyError(
                "a destination number in E.164 format is required, e.g. +15551234567"
            )
        call = await provider.create_call(
            to=number, url=self.public_url("/telephony/voice"), message=message
        )
        self._emit(
            "telephony.call.placed", "ok", {"call_sid": call.get("sid"), "to": number}
        )
        return call


__all__ = [
    "AuditHook",
    "Runner",
    "VoiceGateway",
    "build_provider",
    "normalise_number",
    "spoken_result",
]
