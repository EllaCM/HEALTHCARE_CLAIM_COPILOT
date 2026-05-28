"""Server-Sent Events helpers.

The underlying scripts return whole results (Anthropic calls are unary).
This module exists so progress events can be emitted around long-running
operations (e.g. /initial-screening) without blocking client UX. When
the scripts gain real streaming, swap the producers here.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any


def sse_pack(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def heartbeat_stream(
    work: asyncio.Future,
    *,
    heartbeat_secs: float = 5.0,
    result_event: str = "result",
) -> AsyncIterator[str]:
    """Yield SSE heartbeats while `work` (a Future) is running, then the result."""
    while not work.done():
        try:
            await asyncio.wait_for(asyncio.shield(work), timeout=heartbeat_secs)
        except asyncio.TimeoutError:
            yield sse_pack("ping", {"ts": asyncio.get_event_loop().time()})
            continue
    result = work.result()
    yield sse_pack(result_event, result)
