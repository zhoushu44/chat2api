from __future__ import annotations

import asyncio
import random
import time

from ._browser import click_by_text


def _rand_name() -> str:
    firsts = [
        "James", "John", "Robert", "Michael", "David", "William",
        "Mary", "Linda", "Barbara", "Jennifer", "Elizabeth", "Susan",
    ]
    lasts = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
        "Miller", "Davis", "Wilson", "Anderson", "Taylor", "Thomas",
    ]
    return f"{random.choice(firsts)} {random.choice(lasts)}"


def _rand_birthdate() -> str:
    """与 oumiFree 一致：YYYY-MM-DD，1985–2004。"""
    return f"{random.randint(1985, 2004)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"


def _is_navigation_interruption(exc: Exception) -> bool:
    text = str(exc).lower()
    return "execution context was destroyed" in text or "frame was detached" in text


def _on_profile_page(url: str) -> bool:
    value = (url or "").lower()
    return any(
        marker in value
        for marker in (
            "about-you",
            "create-account",
            "user-details",
            "complete-profile",
            "register",
        )
    )


def _entered_main_site(url: str) -> bool:
    value = (url or "").lower()
    if "chatgpt.com" not in value:
        return False
    if any(x in value for x in ("auth", "login", "signup", "authorize")):
        return False
    return True


async def _dump_profile_inputs(page) -> str:
    try:
        return str(
            await page.evaluate(
                """() => {
                    const visible = (node) => {
                        if (!node) return false;
                        const style = getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden'
                            && rect.width > 0 && rect.height > 0;
                    };
                    return Array.from(document.querySelectorAll('input, textarea, select, button'))
                        .filter(visible)
                        .map((el) => {
                            const tag = el.tagName.toLowerCase();
                            const type = el.type || '';
                            const name = el.name || el.id || '';
                            const ph = el.placeholder || '';
                            const text = (el.innerText || el.value || '').trim().slice(0, 40);
                            return `${tag}[type=${type} name=${name} ph=${ph}] ${text}`;
                        })
                        .join(' | ');
                }"""
            )
            or ""
        )
    except Exception as exc:
        return f"dump_failed:{exc}"


