"""Step 09: 提取 sitekey，由 ctx.captcha 解题（逻辑在 project 编排）。"""

import re


async def extract_sitekey(page) -> str | None:
    sitekey = None
    for _ in range(10):
        sitekey = await page.evaluate(
            """() => {
            const widget = document.querySelector('[data-sitekey]');
            if (widget) return widget.getAttribute('data-sitekey');
            const iframe = document.querySelector('iframe[src*="hcaptcha"]');
            if (iframe) {
                const m = iframe.src.match(/sitekey=([^&]+)/);
                if (m) return m[1];
            }
            if (typeof hcaptcha !== 'undefined') {
                try { return hcaptcha.getConfig ? hcaptcha.getConfig().sitekey : null; } catch(e) {}
            }
            return null;
        }"""
        )
        if sitekey:
            return sitekey
        await page.wait_for_timeout(1000)
    for frame in page.frames:
        if "hcaptcha" in frame.url:
            m_obj = re.search(r"sitekey=([a-f0-9-]+)", frame.url)
            if m_obj:
                return m_obj.group(1)
    return None


__all__ = ["extract_sitekey"]
