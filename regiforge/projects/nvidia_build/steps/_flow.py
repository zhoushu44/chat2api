"""NVIDIA Build 注册流程实现。"""

import os
import re
import sys
import time
import asyncio
import requests as _requests
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from dotenv import load_dotenv

# 步骤 2/4/6/7/8 及辅助函数复用 _rpa.py
from ._rpa import (
    step2_accept_cookies,
    step6_input_password,
    step7_input_confirm_password,
    step8_check_agreement,
    step9_init_and_click_checkbox as step9_nopecha_solve,
    generate_random_email,
    PASSWORD,
    _setup_hcaptcha_route,
)

load_dotenv()

# 邮箱验证码获取器：由 project.py 注入（同步 callable(email, timeout)->code）
_code_fetcher = None
# 邮箱验证码超时（秒）：由 project.py 注入，避免 step12 写死 120s
_mail_timeout = 120


def set_code_fetcher(fn):
    """注入同步验证码获取函数。"""
    global _code_fetcher
    _code_fetcher = fn


def set_mail_timeout(seconds: float) -> None:
    """注入项目 mail_timeout 配置，step12 收码将用此值而非写死 120s。"""
    global _mail_timeout
    try:
        _mail_timeout = max(10.0, float(seconds))
    except (TypeError, ValueError):
        _mail_timeout = 120


def _safe_print(msg: str) -> None:
    """Windows GBK 控制台下避免 page text 含 \\xa0 等字符导致 UnicodeEncodeError。"""
    text = str(msg).replace("\xa0", " ").replace("\u200b", "")
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def cf_fetch_code(email, timeout=None, skip_codes=None):
    if _code_fetcher is None:
        raise RuntimeError("未注入邮箱验证码获取器，请通过 projects.nvidia_build.project 运行")
    if timeout is None:
        timeout = _mail_timeout
    # 注入器签名兼容：若注入器支持 skip_codes 则传，否则忽略（倒退兼容）
    try:
        return _code_fetcher(email, timeout, skip_codes=skip_codes)
    except TypeError:
        return _code_fetcher(email, timeout)

# ============ 配置 ============
SIGNIN_URL = "https://build.nvidia.com/?modal=signin"

# ============ Captcha API 配置 ============
CAPTCHARUN_KEY = os.getenv("CAPTCHARUN_KEY", "d54f3ed6-0753-4ba6-857d-4e3ac56c3853")
CAPTCHARUN_API = "https://api.captcha-run.com/v2/tasks"
CAPTCHARUN_POLL_INTERVAL = 3  # 轮询间隔(秒)
CAPTCHARUN_MAX_POLL = 60       # 最大轮询次数(3s*60=180s)
USE_NOPECHA = os.getenv("USE_NOPECHA", "0").strip().lower() in {"1", "true", "yes", "on"}
USE_NOPECHA_PLUGIN = os.getenv("USE_NOPECHA_PLUGIN", "0").strip().lower() in {"1", "true", "yes", "on"}
NONECAP_EXTENSION_ID = "kahepbmokpbbkfognbmimpmnlfibcolf"
NONECAP_MIN_CHROME_MAJOR = 120
NONECAP_EXTENSION_DIR = os.getenv("NONECAP_EXTENSION_DIR", "").strip()
NOPECHA_PLUGIN_PROFILE_DIR = os.getenv(
    "NOPECHA_PLUGIN_PROFILE_DIR",
    str(Path(__file__).resolve().parents[1] / ".trae" / "chrome-nonecap-profile"),
)


def _find_nonecap_extension_dir() -> Path | None:
    if NONECAP_EXTENSION_DIR:
        path = Path(NONECAP_EXTENSION_DIR)
        return path if (path / "manifest.json").exists() else None

    local_app = os.getenv("LOCALAPPDATA", "")
    if not local_app:
        return None
    base = Path(local_app) / "Google" / "Chrome" / "User Data"
    for profile in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
        ext_root = base / profile / "Extensions" / NONECAP_EXTENSION_ID
        if not ext_root.exists():
            continue
        versions = [p for p in ext_root.iterdir() if (p / "manifest.json").exists()]
        if versions:
            return sorted(versions, key=lambda p: p.name)[-1]
    return None


def get_nonecap_extension_status() -> dict:
    ext_dir = _find_nonecap_extension_dir()
    if not ext_dir:
        return {"installed": False, "compatible": False, "error": "extension_not_found"}
    try:
        import json
        manifest = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))
    except Exception as e:
        return {"installed": True, "compatible": False, "path": str(ext_dir), "error": str(e)}
    min_chrome = int(str(manifest.get("minimum_chrome_version", NONECAP_MIN_CHROME_MAJOR)).split(".")[0])
    compatible = min_chrome <= NONECAP_MIN_CHROME_MAJOR or min_chrome <= 149
    return {
        "installed": True,
        "compatible": compatible,
        "path": str(ext_dir),
        "id": NONECAP_EXTENSION_ID,
        "version": manifest.get("version"),
        "minimum_chrome_version": manifest.get("minimum_chrome_version"),
    }


def get_nopecha_plugin_launch_args(proxy_info=None) -> dict:
    status = get_nonecap_extension_status()
    if not status.get("installed") or not status.get("compatible"):
        raise RuntimeError(f"NoneCap 插件不可用: {status}")
    ext_dir = status["path"]
    launch_args = {
        "headless": False,
        "channel": "chrome",
        "args": [
            f"--disable-extensions-except={ext_dir}",
            f"--load-extension={ext_dir}",
        ],
    }
    if proxy_info:
        launch_args["proxy"] = {"server": proxy_info[0]}
        if len(proxy_info) > 1 and proxy_info[1]:
            launch_args["proxy"]["username"] = proxy_info[1]
            launch_args["proxy"]["password"] = proxy_info[2]
    return launch_args


async def configure_nonecap_plugin(context):
    use_user_key = os.getenv("USE_NOPECHA_PLUGIN_KEY", "0").strip().lower() in {"1", "true", "yes", "on"}
    key = os.getenv("NONECAP_KEY", "").strip() if use_user_key else None
    if use_user_key and not key:
        raise RuntimeError("USE_NOPECHA_PLUGIN_KEY=1 但 NONECAP_KEY 未配置")
    page = await context.new_page()
    try:
        try:
            await page.goto(f"chrome-extension://{NONECAP_EXTENSION_ID}/src/options/index.html", timeout=15000)
        except Exception as e:
            print(f"[NoneCap插件] options 页不可访问，使用插件默认配置: {str(e)[:120]}")
            return {"configured": False, "reason": "options_page_unavailable"}
        state = await page.evaluate(
            """async ({key}) => {
                await chrome.storage.local.set({
                    userKey: key,
                    settings: {
                        autoSolve: true,
                        style: 'human',
                        showOverlay: true,
                        grid: true,
                        drag: true,
                        blocklist: [],
                        pausedHosts: []
                    }
                });
                return await chrome.storage.local.get(['userKey', 'extKey', 'credits', 'settings']);
            }""",
            {"key": key},
        )
        print(f"[NoneCap插件] 配置完成: userKey={'yes' if state.get('userKey') else 'no'} extKey={'yes' if state.get('extKey') else 'no'} credits={state.get('credits')}")
        return state
    finally:
        await page.close()


async def step9_nopecha_plugin_wait(page, timeout_ms=180000):
    print("[步骤9] USE_NOPECHA_PLUGIN=1，等待 NoneCap 插件自动处理 hCaptcha...")
    start = time.perf_counter()
    try:
        await page.wait_for_function(
            """() => {
                const btn = document.querySelector('#register_button');
                const captcha = document.querySelector('[formcontrolname="captcha"]');
                const resp = document.querySelector('[name="h-captcha-response"]');
                return !!btn && !btn.disabled && (
                    !captcha || captcha.classList.contains('ng-valid') || (resp && resp.value && resp.value.length > 20)
                );
            }""",
            timeout=timeout_ms,
        )
        elapsed = time.perf_counter() - start
        print(f"[步骤9] [OK] NoneCap 插件处理完成，耗时 {elapsed:.1f}s")
        return {"ok": True, "elapsed_sec": elapsed}
    except Exception as e:
        elapsed = time.perf_counter() - start
        print(f"[步骤9] [FAIL] NoneCap 插件等待超时/失败，耗时 {elapsed:.1f}s: {e}")
        return {"ok": False, "elapsed_sec": elapsed, "error": str(e)[:200]}


# ============ 步骤 1: 直接打开 signin URL ============

