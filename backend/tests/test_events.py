import asyncio

import pytest

from jarvis.events import Event, EventBus


@pytest.mark.asyncio
async def test_event_bus_roundtrip():
    bus = EventBus()
    event = Event("test.event", {"ok": True})
    await bus.publish(event)
    received = await bus.next_event()
    assert received.id == event.id
    bus.task_done()
    await bus.join()
    bus.close()


def test_event_bus_rejects_publish_after_close():
    async def scenario():
        bus = EventBus()
        bus.close()
        with pytest.raises(RuntimeError):
            await bus.publish(Event("late"))
    asyncio.run(scenario())
