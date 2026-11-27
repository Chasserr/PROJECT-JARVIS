"""Twilio adapter: request signatures, TwiML, and the Calls REST API.

Only the documented algorithms and endpoints are used. ``create_call`` returns
what Twilio actually answered; an HTTP error is raised as ``TelephonyError`` with
Twilio's own message, never softened into a success.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import httpx

from ..config import Settings
from .base import TelephonyError

_CALLS_PATH = "/2010-04-01/Accounts/{sid}/Calls.json"
_ACCOUNT_PATH = "/2010-04-01/Accounts/{sid}.json"
_MAX_SAY_CHARS = 1500


def signature_for(auth_token: str, url: str, params: Mapping[str, str]) -> str:
    """Twilio's documented request signature: HMAC-SHA1 over URL + sorted params."""
    payload = url + "".join(f"{key}{value}" for key, value in sorted(params.items()))
    digest = hmac.new(
        auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def _say(text: str, voice: str, language: str) -> str:
    spoken = escape(" ".join(str(text).split())[:_MAX_SAY_CHARS])
    return f"<Say voice={quoteattr(voice)} language={quoteattr(language)}>{spoken}</Say>"


def twiml_response(
    *,
    say: str = "",
    prompt: str = "",
    gather_action: str = "",
    redirect: str = "",
    pause: int = 0,
    hangup: bool = False,
    voice: str = "Polly.Matthew",
    language: str = "en-US",
    speech_timeout: int = 3,
) -> str:
    """Build one TwiML document.

    ``prompt`` is spoken *inside* ``<Gather>`` so the caller can speak while it
    plays; ``say`` is spoken before any gather. ``redirect`` hands control back
    to the gateway for polling or the next turn.
    """
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<Response>"]
    if say:
        parts.append(_say(say, voice, language))
    if pause:
        parts.append(f'<Pause length="{int(pause)}"/>')
    if gather_action:
        parts.append(
            "<Gather "
            f'input="speech" action={quoteattr(gather_action)} method="POST" '
            f'speechTimeout={quoteattr(str(speech_timeout))} '
            f'language={quoteattr(language)} timeout="8">'
        )
        if prompt:
            parts.append(_say(prompt, voice, language))
        parts.append("</Gather>")
        if not prompt:
            # An empty Gather would leave the caller in silence; ask again.
            parts.append(_say("Are you still there?", voice, language))
    if redirect:
        parts.append(f'<Redirect method="POST">{escape(redirect)}</Redirect>')
    if hangup:
        parts.append("<Hangup/>")
    parts.append("</Response>")
    return "".join(parts)


class TwilioProvider:
    """Twilio implementation of :class:`jarvis.telephony.base.TelephonyProvider`."""

    name = "twilio"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    # -- configuration ---------------------------------------------------
    def missing_settings(self) -> list[str]:
        missing: list[str] = []
        if not self.settings.twilio_account_sid:
            missing.append("JARVIS_TWILIO_ACCOUNT_SID")
        if self.settings.twilio_auth_token is None:
            missing.append("JARVIS_TWILIO_AUTH_TOKEN")
        if not self.settings.twilio_from_number:
            missing.append("JARVIS_TWILIO_FROM_NUMBER")
        if not self.settings.telephony_public_base_url:
            missing.append("JARVIS_TELEPHONY_PUBLIC_BASE_URL")
        return missing

    def verify_signature(
        self, url: str, params: Mapping[str, str], signature: str
    ) -> bool:
        token = self.settings.twilio_auth_token
        if token is None or not signature:
            return False
        expected = signature_for(token.get_secret_value(), url, params)
        return hmac.compare_digest(expected, signature)

    # -- HTTP ------------------------------------------------------------
    def _client_or_new(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        token = self.settings.twilio_auth_token
        return httpx.AsyncClient(
            base_url=self.settings.twilio_api_url.rstrip("/"),
            auth=(
                self.settings.twilio_account_sid or "",
                token.get_secret_value() if token else "",
            ),
            timeout=20.0,
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        client = self._client_or_new()
        owns_client = self._client is None
        try:
            response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise TelephonyError(f"Twilio is unreachable: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code >= 400:
            try:
                detail = response.json().get("message") or response.text
            except ValueError:
                detail = response.text
            raise TelephonyError(
                f"Twilio rejected the request ({response.status_code}): {str(detail)[:500]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise TelephonyError("Twilio returned a non-JSON response") from exc

    async def account(self) -> dict[str, Any]:
        sid = self.settings.twilio_account_sid or ""
        if not sid:
            raise TelephonyError("JARVIS_TWILIO_ACCOUNT_SID is not set")
        return await self._request("GET", _ACCOUNT_PATH.format(sid=sid))

    async def create_call(
        self, *, to: str, url: str, message: str = ""
    ) -> dict[str, Any]:
        missing = self.missing_settings()
        if missing:
            raise TelephonyError("telephony is not configured: " + ", ".join(missing))
        payload: dict[str, str] = {
            "To": to,
            "From": self.settings.twilio_from_number or "",
        }
        if message.strip():
            # Announce first, then hand the call to the normal voice webhook.
            payload["Twiml"] = twiml_response(
                say=message,
                redirect=url,
                voice=self.settings.telephony_voice,
                language=self.settings.telephony_language,
            )
        else:
            payload["Url"] = url
        body = await self._request(
            "POST",
            _CALLS_PATH.format(sid=self.settings.twilio_account_sid),
            data=payload,
        )
        return {
            "sid": body.get("sid"),
            "status": body.get("status"),
            "to": body.get("to", to),
            "from": body.get("from", payload["From"]),
            "provider": self.name,
        }


__all__ = ["TwilioProvider", "signature_for", "twiml_response"]
