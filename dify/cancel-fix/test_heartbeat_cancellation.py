"""The real SSE keepalive must wake the client's idle stop check promptly."""

import asyncio
from datetime import UTC, datetime

import pytest

from dify_agent.client._client import DifyAgentStreamError, _raise_if_stream_stopped
from dify_agent.protocol.schemas import RunStartedEvent
from dify_agent.server.sse import sse_event_stream


def test_idle_backend_stream_wakes_stop_check_before_silent_tool_finishes():
    async def scenario():
        stop = asyncio.Event()
        initial_seen = asyncio.Event()
        tool_output = asyncio.Event()
        business_frames = []

        async def events():
            yield RunStartedEvent(id="1-0", run_id="idle-run", created_at=datetime.now(UTC))
            await tool_output.wait()

        stream = sse_event_stream(events())

        async def consume_like_api_client():
            try:
                async for frame in stream:
                    # The real client checks before its decoder discards comments.
                    _raise_if_stream_stopped("idle-run", deadline=None, should_stop=stop.is_set)
                    if frame.startswith("id:"):
                        business_frames.append(frame)
                        initial_seen.set()
            finally:
                await stream.aclose()

        consumer = asyncio.create_task(consume_like_api_client())
        await asyncio.wait_for(initial_seen.wait(), 2)
        stop.set()
        with pytest.raises(DifyAgentStreamError, match="cancelled by the caller"):
            await asyncio.wait_for(consumer, 2)
        assert len(business_frames) == 1, "Keepalive must not invent business events"
        assert not tool_output.is_set()

    asyncio.run(scenario())