async def _fill_profile_once(page, full_name: str, birth_date: str) -> bool:
    """填写 about-you 页：对齐 oumiFree 的 name + birthdate。"""
    return bool(
        await page.evaluate(
            """({fullName, birthDate}) => {
                const visible = (node) => {
                    if (!node) return false;
                    const style = getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden'
                        && rect.width > 0 && rect.height > 0
                        && !['hidden','submit','button','checkbox','radio','file'].includes(String(node.type||'').toLowerCase());
                };
                const setValue = (node, value) => {
                    node.focus();
                    const proto = node instanceof HTMLTextAreaElement
                        ? HTMLTextAreaElement.prototype
                        : HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                    if (setter) setter.call(node, value); else node.value = value;
                    for (const type of ['input', 'change', 'blur']) {
                        node.dispatchEvent(new Event(type, { bubbles: true }));
                    }
                    try {
                        node.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
                    } catch (_) {}
                };
                const directText = (el) => [
                    el.name, el.id, el.autocomplete, el.placeholder,
                    el.getAttribute('aria-label'), el.getAttribute('data-testid'),
                ].filter(Boolean).join(' ').toLowerCase();
                const profileText = (el) => {
                    const parts = [directText(el)];
                    if (el.id) {
                        const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                        if (label) parts.push(label.textContent || '');
                    }
                    const labelledBy = String(el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
                    for (const id of labelledBy) parts.push(document.getElementById(id)?.textContent || '');
                    const wrap = el.closest?.('label');
                    if (wrap) parts.push(wrap.textContent || '');
                    return parts.join(' ').toLowerCase();
                };
                const inputs = Array.from(document.querySelectorAll('input, textarea')).filter(visible)
                    .filter((el) => !String(el.value || '').includes('@')
                        && !/email|mail|邮箱|验证码|verification|code|password|phone|card|cvc|cvv|otp/.test(directText(el)));

                const birthDateInput = inputs.find((el) =>
                    /birth|birthday|date of birth|dob|出生|生日|mm[\\s/.-]*dd[\\s/.-]*yyyy|dd[\\s/.-]*mm[\\s/.-]*yyyy|yyyy[\\s/.-]*mm[\\s/.-]*dd/.test(profileText(el))
                    || String(el.type || '').toLowerCase() === 'date'
                );
                const firstNameInput = inputs.find((el) => el !== birthDateInput
                    && /first[\\s_-]*name|given[\\s_-]*name|^名$|名字/.test(profileText(el)));
                const lastNameInput = inputs.find((el) => el !== birthDateInput && el !== firstNameInput
                    && /last[\\s_-]*name|family[\\s_-]*name|surname|姓/.test(profileText(el)));
                const fullNameInput = inputs.find((el) => el !== birthDateInput
                    && el !== firstNameInput && el !== lastNameInput
                    && /full[\\s_-]*name|display[\\s_-]*name|name|姓名|全名|昵称/.test(profileText(el)));
                // 无标签时：优先第一个非 date 输入当姓名
                const fallbackName = inputs.find((el) => el !== birthDateInput
                    && el !== firstNameInput && el !== lastNameInput && el !== fullNameInput
                    && String(el.type || '').toLowerCase() !== 'date'
                    && String(el.type || '').toLowerCase() !== 'number');

                const parts = String(fullName || '').trim().split(/\\s+/).filter(Boolean);
                const firstName = parts[0] || fullName;
                const lastName = parts.slice(1).join(' ') || (parts[0] || 'Smith');

                let changed = false;
                if (firstNameInput) {
                    setValue(firstNameInput, firstName);
                    changed = true;
                }
                if (lastNameInput) {
                    setValue(lastNameInput, lastName);
                    changed = true;
                }
                if (!firstNameInput && !lastNameInput) {
                    const nameEl = fullNameInput || fallbackName;
                    if (nameEl) {
                        setValue(nameEl, fullName);
                        changed = true;
                    }
                }
                if (birthDateInput) {
                    const hint = profileText(birthDateInput) + ' ' + directText(birthDateInput);
                    const [year, month, day] = String(birthDate || '').split('-');
                    let formatted = birthDate;
                    if (String(birthDateInput.type || '').toLowerCase() === 'date') {
                        formatted = birthDate;
                    } else if (/dd[\\s/.-]*mm[\\s/.-]*yyyy/.test(hint)) {
                        formatted = `${day}/${month}/${year}`;
                    } else if (/mm[\\s/.-]*dd[\\s/.-]*yyyy/.test(hint)) {
                        formatted = `${month}/${day}/${year}`;
                    } else if (/yyyy[\\s/.-]*mm[\\s/.-]*dd/.test(hint) && hint.includes('/')) {
                        formatted = `${year}/${month}/${day}`;
                    }
                    setValue(birthDateInput, formatted);
                    changed = true;
                }
                return changed;
            }""",
            {"fullName": full_name, "birthDate": birth_date},
        )
    )


async def _submit_profile_ui(page) -> bool:
    """UI 提交：form.requestSubmit + Continue 按钮。"""
    before = page.url or ""
    try:
        await page.evaluate(
            """() => {
                const form = document.querySelector('form');
                if (form) {
                    if (form.requestSubmit) form.requestSubmit();
                    else form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                }
            }"""
        )
    except Exception:
        pass
    await asyncio.sleep(0.8)
    if (page.url or "") != before:
        return True

    await click_by_text(
        page,
        (
            "继续", "下一步", "提交", "确认", "完成", "创建", "完成帐户创建", "开始",
            "continue", "next", "submit", "verify", "done", "create", "finish",
            "get started", "sign up",
        ),
    )
    await asyncio.sleep(1.2)
    if (page.url or "") != before:
        return True

    # Playwright 原生点击
    for selector in (
        'button:has-text("Continue")',
        'button:has-text("继续")',
        'button[type="submit"]',
        'button:has-text("Create")',
        'button:has-text("创建")',
    ):
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=500) and await btn.is_enabled():
                await btn.click()
                await asyncio.sleep(1.2)
                if (page.url or "") != before:
                    return True
        except Exception:
            pass
    return (page.url or "") != before


async def _create_account_api(page, full_name: str, birth_date: str) -> dict:
    """浏览器内直接调 create_account（对齐 oumiFree [7/9]）。"""
    try:
        return await page.evaluate(
            """async ({name, birthdate}) => {
                try {
                    const response = await fetch('https://auth.openai.com/api/accounts/create_account', {
                        method: 'POST',
                        credentials: 'include',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                            'Origin': 'https://auth.openai.com',
                            'Referer': location.href,
                        },
                        body: JSON.stringify({ name, birthdate }),
                    });
                    const text = await response.text();
                    let data = {};
                    try { data = JSON.parse(text); } catch (_) { data = { raw: text.slice(0, 300) }; }
                    return {
                        ok: response.ok,
                        status: response.status,
                        continue_url: data.continue_url || data.continueUrl || '',
                        data,
                    };
                } catch (error) {
                    return { ok: false, status: 0, error: String(error && error.message || error) };
                }
            }""",
            {"name": full_name, "birthdate": birth_date},
        )
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc)}


