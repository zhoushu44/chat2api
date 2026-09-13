from __future__ import annotations

from collections.abc import Iterable


async def click_by_text(page, keywords: Iterable[str]) -> str | None:
    words = [str(item).strip().lower() for item in keywords if str(item).strip()]
    return await page.evaluate(
        r"""(words) => {
            const visible = (node) => {
                if (!node || node.disabled || node.getAttribute('aria-disabled') === 'true') return false;
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const text = (node) => [node.innerText, node.textContent, node.value,
                node.getAttribute('aria-label'), node.getAttribute('title')]
                .filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
            const nodes = Array.from(document.querySelectorAll(
                'button, a, [role="button"], input[type="submit"]'
            )).filter(visible);
            const hit = nodes.find((node) => {
                const value = text(node).toLowerCase().replace(/\s+/g, ' ');
                return words.some((word) => value.includes(word));
            });
            if (!hit) return null;
            hit.focus();
            hit.click();
            return text(hit) || 'clicked';
        }""",
        words,
    )


async def fill_first(page, selectors: Iterable[str], value: str, timeout: float = 30) -> str:
    joined = ", ".join(selectors)
    locator = page.locator(joined)
    await locator.first.wait_for(state="visible", timeout=timeout * 1000)
    count = await locator.count()
    for idx in range(count):
        item = locator.nth(idx)
        if await item.is_visible() and await item.is_enabled():
            await item.fill(value)
            await item.dispatch_event("input")
            await item.dispatch_event("change")
            return joined
    raise RuntimeError(f"未找到可填写输入框: {joined}")


async def submit_near(page, keywords: Iterable[str]) -> str:
    clicked = await click_by_text(page, keywords)
    if clicked:
        return clicked
    submitted = await page.evaluate(
        """() => {
            const active = document.activeElement;
            const form = active && active.closest ? active.closest('form') : document.querySelector('form');
            if (!form) return false;
            if (form.requestSubmit) form.requestSubmit();
            else form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
            return true;
        }"""
    )
    if not submitted:
        raise RuntimeError("未找到可提交按钮或表单")
    return "form-submit"


async def force_set_value(page, selector: str, value: str) -> bool:
    return bool(
        await page.evaluate(
            """({selector, value}) => {
                const el = document.querySelector(selector);
                if (!el) return false;
                const proto = el instanceof HTMLTextAreaElement
                    ? HTMLTextAreaElement.prototype
                    : HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                if (setter) setter.call(el, value);
                else el.value = value;
                for (const type of ['input', 'change', 'blur']) {
                    el.dispatchEvent(new Event(type, { bubbles: true }));
                }
                return true;
            }""",
            {"selector": selector, "value": value},
        )
    )
