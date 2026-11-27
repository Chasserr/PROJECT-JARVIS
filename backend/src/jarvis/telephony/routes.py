"""HTTP surface for the phone gateway.

Two routers, deliberately separated:

- ``public`` (``/telephony/*``) is what the telephony provider calls. It has no
  bearer token because a vendor cannot send one; authenticity comes from the
  provider request signature plus the caller allowlist, and every failure is a
  403 with a generic spoken message.
- ``admin`` (``/api/v1/telephony/*``) is mounted behind the existing API token
  and exposes status, call inspection and outbound dialling.
"""

from __future__ import annotations

from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .base import TelephonyError
from .gateway import VoiceGateway

_TWIML = "application/xml"


def _signed_url(gateway: VoiceGateway, request: Request) -> str:
    """The URL the provider signed, which may differ from the loopback we see."""
    base = (gateway.settings.telephony_public_base_url or "").rstrip("/")
    if not base:
        return str(request.url)
    query = f"?{request.url.query}" if request.url.query else ""
    return base + request.url.path + query


async def _form(request: Request) -> dict[str, str]:
    """Parse Twilio's form body without requiring the multipart dependency.

    Providers post ``application/x-www-form-urlencoded``; reading the raw body and
    parsing it here keeps the gateway dependency-free and rejects anything else,
    which then fails signature verification.
    """
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/x-www-form-urlencoded"):
        return {}
    body = (await request.body()).decode("utf-8", "replace")
    return {key: value for key, value in parse_qsl(body, keep_blank_values=True)}


def _refusal() -> Response:
    return Response(
        content=(
            '<?xml version="1.0" encoding="UTF-8"?><Response>'
            "<Say>This call is not authorised.</Say><Hangup/></Response>"
        ),
        media_type=_TWIML,
        status_code=403,
    )


def build_telephony_routers(gateway: VoiceGateway) -> tuple[APIRouter, APIRouter]:
    public = APIRouter(prefix="/telephony", tags=["telephony"])
    admin = APIRouter(prefix="/telephony", tags=["telephony"])

    @public.post("/voice", response_class=Response)
    async def inbound_voice(request: Request) -> Response:
        """Entry point for an incoming call: greet, then listen for speech."""
        params = await _form(request)
        try:
            gateway.authorise(
                url=_signed_url(gateway, request),
                params=params,
                signature=request.headers.get("X-Twilio-Signature", ""),
            )
        except TelephonyError as exc:
            gateway.record_refusal("telephony.call.refused", str(exc))
            return _refusal()
        return Response(content=gateway.inbound(params), media_type=_TWIML)

    @public.post("/turn", response_class=Response)
    async def conversation_turn(request: Request) -> Response:
        """One spoken turn: hand the transcript to the agent and hold the line."""
        params = await _form(request)
        try:
            gateway.authorise(
                url=_signed_url(gateway, request),
                params=params,
                signature=request.headers.get("X-Twilio-Signature", ""),
            )
        except TelephonyError as exc:
            gateway.record_refusal("telephony.turn.refused", str(exc))
            return _refusal()
        return Response(content=gateway.turn(params), media_type=_TWIML)

    @public.post("/poll", response_class=Response)
    async def conversation_poll(request: Request) -> Response:
        """Wait for the agent run without inventing a result."""
        params = await _form(request)
        try:
            gateway.authorise(
                url=_signed_url(gateway, request),
                params=params,
                signature=request.headers.get("X-Twilio-Signature", ""),
            )
        except TelephonyError as exc:
            gateway.record_refusal("telephony.poll.refused", str(exc))
            return _refusal()
        return Response(content=gateway.poll(params), media_type=_TWIML)

    @admin.get("/status")
    def telephony_status() -> dict:
        return gateway.status()

    @admin.get("/calls")
    def telephony_calls() -> dict:
        calls = gateway.calls()
        return {"calls": calls, "count": len(calls)}

    @admin.post("/calls")
    async def place_call(payload: dict) -> dict:
        to = str(payload.get("to", "")).strip()
        message = str(payload.get("message", ""))[:1000]
        try:
            return await gateway.outbound(to=to, message=message)
        except TelephonyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return public, admin


__all__ = ["build_telephony_routers"]