async def _follow_continue_url(page, continue_url: str, ctx) -> None:
    if not continue_url:
        return
    cur = continue_url
    for _ in range(8):
        if not cur:
            break
        if cur.startswith("/"):
            cur = f"https://chatgpt.com{cur}"
        try:
            ctx.log(f"跟随 continue_url: {cur[:120]}")
            await page.goto(cur, wait_until="commit", timeout=60_000)
            await page.wait_for_timeout(1500)
        except Exception as exc:
            ctx.log(f"跟随 continue_url 失败: {exc}")
            break
        # 若仍是 auth 相对跳转，尽量读 Location 已由浏览器完成
        url = page.url or ""
        if _entered_main_site(url):
            break
        if "about-you" not in url.lower() and "auth.openai.com" not in url.lower():
            break
        cur = ""


async def run(page, ctx, *, timeout: float = 90) -> dict[str, str]:
    profile = {
        "name": _rand_name(),
        "birth_date": _rand_birthdate(),
    }
    # age 仅作兼容日志字段
    try:
        year = int(profile["birth_date"].split("-")[0])
        profile["age"] = str(max(18, time.localtime().tm_year - year))
    except Exception:
        profile["age"] = "25"

    deadline = time.monotonic() + timeout
    filled = False
    api_tried = False

    while time.monotonic() < deadline:
        try:
            url = page.url or ""
            if _entered_main_site(url):
                ctx.log(f"已在主站，跳过资料页: {url}")
                return profile

            # 引导页跳过
            await click_by_text(
                page,
                ("跳过", "skip", "get started", "开始", "okay", "ok", "got it"),
            )

            if _on_profile_page(url) or await _fill_profile_once(page, profile["name"], profile["birth_date"]):
                filled = True
                dump = await _dump_profile_inputs(page)
                if dump and "dump_failed" not in dump:
                    ctx.log(f"资料页控件: {dump[:240]}")
                await _fill_profile_once(page, profile["name"], profile["birth_date"])
                ctx.log(f"资料已填写: name={profile['name']} birthdate={profile['birth_date']}")

                # 1) UI 提交
                moved = await _submit_profile_ui(page)
                after = (page.url or "").lower()
                if moved:
                    ctx.log(f"资料页 UI 提交后跳转: {after}")
                if _entered_main_site(after):
                    return profile
                if after and "about-you" not in after and "create-account" not in after:
                    # 可能进入 onboarding / callback
                    if "chatgpt.com" in after or "callback" in after:
                        return profile

                # 2) 仍停 about-you：用 oumiFree 同款 create_account API
                if not api_tried and ("about-you" in after or _on_profile_page(page.url or "")):
                    api_tried = True
                    ctx.log("UI 未离开资料页，尝试 create_account API（对齐 oumiFree）")
                    result = await _create_account_api(page, profile["name"], profile["birth_date"])
                    ctx.log(
                        f"create_account API: ok={result.get('ok')} status={result.get('status')} "
                        f"continue={str(result.get('continue_url') or '')[:100]} err={result.get('error') or ''}"
                    )
                    if result.get("ok"):
                        continue_url = str(result.get("continue_url") or "")
                        if continue_url:
                            await _follow_continue_url(page, continue_url, ctx)
                        else:
                            # 无 continue_url 时回 chatgpt 主站
                            try:
                                await page.goto("https://chatgpt.com/", wait_until="commit", timeout=60_000)
                                await page.wait_for_timeout(2000)
                            except Exception:
                                pass
                        if _entered_main_site(page.url or "") or "chatgpt.com" in (page.url or "").lower():
                            ctx.log(f"create_account 后页面: {page.url}")
                            return profile
            else:
                # 还没到资料页：等 OTP 后跳转
                if "email-verification" in (url or "").lower():
                    ctx.log("仍在邮箱验证页，等待进入资料页...")
                await asyncio.sleep(1.0)
                continue

        except Exception as exc:
            if _is_navigation_interruption(exc):
                await asyncio.sleep(0.8)
                continue
            raise

        await asyncio.sleep(1.0)

    if not filled:
        ctx.log("未检测到姓名/生日页，继续后续 Session 提取")
    else:
        ctx.log(f"资料页处理后仍停在: {page.url}")
    return profile
