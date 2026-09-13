"""ChatGPT 2FA 设置步骤

功能:
- 检测是否已启用 2FA
- 如未启用，导航至安全设置页面
- 启用 TOTP 身份验证器
- 提取 TOTP secret (用于后续保活重登)
- 保存备用码
- 完成验证并提交

输出:
- totp_secret: TOTP 密钥 (用于保活重登)
- backup_codes: 备用码列表 (紧急恢复用)
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from ._browser import click_by_text


def _is_2fa_already_enabled(page_url: str) -> bool:
    """检查是否已启用 2FA"""
    url = (page_url or "").lower()
    # 如已在 2FA 管理页，说明已启用
    return "settings" in url and "2fa" in url


async def _navigate_to_security_settings(page) -> bool:
    """导航到安全设置页面
    
    流程:
    1. 点击头像/设置菜单
    2. 选择「设置」
    3. 选择「数据 controls」或「安全」
    """
    try:
        # 尝试直接导航到设置页
        await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2000)
        
        # 查找设置入口 (头像/菜单按钮)
        settings_selectors = [
            'button[aria-label*="设置"]',
            'button[aria-label*="Settings"]',
            '[data-testid="user-menu"]',
            'button[class*="user-menu"]',
            'div[class*="avatar"]',  # 头像
        ]
        
        settings_btn = None
        for selector in settings_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.is_visible(timeout=2000):
                    settings_btn = locator
                    break
            except Exception:
                continue
        
        if not settings_btn:
            # 尝试通过文本查找
            settings_texts = ("设置", "Settings", "设置", "设定")
            for text in settings_texts:
                try:
                    btn = page.locator(f'text={text}').first
                    if await btn.is_visible(timeout=1000):
                        settings_btn = btn
                        break
                except Exception:
                    continue
        
        if settings_btn:
            await settings_btn.click()
            await asyncio.sleep(1.0)
        
        # 在菜单中查找「设置」选项
        menu_items = [
            'a[href*="/settings"]',
            'button:has-text("设置")',
            'button:has-text("Settings")',
            '[role="menuitem"]:has-text("设置")',
            '[role="menuitem"]:has-text("Settings")',
        ]
        
        for selector in menu_items:
            try:
                item = page.locator(selector).first
                if await item.is_visible(timeout=1000):
                    await item.click()
                    await asyncio.sleep(1.5)
                    return True
            except Exception:
                continue
        
        # 兜底：直接导航到 settings 页
        await page.goto("https://chatgpt.com/settings", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2000)
        return True
        
    except Exception as e:
        print(f"导航到设置页失败：{e}")
        return False


async def _find_2fa_section(page, ctx) -> bool:
    """找到 2FA 设置区域
    
    返回：是否找到 2FA 设置入口
    """
    try:
        # 查找 2FA 相关文本
        fa_texts = [
            "双重验证",
            "双因素认证",
            "2FA",
            "Two-factor",
            "Two-step",
            "身份验证器",
            "Authenticator",
            "TOTP",
        ]
        
        for text in fa_texts:
            try:
                locator = page.locator(f'text={text}').first
                if await locator.is_visible(timeout=1500):
                    # 点击「启用」或「设置」按钮
                    await locator.scroll_into_view_if_needed()
                    await asyncio.sleep(0.5)
                    
                    # 查找附近的按钮
                    parent = locator.locator("..")
                    enable_btn = parent.locator(
                        'button:has-text("启用"), button:has-text("Enable"), '
                        'button:has-text("设置"), button:has-text("Set up")'
                    ).first
                    
                    if await enable_btn.is_visible(timeout=1000):
                        await enable_btn.click()
                        await asyncio.sleep(1.5)
                        return True
            except Exception:
                continue
        
        # 尝试通过设置面板查找
        # 查找「数据 controls」或「安全」标签页
        tab_selectors = [
            'button:has-text("数据 controls")',
            'button:has-text("Data controls")',
            'button:has-text("安全")',
            'button:has-text("Security")',
            'a:has-text("安全")',
        ]
        
        for selector in tab_selectors:
            try:
                tab = page.locator(selector).first
                if await tab.is_visible(timeout=1000):
                    await tab.click()
                    await asyncio.sleep(1.0)
                    break
            except Exception:
                continue
        
        return True
        
    except Exception as e:
        ctx.log(f"查找 2FA 区域失败：{e}")
        return False


async def _extract_totp_secret(page, ctx) -> str | None:
    """提取 TOTP secret
    
    方法:
    1. 查找二维码
    2. 从二维码的 alt 文本或 data-uri 中提取 secret
    3. 或从显示的文本中复制 secret
    
    返回：TOTP secret (如: JBSWY3DPEHPK3PXP)
    """
    try:
        # 等待二维码出现
        qr_selectors = [
            'img[alt*="QR"]',
            'img[src*="qr"]',
            'canvas[class*="qr"]',
            '[class*="qrcode"]',
            'svg[class*="qr"]',
        ]
        
        qr_element = None
        for selector in qr_selectors:
            try:
                element = page.locator(selector).first
                if await element.is_visible(timeout=2000):
                    qr_element = element
                    break
            except Exception:
                continue
        
        if qr_element:
            # 尝试从 img 的 src 或 alt 提取
            try:
                src = await qr_element.get_attribute("src")
                if src and "otpauth://" in src:
                    # otpauth://totp/...?secret=XXX&...
                    match = re.search(r"secret=([A-Z0-9]+)", src)
                    if match:
                        secret = match.group(1)
                        ctx.log(f"从二维码提取 TOTP secret: {secret[:4]}****")
                        return secret
            except Exception:
                pass
            
            # 尝试从 canvas 或 svg 提取 (较复杂，先跳过)
        
        # 查找显示的 secret 文本 (通常格式: XXXX-XXXX-XXXX-XXXX)
        secret_patterns = [
            r"([A-Z]{4}-[A-Z]{4}-[A-Z]{4}-[A-Z]{4})",
            r"secret[:\s]+([A-Z0-9]+)",
            r"密钥[:\s]+([A-Z0-9]+)",
        ]
        
        page_text = await page.evaluate("() => document.body.innerText")
        for pattern in secret_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                secret = match.group(1).replace("-", "")
                ctx.log(f"从页面文本提取 TOTP secret: {secret[:4]}****")
                return secret
        
        # 尝试从输入框读取
        try:
            secret_input = page.locator('input[readonly], input[class*="secret"]').first
            if await secret_input.is_visible(timeout=1000):
                secret = await secret_input.input_value()
                if secret and len(secret) >= 16:
                    ctx.log(f"从输入框读取 TOTP secret: {secret[:4]}****")
                    return secret
        except Exception:
            pass
        
        ctx.log("未能提取 TOTP secret")
        return None
        
    except Exception as e:
        ctx.log(f"提取 TOTP secret 失败：{e}")
        return None


async def _save_backup_codes(page, ctx) -> list[str]:
    """保存备用码
    
    返回：备用码列表
    """
    try:
        # 查找备用码区域
        backup_texts = [
            "备用码",
            "Backup codes",
            "恢复代码",
            "Recovery codes",
            "备用代码",
        ]
        
        backup_section = None
        for text in backup_texts:
            try:
                locator = page.locator(f'text={text}').first
                if await locator.is_visible(timeout=1500):
                    backup_section = locator
                    break
            except Exception:
                continue
        
        if not backup_section:
            ctx.log("未找到备用码区域")
            return []
        
        # 查找备用码列表 (通常是 8-10 个 8 位代码)
        code_patterns = [
            r'\b([A-Z0-9]{8}-[A-Z0-9]{4})\b',
            r'\b([A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})\b',
        ]
        
        page_text = await page.evaluate("() => document.body.innerText")
        codes = []
        for pattern in code_patterns:
            matches = re.findall(pattern, page_text)
            for match in matches:
                code = match.replace("-", "")
                if len(code) == 8 and code not in codes:
                    codes.append(code)
        
        if codes:
            ctx.log(f"提取到 {len(codes)} 个备用码")
        
        return codes
        
    except Exception as e:
        ctx.log(f"保存备用码失败：{e}")
        return []


async def _verify_and_enable(page, ctx, timeout: float = 30) -> bool:
    """验证并启用 2FA
    
    需要用户或自动化输入 TOTP 代码
    由于需要实时 TOTP，这里只做页面等待
    
    返回：是否成功启用
    """
    try:
        # 查找验证输入框
        input_selectors = [
            'input[type="text"][maxlength="6"]',
            'input[placeholder*="6"]',
            'input[aria-label*="code"]',
            'input[name="code"]',
        ]
        
        code_input = None
        for selector in input_selectors:
            try:
                element = page.locator(selector).first
                if await element.is_visible(timeout=2000):
                    code_input = element
                    break
            except Exception:
                continue
        
        if not code_input:
            ctx.log("未找到 2FA 验证输入框")
            return False
        
        # 等待用户手动输入或使用外部 TOTP 生成器
        # 这里设置一个等待时间，让用户有时间处理
        ctx.log("等待 2FA 验证完成...")
        
        # 查找提交按钮
        submit_selectors = [
            'button:has-text("验证")',
            'button:has-text("Verify")',
            'button:has-text("确认")',
            'button:has-text("Confirm")',
            'button[type="submit"]',
        ]
        
        for _ in range(int(timeout / 2)):
            # 检查是否已完成 (成功提示或页面跳转)
            url = (page.url or "").lower()
            if "settings" in url and "2fa" in url and "enabled" in url:
                ctx.log("2FA 已启用")
                return True
            
            # 查找成功提示
            success_texts = ["已启用", "Enabled", "成功", "Success", "已激活", "Activated"]
            for text in success_texts:
                try:
                    msg = page.locator(f'text={text}').first
                    if await msg.is_visible(timeout=500):
                        ctx.log("2FA 启用成功")
                        return True
                except Exception:
                    continue
            
            await asyncio.sleep(2)
        
        ctx.log("2FA 验证超时")
        return False
        
    except Exception as e:
        ctx.log(f"验证 2FA 失败：{e}")
        return False


async def run(page, ctx, *, timeout: float = 120, enable_2fa: bool = True) -> dict[str, Any] | None:
    """执行 2FA 设置
    
    参数:
        enable_2fa: 是否启用 2FA (默认 True)
        timeout: 超时时间 (秒)
    
    返回:
        {
            "enabled": bool,  # 是否成功启用
            "totp_secret": str | None,  # TOTP secret
            "backup_codes": list[str],  # 备用码
        }
    """
    if not enable_2fa:
        ctx.log("跳过 2FA 设置 (enable_2fa=False)")
        return None
    
    ctx.log("开始 2FA 设置流程...")
    deadline = time.monotonic() + timeout
    result: dict[str, Any] = {
        "enabled": False,
        "totp_secret": None,
        "backup_codes": [],
    }
    
    try:
        # 1. 检查是否已启用 2FA
        if _is_2fa_already_enabled(page.url):
            ctx.log("检测到已在 2FA 设置页，可能已启用")
            result["enabled"] = True
            return result
        
        # 2. 导航到安全设置
        ctx.log("导航到安全设置页面...")
        if not await _navigate_to_security_settings(page):
            ctx.log("导航到设置页失败，跳过 2FA 设置")
            return None
        
        # 3. 找到 2FA 设置区域
        ctx.log("查找 2FA 设置区域...")
        if not await _find_2fa_section(page, ctx):
            ctx.log("未找到 2FA 设置入口，可能页面结构不同")
            return None
        
        # 4. 点击启用 2FA
        # (已在 _find_2fa_section 中处理)
        
        # 5. 提取 TOTP secret
        ctx.log("提取 TOTP secret...")
        totp_secret = await _extract_totp_secret(page, ctx)
        if totp_secret:
            result["totp_secret"] = totp_secret
            ctx.log(f"TOTP secret: {totp_secret[:4]}**** (共{len(totp_secret)}位)")
        else:
            ctx.log("未能提取 TOTP secret，但仍继续流程")
        
        # 6. 保存备用码
        ctx.log("保存备用码...")
        backup_codes = await _save_backup_codes(page, ctx)
        if backup_codes:
            result["backup_codes"] = backup_codes
        
        # 7. 验证并启用 2FA
        ctx.log("等待 2FA 验证完成...")
        remaining_time = max(30, deadline - time.monotonic())
        enabled = await _verify_and_enable(page, ctx, timeout=remaining_time)
        result["enabled"] = enabled
        
        if enabled:
            ctx.log("✅ 2FA 设置完成")
            if result["totp_secret"]:
                ctx.log(f"  TOTP: {result['totp_secret'][:4]}****")
            if result["backup_codes"]:
                ctx.log(f"  备用码：{len(result['backup_codes'])} 个")
        else:
            ctx.log("⚠️ 2FA 设置未完成 (可能需手动验证)")
        
        return result
        
    except Exception as e:
        ctx.log(f"2FA 设置失败：{e}")
        return result
