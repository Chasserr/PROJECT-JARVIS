import pytest

from jarvis.providers.router import FallbackProvider


class FakeProvider:
    def __init__(self, name: str, result: str | None = None, fail: bool = False):
        self.name = name
        self.result = result
        self.fail = fail
        self.calls = 0

    async def complete(self, messages, *, temperature=0.2, max_tokens=1200):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} unavailable")
        return self.result or "ok"


async def test_router_uses_primary_when_available():
    primary = FakeProvider("claude", "cloud result")
    fallback = FakeProvider("local", "local result")
    router = FallbackProvider(primary, fallback)

    result = await router.complete([{"role": "user", "content": "hello"}])

    assert result == "cloud result"
    assert primary.calls == 1
    assert fallback.calls == 0
    assert router.last_provider == "claude"


async def test_router_falls_back_to_local_when_primary_fails():
    primary = FakeProvider("claude", fail=True)
    fallback = FakeProvider("lm_studio", "local result")
    router = FallbackProvider(primary, fallback)

    result = await router.complete([{"role": "user", "content": "hello"}])

    assert result == "local result"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert router.last_provider == "lm_studio"


async def test_router_reports_both_provider_failures_without_secrets():
    primary = FakeProvider("claude", fail=True)
    fallback = FakeProvider("local", fail=True)
    router = FallbackProvider(primary, fallback)

    with pytest.raises(RuntimeError, match="Primary and fallback AI providers are unavailable"):
        await router.complete([{"role": "user", "content": "hello"}])
