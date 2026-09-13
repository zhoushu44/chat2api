from __future__ import annotations


async def run(page) -> None:
    checkbox = page.locator('input[type="checkbox"]').first
    await checkbox.wait_for(state="attached", timeout=20_000)
    if not await checkbox.is_checked():
        await checkbox.check()