async def step1_open_signin(page):
    """步骤1：直接打开 signin URL，跳过点击 Login 的导航竞争
    代理模式下 signin 模态框可能不加载，需重载页面重试"""
    print(f"[步骤1] 打开 signin URL: {SIGNIN_URL}")
    # 最多重试3次：goto + 等待 email 输入框可见
    for attempt in range(3):
        try:
            await page.goto(SIGNIN_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[步骤1] goto 异常 (第{attempt+1}次): {type(e).__name__}")
            if attempt == 2:
                raise
            await page.wait_for_timeout(3000)
            continue
        # 等邮箱框出现（signin 模态框加载标志）
        try:
            await page.wait_for_selector("input[name='email']", state="visible", timeout=30000)
            print("[步骤1] 完成 - 邮箱输入页已就绪")
            return True
        except PlaywrightTimeoutError:
            # 模态框没加载，重载页面重试
            print(f"[步骤1] email 输入框未出现 (第{attempt+1}次), 模态框未加载, 重载页面...")
            if attempt < 2:
                await page.wait_for_timeout(2000)
    # 最后兜底：检查是否 email 输入框存在（即使 timeout 也可能已加载）
    if await page.locator("input[name='email']").count() > 0:
        print("[步骤1] 完成 - 邮箱输入页已就绪(兜底)")
        return True
    print("[步骤1] [FAIL] 3次重试后 signin 模态框仍未加载")
    return False


# ============ 步骤 3: 填邮箱并点 Next → NVGS 注册页 ============

async def step3_email_next_and_continue(page, email):
    """填邮箱 → 点 Next → 等页面导航到 NVGS 注册页(create-account)
    2026-06 实际行为：点 Next 后 build.nvidia.com 直接导航到
      login.nvgs.nvidia.cn/v1/create-account?...&email=xxx&key=yyy
    邮箱已自动预填，无需再点 #loginNextButton
    """
    # --- 填邮箱（click + type 更易触发前端校验启用 Next）---
    print(f"[步骤3] 输入邮箱: {email}")
    # NVIDIA 登录弹窗会调整 input 属性；按语义从稳定到宽松依次定位。
    email_input = None
    for selector in (
        "input[type='email']:visible",
        "input[name='email']:visible",
        "input[autocomplete='email']:visible",
        "input[placeholder*='email' i]:visible",
        ".nv-modal-content input:visible",
    ):
        candidate = page.locator(selector).first
        if await candidate.count() > 0:
            email_input = candidate
            print(f"[步骤3] 邮箱框选择器: {selector}")
            break
    if email_input is None:
        raise RuntimeError("NVIDIA signin 弹窗中未找到可见邮箱输入框")
    try:
        await email_input.click(timeout=5000)
        await email_input.fill("")
        await email_input.type(email, delay=30)
    except Exception:
        await email_input.fill(email)
    try:
        await email_input.dispatch_event("input")
        await email_input.dispatch_event("change")
        await email_input.dispatch_event("blur")
    except Exception:
        pass
    # 校验模态框内邮箱值，不对则重填（减少「看起来填了其实空」）
    try:
        got = (await email_input.input_value() or "").strip()
        if got.lower() != str(email).strip().lower():
            print(f"[步骤3] 邮箱值不一致 got={got!r}，重填")
            await email_input.fill(email)
            await email_input.dispatch_event("input")
            await email_input.dispatch_event("change")
    except Exception:
        pass
    await page.wait_for_timeout(1000)
    print("[步骤3] 完成 - 邮箱已输入")

    # --- 等 Next 按钮启用并点击 ---
    enabled = False
    for i in range(30):
        dis = await page.evaluate("""() => {
            const candidates = Array.from(document.querySelectorAll('button'))
                .filter(b => (b.textContent || '').trim() === 'Next');
            // 优先可见；否则取第一个
            const b = candidates.find(b => b.offsetParent !== null) || candidates[0] || null;
            if (!b) return { found: false, disabled: null, visible: false };
            return {
                found: true,
                disabled: !!b.disabled,
                visible: b.offsetParent !== null,
                aria: b.getAttribute('aria-disabled'),
            };
        }""")
        if isinstance(dis, dict) and dis.get("found") and dis.get("disabled") is False and dis.get("aria") != "true":
            enabled = True
            break
        # 中途再清一次 Cookie，避免遮罩导致 Next 不启用
        if i in (8, 16):
            try:
                await step2_accept_cookies(page)
            except Exception:
                pass
            try:
                await email_input.fill(email)
            except Exception:
                pass
        await page.wait_for_timeout(500)
    if not enabled:
        err = await page.evaluate("""() => {
            const e = document.querySelectorAll('.error, [role="alert"], .nv-text-input__error, [class*="error"]');
            return Array.from(e).map(x => x.textContent.trim()).filter(t => t).join(' | ');
        }""")
        print(f"[步骤3] [FAIL] Next 按钮未启用, 错误提示: {err}")
        try:
            await page.screenshot(path="data/logs/step3_next_disabled.png")
        except Exception:
            await page.screenshot(path="step3_next_disabled.png")
        return False

    print("[步骤3] Next 按钮已启用，点击 ...")
    # 点 Next 前强制再处理一次 Cookie（Banner 常在 step2 之后才弹出，会挡住 Next）
    try:
        await step2_accept_cookies(page)
    except Exception as e:
        print(f"[步骤3] 预点 Cookie 异常: {e}")

    clicked_next = False
    for sel in [
        ".nv-modal-content button.btn-primary.btn-lg.btn-rounded >> visible=true",
        ".nv-modal-content button.btn-primary.btn-lg.btn-rounded",
        "button.btn-primary.btn-lg.btn-rounded >> visible=true",
        "button.btn-primary.btn-lg.btn-rounded",
        "button.btn-primary.btn-lg",
        "button.btn-primary",
    ]:
        try:
            loc = page.locator(sel).first
            cnt = await loc.count()
            if cnt > 0:
                await loc.click(force=True, no_wait_after=True)
                print(f"[步骤3] 已点击 Next: {sel}")
                clicked_next = True
                break
        except Exception as e:
            print(f"[步骤3] 点击 {sel} 失败: {e}")
            continue

    # Next 仍失败：再清 Cookie 后重试
    if not clicked_next:
        try:
            await step2_accept_cookies(page)
        except Exception:
            pass
        for sel2 in [
            ".nv-modal-content button.btn-primary.btn-lg.btn-rounded >> visible=true",
            "button.btn-primary.btn-lg.btn-rounded >> visible=true",
            "button.btn-primary.btn-lg.btn-rounded",
            "button.btn-primary",
        ]:
            try:
                loc2 = page.locator(sel2).first
                if await loc2.count() > 0:
                    await loc2.click(force=True, no_wait_after=True)
                    print(f"[步骤3] Cookie后已点击 Next: {sel2}")
                    clicked_next = True
                    break
            except Exception:
                continue

    if not clicked_next:
        # JS 兜底：找文本为 Next/Continue 的可见按钮
        print("[步骤3] 尝试 JS evaluate 兜底点击 Next ...")
        js_clicked = await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button'))
                .filter(b => b.offsetParent !== null);
            // 优先精确匹配 Next
            let b = btns.find(b => b.textContent.trim() === 'Next');
            if (!b) b = btns.find(b => b.textContent.trim() === 'Continue');
            if (!b) b = btns.find(b => /next|continue/i.test(b.textContent) && b.className.includes('btn-primary'));
            if (b) { b.click(); return 'clicked: ' + b.textContent.trim(); }
            return 'no Next button found, all=' + btns.map(b => b.textContent.trim().substring(0,30)).join(' | ');
        }""")
        print(f"[步骤3] JS 兜底结果: {js_clicked}")
        clicked_next = js_clicked.startswith("clicked")

    # 等 URL 导航到 nvgs/login/create-account 域
    navigated = False
    for _ in range(50):  # 最多等 25s
        await page.wait_for_timeout(500)
        url = page.url
        if "nvgs" in url or ("login" in url and "build.nvidia" not in url) or "create-account" in url:
            print(f"[步骤3] 页面已导航到: {url}")
            navigated = True
            break
    if not navigated:
        print(f"[步骤3] [WARN] 点击后URL未变, 当前: {page.url}")
        # 诊断：模态框/错误提示/Next 状态（常见于直连 IP 被拒或点错隐藏按钮）
        try:
            diag = await page.evaluate("""() => {
                const modal = document.querySelector('.nv-modal-content');
                const email = document.querySelector("input[name='email']");
                const next = Array.from(document.querySelectorAll('button'))
                    .find(b => b.offsetParent !== null && b.textContent.trim() === 'Next');
                const errs = Array.from(document.querySelectorAll(
                    '.error, [role="alert"], .nv-text-input__error, [class*="error"], [class*="Error"]'
                )).map(x => (x.textContent || '').trim()).filter(Boolean).slice(0, 5);
                return {
                    hasModal: !!modal,
                    emailValue: email ? email.value : null,
                    nextDisabled: next ? next.disabled : null,
                    nextText: next ? next.textContent.trim() : null,
                    errors: errs,
                };
            }""")
            print(f"[步骤3] 诊断: {diag}")
        except Exception as e:
            print(f"[步骤3] 诊断失败: {e}")

    # --- 确认 URL 已导航 ---
    url = page.url
    if "nvgs" not in url and "create-account" not in url and ("login" not in url or "build.nvidia" in url):
        print("[步骤3] [WARN] 点击后仍在 build.nvidia.com, 等待额外5s...")
        await page.wait_for_timeout(5000)

    # --- 等注册表单出现（可能直接到 create-account，也可能先进 identifier 页）---
    try:
        sel = "#registration_password, #loginNextButton"
        await page.wait_for_selector(sel, state="visible", timeout=25000)
    except PlaywrightTimeoutError:
        print(f"[步骤3] [FAIL] 注册表单和标识页均未出现, URL: {page.url}")
        # dump 页面信息便于排查
        body_text = await page.evaluate("() => document.body.innerText.substring(0, 500)")
        print(f"[步骤3] 页面文本: {body_text}")
        try:
            await page.screenshot(path="data/debug/nvidia_build/step3_stuck.png", full_page=True)
            print("[步骤3] 截图: data/debug/nvidia_build/step3_stuck.png")
        except Exception:
            pass
        return False

    # 如果是 identifier 页，还需点 #loginNextButton
    has_next_btn = await page.locator("#loginNextButton").count()
    if has_next_btn:
        print("[步骤3] 在 NVGS 标识页，点击 #loginNextButton ...")
        try:
            await page.locator("#loginNextButton").click(force=True, no_wait_after=True, timeout=10000)
        except Exception as e:
            print(f"[步骤3] 点击 #loginNextButton 失败: {e}")
        try:
            await page.wait_for_selector("#registration_password", state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            print(f"[步骤3] [FAIL] #registration_password 未出现, URL: {page.url}")
            return False

    # 确认注册表单已就绪
    has_reg = await page.locator("#registration_password").count()
    if has_reg:
        print(f"[步骤3] 已到 create-account 注册表单页: {page.url}")
        return True
    print(f"[步骤3] [FAIL] 未到注册表单, URL: {page.url}")
    return False


# ============ 步骤 9: CaptchaRun API 解决 hCaptcha ============

async def step9_captcharun_solve(page):
    """步骤9：根据 USE_NOPECHA 开关选择 NOPECHA 或 CaptchaRun 获取 hCaptcha token"""
    if USE_NOPECHA:
        print("[步骤9] USE_NOPECHA=1，使用 NOPECHA 解决 hCaptcha...")
        _, token = await step9_nopecha_solve(page)
        return token

    print("[步骤9] 使用 CaptchaRun API 解决 hCaptcha...")

    # 提取 sitekey（多种方式，NVGS 页 widget 无 data-sitekey，从 iframe src / hcaptcha.getConfig 取）
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
        return None

    # siteReferer：create-account 页 origin
    parsed = urlparse(page.url)
    site_referer = f"{parsed.scheme}://{parsed.netloc}/"
    print(f"[步骤9] sitekey={sitekey}  siteReferer={site_referer}")

    # --- 创建任务 ---
    task_payload = {
        "captchaType": "HCaptcha",
        "siteKey": sitekey,
        "siteReferer": site_referer,
        "fallbackToActualUA": True,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CAPTCHARUN_KEY}",
    }

    try:
        create_resp = _requests.post(CAPTCHARUN_API, headers=headers, json=task_payload, timeout=30)
    except Exception as e:
        print(f"[步骤9] [FAIL] 创建任务请求异常: {e}")
        return None

    print(f"[步骤9] 创建任务响应: HTTP {create_resp.status_code}")
    if create_resp.status_code not in (200, 201):
        print(f"[步骤9] [FAIL] 创建任务失败: {create_resp.text[:300]}")
        return None

    task_data = create_resp.json()
    task_id = task_data.get("taskId")
    if not task_id:
        print(f"[步骤9] [FAIL] 响应中无 taskId: {task_data}")
        return None
    print(f"[步骤9] 任务已创建, taskId={task_id}")

    # --- 轮询获取结果 ---
    poll_url = f"{CAPTCHARUN_API}/{task_id}"
    for poll_i in range(CAPTCHARUN_MAX_POLL):
        await page.wait_for_timeout(CAPTCHARUN_POLL_INTERVAL * 1000)
        try:
            poll_resp = _requests.get(poll_url, headers=headers, timeout=15)
        except Exception as e:
            print(f"[步骤9] 轮询异常: {e}")
            continue

        if poll_resp.status_code != 200:
            print(f"[步骤9] 轮询 HTTP {poll_resp.status_code}, 重试...")
            continue

        result = poll_resp.json()
        status = result.get("status", "")

        if status == "Working":
            if poll_i % 5 == 0:
                print(f"[步骤9] 轮询中... ({poll_i + 1}/{CAPTCHARUN_MAX_POLL}) status=Working")
            continue

        if status == "Fail":
            print(f"[步骤9] [FAIL] CaptchaRun 任务失败: {result.get('reason', 'unknown')}")
            return None

        # 非 Working/Fail：检查 token
        response_obj = result.get("response", {})
        token = response_obj.get("gRecaptchaResponse") if isinstance(response_obj, dict) else None
        if not token:
            token = (result.get("gRecaptchaResponse") or result.get("token")
                     or (result.get("solution") or {}).get("gRecaptchaResponse"))
        if token:
            print(f"[步骤9] [OK] CaptchaRun token 获取成功 (status={status}), 长度={len(token)}")
            return token
        if poll_i % 5 == 0:
            print(f"[步骤9] status={status}, response={str(result)[:200]}")

    print("[步骤9] [FAIL] CaptchaRun 轮询超时")
    return None


# ============ 步骤 10: 注入 token ============

async def step10_inject_token(page, token):
    """步骤10：调用 hcaptcha render callback 注入 token"""
    print("[步骤10] 调用 hcaptcha callback 注入 CaptchaRun token...")
    escaped_token = token.replace("\\", "\\\\").replace("'", "\\'")

    # 注入方式1：postMessage 模拟 hCaptcha challenge-passed 事件
    print("[步骤10] 尝试 postMessage 注入...")
    pm_result = await page.evaluate(f"""() => {{
        var token = '{escaped_token}';
        var iframes = document.querySelectorAll("iframe[data-hcaptcha-widget-id]");
        var injected = 0;
        for (var i = 0; i < iframes.length; i++) {{
            var id = iframes[i].attributes["data-hcaptcha-widget-id"].value;
            var data = JSON.stringify({{
                source: "hcaptcha", label: "challenge-closed", id: id,
                contents: {{ event: "challenge-passed", response: token, expiration: 120 }}
            }});
            window.dispatchEvent(new MessageEvent('message', {{data: data}}));
            injected++;
        }}
        return injected;
    }}""")
    print(f"[步骤10] postMessage 注入到 {pm_result} 个 iframe")

    # 注入方式2：调用 hcaptcha render callback
    callback_count = await page.evaluate("(window.__hcaptcha_callbacks || []).length")
    print(f"[步骤10] __hcaptcha_callbacks 数量: {callback_count}")

    debug_info = await page.evaluate("""() => ({
        hasHcaptcha: typeof hcaptcha !== 'undefined',
        hasCaptchaEl: !!document.querySelector('[formcontrolname="captcha"]'),
        captchaClasses: document.querySelector('[formcontrolname="captcha"]')?.className || 'N/A',
        hasRegisterBtn: !!document.querySelector('#register_button'),
        btnDisabled: document.querySelector('#register_button')?.disabled ?? 'N/A',
        hcaptchaResponseEl: !!document.querySelector('[name="h-captcha-response"]'),
        iframes: document.querySelectorAll('iframe[data-hcaptcha-widget-id]').length,
    })""")
    print(f"[步骤10] 调试信息: {debug_info}")

    if callback_count > 0:
        result = await page.evaluate(f"""() => {{
            var token = '{escaped_token}';
            var callbacks = window.__hcaptcha_callbacks || [];
            var results = [];
            for (var i = 0; i < callbacks.length; i++) {{
                try {{ callbacks[i](token); results.push('callback#' + i + ' OK'); }}
                catch(e) {{ results.push('callback#' + i + ' err: ' + e.message); }}
            }}
            var el = document.querySelector('[name="h-captcha-response"]');
            if (el) el.value = token;
            var widget = document.querySelector('[data-hcaptcha-widget-id]');
            if (widget) widget.setAttribute('data-hcaptcha-response', token);
            return results.join('; ');
        }}""")
        print(f"[步骤10] callback 调用结果: {result}")
        await page.wait_for_timeout(1500)

        state = await page.evaluate("""() => {
            var captchaEl = document.querySelector('[formcontrolname="captcha"]');
            var btn = document.querySelector('#register_button');
            return {
                captchaValid: captchaEl ? captchaEl.classList.contains('ng-valid') : false,
                btnDisabled: btn ? btn.disabled : true
            };
        }""")
        if state.get("captchaValid") and not state.get("btnDisabled"):
            print("[步骤10] [OK] Angular form control 已 valid，按钮已启用")
            return True
        print(f"[步骤10] [WARN] callback 后状态: {state}")

    # 注入方式3：hcaptcha 全局对象
    set_result = await page.evaluate(f"""() => {{
        var token = '{escaped_token}'; var ok = false;
        if (typeof hcaptcha !== 'undefined') {{
            try {{
                var widgets = document.querySelectorAll('[data-hcaptcha-widget-id]');
                widgets.forEach(function(w) {{
                    var wid = w.attributes["data-hcaptcha-widget-id"].value;
                    try {{ hcaptcha.setValue(wid, token); ok = true; }} catch(e) {{}}
                }});
                try {{ hcaptcha.setResponse(token); ok = true; }} catch(e) {{}}
                if (hcaptcha.getResponse) hcaptcha.getResponse = function() {{ return token; }};
                if (hcaptcha.execute) hcaptcha.execute = function() {{ return Promise.resolve(token); }};
            }} catch(e) {{}}
        }}
        return ok;
    }}""")
    print(f"[步骤10] hcaptcha 全局对象设置: {set_result}")

    # 兜底：手动设 Angular 状态 + h-captcha-response + 强制启用按钮
    print("[步骤10] 尝试兜底方案...")
    await page.evaluate(f"""() => {{
        var token = '{escaped_token}';
        function markValid(el) {{
            if (!el) return;
            el.classList.remove('ng-invalid', 'ng-untouched', 'ng-pristine');
            el.classList.add('ng-valid', 'ng-dirty', 'ng-touched');
        }}
        var el = document.querySelector('[name="h-captcha-response"], textarea[name="h-captcha-response"]');
        if (!el) {{
            el = document.createElement('textarea');
            el.name = 'h-captcha-response';
            el.style.display = 'none';
            (document.querySelector('form') || document.body).appendChild(el);
        }}
        el.value = token;
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));

        var gresp = document.querySelector('[name="g-recaptcha-response"]');
        if (gresp) {{
            gresp.value = token;
            gresp.dispatchEvent(new Event('input', {{bubbles: true}}));
        }}

        var widget = document.querySelector('[data-hcaptcha-widget-id], iframe[src*="hcaptcha"]');
        if (widget) {{
            try {{ widget.setAttribute('data-hcaptcha-response', token); }} catch (e) {{}}
            markValid(widget.parentElement);
        }}
        var captchaEl = document.querySelector('[formcontrolname="captcha"], .captcha-block');
        markValid(captchaEl);

        // 尝试写入 Angular 表单控件（Ivy / 旧 probe）
        try {{
            var nodes = [captchaEl, el, document.querySelector('form')].filter(Boolean);
            for (var i = 0; i < nodes.length; i++) {{
                var n = nodes[i];
                var keys = Object.keys(n);
                for (var k = 0; k < keys.length; k++) {{
                    var key = keys[k];
                    if (key.indexOf('__ngContext') === 0 || key.indexOf('_ng') === 0) {{
                        // 无法稳定遍历 context，跳过
                    }}
                }}
                if (n.__ngContext__ && Array.isArray(n.__ngContext__)) {{
                    // 尽力而为：找到带 setValue/patchValue 的对象
                    n.__ngContext__.forEach(function(item) {{
                        try {{
                            if (item && typeof item.setValue === 'function') item.setValue(token);
                            if (item && item.control && typeof item.control.setValue === 'function') item.control.setValue(token);
                            if (item && item.form && item.form.controls && item.form.controls.captcha) {{
                                item.form.controls.captcha.setValue(token);
                                item.form.controls.captcha.markAsDirty();
                                item.form.controls.captcha.updateValueAndValidity();
                            }}
                        }} catch (e) {{}}
                    }});
                }}
            }}
            if (window.ng && typeof window.ng.getComponent === 'function') {{
                var host = document.querySelector('form') || captchaEl;
                var comp = host ? window.ng.getComponent(host) : null;
                if (comp) {{
                    var ctrl = comp.captcha || (comp.form && (comp.form.controls || {{}}).captcha) || null;
                    if (ctrl && typeof ctrl.setValue === 'function') {{
                        ctrl.setValue(token);
                        if (ctrl.markAsDirty) ctrl.markAsDirty();
                        if (ctrl.updateValueAndValidity) ctrl.updateValueAndValidity();
                    }}
                }}
            }}
        }} catch (e) {{}}

        if (typeof hcaptcha === 'undefined') {{
            window.hcaptcha = {{
                getResponse: function() {{ return token; }},
                execute: function() {{ return Promise.resolve(token); }},
                render: function() {{ return '1'; }},
                reset: function() {{}},
                remove: function() {{}},
            }};
        }} else {{
            try {{ hcaptcha.getResponse = function() {{ return token; }}; }} catch (e) {{}}
            try {{ hcaptcha.execute = function() {{ return Promise.resolve(token); }}; }} catch (e) {{}}
        }}

        // 强制启用创建账户按钮（token 已写入表单字段）
        var btn = document.querySelector('#register_button');
        if (btn) {{
            btn.disabled = false;
            btn.removeAttribute('disabled');
            btn.classList.remove('disabled');
            btn.setAttribute('aria-disabled', 'false');
        }}
        // 同步清理 form 的 ng-invalid
        document.querySelectorAll('form .ng-invalid').forEach(function(node) {{
            if (node.matches('[formcontrolname="captcha"], .captcha-block, [name="h-captcha-response"]')) {{
                markValid(node);
            }}
        }});
    }}""")
    await page.wait_for_timeout(800)

    final_state = await page.evaluate("""() => ({
        captchaValid: document.querySelector('[formcontrolname="captcha"]')?.classList.contains('ng-valid') || false,
        btnDisabled: document.querySelector('#register_button')?.disabled ?? true,
        hcaptchaResponse: document.querySelector('[name="h-captcha-response"]')?.value?.length || 0,
        formInvalid: document.querySelectorAll('form .ng-invalid').length,
    })""")
    print(f"[步骤10] 兜底后最终状态: {final_state}")
    return True


# ============ 步骤 11: 点击创建账号 ============

async def step11_click_create_account(page):
    """步骤11：点击 #register_button (创建账户)"""
    print("[步骤11] 点击创建账号按钮 (#register_button) ...")
    btn = page.locator("#register_button")
    try:
        await btn.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        pass
    except Exception:
        pass

    # 若按钮仍 disabled，强制解除 + 等 Angular 异步启用
    for _ in range(8):
        state = await page.evaluate(
            """() => {
                const btn = document.querySelector('#register_button');
                if (!btn) return {exists: false, disabled: true};
                if (btn.disabled) {
                    btn.disabled = false;
                    btn.removeAttribute('disabled');
                    btn.classList.remove('disabled');
                }
                return {exists: true, disabled: !!btn.disabled};
            }"""
        )
        if state.get("exists") and not state.get("disabled"):
            break
        await page.wait_for_timeout(500)

    clicked = False
    try:
        await btn.click(no_wait_after=True, force=True, timeout=5000)
        print("[步骤11] 已点击 #register_button (force)")
        clicked = True
    except Exception as e:
        print(f"[步骤11] Playwright 点击失败: {e}")

    if not clicked:
        js_click = await page.evaluate(
            """() => {
                const btn = document.querySelector('#register_button');
                if (!btn) return 'no-btn';
                btn.disabled = false;
                btn.removeAttribute('disabled');
                btn.click();
                const form = btn.closest('form');
                if (form) {
                    try { form.requestSubmit ? form.requestSubmit(btn) : form.dispatchEvent(new Event('submit', {bubbles:true, cancelable:true})); } catch (e) {}
                }
                return 'js-click';
            }"""
        )
        print(f"[步骤11] JS 兜底点击: {js_click}")

    # 等待跳转或验证码输入框（邮箱验证）
    try:
        await page.wait_for_url("**/profile-complete**", timeout=20000)
    except PlaywrightTimeoutError:
        try:
            await page.wait_for_selector(
                "input[type='number'], input[maxlength='1'], input[autocomplete='one-time-code']",
                timeout=10000,
            )
        except Exception:
            await page.wait_for_timeout(2000)
    except Exception:
        await page.wait_for_timeout(2000)

    print(f"[步骤11] 当前URL: {page.url}")

    # NVIDIA 服务端错误页检测：URL 含 /v1/error 且 jarvis_error 参数 → 创建账号失败
    # 之前在此处假阳性 OK=true，导致 step12 在 error 页空等 mail_timeout 秒
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(page.url)
    if "/v1/error" in (parsed.path or ""):
        qs = parse_qs(parsed.query or "")
        jarvis_err = (qs.get("jarvis_error") or [""])[0]
        _safe_print(
            f"[步骤11] [FAIL] 跳到 NVIDIA 错误页 /v1/error，jarvis_error={jarvis_err}"
        )
        return False

    return True


