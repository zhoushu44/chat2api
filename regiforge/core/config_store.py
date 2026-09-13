from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

from dotenv import load_dotenv

from .paths import CONFIG_EXAMPLE, CONFIG_FILE, ROOT, ensure_data_dirs


load_dotenv(ROOT / ".env")

DEFAULT_CONFIG: dict[str, Any] = {
    "captcha": {
        # 嵌套结构与前端 getByPath 一致：captcha.turnstile.yescaptcha.*
        "hcaptcha": {
            "captcharun": {
                "api_key": os.getenv("CAPTCHARUN_KEY") or "",
                "api_url": "https://api.captcha-run.com/v2/tasks",
                "poll_interval": 3,
                "max_poll": 60,
            },
        },
        "cloudflare": {
            "captcharun": {
                "api_key": os.getenv("CAPTCHARUN_KEY") or "",
                "api_url": "https://api.captcha-run.com/v2/tasks",
                "poll_interval": 3,
                "max_poll": 60,
            },
        },
        "slider": {
            "aliyun": {
                "api_url": "",
                "secret_key": "",
                "type_id": "20040",
                "max_retries": 3,
            },
            "sensenova": {},
        },
        "turnstile": {
            "yescaptcha": {
                "api_key": (os.getenv("YESCAPTCHA_API_KEY") or os.getenv("YESCAPTCHA_KEY") or ""),
                "api_url": os.getenv("YESCAPTCHA_API_URL") or "https://api.yescaptcha.com",
            },
            "captcharun": {
                "api_key": os.getenv("CAPTCHARUN_KEY") or "",
                "api_url": "https://api.captcha-run.com/v2/tasks",
                "poll_interval": 3,
                "max_poll": 60,
            },
            "capsolver": {
                "api_key": os.getenv("CAPSOLVER_KEY") or "",
                "api_url": "https://api.capsolver.com",
            },
        },
    },
    "email": {
        # 环境变量优先
        "tempmail": {
            "api_key": os.getenv("TEMPMAIL_API_KEY") or "",
        },
        "cloudflare_worker": {
            "cloudmail_api_base": os.getenv("CLOUDMAIL_API_BASE") or "",
            "cloudmail_api_key": os.getenv("CLOUDMAIL_API_KEY") or "",
            "cloudmail_domains": os.getenv("CLOUDMAIL_DOMAIN") or "",
            "cloudmail_path_messages": os.getenv("CLOUDMAIL_PATH_MESSAGES") or "/api/public/emailList",
        },
        "xunmail": {
            "api_address": "https://www.xunmail.cn/api-doc",
            "accounts": "",
        },
        "mailnest": {
            "api_key": os.getenv("MAILNEST_API_KEY") or "",
            "base_url": os.getenv("MAILNEST_BASE_URL") or "https://mailnest.top",
            "project_code": os.getenv("MAILNEST_PROJECT_CODE") or "chatgpt001",
            "project_codes": {
                "chatgpt_register": "chatgpt001",
                "nvidia_build": "nvidia001",
                "grok_register": "x-ai001",
            },
            "poll_interval": 3,
            "auto_release": True,
        },
    },
    "proxy": {
        "none": {},
        "socks5": {
            "server": "",
            "api_url": "",
            "api_key": "",
            "timeout": 10,
            "protocol": "socks5",
            "json_path": "",
        },
        "http_proxy": {
            "server": "",
        },
        "clash": {
            "clash_api_url": "",
            "clash_api_secret": "",
            "clash_group_name": "",
            "clash_local_port": 7897,
        },
    },
    "sms": {
        "jichisms": {
            "token": os.getenv("JC_TOKEN") or "",
            "sid": os.getenv("JC_SID") or "",
            "ascription": os.getenv("SMS_ASCRIPTION") or "1",
            "paragraph": os.getenv("SMS_PARAGRAPH") or "",
        },
    },
    "verify": {
        "nvidia_api": {
            "api_url": "https://integrate.api.nvidia.com/v1/models",
        },
    },
    "export": {
        "file": {"output_dir": "data/exports", "filename": "accounts.txt"},
        "sub2api": {
            "base_url": "",
            "admin_access_token": "",
        },
        "grok2api": {
            "base_url": "", "admin_password": "",
        },
        "chatgpt2api": {
            "base_url": "", "admin_password": "",
        },
    },
    "browser": {
        "backend": "playwright",
    },
    "debug": {
        "trace": True,
        "screenshot_on_fail": True,
        "save_html_on_fail": True,
        "keep_open_on_fail_seconds": 0,
    },
    "projects": {
        "nvidia_build": {
            "password": "",
            "browser_backend": "",
            "browser_channel": "chrome",
        },
        "grok_register": {
            "mail_timeout": 180,
            "turnstile_timeout": 180,
            "user_agent": "",
        },
        "chatgpt_register": {
            "register_mode": "browser",
            "http_fetch_refresh_token": True,
            "mail_timeout": 180,
            "profile_timeout": 90,
            "session_timeout": 120,
            "user_agent": "",
            "browser_channel": "chrome",
            "browser_backend": "",
        },
        "sensenova_register": {
            "sms_timeout": 120,
            "retry_count": 3,
            "region_code": "86",
            "user_agent": "",
        },
        "tokenrhythm_register": {
            "sms_timeout": 120,
            "captcha_timeout": 30,
            "browser_channel": "chrome",
            "browser_backend": "playwright",
            "user_agent": "",
        },
    },
    "ui": {
        "last_project_id": "nvidia_build",
        "last_captcha_id": "hcaptcha.captcharun",
        "last_email_id": "cloudflare_worker",
        "last_sms_id": "",
        "last_proxy_id": "socks5",
        "last_total": 1,
        "last_start": 1,
        "last_concurrency": 1,
        "last_stagger": 0,
        "last_headless": False,
        "keys_output_dir": "",
    },
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    ensure_data_dirs()
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _deep_merge(DEFAULT_CONFIG, data)
        except Exception:
            pass
    if CONFIG_EXAMPLE.exists():
        try:
            data = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg = _deep_merge(DEFAULT_CONFIG, data)
                save_config(cfg)
                return cfg
        except Exception:
            pass
    save_config(DEFAULT_CONFIG)
    return deepcopy(DEFAULT_CONFIG)


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    ensure_data_dirs()
    merged = _deep_merge(DEFAULT_CONFIG, config or {})
    CONFIG_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return merged


def provider_config(config: dict[str, Any], kind: str, provider_id: str) -> dict[str, Any]:
    """从 config 中取 kind.provider_id 对应的配置字典。

    provider_id 可能含点号（如 "turnstile.yescaptcha"），
    先尝试扁平 key（section["turnstile.yescaptcha"]），
    再尝试嵌套路径（section["turnstile"]["yescaptcha"]）。
    """
    section = config.get(kind) or {}
    # 1) 扁平 key（旧格式兼容）
    value = section.get(provider_id)
    if isinstance(value, dict) and value:
        return value
    # 2) 嵌套路径（与前端 getByPath 一致）
    parts = provider_id.split(".")
    cur: Any = section
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = None
        if cur is None:
            break
    if isinstance(cur, dict):
        return cur
    return {}
