"""NVIDIA Build 浏览器步骤与 hCaptcha route hook。"""

import os
import re
import random
import time
import json
import asyncio
import requests as _requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

# ============ NoneCap hCaptcha API 配置（旧版，保留兼容） ============
NONECAP_KEY = os.getenv("NONECAP_KEY", "nc_live_T4dbP_DG2PUt-f0HW17mjqol3GQw3iS0")
NONECAP_API = "https://api.nonecap.com/v1/solves"

# ============ 配置 ============
TARGET_URL = "https://build.nvidia.com/"
EMAIL_DOMAIN = "zhoushu.kdns.fr"
PASSWORD = "zs1236547."


def generate_random_email(domain=EMAIL_DOMAIN):
    """生成随机8位数字邮箱"""
    random_num = "".join(random.choice("0123456789") for _ in range(8))
    return f"{random_num}@{domain}"


# ============ RPA 步骤（async） ============


async def step1_open_page(page):
    """步骤1：打开 https://build.nvidia.com/"""
    print("[步骤1] 打开 NVIDIA Build 页面...")
    await page.goto(TARGET_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    print("[步骤1] 完成 - 页面已打开")
    return True


async def step2_accept_cookies(page):
    """步骤2：处理 Cookie 弹窗（OneTrust Accept All）。

    注意：Banner 常延迟出现；找不到按钮时不得谎称「已处理」。
    """
    print("[步骤2] 检查 Cookie 弹窗...")
    clicked = False
    selectors = [
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        "#onetrust-banner-sdk #onetrust-accept-btn-handler",
        "button:has-text('Accept All')",
        "button:has-text('Accept all')",
        "button:has-text('ALLOW ALL')",
        "#accept-recommended-btn-handler",
    ]

    # Banner 可能晚于 signin 模态框 2–8s 出现
    for attempt in range(12):
        # 主页面 + 各 frame 都试（部分站点 OneTrust 在 iframe）
        targets = [page]
        try:
            targets.extend(page.frames)
        except Exception:
            pass

        for target in targets:
            for sel in selectors:
                try:
                    loc = target.locator(sel).first
                    cnt = await loc.count()
                    if cnt <= 0:
                        continue
                    # 有节点即尝试 force 点（is_visible 对动画/半透明易误判）
                    await loc.click(force=True, timeout=3000)
                    print(f"[步骤2] 已点击 Accept All: {sel}")
                    clicked = True
                    break
                except Exception:
                    continue
            if clicked:
                break

        if not clicked:
            # JS 兜底：按文案找按钮
            try:
                js_hit = await page.evaluate(
                    """() => {
                        const texts = ['accept all', 'allow all', '同意全部', '接受全部'];
                        const nodes = Array.from(document.querySelectorAll(
                            'button, a, [role="button"], input[type="button"], input[type="submit"]'
                        ));
                        for (const n of nodes) {
                            const t = (n.innerText || n.value || n.getAttribute('aria-label') || '').trim().toLowerCase();
                            if (!t) continue;
                            if (texts.some(x => t === x || t.includes(x))) {
                                n.click();
                                return t;
                            }
                        }
                        const ot = document.querySelector('#onetrust-accept-btn-handler');
                        if (ot) { ot.click(); return 'onetrust-id'; }
                        return '';
                    }"""
                )
                if js_hit:
                    print(f"[步骤2] JS 兜底点击 Accept All: {js_hit}")
                    clicked = True
            except Exception:
                pass

        if clicked:
            break
        await page.wait_for_timeout(800)

    if clicked:
        # 等 Banner/遮罩消失
        for _ in range(8):
            try:
                still = await page.evaluate(
                    """() => {
                        const b = document.querySelector('#onetrust-accept-btn-handler');
                        const filter = document.querySelector('.onetrust-pc-dark-filter');
                        const banner = document.querySelector('#onetrust-banner-sdk');
                        const vis = (el) => !!(el && el.offsetParent !== null);
                        return {
                            accept: vis(b),
                            filter: vis(filter),
                            banner: vis(banner),
                        };
                    }"""
                )
                if not still.get("accept") and not still.get("filter"):
                    break
            except Exception:
                break
            # 再点一次 close
            try:
                close_btn = page.locator(
                    ".onetrust-close-btn-handler, button.onetrust-close-btn-handler, #onetrust-close-btn-container button"
                ).first
                if await close_btn.count() > 0:
                    await close_btn.click(force=True, timeout=1500)
            except Exception:
                pass
            await page.wait_for_timeout(500)
        print("[步骤2] 完成 - Cookie Accept All 已点击")
        return True

    # 没有 Banner 也算可继续，但必须打清楚日志
    has_banner = False
    try:
        has_banner = await page.evaluate(
            """() => !!(document.querySelector('#onetrust-banner-sdk')
                || document.querySelector('#onetrust-accept-btn-handler')
                || document.querySelector('#onetrust-consent-sdk'))"""
        )
    except Exception:
        pass
    if has_banner:
        # 节点还在但不可见：强制 JS 点 id（常见于遮罩残留 / 动画中）
        try:
            forced = await page.evaluate(
                """() => {
                    const ids = [
                      'onetrust-accept-btn-handler',
                      'accept-recommended-btn-handler',
                      'onetrust-reject-all-handler'
                    ];
                    for (const id of ids) {
                      const el = document.getElementById(id);
                      if (el) { el.click(); return id; }
                    }
                    const bannerBtn = document.querySelector(
                      '#onetrust-banner-sdk button, #onetrust-pc-sdk button'
                    );
                    if (bannerBtn) { bannerBtn.click(); return bannerBtn.id || bannerBtn.textContent.trim().slice(0,40); }
                    return '';
                }"""
            )
            if forced:
                print(f"[步骤2] 强制 JS 点击: {forced}")
                await page.wait_for_timeout(800)
                print("[步骤2] 完成 - Cookie 强制点击")
                return True
        except Exception as e:
            print(f"[步骤2] 强制点击失败: {e}")
        print("[步骤2] [WARN] 检测到 OneTrust 节点但未能点击 Accept All")
        try:
            await page.screenshot(path="data/logs/step2_cookie_stuck.png")
        except Exception:
            pass
        # 不阻断主流程：遮罩可能仍可 force 点 Next
        return True

    print("[步骤2] 完成 - 未出现 Cookie 弹窗（可继续）")
    return True


async def step3_click_login(page):
    """步骤3：点击 Login 按钮"""
    print("[步骤3] 点击 Login 按钮...")
    login_btn = page.locator("button[data-nvtrack-nav-object='login-button']")
    await login_btn.click(no_wait_after=True)
    await page.wait_for_timeout(3000)
    print("[步骤3] 完成 - 已点击 Login 按钮")
    return True


async def step4_input_email(page, email):
    """步骤4：输入随机8位数邮箱"""
    print(f"[步骤4] 输入邮箱: {email}")
    email_input = page.locator("input[data-testid='nv-text-input-element'][name='email']")
    await email_input.fill(email)
    await page.wait_for_timeout(1000)
    print("[步骤4] 完成 - 邮箱已输入")
    return True


async def step5_click_next(page):
    """步骤5：点击 Next 按钮"""
    print("[步骤5] 点击 Next 按钮...")
    next_btn = page.locator("button.btn-primary.btn-lg.btn-rounded").first
    await next_btn.click(force=True, no_wait_after=True)
    # 等密码输入框出现（替代死等 5s）
    try:
        await page.wait_for_selector("#registration_password", timeout=10000)
    except PlaywrightTimeoutError:
        await page.wait_for_timeout(2000)
    print("[步骤5] 完成 - 已点击 Next 按钮")
    return True


async def step6_input_password(page):
    """步骤6：输入密码"""
    print(f"[步骤6] 输入密码: {PASSWORD}")
    pwd_input = page.locator("#registration_password")
    await pwd_input.fill(PASSWORD)
    await page.wait_for_timeout(1000)
    print("[步骤6] 完成 - 密码已输入")
    return True


async def step7_input_confirm_password(page):
    """步骤7：输入确认密码"""
    print(f"[步骤7] 输入确认密码: {PASSWORD}")
    confirm_input = page.locator("#registration_passwordConfirm")
    await confirm_input.fill(PASSWORD)
    await page.wait_for_timeout(1000)
    print("[步骤7] 完成 - 确认密码已输入")
    return True


async def step8_check_agreement(page):
    """步骤8：勾选同意条款复选框
    优化：input 元素被隐藏在自定义 checkbox 后面，click 会因 not visible 超时。
    改为先尝试 JS click（直击 hidden input），失败再试 Playwright click。
    """
    print("[步骤8] 勾选同意条款...")
    # input 常被自定义样式隐藏：用 attached 等待，不要用 visible
    for _ in range(8):
        try:
            found = await page.evaluate(
                """() => !!(
                    document.getElementById('data_general_agreement-input')
                    || document.querySelector("input[name='data_general_agreement']")
                    || document.querySelector("input[type='checkbox']")
                )"""
            )
            if found:
                break
        except Exception:
            pass
        await page.wait_for_timeout(500)

    # 优先 JS 点击（绕过 visibility 检查，最可靠最快）
    try:
        js_result = await page.evaluate("""
            () => {
                const cb = document.getElementById('data_general_agreement-input')
                    || document.querySelector("input[name='data_general_agreement']");
                if (cb) {
                    cb.checked = true;
                    cb.dispatchEvent(new Event('input', { bubbles: true }));
                    cb.dispatchEvent(new Event('change', { bubbles: true }));
                    try { cb.click(); } catch (e) {}
                    return true;
                }
                const labels = Array.from(document.querySelectorAll('label'));
                const agree = labels.find(l => /agree|terms|privacy|同意|条款|隐私/i.test(l.textContent || ''));
                if (agree) { agree.click(); return true; }
                const cbs = document.querySelectorAll('input[type="checkbox"]');
                if (cbs.length > 0) {
                    const last = cbs[cbs.length - 1];
                    last.checked = true;
                    last.dispatchEvent(new Event('change', { bubbles: true }));
                    try { last.click(); } catch (e) {}
                    return true;
                }
                return false;
            }
        """)
        if js_result:
            print("[步骤8] 完成 - 已通过JS勾选同意条款")
            return True
    except Exception:
        pass

    # JS 也没成功，试 force click（短超时避免卡住）
    for sel in [
        "#data_general_agreement-input",
        "input[name='data_general_agreement']",
        "label:has(input[type='checkbox'])",
        "label[class*='checkbox']",
        "[class*='agreement']",
    ]:
        try:
            loc = page.locator(sel)
            cnt = await loc.count()
            if cnt == 0:
                continue
            await loc.first.click(timeout=2000, force=True)
            print(f"[步骤8] 完成 - 已勾选同意条款 ({sel})")
            return True
        except Exception:
            continue
    print("[步骤8] 未找到同意条款复选框")
    return False


async def step9_init_and_click_checkbox(page):
    """步骤9：使用 NoneCap API 获取 hCaptcha token
    返回 (page, token) 供 step10 注入。
    """
    print("[步骤9] 使用 NoneCap API 解决 hCaptcha...")

    # 提取 sitekey
    sitekey = None
    for _ in range(10):
        sitekey = await page.evaluate("""() => {
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
        }""")
        if sitekey:
            break
        await page.wait_for_timeout(1000)

    if not sitekey:
        for f in page.frames:
            if "hcaptcha" in f.url:
                m_obj = re.search(r"sitekey=([a-f0-9-]+)", f.url)
                if m_obj:
                    sitekey = m_obj.group(1)
                    break

    if not sitekey:
        print("[步骤9] [FAIL] 无法从页面提取 hCaptcha sitekey")
        return page, None

    current_url = page.url
    print(f"[步骤9] sitekey={sitekey}  url={current_url}")

    # 调用 NoneCap API 获取 token
    try:
        resp = _requests.post(
            NONECAP_API,
            params={"wait": 60},
            headers={
                "Authorization": f"Bearer {NONECAP_KEY}",
                "Content-Type": "application/json",
            },
            json={"type": "hcaptcha", "sitekey": sitekey, "url": current_url},
            timeout=70,
        )
    except Exception as e:
        print(f"[步骤9] [FAIL] NoneCap API 请求异常: {e}")
        return page, None

    if resp.status_code == 200:
        solve = resp.json()
        if solve.get("status") == "solved":
            token = solve["token"]
            print(f"[步骤9] [OK] NoneCap token 获取成功 (queue={solve.get('queue_ms')}ms resolve={solve.get('resolve_ms')}ms credits={solve.get('credits_charged')})")
            return page, token
        else:
            err = solve.get("error", {})
            print(f"[步骤9] [FAIL] NoneCap solve 失败: status={solve.get('status')} error={err.get('code')}: {err.get('message', '')[:80]}")
            return page, None
    elif resp.status_code == 202:
        print("[步骤9] [FAIL] NoneCap 超时未完成")
        return page, None
    else:
        print(f"[步骤9] [FAIL] NoneCap API HTTP {resp.status_code}: {resp.text[:200]}")
        return page, None


async def step10_solve_challenge(page, token):
    """步骤10：调用 hcaptcha render 时注册的 callback 来注入 NoneCap token
    核心原理：通过 route 拦截 hcaptcha api.js，注入 hook 代码来捕获
    Angular ngx-hcaptcha 组件调用 hcaptcha.render() 时传入的 callback。
    验证成功后直接调用该 callback(token)，Angular 会自动更新 form control
    为 ng-valid，按钮变为 enabled，表单可以自然提交。
    """
    print("[步骤10] 调用 hcaptcha callback 注入 NoneCap token...")

    escaped_token = token.replace("\\", "\\\\").replace("'", "\\'")

    # 检查是否捕获到了 hcaptcha render callback
    callback_count = await page.evaluate("(window.__hcaptcha_callbacks || []).length")

    if callback_count > 0:
        # 直接调用 callback —— 这是验证通过的核心！
        result = await page.evaluate(f"""() => {{
            var token = '{escaped_token}';
            var callbacks = window.__hcaptcha_callbacks || [];
            var results = [];
            for (var i = 0; i < callbacks.length; i++) {{
                try {{
                    callbacks[i](token);
                    results.push('callback#' + i + ' called OK');
                }} catch(e) {{
                    results.push('callback#' + i + ' error: ' + e.message);
                }}
            }}
            // 同时设置 h-captcha-response
            var el = document.querySelector('[name="h-captcha-response"]');
            if (el) el.value = token;
            var widget = document.querySelector('[data-hcaptcha-widget-id]');
            if (widget) widget.setAttribute('data-hcaptcha-response', token);
            return results.join('; ');
        }}""")
        print(f"[步骤10] callback 调用结果: {result}")

        await page.wait_for_timeout(1500)

        # 检查 Angular form control 状态
        state = await page.evaluate("""() => {
            var captchaEl = document.querySelector('[formcontrolname="captcha"]');
            var btn = document.querySelector('#register_button');
            return {
                captchaValid: captchaEl ? captchaEl.classList.contains('ng-valid') : false,
                btnDisabled: btn ? btn.disabled : true
            };
        }""")

        if state.get("captchaValid") and not state.get("btnDisabled"):
            print("[步骤10] [OK] Angular form control 已更新为 valid，按钮已启用")
            return True
        else:
            print(f"[步骤10] [WARN] 状态异常: {state}")

    # 兜底：手动设置 Angular 状态 + h-captcha-response
    print("[步骤10] 尝试兜底方案...")
    await page.evaluate(f"""() => {{
        var token = '{escaped_token}';
        var el = document.querySelector('[name="h-captcha-response"]');
        if (el) {{
            el.value = token;
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}
        var widget = document.querySelector('[data-hcaptcha-widget-id]');
        if (widget) widget.setAttribute('data-hcaptcha-response', token);
        var parentDiv = widget?.parentElement;
        if (parentDiv) {{
            parentDiv.classList.remove('ng-invalid', 'ng-untouched', 'ng-pristine');
            parentDiv.classList.add('ng-valid', 'ng-dirty', 'ng-touched');
        }}
        if (typeof hcaptcha !== 'undefined') {{
            if (hcaptcha.execute) hcaptcha.execute = function() {{ return Promise.resolve(token); }};
            if (hcaptcha.getResponse) hcaptcha.getResponse = function() {{ return token; }};
        }}
    }}""")

    await page.wait_for_timeout(1000)
    print("[步骤10] 兜底方案已执行")
    return True


async def step11_click_create_account(page):
    """步骤11：点击创建账号按钮"""
    print("[步骤11] 点击创建账号按钮...")
    for selector in [
        "button.btn-primary.btn-lg.btn-rounded",
        "button[type='submit']",
        "button:has-text('Create Account')",
        "button:has-text('创建账户')",
        "button:has-text('创建账号')",
        "button:has-text('注册')",
        "button:has-text('Sign Up')",
    ]:
        try:
            loc = page.locator(selector)
            cnt = await loc.count()
            if cnt == 0:
                continue
            for idx in range(min(cnt, 3)):
                btn = loc.nth(idx)
                if await btn.is_visible():
                    await btn.click(no_wait_after=True)
                    # 等 URL 变化或 profile-complete 页面元素（替代死等 5s）
                    try:
                        # 创建账号后通常跳转到 profile-complete 或显示验证码输入框
                        await page.wait_for_url(
                            "**/profile-complete**", timeout=15000
                        )
                    except PlaywrightTimeoutError:
                        # URL 没变，可能仍在原页面，等验证码输入框
                        try:
                            await page.wait_for_selector(
                                "input[type='number'], input[maxlength='1']",
                                timeout=5000,
                            )
                        except PlaywrightTimeoutError:
                            await page.wait_for_timeout(2000)
                    print(f"[步骤11] 完成 - 已点击创建账号 ({selector})")
                    print(f"[步骤11] 当前URL: {page.url}")
                    return True
        except Exception:
            continue
    print("[步骤11] 未找到创建账号按钮，可能已自动提交")
    print(f"[步骤11] 当前URL: {page.url}")
    return True


async def step12_input_code(page, code):
    """步骤12：将验证码输入到 profile-complete 页面（纯页面操作，不等待邮件）"""
    code = str(code).strip()
    if len(code) < 6:
        print(f"[步骤12] 验证码长度不足: {code}")
        return False
    code = code[:6]
    print(f"[步骤12] 输入验证码: {code}")

    # 等待验证码输入框出现（最长 10s，替代死等）
    digit_inputs = None
    digit_count = 0
    for sel in ["input[type='number']", "input[maxlength='1']", "input.mat-input-element"]:
        try:
            locs = page.locator(sel)
            cnt = await locs.count()
            if cnt >= 6:
                digit_inputs = locs
                digit_count = cnt
                print(f"[步骤12] 找到 {cnt} 个输入框 (selector={sel})")
                break
        except Exception:
            continue

    if digit_inputs is None or digit_count < 6:
        # 兜底：单个输入框
        for selector in [
            "input[name='code']",
            "input[name='verificationCode']",
            "input[placeholder*='code']",
            "input[placeholder*='验证']",
        ]:
            try:
                inp = page.locator(selector).first
                if await inp.is_visible(timeout=3000):
                    await inp.fill(code)
                    await page.keyboard.press("Enter")
                    print("[步骤12] 完成 - 单框输入验证码")
                    await _wait_for_login_redirect(page)
                    return True
            except Exception:
                continue
        print("[步骤12] 未找到验证码输入框")
        return False

    # 逐位输入6位验证码（无延迟）
    for i in range(6):
        try:
            await digit_inputs.nth(i).fill(code[i])
        except Exception:
            try:
                await digit_inputs.nth(i).click()
                await page.keyboard.type(code[i])
            except Exception:
                pass
    print("[步骤12] 已输入6位验证码")

    # 点击"继续"按钮（等按钮可点击，最长 10s）
    clicked = False
    for sel in ["button:has-text('继续')", "button:has-text('Continue')", "button.btn-primary"]:
        try:
            btn = page.locator(sel).first
            # 等按钮可点击（替代固定死等）
            try:
                await page.wait_for_selector(
                    f"{sel}:not([disabled])", timeout=10000
                )
            except PlaywrightTimeoutError:
                pass
            await btn.click(no_wait_after=True, timeout=5000)
            print(f"[步骤12] 已点击继续按钮: {sel}")
            clicked = True
            break
        except Exception as e:
            print(f"[步骤12] 点击 {sel} 失败: {e}")
            continue
    if not clicked:
        try:
            await page.keyboard.press("Enter")
            print("[步骤12] 已按 Enter 提交")
        except Exception:
            pass

    print("[步骤12] 完成 - 验证码已提交")
    await _wait_for_login_redirect(page)
    return True


async def step12_verify_email(page, reg_email, since_ts=None):
    raise RuntimeError("旧独立邮箱验证流程已移除，请使用 projects.nvidia_build.project")


async def _wait_for_login_redirect(page, timeout=30):
    """等待登录后页面跳转完成"""
    print(f"[步骤12] 等待登录跳转 (最多{timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        url = page.url
        if "build.nvidia.com" in url and ("/login" not in url and "/register" not in url and "/verify" not in url):
            print(f"[步骤12] 已跳转到: {url}")
            return True
        try:
            err = page.locator("[class*='error'], [class*='Error'], [role='alert']").first
            if await err.is_visible(timeout=500):
                err_text = (await err.text_content()) or ""
                if err_text and any(kw in err_text.lower() for kw in ["invalid", "expired", "无效", "过期", "错误"]):
                    print(f"[步骤12] 检测到错误: {err_text}")
                    return False
        except Exception:
            pass
        await page.wait_for_timeout(1000)
    print(f"[步骤12] 跳转等待超时, 当前URL: {page.url}")
    return True


async def step13_get_api_key(page):
    """步骤13：在浏览器中执行脚本获取 API Key"""
    print("[步骤13] 获取 API Key...")
    if "build.nvidia.com" not in page.url:
        print("[步骤13] 当前不在 build.nvidia.com，导航中...")
        await page.goto("https://build.nvidia.com/", wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

    await page.wait_for_timeout(3000)

    # 检查用户是否已登录
    try:
        login_check = await page.evaluate("""
            async () => {
                const res = await fetch('https://api.ngc.nvidia.com/user-context', {
                    method: 'GET',
                    credentials: 'include',
                    headers: { accept: 'application/json' }
                });
                const status = res.status;
                let body = null;
                try { body = await res.json(); } catch(e) { body = await res.text(); }
                return { status, body };
            }
        """)
        print(f"[步骤13] 登录状态检查: HTTP {login_check['status']}")
        if login_check["status"] != 200:
            print(f"[步骤13] 用户未登录或会话无效: {str(login_check['body'])[:200]}")
            print("[步骤13] 尝试刷新页面...")
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
    except Exception as e:
        print(f"[步骤13] 登录检查失败: {e}")

    try:
        result = await page.evaluate("""
            async () => {
                const res1 = await fetch('https://api.ngc.nvidia.com/user-context', {
                    method: 'GET',
                    credentials: 'include',
                    headers: { accept: 'application/json' }
                });
                const data1 = await res1.json();
                if (!res1.ok) throw new Error(`user-context 请求失败: ${res1.status} ${JSON.stringify(data1).slice(0, 200)}`);
                const orgName = data1.orgName;
                if (!orgName) throw new Error(`未找到 orgName, 返回: ${JSON.stringify(data1).slice(0, 200)}`);
                const res2 = await fetch(`https://api.ngc.nvidia.com/v3/orgs/${orgName}/keys/type/AI_PLAYGROUNDS_KEY`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: { accept: '*/*', 'content-type': 'application/json' },
                    body: JSON.stringify({
                        expiryDate: '2126-04-08T07:00:00Z',
                        name: 'dev',
                        type: 'AI_PLAYGROUNDS_KEY',
                        policies: [{
                            product: 'nv-cloud-functions',
                            scopes: ['invoke_function'],
                            resources: [{ id: '*', type: 'account-functions' }]
                        }]
                    })
                });
                const data2 = await res2.json();
                if (!res2.ok) throw new Error(`创建 key 请求失败: ${res2.status} ${JSON.stringify(data2).slice(0, 200)}`);
                return { orgName, result: data2, apiKey: data2?.result?.apiKey?.value || '' };
            }
        """)
        api_key = result.get("apiKey", "")
        if api_key:
            print(f"[步骤13] 成功获取 API Key: {api_key[:20]}...")
            return api_key
        else:
            print(f"[步骤13] API Key 为空, 返回: {json.dumps(result, ensure_ascii=False)[:200]}")
            return None
    except Exception as e:
        print(f"[步骤13] 获取 API Key 失败: {e}")
        return None


def step14_save_api_key(api_key, email):
    """步骤14：保存 API Key 到文件"""
    print("[步骤14] 保存 API Key...")
    if not api_key:
        print("[步骤14] API Key 为空，跳过保存")
        return False
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_keys.txt")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"{email}\t{api_key}\n")
    print(f"[步骤14] 已保存到 {filepath}")
    return True


# ============ 主流程 ============


async def _run_pipeline(page, email, reg_start_ts, result):
    raise RuntimeError("旧独立注册流程已移除，请使用 projects.nvidia_build.project")
    steps_pre_captcha = [
        ("打开页面", lambda: step1_open_page(page)),
        ("Cookie", lambda: step2_accept_cookies(page)),
        ("Login", lambda: step3_click_login(page)),
        ("邮箱", lambda: step4_input_email(page, email)),
        ("Next", lambda: step5_click_next(page)),
        ("密码", lambda: step6_input_password(page)),
        ("确认密码", lambda: step7_input_confirm_password(page)),
        ("同意条款", lambda: step8_check_agreement(page)),
    ]
    for i, (name, step) in enumerate(steps_pre_captcha, 1):
        try:
            success = await step()
        except Exception as e:
            print(f"[步骤{i}] 异常: {e}")
            success = False
        if not success:
            print(f"\n步骤 {i} ({name}) 未完成，流程终止。")
            result["failed_step"] = i
            return result

    # 关键优化：在 hCaptcha 开始前，后台启动 CF-KV 等待验证码邮件
    # 这样 hCaptcha 解决期间（30-60s）CF-KV 已在等邮件，邮件到达立即感知
    print("[CF-KV] 启动后台 CF-KV 读验证码任务（与 hCaptcha 并行）")
    cf_task = asyncio.create_task(
        asyncio.to_thread(cf_fetch_code, email, 300)
    )

    # step 9：从页面提取 sitekey + 调 NoneCap API 获取 token
    try:
        page_result, token = await step9_init_and_click_checkbox(page)
    except Exception as e:
        print(f"[步骤9] 异常: {e}")
        cf_task.cancel()
        result["failed_step"] = 9
        return result
    if not token:
        cf_task.cancel()
        print("\n步骤 9 (NoneCap API) 未获取到 token，流程终止。")
        result["failed_step"] = 9
        return result

    # step 10：hook hcaptcha.execute 让它返回 NoneCap token
    try:
        await step10_solve_challenge(page, token)
    except Exception as e:
        print(f"[步骤10] 异常: {e}")
        cf_task.cancel()
        result["failed_step"] = 10
        return result

    # step 11：创建账号（用 URL 等待替代死等）
    try:
        success = await step11_click_create_account(page)
    except Exception as e:
        print(f"[步骤11] 异常: {e}")
        success = False
    if not success:
        cf_task.cancel()
        print("\n步骤 11 (创建账号) 未完成，流程终止。")
        result["failed_step"] = 11
        return result

    # step 12：等 CF-KV 后台任务返回验证码（邮件可能已到，立即返回）
    print("[步骤12] 等待 CF-KV 验证码...")
    code = None
    try:
        # 最多等 120s（邮件通常在创建账号后 30-60s 到）
        code = await asyncio.wait_for(cf_task, timeout=120)
    except asyncio.TimeoutError:
        print("[步骤12] CF-KV 等待超时（120s）")
        cf_task.cancel()
    except Exception as e:
        print(f"[步骤12] CF-KV 任务异常: {e}")
        cf_task.cancel()

    if code:
        success = await step12_input_code(page, code)
    else:
        # 兜底：再试一次同步等待
        print("[步骤12] 后台 CF-KV 未返回，尝试同步等待...")
        code = await asyncio.get_event_loop().run_in_executor(None, cf_fetch_code, email, 60)
        if code:
            success = await step12_input_code(page, code)
        else:
            success = False
    if not success:
        print("\n步骤 12 (邮箱验证) 未完成，流程终止。")
        result["failed_step"] = 12
        return result

    # step 13-14：获取并保存 API Key
    api_key = await step13_get_api_key(page)
    if api_key:
        step14_save_api_key(api_key, email)
        result["api_key"] = api_key
        result["success"] = True
        print(f"\n[成功] 邮箱: {email}, Key: {api_key[:20]}...")
    else:
        print(f"\n[失败] 获取 API Key 失败, 邮箱: {email}")
    return result


async def _setup_hcaptcha_route(context):
    """拦截 hCaptcha api.js，注入 hook 代码来捕获 render callback
    核心：ngx-hcaptcha 组件通过 hcaptcha.render(container, {callback: fn})
    注册成功回调。我们拦截 api.js，在代码开头注入 hook 来捕获这个 callback，
    然后在 step10 中直接调用 callback(token) 让 Angular form control 更新。
    """
    async def intercept_hcaptcha_api(route):
        try:
            resp = await route.fetch()
            body = await resp.text()
        except Exception:
            await route.continue_()
            return
        hook_code = """
;(function(){
    window.__hcaptcha_callbacks = window.__hcaptcha_callbacks || [];
    window.__hcaptcha_widget_config = null;
    var _origRender = null;
    var checkCount = 0;
    var hookInterval = setInterval(function(){
        checkCount++;
        if(typeof hcaptcha !== 'undefined' && hcaptcha.render && !_origRender){
            _origRender = hcaptcha.render.bind(hcaptcha);
            hcaptcha.render = function(container, config){
                if(config && typeof config.callback === 'function'){
                    window.__hcaptcha_callbacks.push(config.callback);
                }
                if(config && typeof config['callback-fn'] === 'function'){
                    window.__hcaptcha_callbacks.push(config['callback-fn']);
                }
                window.__hcaptcha_widget_config = config || null;
                return _origRender(container, config);
            };
            clearInterval(hookInterval);
        }
        if(checkCount > 200) clearInterval(hookInterval);
    }, 10);
})();
"""
        try:
            await route.fulfill(response=resp, body=hook_code + body)
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass

    # 兼容 js.hcaptcha.com / newassets.hcaptcha.com 等路径
    for pattern in (
        "**/hcaptcha.com/**/api.js**",
        "**/hcaptcha.com/1/api.js**",
        "**/js.hcaptcha.com/**",
        "**/newassets.hcaptcha.com/**/api.js**",
    ):
        await context.route(pattern, intercept_hcaptcha_api)


async def run_one(headless=False, browser=None, email=None, context_label=None):
    """执行一次完整注册流程，返回结果字典。

    Args:
        headless: 是否无头模式（仅当 browser=None 时生效）
        browser: 外部传入的 browser 实例。若传入，则只创建新 context（用于多 worker 并发）；
                 若为 None，则自行启动 Playwright+Chromium。
        email: 指定邮箱，None 则随机生成
        context_label: 日志前缀（多 worker 区分用）
    """
    if email is None:
        email = generate_random_email()
    reg_start_ts = time.time()
    prefix = f"[{context_label}] " if context_label else ""
    print(f"{prefix}本次注册邮箱: {email}")
    print(f"{prefix}" + "=" * 50)

    result = {"email": email, "api_key": "", "success": False, "failed_step": 0}

    # 外部传入 browser：只创建 context，跑完关闭
    if browser is not None:
        context = await browser.new_context()
        await _setup_hcaptcha_route(context)
        page = await context.new_page()
        try:
            return await _run_pipeline(page, email, reg_start_ts, result)
        finally:
            await context.close()

    # 自启动模式（兼容单跑）
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        await _setup_hcaptcha_route(context)
        page = await context.new_page()
        try:
            return await _run_pipeline(page, email, reg_start_ts, result)
        finally:
            await context.close()
            await browser.close()


def main():
    asyncio.run(run_one(headless=False))


if __name__ == "__main__":
    main()
