"""Telephony tests.

Nothing here dials a real number. The signature algorithm is checked against
Twilio's published example, the call flow runs against a scripted agent, and the
outbound call uses a mock transport so we assert the exact REST payload without
spending money.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from jarvis.api.app import create_app
from jarvis.config import Settings
from jarvis.llm.base import LLMResponse
from jarvis.security.permissions import PermissionTier
from jarvis.telephony.base import TelephonyError
from jarvis.telephony.gateway import VoiceGateway, normalise_number, spoken_result
from jarvis.telephony.routes import build_telephony_routers
from jarvis.telephony.twilio import TwilioProvider, signature_for, twiml_response

TOKEN = "12345"
PUBLIC = "https://jarvis.example.com"
CALLER = "+15550109999"
NUMBER = "+15550100000"


class NullLLM:
    model = "null-model"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, **kwargs) -> LLMResponse:
        self.calls += 1
        raise AssertionError("telephony tests must not call the model")


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "data_dir": tmp_path,
        "database_path": tmp_path / "telephony.sqlite3",
        "master_key": base64.b64encode(b"k" * 32).decode(),
        "api_token": None,
        "brave_api_key": None,
        "ollama_embed_model": "",
        "capability_probes": False,
        "telephony_provider": "twilio",
        "telephony_public_base_url": PUBLIC,
        "telephony_allowed_callers": [CALLER],
        "telephony_poll_seconds": 1,
        "telephony_max_polls": 2,
        "twilio_account_sid": "AC" + "0" * 32,
        "twilio_auth_token": TOKEN,
        "twilio_from_number": NUMBER,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def answered(answer: str = "It is noon."):
    async def run(goal: str) -> dict[str, Any]:
        assert goal
        return {"id": "run-1", "status": "completed", "answer": answer}

    return run


def gateway_for(tmp_path: Path, runner=None, **overrides: Any) -> VoiceGateway:
    return VoiceGateway(
        make_settings(tmp_path, **overrides), runner=runner or answered()
    )


def signed_post(client: AsyncClient, path: str, params: Mapping[str, str]):
    url = PUBLIC + path
    return client.post(
        path,
        data=dict(params),
        headers={"X-Twilio-Signature": signature_for(TOKEN, url, params)},
    )


def bare_app(gateway: VoiceGateway) -> FastAPI:
    app = FastAPI()
    public, admin = build_telephony_routers(gateway)
    app.include_router(public)
    app.include_router(admin)
    return app


def test_signature_matches_twilio_published_example() -> None:
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+12349013030",
        "Digits": "1234",
        "From": "+12349013030",
        "To": "+18005551212",
    }
    assert (
        signature_for("12345", "https://mycompany.com/myapp.php?foo=1&bar=2", params)
        == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="
    )


def test_signature_rejects_tampering_and_a_wrong_token(tmp_path: Path) -> None:
    provider = TwilioProvider(make_settings(tmp_path))
    url = PUBLIC + "/telephony/voice"
    params = {"From": CALLER, "CallSid": "CA1", "SpeechResult": "hello"}
    good = signature_for(TOKEN, url, params)
    assert provider.verify_signature(url, params, good)
    assert not provider.verify_signature(url, {**params, "SpeechResult": "evil"}, good)
    assert not provider.verify_signature(url, params, signature_for("other", url, params))
    assert not provider.verify_signature(url, params, "")


def test_twiml_escapes_spoken_text() -> None:
    document = twiml_response(say='A & B <script> "quoted"')
    assert document.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "&amp;" in document
    assert "&lt;script&gt;" in document
    assert '"quoted"' in document
    assert "<script>" not in document


def test_twiml_gathers_with_a_redirect_and_hangup() -> None:
    document = twiml_response(
        prompt="Say something", gather_action="https://x.test/telephony/turn", redirect="https://x.test/p"
    )
    assert '<Gather input="speech" action="https://x.test/telephony/turn"' in document
    assert "<Redirect method=\"POST\">https://x.test/p</Redirect>" in document
    assert "<Hangup/>" not in document
    assert "<Hangup/>" in twiml_response(say="bye", hangup=True)


def test_status_lists_every_missing_setting(tmp_path: Path) -> None:
    gateway = VoiceGateway(
        make_settings(
            tmp_path,
            telephony_provider="none",
            telephony_public_base_url=None,
            twilio_account_sid=None,
            twilio_auth_token=None,
            twilio_from_number=None,
            telephony_allowed_callers=[],
        ),
        runner=answered(),
    )
    status = gateway.status()
    assert status["configured"] is False
    assert status["provider"] == "none"
    assert status["missing"] == ["JARVIS_TELEPHONY_PROVIDER"]
    assert status["authorised_callers"] == 0


def test_configured_provider_without_callers_is_still_unconfigured(tmp_path: Path) -> None:
    gateway = gateway_for(tmp_path, telephony_allowed_callers=[])
    status = gateway.status()
    assert status["configured"] is False
    assert status["missing"] == ["JARVIS_TELEPHONY_ALLOWED_CALLERS"]


async def test_inbound_rejects_a_bad_signature(tmp_path: Path) -> None:
    app = bare_app(gateway_for(tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/telephony/voice",
            data={"From": CALLER, "CallSid": "CA1"},
            headers={"X-Twilio-Signature": "not-a-signature"},
        )
    assert response.status_code == 403
    assert "not authorised" in response.text


async def test_inbound_rejects_an_unauthorised_caller(tmp_path: Path) -> None:
    app = bare_app(gateway_for(tmp_path))
    transport = ASGITransport(app=app)
    params = {"From": "+15550000000", "CallSid": "CA1"}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await signed_post(client, "/telephony/voice", params)
    assert response.status_code == 403


async def test_inbound_accepts_an_authorised_caller(tmp_path: Path) -> None:
    app = bare_app(gateway_for(tmp_path))
    transport = ASGITransport(app=app)
    params = {"From": CALLER, "CallSid": "CA1"}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await signed_post(client, "/telephony/voice", params)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<Gather" in response.text
    assert "JARVIS here" in response.text
    assert PUBLIC + "/telephony/turn" in response.text


async def test_a_turn_is_delegated_then_read_back(tmp_path: Path) -> None:
    gateway = gateway_for(tmp_path, runner=answered("The time is noon."))
    app = bare_app(gateway)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await signed_post(client, "/telephony/voice", {"From": CALLER, "CallSid": "CA9"})
        turn = await signed_post(
            client,
            "/telephony/turn",
            {"From": CALLER, "CallSid": "CA9", "SpeechResult": "what time is it"},
        )
        assert turn.status_code == 200
        assert "One moment" in turn.text
        assert PUBLIC + "/telephony/poll" in turn.text
        await asyncio.sleep(0.05)
        polled = await signed_post(client, "/telephony/poll", {"From": CALLER, "CallSid": "CA9"})
    assert polled.status_code == 200
    assert "The time is noon." in polled.text
    assert PUBLIC + "/telephony/turn" in polled.text
    assert gateway.calls()[0]["status"] == "listening"
    assert gateway.calls()[0]["turns"] == 1


async def test_an_empty_transcript_asks_again(tmp_path: Path) -> None:
    gateway = gateway_for(tmp_path)
    app = bare_app(gateway)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await signed_post(client, "/telephony/voice", {"From": CALLER, "CallSid": "CA2"})
        response = await signed_post(
            client, "/telephony/turn", {"From": CALLER, "CallSid": "CA2"}
        )
    assert "did not catch that" in response.text
    assert gateway.calls()[0]["status"] == "listening"


async def test_a_slow_run_is_abandoned_instead_of_guessed(tmp_path: Path) -> None:
    never = asyncio.Event()

    async def slow(goal: str) -> dict[str, Any]:
        await never.wait()
        return {"status": "completed", "answer": "too late"}

    gateway = gateway_for(tmp_path, runner=slow)
    app = bare_app(gateway)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await signed_post(client, "/telephony/voice", {"From": CALLER, "CallSid": "CA3"})
        await signed_post(
            client, "/telephony/turn", {"From": CALLER, "CallSid": "CA3", "SpeechResult": "long job"}
        )
        for _ in range(3):
            response = await signed_post(
                client, "/telephony/poll", {"From": CALLER, "CallSid": "CA3"}
            )
    never.set()
    assert "taking longer than the call allows" in response.text
    assert gateway.calls()[0]["status"] == "abandoned"


async def test_a_timed_out_run_says_so(tmp_path: Path) -> None:
    async def sleepy(goal: str) -> dict[str, Any]:
        await asyncio.sleep(2)
        return {"status": "completed", "answer": "late"}

    gateway = gateway_for(tmp_path, runner=sleepy, telephony_turn_timeout_s=0.05)
    app = bare_app(gateway)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await signed_post(client, "/telephony/voice", {"From": CALLER, "CallSid": "CA4"})
        await signed_post(
            client, "/telephony/turn", {"From": CALLER, "CallSid": "CA4", "SpeechResult": "slow"}
        )
        await asyncio.sleep(0.2)
        response = await signed_post(
            client, "/telephony/poll", {"From": CALLER, "CallSid": "CA4"}
        )
    assert "took longer than I can hold the call" in response.text


def test_spoken_result_is_honest_about_each_outcome() -> None:
    assert spoken_result({"status": "completed", "answer": "done it"}) == "done it"
    assert "no answer to read back" in spoken_result({"status": "completed", "answer": ""})
    assert "approval" in spoken_result({"status": "awaiting_approval"})
    assert spoken_result({"status": "failed", "error": "boom"}).startswith("That did not complete")
    assert "cancelled" in spoken_result({"status": "cancelled"})


def test_numbers_are_normalised_for_comparison() -> None:
    assert normalise_number("+1 (555) 010-9999") == "+15550109999"
    assert normalise_number("+15550109999") == "+15550109999"


async def test_outbound_refuses_when_unconfigured(tmp_path: Path) -> None:
    gateway = gateway_for(tmp_path, telephony_provider="none")
    with pytest.raises(TelephonyError, match="not configured"):
        await gateway.outbound(to=CALLER, message="hello")


async def test_outbound_requires_e164(tmp_path: Path) -> None:
    gateway = gateway_for(tmp_path)
    with pytest.raises(TelephonyError, match="E.164"):
        await gateway.outbound(to="555 0100", message="hello")


async def test_outbound_posts_the_documented_twilio_payload(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        return httpx.Response(
            201,
            json={"sid": "CA42", "status": "queued", "to": CALLER, "from": NUMBER},
        )

    settings = make_settings(tmp_path)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=settings.twilio_api_url,
    )
    provider = TwilioProvider(settings, client=client)
    call = await provider.create_call(to=CALLER, url=PUBLIC + "/telephony/voice", message="Calling")
    await client.aclose()

    assert seen["method"] == "POST"
    assert seen["path"].endswith("/Calls.json")
    assert "To=%2B15550109999" in seen["body"]
    assert "From=%2B15550100000" in seen["body"]
    assert "Twiml=" in seen["body"]
    assert call == {
        "sid": "CA42",
        "status": "queued",
        "to": CALLER,
        "from": NUMBER,
        "provider": "twilio",
    }


def test_phone_call_tool_is_approval_gated(tmp_path: Path) -> None:
    from jarvis.container import build_container

    container = build_container(make_settings(tmp_path), llm=NullLLM(), embeddings=None)
    manifest = next(item for item in container.registry.manifests() if item.name == "phone.call")
    assert manifest.permission is PermissionTier.CONFIRM
    assert manifest.dangerous is True


def test_api_exposes_telephony_status(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path), llm=NullLLM(), embeddings=None)
    transport = ASGITransport(app=app)
    with_client = AsyncClient(transport=transport, base_url="http://testserver")

    async def check() -> None:
        async with with_client as client:
            response = await client.get("/api/v1/telephony/status")
        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is True
        assert body["provider"] == "twilio"
        assert body["missing"] == []

    asyncio.run(check())


async def test_probe_reports_telephony_as_unconfigured() -> None:
    from jarvis.capabilities import probe_telephony

    probe = await probe_telephony(Settings(_env_file=None, telephony_provider="none"))
    assert probe["available"] is False
    assert "JARVIS_TELEPHONY_PROVIDER" in probe["error"]
