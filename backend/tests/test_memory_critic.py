from jarvis.agent.llm_planner import LLMCritic


class NoCallProvider:
    name = "test"

    async def complete(self, messages, *, temperature=0.2, max_tokens=1200):
        raise AssertionError("Memory-only verification must not call the LLM")


async def test_critic_verifies_structured_memory_search_result():
    verified, note = await LLMCritic(NoCallProvider()).verify(
        "Find my saved JARVIS preferences.",
        [{
            "skill_id": "memory.search",
            "result": {"memories": [{"content": "local-first"}, {"content": "approval first"}]},
        }],
    )

    assert verified
    assert "2 matching records" in note