# ============ 步骤 12: 通过共用邮箱 Provider 读验证码并提交 ============

async def step12_verify_email(page, target_email):
    """步骤12：profile-complete 页邮箱验证 + 提交验证码"""
    _safe_print("[步骤12] 邮箱验证 ...")
    await page.wait_for_timeout(3000)
    _safe_print(f"[步骤12] 当前URL: {page.url}")

    # dump profile-complete 页结构
    probe = await page.evaluate("""() => ({
        url: location.href,
        text: document.body.innerText.substring(0, 800),
        inputs: Array.from(document.querySelectorAll('input')).filter(i=>i.offsetParent!==null).map(i=>({
            id:i.id, name:i.name, type:i.type, maxlength:i.getAttribute('maxlength'),
            placeholder:i.placeholder, cls:i.className.substring(0,60)
        })),
        buttons: Array.from(document.querySelectorAll('button')).filter(b=>b.offsetParent!==null&&b.textContent.trim())
            .map(b=>({text:b.textContent.trim().substring(0,30), id:b.id, disabled:b.disabled, cls:b.className.substring(0,60)})),
    })""")
    _safe_print(
        f"[步骤12] profile-complete 探查:\n  text={probe.get('text','')[:400]}\n"
        f"  inputs={probe.get('inputs')}\n  buttons={probe.get('buttons')}"
    )
    try:
        await page.screenshot(path="data/debug/nvidia_build/profile_complete_page.png")
    except Exception:
        pass

    # 由 project.py 注入共用邮箱 Provider，支持 CloudMail 及兼容后端。
    # 内部 retry once：若 NVIDIA 返回"验证码无效"，则点"重新请求新验证码"+ 把旧 code 加进 skip_codes 再取一次。
    used_codes = []

    async def _fetch_code_once(skip_codes):
        _safe_print(f"[步骤12] 等待邮箱 Provider 返回验证码 ... (mail_timeout={_mail_timeout}s skip={len(skip_codes or [])})")
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: cf_fetch_code(target_email, skip_codes=skip_codes or None)
        )

    async def _fill_and_submit(otp_code):
        """填 OTP/单格验证码并提交。返回 clicked=True/False。"""
        otp_inputs = page.locator("input[maxlength='1']:visible")
        otp_count = await otp_inputs.count()
        _safe_print(f"[步骤12] OTP 单格输入框数量: {otp_count}")
        if otp_count >= len(otp_code):
            for idx, ch in enumerate(otp_code):
                await otp_inputs.nth(idx).fill(ch)
                await otp_inputs.nth(idx).dispatch_event("input")
                await otp_inputs.nth(idx).dispatch_event("change")
                await page.wait_for_timeout(60)
            _safe_print(f"[步骤12] 已填入 OTP: {otp_code}")
            btn_enabled = False
            for _ in range(10):
                is_dis = await page.evaluate("""() => {
                    const b = Array.from(document.querySelectorAll('button'))
                        .find(b => b.offsetParent !== null && /continue|继续|verify|next/i.test(b.textContent));
                    return b ? b.disabled : null;
                }""")
                if is_dis is False:
                    btn_enabled = True
                    break
                await page.wait_for_timeout(500)
            if not btn_enabled:
                _safe_print("[步骤12] [WARN] Continue 按钮未启用，尝试 JS 重新填入 OTP ...")
                await page.evaluate(f"""() => {{
                    const code = '{otp_code}';
                    const inputs = Array.from(document.querySelectorAll("input[maxlength='1']")).filter(i => i.offsetParent !== null);
                    for (let i = 0; i < inputs.length && i < code.length; i++) {{
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        setter.call(inputs[i], code[i]);
                        inputs[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                        inputs[i].dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}""")
                await page.wait_for_timeout(1000)
        else:
            filled = False
            for sel in ["input[type='number']:visible", "input[name*='code']:visible", "input[name*='verif']:visible",
                        "input[autocomplete='one-time-code']:visible", "input:visible"]:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.fill(otp_code)
                        _safe_print(f"[步骤12] 已填入验证码到 {sel}: {otp_code}")
                        filled = True
                        break
                except Exception:
                    continue
            if not filled:
                _safe_print(f"[步骤12] [WARN] 未找到验证码输入框，code={otp_code}")

        await page.wait_for_timeout(800)
        clicked_once = False
        for sel in [
            "button:has-text('继续'):visible",
            "button:has-text('Continue'):visible",
            "button[type='submit']:visible",
            "button:has-text('验证'):visible",
            "button:has-text('下一步'):visible",
            "button:has-text('Verify'):visible",
            "button:has-text('Submit'):visible",
        ]:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                try:
                    disabled = await loc.is_disabled()
                except Exception:
                    disabled = False
                if disabled:
                    await page.evaluate(
                        """(sel) => {
                            const nodes = Array.from(document.querySelectorAll('button'));
                            const b = nodes.find(n => n.offsetParent !== null && /继续|continue|verify|next|submit|验证|下一步/i.test(n.textContent||''));
                            if (!b) return false;
                            b.disabled = false;
                            b.removeAttribute('disabled');
                            b.classList.remove('disabled');
                            b.click();
                            return true;
                        }"""
                    )
                    _safe_print("[步骤12] 按钮 disabled，已 JS 强制点击")
                else:
                    await loc.click(no_wait_after=True)
                    _safe_print(f"[步骤12] 已点击 {sel}")
                clicked_once = True
                break
            except Exception:
                continue
        if not clicked_once:
            js_clicked = await page.evaluate(
                """() => {
                    const b = Array.from(document.querySelectorAll('button'))
                        .find(n => n.offsetParent !== null && /继续|continue|verify|next|submit|验证|下一步/i.test(n.textContent||''));
                    if (!b) return false;
                    b.disabled = false;
                    b.removeAttribute('disabled');
                    b.click();
                    return true;
                }"""
            )
            _safe_print(f"[步骤12] JS 兜底点击 Continue: {js_clicked}")
            clicked_once = bool(js_clicked)
        return clicked_once

    code = await _fetch_code_once(used_codes)
    if not code:
        _safe_print("[步骤12] [FAIL] 邮箱 Provider 未获取到验证码，跳过提交")
        return False
    used_codes.append(str(code).strip())

    await _fill_and_submit(code)

    # 成功条件：离开 profile-complete（consent / build / login 回调等）
    # 失败 rescue：检测"验证码无效"提示 -> 点"重新请求新验证码"链接 -> 再取一次新码 -> 重新填+提交
    retried_for_invalid = False
    left_profile = False
    for wait_i in range(20):
        url = page.url or ""
        if "profile-complete" not in url:
            left_profile = True
            break
        if url.startswith("chrome-error://"):
            break
        # 检测"验证码无效"提示并触发一次 retry
        if not retried_for_invalid and wait_i >= 2:
            invalid_seen = await page.evaluate(
                """() => {
                    const t = document.body && document.body.innerText ? document.body.innerText : '';
                    return /验证码无效|invalid|无效/.test(t) && !!document.querySelector('.notice-alert');
                }"""
            )
            if invalid_seen:
                _safe_print("[步骤12] 检测到 NVIDIA '验证码无效' 提示，准备申请重发...")
                # 点"重新请求新验证码"链接
                clicked_resend = await page.evaluate(
                    """() => {
                        const links = Array.from(document.querySelectorAll('a'));
                        const link = links.find(a => /重新请求|resend|重新发送|request new code/i.test(a.textContent||''));
                        if (link) { link.click(); return true; }
                        return false;
                    }"""
                )
                _safe_print(f"[步骤12] 点击'重新请求新验证码'链接: {clicked_resend}")
                await page.wait_for_timeout(1500)
                # 重新拉取新 code（跳过已用过的）
                new_code = await _fetch_code_once(used_codes)
                if not new_code:
                    _safe_print("[步骤12] [FAIL] 重发后仍未拿到新验证码")
                    return False
                if str(new_code).strip() in used_codes:
                    _safe_print(f"[步骤12] [WARN] 重发后拿到与上次相同的 code={new_code}，跳过")
                    return False
                used_codes.append(str(new_code).strip())
                # 清空已填的 OTP 输入框再重新填
                await page.evaluate(
                    """() => {
                        const inputs = Array.from(document.querySelectorAll("input[maxlength='1']")).filter(i => i.offsetParent !== null);
                        inputs.forEach(i => { const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set; s.call(i, ''); i.dispatchEvent(new Event('input', {bubbles: true})); });
                    }"""
                )
                await _fill_and_submit(new_code)
                retried_for_invalid = True
                continue
        # 仍在 OTP 页时，重试 JS 填码+点继续（并发下 Angular 偶发未吃到 input）
        if wait_i in (4, 10) and code:
            try:
                await page.evaluate(
                    f"""() => {{
                        const code = '{code}';
                        const inputs = Array.from(document.querySelectorAll("input[maxlength='1']")).filter(i => i.offsetParent !== null);
                        for (let i = 0; i < inputs.length && i < code.length; i++) {{
                            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            setter.call(inputs[i], code[i]);
                            inputs[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                            inputs[i].dispatchEvent(new Event('change', {{bubbles: true}}));
                        }}
                        const b = Array.from(document.querySelectorAll('button'))
                            .find(n => n.offsetParent !== null && /继续|continue|verify|next|submit|验证|下一步/i.test(n.textContent||''));
                        if (b) {{ b.disabled = false; b.removeAttribute('disabled'); b.click(); }}
                    }}"""
                )
                _safe_print(f"[步骤12] 仍在 profile-complete，第{wait_i}次重试提交 OTP")
            except Exception:
                pass
        await page.wait_for_timeout(1000)

    final_url = page.url or ""
    _safe_print(f"[步骤12] 提交后URL: {final_url}")
    try:
        await page.screenshot(path="data/debug/nvidia_build/after_verify.png")
    except Exception:
        pass

    if final_url.startswith("chrome-error://"):
        _safe_print("[步骤12] [FAIL] 页面落到 chrome-error")
        return False
    if "profile-complete" in final_url:
        _safe_print("[步骤12] [FAIL] 提交 OTP 后仍停在 profile-complete")
        return False
    if not left_profile:
        _safe_print("[步骤12] [FAIL] 邮箱验证未离开 profile-complete")
        return False
    return True


