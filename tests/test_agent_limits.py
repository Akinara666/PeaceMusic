from __future__ import annotations

import asyncio

from peacemusic.modules.agent.limits import UserRateLimiter


def test_user_rate_limiter_uses_a_sliding_window() -> None:
    async def scenario() -> None:
        limiter = UserRateLimiter(window_seconds=0.01)
        key = (1, 2)

        assert await limiter.allow(key, 1) is True
        assert await limiter.allow(key, 1) is False
        await asyncio.sleep(0.02)
        assert await limiter.allow(key, 1) is True

    asyncio.run(scenario())
