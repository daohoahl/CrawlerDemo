from __future__ import annotations

import httpx


def make_client(user_agent: str, timeout_s: float) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": user_agent, "Accept": "*/*"},
        timeout=httpx.Timeout(timeout_s),
        follow_redirects=True,
    )

