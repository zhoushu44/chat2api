from __future__ import annotations


async def run(page) -> None:
    button = page.locator("button.primary-button")
    await button.wait_for(state="visible", timeout=20_000)
    await button.click()
    await page.wait_for_url("**/register/success**", timeout=30_000)