# ============ 辅助: 处理 select-account (创建云账户) ============

async def _handle_select_account(page):
    """处理 cloudaccounts.nvidia.com 的 select-account 页面。
    
    页面可能使用 iframe 嵌套 KUI 组件，需要同时搜索主文档和 iframe 内的元素。
    SPA 页面渲染较慢，需要轮询等待元素出现。
    返回 True 表示处理完成（无论成功失败），False 表示需要重试。
    """
    try:
        # 等页面完全加载 — cloudaccounts 是 SPA，需要等 JS 渲染
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # 轮询等待 SPA 渲染出元素（最多 30 秒）
        print("[select-account] 等待 SPA 渲染...")
        found_elements = False
        for poll_i in range(15):
            await page.wait_for_timeout(2000)
            # 同时检查主文档 + Playwright frames
            total_inputs = 0
            total_buttons = 0
            for frame in page.frames:
                try:
                    n_inputs = await frame.evaluate("() => document.querySelectorAll('input').length")
                    n_buttons = await frame.evaluate("() => document.querySelectorAll('button').length")
                    total_inputs += n_inputs
                    total_buttons += n_buttons
                except Exception:
                    pass
            # 也检查 iframe 元素（主文档级别）
            try:
                n_iframes = await page.evaluate("() => document.querySelectorAll('iframe').length")
            except Exception:
                n_iframes = 0
            print(f"[select-account] 轮询 {poll_i+1}/15: inputs={total_inputs} buttons={total_buttons} iframes={n_iframes}")
            if total_inputs > 0 or total_buttons > 0 or n_iframes > 0:
                found_elements = True
                break
            # 检查是否 403
            try:
                page_text = await page.evaluate("() => document.body.innerText.substring(0, 100)")
                if "403" in page_text or "Forbidden" in page_text:
                    print(f"[select-account] 页面返回 403，需要先登录: {page_text}")
                    break
            except Exception:
                pass

        if not found_elements:
            # 可能 403 或页面未加载，尝试刷新
            print("[select-account] 未找到任何元素，尝试刷新页面...")
            try:
                await page.reload(wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(5000)
                for poll_i in range(10):
                    total_inputs = 0
                    for frame in page.frames:
                        try:
                            n = await frame.evaluate("() => document.querySelectorAll('input').length")
                            total_inputs += n
                        except Exception:
                            pass
                    if total_inputs > 0:
                        found_elements = True
                        break
                    await page.wait_for_timeout(2000)
            except Exception as e:
                print(f"[select-account] 刷新失败: {e}")

        # 探查页面结构
        probe_main = await page.evaluate("""() => ({
            url: location.href.substring(0, 120),
            iframes: Array.from(document.querySelectorAll('iframe')).map(f => ({
                src: (f.src || f.getAttribute('src') || '').substring(0, 120),
                id: f.id, name: f.name, cls: f.className.substring(0, 40),
                w: f.offsetWidth, h: f.offsetHeight
            })),
            inputs: Array.from(document.querySelectorAll('input')).filter(i => i.offsetParent !== null).length,
            buttons: Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).length
        })""")
        print(f"[select-account] 主文档: iframes={probe_main.get('iframes')} inputs={probe_main.get('inputs')} buttons={probe_main.get('buttons')}")

        # Playwright frame 级别探查
        for i, frame in enumerate(page.frames):
            if frame == page.main_frame:
                continue
            try:
                fi = await frame.evaluate("() => Array.from(document.querySelectorAll('input')).map(i => ({type:i.type,name:i.name,vis:i.offsetParent!==null,placeholder:i.placeholder}))")
                fb = await frame.evaluate("() => Array.from(document.querySelectorAll('button')).map(b => ({text:b.textContent.trim().substring(0,40),vis:b.offsetParent!==null,disabled:b.disabled}))")
                print(f"[select-account] Frame {i}: url={frame.url[:80]} inputs={fi} buttons={fb}")
            except Exception as e:
                print(f"[select-account] Frame {i}: error={e}")

        # 收集所有可操作上下文：主页面 + 所有 iframe
        contexts = [page]
        for frame in page.frames:
            if frame != page.main_frame:
                contexts.append(frame)

        # 在所有上下文中查找 name input 并填入
        name_filled = False
        fill_selectors = [
            "input[data-testid='kui-text-input-element'][name='name']",
            "input[name='name']",
            "input[placeholder*='Organization']",
            "input[placeholder*='rganization']",
            "input[placeholder*='name']",
            "input[type='text']",
        ]
        for ctx in contexts:
            if name_filled:
                break
            ctx_name = "main" if ctx == page else getattr(ctx, 'url', '?')[:60]
            for sel in fill_selectors:
                try:
                    loc = ctx.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.fill("11")
                        print(f"[select-account] 已输入云账户名称 '11' (上下文={ctx_name}, 选择器={sel})")
                        name_filled = True
                        await page.wait_for_timeout(1000)
                        break
                except Exception:
                    continue

        if not name_filled:
            # JS 兜底：在主文档 + 所有 iframe 中查找
            js_result = await page.evaluate("""() => {
                const allDocs = [document];
                try {
                    Array.from(document.querySelectorAll('iframe')).forEach(f => {
                        try { allDocs.push(f.contentDocument); } catch(e) {}
                    });
                } catch(e) {}
                for (const doc of allDocs) {
                    if (!doc) continue;
                    const inputs = Array.from(doc.querySelectorAll('input'));
                    const visible = inputs.filter(i => i.offsetParent !== null && (i.type === 'text' || i.type === '' || !i.type));
                    if (visible.length > 0) {
                        visible[0].value = '11';
                        visible[0].dispatchEvent(new Event('input', {bubbles: true}));
                        visible[0].dispatchEvent(new Event('change', {bubbles: true}));
                        return 'filled in ' + (doc === document ? 'main' : 'iframe');
                    }
                }
                return 'no visible text input found';
            }""")
            print(f"[select-account] JS兜底: {js_result}")
            await page.wait_for_timeout(1000)

        # 点击 Create 按钮
        clicked_sa = False
        create_selectors = [
            "button:has-text('Create NVIDIA Cloud Account')",
            "button:has-text('Create')",
            "button:has-text('创建')",
            "button[data-testid='kui-button']",
            "button[type='submit']",
        ]
        for ctx in contexts:
            if clicked_sa:
                break
            ctx_name = "main" if ctx == page else getattr(ctx, 'url', '?')[:60]
            for sel in create_selectors:
                try:
                    loc = ctx.locator(sel + ":visible").first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click(no_wait_after=True)
                        print(f"[select-account] 已点击: {sel} (上下文={ctx_name})")
                        clicked_sa = True
                        break
                except Exception:
                    continue

        if not clicked_sa:
            # 兜底：JS 在主文档+iframe中查找并点击
            js_click = await page.evaluate("""() => {
                const allDocs = [document];
                try {
                    Array.from(document.querySelectorAll('iframe')).forEach(f => {
                        try { allDocs.push(f.contentDocument); } catch(e) {}
                    });
                } catch(e) {}
                for (const doc of allDocs) {
                    if (!doc) continue;
                    const btns = Array.from(doc.querySelectorAll('button')).filter(b => b.offsetParent !== null);
                    for (const b of btns) {
                        const t = (b.textContent || '').trim();
                        if (/create|creat|创建/i.test(t)) {
                            b.click();
                            return 'clicked: ' + t.substring(0, 40) + ' in ' + (doc === document ? 'main' : 'iframe');
                        }
                    }
                }
                for (const doc of allDocs) {
                    if (!doc) continue;
                    const btn = doc.querySelector('button');
                    if (btn && btn.offsetParent !== null) {
                        btn.click();
                        return 'fallback clicked first button in ' + (doc === document ? 'main' : 'iframe');
                    }
                }
                return 'no button found';
            }""")
            print(f"[select-account] JS兜底点击: {js_click}")

        # 等待页面跳转
        await page.wait_for_timeout(5000)

        # 验证是否成功创建
        final_url = page.url
        if "select-account" in final_url or "cloudaccounts" in final_url:
            print(f"[select-account] [WARN] 仍在 cloudaccounts 页: {final_url[:100]}")
            # 最后一次尝试：直接用 page 级别 locator（Playwright 自动搜索 iframe）
            try:
                loc = page.locator("input[name='name']:visible").first
                if await loc.count() > 0:
                    await loc.fill("11", timeout=5000)
                    await page.wait_for_timeout(800)
                    await page.locator("button:has-text('Create'):visible").first.click(no_wait_after=True)
                    print("[select-account] Playwright 全局搜索最后重试成功")
                    await page.wait_for_timeout(5000)
            except Exception as e:
                print(f"[select-account] 最后重试失败: {e}")
        else:
            print(f"[select-account] 已离开 cloudaccounts, 当前: {final_url[:80]}")

        return True
    except Exception as e:
        print(f"[select-account] 异常: {e}")
        return True


# ============ 步骤 13: 取 API Key（NGC 两步流程）============

async def step13_fetch_apikey(page, email):
    """步骤13：处理 consent 页 → 密码登录 → 跑 NGC 两步流程拿 apiKey.value"""
    print("[步骤13] 取 API Key ...")

    # --- 处理 consent 页（邮件验证后跳转的开发者同意页）---
    if "consent" in page.url:
        print(f"[步骤13] 检测到 consent 页: {page.url}")
        await page.wait_for_timeout(2000)
        consent_probe = await page.evaluate("""() => ({
            text: document.body.innerText.substring(0, 500),
            checks: Array.from(document.querySelectorAll('input[type="checkbox"]'))
                .filter(c => c.offsetParent !== null)
                .map(c => ({id:c.id, name:c.name, checked:c.checked, cls:c.className.substring(0,40),
                            label:c.closest('label')?.textContent?.trim().substring(0,40) || ''})),
            buttons: Array.from(document.querySelectorAll('button, input[type="submit"]'))
                .filter(e => e.offsetParent !== null)
                .map(e => ({tag:e.tagName, text:(e.textContent||e.value||'').trim().substring(0,30),
                            id:e.id, type:e.type, cls:e.className.substring(0,50)}))
                .filter(b => b.text)
        })""")
        print(f"[步骤13] consent 文本: {consent_probe.get('text','')[:300]}")
        print(f"[步骤13] consent 复选框: {consent_probe.get('checks')}")
        print(f"[步骤13] consent 按钮: {consent_probe.get('buttons')}")

        # 1) 勾选同意 checkbox（未勾选的）
        try:
            checked_n = await page.evaluate("""() => {
                let n = 0;
                document.querySelectorAll('input[type="checkbox"]').forEach(c => {
                    if (c.offsetParent !== null && !c.checked) { c.click(); n++; }
                });
                return n;
            }""")
            print(f"[步骤13] 勾选了 {checked_n} 个复选框")
            await page.wait_for_timeout(800)
        except Exception as e:
            print(f"[步骤13] 勾选异常: {e}")

        # 2) 点提交/接受按钮
        clicked = False
        for sel in ["button.button-cta:visible", "button[type='submit']:visible",
                    "input[type='submit']:visible", "button:has-text('提交'):visible",
                    "button:has-text('Accept'):visible", "button:has-text('Agree'):visible",
                    "button:has-text('Continue'):visible", "button:has-text('接受'):visible",
                    "button:has-text('同意'):visible", "button:has-text('继续'):visible"]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(no_wait_after=True)
                    print(f"[步骤13] 已点击 consent: {sel}")
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            # 并发下 consent SPA 偶发未渲染（空页面），重载一次再试
            print("[步骤13] [WARN] 未找到 consent 提交按钮，重载页面重试 ...")
            for retry_i in range(2):
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"[步骤13] consent 重载异常 (第{retry_i+1}次): {e}")
                # 重新探测
                consent_probe2 = await page.evaluate("""() => ({
                    checks: document.querySelectorAll('input[type="checkbox"]:not([style*="none"])').length,
                    buttons: Array.from(document.querySelectorAll('button, input[type="submit"]'))
                        .filter(e => e.offsetParent !== null && (e.textContent||e.value||'').trim()).length
                })""")
                if consent_probe2.get("buttons", 0) > 0:
                    print(f"[步骤13] consent 重载后找到 {consent_probe2.get('checks')} 复选框 + {consent_probe2.get('buttons')} 按钮")
                    # 重新勾选 + 点击
                    try:
                        await page.evaluate("""() => { document.querySelectorAll('input[type="checkbox"]').forEach(c => { if (c.offsetParent !== null && !c.checked) c.click(); }); }""")
                        await page.wait_for_timeout(500)
                    except Exception:
                        pass
                    for sel in ["button.button-cta:visible", "button[type='submit']:visible",
                                "button:has-text('提交'):visible", "button:has-text('Accept'):visible",
                                "button:has-text('Continue'):visible", "button:has-text('接受'):visible"]:
                        try:
                            loc = page.locator(sel).first
                            if await loc.count() > 0:
                                await loc.click(no_wait_after=True)
                                print(f"[步骤13] 重载后点击 consent: {sel}")
                                clicked = True
                                break
                        except Exception:
                            continue
                    if clicked:
                        break
            if not clicked:
                print("[步骤13] [WARN] 重载后仍未找到 consent 提交按钮")

        # 3) 等回调跳转 build.nvidia.com；途中处理 密码登录页 / select-account(创建云账户) 页
        print("[步骤13] 等待回调跳转 build.nvidia.com（途中处理密码登录页 + select-account）...")
        pwd_done = False
        sa_done = False
        for _ in range(60):
            await page.wait_for_timeout(1500)
            url = page.url
            if "build.nvidia.com" in url and "modal=signin" not in url:
                print(f"[步骤13] 已跳到 build.nvidia.com: {url}")
                break
            # chrome-error：代理抖动中断重定向，等 5s 恢复后直接 goto build.nvidia.com
            if url.startswith("chrome-error://"):
                print(f"[步骤13] consent 重定向途中 chrome-error，等 5s 恢复 ...")
                await page.wait_for_timeout(5000)
                try:
                    await page.goto("https://build.nvidia.com/", wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"[步骤13] chrome-error 恢复 goto 异常: {e}")
                break
            # 密码登录页 → 填邮箱+Next → 填密码+提交
            if (not pwd_done) and ("/login/password" in url or "/login/identifier" in url or "/login/" in url):
                print(f"[步骤13] 检测到登录页, 处理: {url[:90]}")
                try:
                    await page.wait_for_timeout(1500)
                    # 检查当前是 identifier（只有邮箱+Next）还是 password 页（有密码框）
                    has_password = await page.evaluate("() => !!document.querySelector(\"input[type='password']\")")
                    if not has_password:
                        # identifier 页: 填邮箱 + 点 Next/Continue → 等密码框出现
                        print("[步骤13] identifier页, 填邮箱点Next...")
                        await page.evaluate(f"""() => {{
                            const ei = document.querySelector("input[name='email'], input[type='email']");
                            if (ei && !ei.value) {{ ei.value = '{email}'; ei.dispatchEvent(new Event('input', {{bubbles:true}})); ei.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                        }}""")
                        # 点 Next/Continue 按钮
                        for sel in ["button.btn-primary", "button[type='submit']"]:
                            try:
                                loc = page.locator(sel).first
                                if await loc.count() > 0 and await loc.is_visible():
                                    await loc.click(no_wait_after=True)
                                    print(f"[步骤13] 点击了 Next: {sel}")
                                    break
                            except Exception:
                                continue
                        # 等密码框出现
                        try:
                            await page.wait_for_selector("input[type='password']", state="visible", timeout=10000)
                            await page.wait_for_timeout(500)
                        except Exception:
                            pass

                    # 密码页: 填密码 + 点提交
                    has_password = await page.evaluate("() => !!document.querySelector(\"input[type='password']\")")
                    if has_password:
                        print("[步骤13] password页, 填密码点提交...")
                        pw = page.locator("input[type='password']").first
                        if await pw.count() > 0 and await pw.is_visible():
                            await pw.fill(PASSWORD)
                            await page.wait_for_timeout(500)
                        # 点 Sign In / Login / 提交
                        for sel in ["button.btn-primary:visible", "button[type='submit']:visible",
                                    "button:has-text('Sign In'):visible", "button:has-text('Login'):visible",
                                    "button:has-text('Continue'):visible", "button:has-text('继续'):visible"]:
                            try:
                                loc = page.locator(sel).first
                                if await loc.count() > 0 and await loc.is_visible():
                                    await loc.click(no_wait_after=True)
                                    print(f"[步骤13] 点击提交: {sel}")
                                    break
                            except Exception:
                                continue
                    pwd_done = True
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"[步骤13] 密码登录异常: {e}")
                    pwd_done = True
            # select-account / cloudaccounts 页
            if (not sa_done) and ("select-account" in url or "cloudaccounts" in url):
                print(f"[步骤13] 检测到 select-account 页: {url[:90]}")
                # 检查是否 403
                try:
                    page_text = await page.evaluate("() => document.body.innerText.substring(0, 50)")
                    if "403" in page_text or "Forbidden" in page_text:
                        print("[步骤13] cloudaccounts 403，跳过页面方式，直接完成回调链")
                        # 直接访问 nca_picker 回调，让 session 建立
                        try:
                            await page.goto("https://login.nvidia.com/callback/nca_picker", wait_until="domcontentloaded", timeout=15000)
                            await page.wait_for_timeout(3000)
                            print(f"[步骤13] nca_picker 回调后 URL: {page.url[:80]}")
                        except Exception as e:
                            print(f"[步骤13] nca_picker 回调异常: {e}")
                        sa_done = True
                        continue
                except Exception:
                    pass
                print(f"[步骤13] 处理云账户: {url[:90]}")
                sa_done = await _handle_select_account(page)

        else:
            print(f"[步骤13] [WARN] 未跳到 build.nvidia.com, 当前: {page.url}")
        await page.wait_for_timeout(2000)

    # 确保在 build.nvidia.com 建立 NGC 会话
    # 代理模式下 OTP 后可能跳到 signin-redirect（自动重定向中），等它完成
    # chrome-error 时需等代理恢复后重试
    if "build.nvidia.com" not in page.url:
        # 等 signin-redirect 自动重定向到 build.nvidia.com（最多 30s）
        for _ in range(30):
            url = page.url
            if "build.nvidia.com" in url:
                print(f"[步骤13] signin-redirect 已自动跳到: {url[:80]}")
                break
            await page.wait_for_timeout(1000)
    # chrome-error 或非 build.nvidia.com 时，重试 goto（代理偶发中断，等 10s 恢复）
    for fb_attempt in range(3):
        if "build.nvidia.com" in page.url and "modal=signin" not in page.url:
            break
        if fb_attempt > 0:
            print(f"[步骤13] 等待 10s 后重试 goto build.nvidia.com (第{fb_attempt+1}次) ...")
            await page.wait_for_timeout(10000)
        try:
            await page.goto("https://build.nvidia.com/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
        except Exception as e:
            print(f"[步骤13] goto build.nvidia.com 异常 (第{fb_attempt+1}次): {e}, 当前URL: {page.url}")
    print(f"[步骤13] 当前URL: {page.url}")

    result = await page.evaluate("""async () => {
        const r = {step1: null, step2: null, apiKey: null, error: null};
        try {
            const r1 = await fetch('https://api.ngc.nvidia.com/user-context', {
                method:'GET', credentials:'include',
                headers:{accept:'application/json, text/plain, */*'}
            });
            const d1 = await r1.json().catch(()=>r1.text());
            r.step1 = {status: r1.status, data: d1};
            const orgName = d1 && d1.orgName;
            if (!r1.ok || !orgName) { r.error = 'step1 失败或无 orgName'; return r; }
            const url2 = `https://api.ngc.nvidia.com/v3/orgs/${orgName}/keys/type/AI_PLAYGROUNDS_KEY`;
            const payload = {
                expiryDate: '2126-04-08T07:00:00Z',
                name: 'dev',
                type: 'AI_PLAYGROUNDS_KEY',
                policies: [{product:'nv-cloud-functions', scopes:['invoke_function'],
                             resources:[{id:'*', type:'account-functions'}]}],
            };
            const r2 = await fetch(url2, {
                method:'POST', credentials:'include',
                headers:{accept:'*/*', 'content-type':'application/json'},
                body: JSON.stringify(payload)
            });
            const d2 = await r2.json().catch(()=>r2.text());
            r.step2 = {status: r2.status, data: d2};
            r.apiKey = (d2 && d2.key && d2.key.value) || (d2 && d2.apiKey && d2.apiKey.value) || null;
        } catch(e) { r.error = String(e); }
        return r;
    }""")
    print(f"[步骤13] step1 status={result.get('step1',{}).get('status') if isinstance(result.get('step1'),dict) else result.get('step1')}")
    print(f"[步骤13] step2 status={result.get('step2',{}).get('status') if isinstance(result.get('step2'),dict) else result.get('step2')}")
    if result.get("error"):
        print(f"[步骤13] error: {result['error']}")
    apikey = result.get("apiKey")

    # 401 重试：如果 step1 返回 401（session 未建立），尝试重建 session 或创建 org
    step1_status = result.get('step1',{}).get('status') if isinstance(result.get('step1'),dict) else result.get('step1')
    if not apikey and step1_status == 401:
        print("[步骤13] 检测到 401，尝试重建 NGC session...")
        try:
            # 方案1：通过 build.nvidia.com 页面上的 JS 请求 NGC（同站请求，cookie 会带上）
            # 先确保在 build.nvidia.com
            if "build.nvidia.com" not in page.url:
                await page.goto("https://build.nvidia.com/", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(4000)
            
            # 尝试通过 build.nvidia.com 的 internal API 获取 user context
            print("[步骤13] [401重试] 尝试 build.nvidia.com internal API...")
            result = await page.evaluate("""async () => {
                const r = {step1: null, step2: null, apiKey: null, error: null};
                try {
                    // 先尝试 build.nvidia.com 自己的 API 代理
                    for (const baseUrl of ['https://build.nvidia.com/api', 'https://api.ngc.nvidia.com']) {
                        try {
                            const r1 = await fetch(baseUrl + '/user-context', {
                                method:'GET', credentials:'include',
                                headers:{accept:'application/json, text/plain, */*'}
                            });
                            let d1;
                            try { d1 = await r1.json(); } catch(e) { d1 = await r1.text(); }
                            r.step1 = {status: r1.status, data: typeof d1 === 'string' ? d1.substring(0,200) : d1};
                            if (r1.ok && d1 && d1.orgName) {
                                const url2 = `https://api.ngc.nvidia.com/v3/orgs/${d1.orgName}/keys/type/AI_PLAYGROUNDS_KEY`;
                                const payload = {
                                    expiryDate: '2126-04-08T07:00:00Z', name: 'dev', type: 'AI_PLAYGROUNDS_KEY',
                                    policies: [{product:'nv-cloud-functions', scopes:['invoke_function'],
                                                 resources:[{id:'*', type:'account-functions'}]}],
                                };
                                const r2 = await fetch(url2, {
                                    method:'POST', credentials:'include',
                                    headers:{accept:'*/*', 'content-type':'application/json'},
                                    body: JSON.stringify(payload)
                                });
                                let d2;
                                try { d2 = await r2.json(); } catch(e) { d2 = await r2.text(); }
                                r.step2 = {status: r2.status, data: typeof d2 === 'string' ? d2.substring(0,200) : d2};
                                r.apiKey = (d2 && d2.key && d2.key.value) || (d2 && d2.apiKey && d2.apiKey.value) || null;
                                if (r.apiKey) break;
                            }
                        } catch(e) { continue; }
                    }
                    if (!r.apiKey) { r.error = 'session 重建失败，仍无 org'; }
                } catch(e) { r.error = String(e); }
                return r;
            }""")
            print(f"[步骤13] [401重试] step1={result.get('step1',{}).get('status') if isinstance(result.get('step1'),dict) else result.get('step1')} error={result.get('error')}")
            apikey = result.get("apiKey")

            # 方案2：如果仍然 401，尝试通过 nca_picker 回调建立 session
            if not apikey:
                print("[步骤13] [401重试2] 尝试通过 nca_picker 回调建立 session...")
                try:
                    await page.goto("https://login.nvidia.com/callback/nca_picker", wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(3000)
                    print(f"[步骤13] [401重试2] nca_picker 后 URL: {page.url[:80]}")
                    # 再回 build.nvidia.com
                    if "build.nvidia.com" not in page.url:
                        await page.goto("https://build.nvidia.com/", wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(4000)
                    # 再试 NGC API
                    result2 = await page.evaluate("""async () => {
                        const r = {step1: null, step2: null, apiKey: null, error: null};
                        try {
                            const r1 = await fetch('https://api.ngc.nvidia.com/user-context', {
                                method:'GET', credentials:'include',
                                headers:{accept:'application/json, text/plain, */*'}
                            });
                            let d1;
                            try { d1 = await r1.json(); } catch(e) { d1 = await r1.text(); }
                            r.step1 = {status: r1.status};
                            if (r1.ok && d1 && d1.orgName) {
                                const url2 = `https://api.ngc.nvidia.com/v3/orgs/${d1.orgName}/keys/type/AI_PLAYGROUNDS_KEY`;
                                const payload = {
                                    expiryDate: '2126-04-08T07:00:00Z', name: 'dev', type: 'AI_PLAYGROUNDS_KEY',
                                    policies: [{product:'nv-cloud-functions', scopes:['invoke_function'],
                                                 resources:[{id:'*', type:'account-functions'}]}],
                                };
                                const r2 = await fetch(url2, {
                                    method:'POST', credentials:'include',
                                    headers:{accept:'*/*', 'content-type':'application/json'},
                                    body: JSON.stringify(payload)
                                });
                                let d2;
                                try { d2 = await r2.json(); } catch(e) { d2 = await r2.text(); }
                                r.step2 = {status: r2.status};
                                r.apiKey = (d2 && d2.key && d2.key.value) || (d2 && d2.apiKey && d2.apiKey.value) || null;
                            } else {
                                r.error = 'nca_picker 后仍 401 或无 org';
                            }
                        } catch(e) { r.error = String(e); }
                        return r;
                    }""")
                    print(f"[步骤13] [401重试2] step1={result2.get('step1',{}).get('status') if isinstance(result2.get('step1'),dict) else result2.get('step1')} error={result2.get('error')}")
                    apikey = result2.get("apiKey")
                    result = result2
                except Exception as e:
                    print(f"[步骤13] [401重试2] 异常: {e}")
        except Exception as e:
            print(f"[步骤13] [401重试] 异常: {e}")

    # 401重试3：consent 重定向途中 chrome-error/跳过 select-account → 无 org → 401
    # 显式导航到 cloudaccounts select-account 页面触发 org 创建，再回 build.nvidia.com 取 key
    if not apikey and step1_status == 401:
        print("[步骤13] [401重试3] 显式导航 select-account 创建云账户 ...")
        try:
            # 先走 consent 回调链到 select-account（绕过 chrome-error 中断的重定向）
            sa_url = "https://cloudaccounts.nvidia.com/sf/v2/select-account?redirect_uri=https%3A%2F%2Flogin.nvidia.com%2Fcallback%2Fnca_picker"
            await page.goto(sa_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            cur = page.url or ""
            print(f"[步骤13] [401重试3] select-account 后 URL: {cur[:90]}")
            if "select-account" in cur or "cloudaccounts" in cur:
                # 处理 select-account 页面（创建云账户）
                sa_ok = await _handle_select_account(page)
                print(f"[步骤13] [401重试3] _handle_select_account 返回: {sa_ok}")
                await page.wait_for_timeout(2000)
            # 回 build.nvidia.com 建立 NGC session
            for fb in range(2):
                try:
                    await page.goto("https://build.nvidia.com/", wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(4000)
                    break
                except Exception as e:
                    print(f"[步骤13] [401重试3] goto build.nvidia.com 异常 (第{fb+1}次): {e}")
                    await page.wait_for_timeout(5000)
            # 再试 NGC API
            result3 = await page.evaluate("""async () => {
                const r = {step1: null, step2: null, apiKey: null, error: null};
                try {
                    const r1 = await fetch('https://api.ngc.nvidia.com/user-context', {
                        method:'GET', credentials:'include',
                        headers:{accept:'application/json, text/plain, */*'}
                    });
                    let d1;
                    try { d1 = await r1.json(); } catch(e) { d1 = await r1.text(); }
                    r.step1 = {status: r1.status};
                    if (r1.ok && d1 && d1.orgName) {
                        const url2 = `https://api.ngc.nvidia.com/v3/orgs/${d1.orgName}/keys/type/AI_PLAYGROUNDS_KEY`;
                        const payload = {
                            expiryDate: '2126-04-08T07:00:00Z', name: 'dev', type: 'AI_PLAYGROUNDS_KEY',
                            policies: [{product:'nv-cloud-functions', scopes:['invoke_function'],
                                         resources:[{id:'*', type:'account-functions'}]}],
                        };
                        const r2 = await fetch(url2, {
                            method:'POST', credentials:'include',
                            headers:{accept:'*/*', 'content-type':'application/json'},
                            body: JSON.stringify(payload)
                        });
                        let d2;
                        try { d2 = await r2.json(); } catch(e) { d2 = await r2.text(); }
                        r.step2 = {status: r2.status};
                        r.apiKey = (d2 && d2.key && d2.key.value) || (d2 && d2.apiKey && d2.apiKey.value) || null;
                    } else {
                        r.error = 'select-account 后仍 401 或无 org';
                    }
                } catch(e) { r.error = String(e); }
                return r;
            }""")
            print(f"[步骤13] [401重试3] step1={result3.get('step1',{}).get('status') if isinstance(result3.get('step1'),dict) else result3.get('step1')} error={result3.get('error')}")
            apikey = result3.get("apiKey")
            result = result3
        except Exception as e:
            print(f"[步骤13] [401重试3] 异常: {e}")

    if apikey:
        print(f"\n{'='*60}")
        print("[步骤13] [OK] 拿到 API KEY:")
        print(apikey)
        print(f"{'='*60}")
    else:
        print(f"[步骤13] [WARN] 未拿到 apiKey.value, 完整响应: {str(result.get('step2'))[:500]}")
    return apikey


# ============ 主流程 ============

KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_keys.txt")
HEADLESS = os.getenv("HEADLESS", "0") == "1"  # 默认有头，便于观察；HEADLESS=1 批量跑

async def run_one_account(idx, total, headless=HEADLESS):
    """跑一个账号的完整流程，返回 dict {email, apikey, status}"""
    email = generate_random_email()
    print(f"\n{'='*60}")
    print(f"[{idx}/{total}] 邮箱: {email}")
    print(f"{'='*60}")
    apikey = None
    async with async_playwright() as p:
        # 代理配置（每个账号用独立代理 IP，避免 NVIDIA IP 风控）
        launch_args = {"headless": headless}
        proxy_info = None
        browser = None
        if USE_NOPECHA_PLUGIN:
            context = await p.chromium.launch_persistent_context(
                NOPECHA_PLUGIN_PROFILE_DIR,
                **get_nopecha_plugin_launch_args(proxy_info),
            )
            await configure_nonecap_plugin(context)
        else:
            browser = await p.chromium.launch(**launch_args)
            context = await browser.new_context()
            await _setup_hcaptcha_route(context)
        page = await context.new_page()
        try:
            steps = [
                ("打开signin页", lambda: step1_open_signin(page)),
                ("Cookie", lambda: step2_accept_cookies(page)),
                ("邮箱→Next→NVGS→注册表单", lambda: step3_email_next_and_continue(page, email)),
                ("密码", lambda: step6_input_password(page)),
                ("确认密码", lambda: step7_input_confirm_password(page)),
                ("同意条款", lambda: step8_check_agreement(page)),
            ]
            for i, (name, step) in enumerate(steps, 1):
                try:
                    success = await step()
                except Exception as e:
                    print(f"[{idx}] 步骤{i}({name}) 异常: {e}")
                    success = False
                if not success:
                    # step3 失败时重试一次（重新打开signin+Cookie+邮箱→Next）
                    if i == 3:
                        print(f"[{idx}] 步骤3失败, 重试: 重新打开 signin 页...")
                        for _retry in range(2):
                            try:
                                await step1_open_signin(page)
                                await step2_accept_cookies(page)
                                success = await step3_email_next_and_continue(page, email)
                                if success:
                                    print(f"[{idx}] 步骤3重试第{_retry+1}次成功")
                                    break
                            except Exception as e2:
                                print(f"[{idx}] 步骤3重试异常: {e2}")
                    if not success:
                        print(f"[{idx}] 步骤{i}({name}) 未完成，跳过此账号")
                        return {"email": email, "apikey": None, "status": f"fail_step{i}"}

            # step9 captcha
            try:
                if USE_NOPECHA_PLUGIN:
                    plugin_result = await step9_nopecha_plugin_wait(page)
                    if not plugin_result.get("ok"):
                        print(f"[{idx}] 步骤9 NoneCap 插件未完成: {plugin_result.get('error')}")
                        return {"email": email, "apikey": None, "status": "fail_captcha"}
                    token = None
                else:
                    token = await step9_captcharun_solve(page)
                    if not token:
                        print(f"[{idx}] 步骤9 未拿到 token")
                        return {"email": email, "apikey": None, "status": "fail_captcha"}
            except Exception as e:
                print(f"[{idx}] 步骤9异常: {e}")
                return {"email": email, "apikey": None, "status": "fail_captcha"}

            try:
                if not USE_NOPECHA_PLUGIN:
                    await step10_inject_token(page, token)
            except Exception as e:
                print(f"[{idx}] 步骤10异常: {e}")

            try:
                await step11_click_create_account(page)
            except Exception as e:
                print(f"[{idx}] 步骤11异常: {e}")

            try:
                await step12_verify_email(page, email)
            except Exception as e:
                print(f"[{idx}] 步骤12异常: {e}")

            try:
                apikey = await step13_fetch_apikey(page, email)
            except Exception as e:
                print(f"[{idx}] 步骤13异常: {e}")

            print(f"[{idx}] 完成, URL: {page.url}")
            return {"email": email, "apikey": apikey, "status": "ok" if apikey else "no_key"}
        finally:
            await context.close()
            if browser:
                await browser.close()


def save_key(email, apikey):
    if apikey:
        # 格式: email|apikey（| 分隔，兼容已有数据）
        with open(KEYS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{email}|{apikey}\n")
        print(f"[SAVE] {email} -> api_keys.txt")


async def main():
    import sys
    args = sys.argv[1:]
    total = int(args[0]) if args and args[0].isdigit() else 200
    start = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
    concurrency = int(args[2]) if len(args) > 2 and args[2].isdigit() else 1
    stagger = int(args[3]) if len(args) > 3 and args[3].isdigit() else 0  # 启动间隔秒数(错开避免风控)
    end = start + total - 1
    print(f"批量注册: 跑 {total} 个 (第 {start}-{end} 号), 并发={concurrency}, 错开={stagger}s, HEADLESS={HEADLESS}")
    print(f"Key 存到: {KEYS_FILE}")

    # 并发模式：用 Semaphore 限制并发数，用 Lock 保护文件写入
    sem = asyncio.Semaphore(concurrency)
    file_lock = asyncio.Lock()
    progress_lock = asyncio.Lock()
    counter = {"ok": 0, "done": 0}

    async def run_with_sem(idx):
        # 错开启动：第 N 个账号延迟 N*stagger 秒启动，避免同时注册触发 NVIDIA 风控
        if stagger > 0 and idx > start:
            delay = (idx - start) * stagger
            print(f"[{idx}] 错开启动, 等待 {delay}s ...")
            await asyncio.sleep(delay)
        async with sem:
            try:
                r = await run_one_account(idx, end)
                async with file_lock:
                    save_key(r["email"], r["apikey"])
            except Exception as e:
                print(f"[{idx}] 账号级异常: {e}")
                r = {"email": "", "apikey": None, "status": f"exception: {e}"}
            async with progress_lock:
                counter["done"] += 1
                if r.get("apikey"):
                    counter["ok"] += 1
                    print(f"[{idx}] [OK] key={r['apikey'][:24]}...  累计成功 {counter['ok']} 个 (完成 {counter['done']}/{total})")
                else:
                    print(f"[{idx}] [SKIP] status={r.get('status')} (完成 {counter['done']}/{total})")
            return r

    tasks = [asyncio.create_task(run_with_sem(idx)) for idx in range(start, end + 1)]
    await asyncio.gather(*tasks)

    print(f"\n{'='*60}")
    print(f"全部完成: 成功 {counter['ok']}/{total}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
