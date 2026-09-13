# -*- coding: utf-8 -*-
"""A+ 指纹随机化 + IP 地理联动。

每次注册生成一套**内部一致**的浏览器指纹（curl_cffi 与 Sentinel 浏览器共用）：
- 多浏览器家族随机（chrome / firefox / safari）
- UA / TLS impersonate / sec-ch-ua / Accept-Language / locale / timezone / viewport / 硬件画像 全部绑定同一套
- IP 地理联动：按代理出口国家选时区与语言，语言与时区不匹配 IP 是国家级风控信号

参考：Regert888/gpt-outlook-register 的 fingerprint.py（开源实测批量存活率 ~2%，
同指纹批量注册是 OpenAI 反欺诈最大关联信号）。
"""
from __future__ import annotations

import random
import re
from typing import Any

# ─────────────────────────────────────────────────────────────
# 浏览器家族表（版本均为 curl_cffi 0.15.0 确认可构造）
# ─────────────────────────────────────────────────────────────
_CHROME = (
    {"impersonate": "chrome131", "ver": "131", "full_ver": "131.0.6778.86", "grease": "Not/A)Brand", "gv": "24"},
    {"impersonate": "chrome136", "ver": "136", "full_ver": "136.0.7103.92", "grease": "Not.A/Brand", "gv": "99"},
    {"impersonate": "chrome142", "ver": "142", "full_ver": "142.0.7103.40", "grease": "Not_A Brand", "gv": "8"},
    {"impersonate": "chrome145", "ver": "145", "full_ver": "145.0.7080.42", "grease": "Not/A)Brand", "gv": "24"},
)
_FIREFOX = (
    {"impersonate": "firefox133", "ver": "133.0"},
    {"impersonate": "firefox135", "ver": "135.0"},
)
_SAFARI = (
    {"impersonate": "safari15_3", "ver": "15.3", "macos": "12_0"},
    {"impersonate": "safari17_0", "ver": "17.0", "macos": "13_6"},
    {"impersonate": "safari18_0", "ver": "18.0", "macos": "14_5"},
)

# 家族权重：chrome 为主（服务端见的最多），firefox/safari 提供区分度
_FAMILIES = (
    ("chrome", 55, _CHROME),
    ("firefox", 25, _FIREFOX),
    ("safari", 20, _SAFARI),
)

_WIN_SCREENS = ((1920, 1080), (1366, 768), (1536, 864), (1440, 900), (2560, 1440))
_MAC_SCREENS = ((1440, 900), (1512, 982), (1728, 1117), (2560, 1440))

# 硬件画像（按家族绑定；一次注册内固定，真实浏览器同会话不变）
_HARDWARE = {
    "chrome": {
        "navigator_platform": "Win32",
        "navigator_vendor": "Google Inc.",
        "hardware_concurrency": (4, 6, 8, 12, 16),
        "device_memory": (4, 8),
        "max_touch_points": 0,
        "device_pixel_ratio": (1.0, 1.25, 1.5),
    },
    "firefox": {
        "navigator_platform": "Win32",
        "navigator_vendor": "",
        "hardware_concurrency": (4, 6, 8, 12, 16),
        "device_memory": None,
        "max_touch_points": 0,
        "device_pixel_ratio": (1.0, 1.5),
    },
    "safari": {
        "navigator_platform": "MacIntel",
        "navigator_vendor": "Apple Computer, Inc.",
        "hardware_concurrency": (8, 10, 12, 16),
        "device_memory": None,
        "max_touch_points": 0,
        "device_pixel_ratio": (2.0,),
    },
}

# ─────────────────────────────────────────────────────────────
# IP 地理联动画像（国家 → 时区 / 语言）
# ─────────────────────────────────────────────────────────────
_COUNTRY_PROFILES = {
    "US": (("America/New_York", 0.4), ("America/Los_Angeles", 0.3), ("America/Chicago", 0.2), ("America/Denver", 0.1)),
    "CA": (("America/Toronto", 0.6), ("America/Vancouver", 0.3), ("America/Edmonton", 0.1)),
    "GB": (("Europe/London", 1.0),),
    "DE": (("Europe/Berlin", 1.0),),
    "FR": (("Europe/Paris", 1.0),),
    "ES": (("Europe/Madrid", 1.0),),
    "IT": (("Europe/Rome", 1.0),),
    "NL": (("Europe/Amsterdam", 1.0),),
    "SE": (("Europe/Stockholm", 1.0),),
    "PL": (("Europe/Warsaw", 1.0),),
    "PT": (("Europe/Lisbon", 1.0),),
    "CH": (("Europe/Zurich", 1.0),),
    "UA": (("Europe/Kiev", 1.0),),
    "RU": (("Europe/Moscow", 0.7), ("Asia/Yekaterinburg", 0.15), ("Asia/Novosibirsk", 0.15)),
    "TR": (("Europe/Istanbul", 1.0),),
    "SA": (("Asia/Riyadh", 1.0),),
    "AE": (("Asia/Dubai", 1.0),),
    "IL": (("Asia/Jerusalem", 1.0),),
    "JP": (("Asia/Tokyo", 1.0),),
    "KR": (("Asia/Seoul", 1.0),),
    "SG": (("Asia/Singapore", 1.0),),
    "HK": (("Asia/Hong_Kong", 1.0),),
    "TW": (("Asia/Taipei", 1.0),),
    "TH": (("Asia/Bangkok", 1.0),),
    "VN": (("Asia/Ho_Chi_Minh", 1.0),),
    "MY": (("Asia/Kuala_Lumpur", 1.0),),
    "ID": (("Asia/Jakarta", 1.0),),
    "PH": (("Asia/Manila", 1.0),),
    "IN": (("Asia/Kolkata", 1.0),),
    "BR": (("America/Sao_Paulo", 0.7), ("America/Manaus", 0.2), ("America/Fortaleza", 0.1)),
    "MX": (("America/Mexico_City", 1.0),),
    "AU": (("Australia/Sydney", 0.5), ("Australia/Melbourne", 0.3), ("Australia/Brisbane", 0.2)),
    "NZ": (("Pacific/Auckland", 1.0),),
    # 常用非洲/中东/南美/中亚补充（避免未知国家回退成美国时区造成地理矛盾）
    "DZ": (("Africa/Algiers", 1.0),),
    "MA": (("Africa/Casablanca", 1.0),),
    "EG": (("Africa/Cairo", 1.0),),
    "ZA": (("Africa/Johannesburg", 1.0),),
    "NG": (("Africa/Lagos", 1.0),),
    "KE": (("Africa/Nairobi", 1.0),),
    "QA": (("Asia/Qatar", 1.0),),
    "KW": (("Asia/Kuwait", 1.0),),
    "PK": (("Asia/Karachi", 1.0),),
    "BD": (("Asia/Dhaka", 1.0),),
    "KZ": (("Asia/Almaty", 1.0),),
    "UZ": (("Asia/Tashkent", 1.0),),
    "CO": (("America/Bogota", 1.0),),
    "CL": (("America/Santiago", 1.0),),
    "PE": (("America/Lima", 1.0),),
    "AR": (("America/Argentina/Buenos_Aires", 1.0),),
}
_LANGUAGES_BY_COUNTRY = {
    "US": ["en-US", "en", "es-US"],
    "CA": ["en-CA", "en-US", "en", "fr-CA"],
    "GB": ["en-GB", "en-US", "en"],
    "DE": ["de-DE", "de", "en-US", "en"],
    "FR": ["fr-FR", "fr", "en-US", "en"],
    "ES": ["es-ES", "es", "en-US", "en"],
    "IT": ["it-IT", "it", "en-US", "en"],
    "NL": ["nl-NL", "nl", "en-US", "en"],
    "SE": ["sv-SE", "sv", "en-US", "en"],
    "PL": ["pl-PL", "pl", "en-US", "en"],
    "PT": ["pt-PT", "pt", "en-US", "en"],
    "CH": ["de-CH", "fr-CH", "de", "fr", "en-US", "en"],
    "UA": ["uk-UA", "uk", "ru", "en-US", "en"],
    "RU": ["ru-RU", "ru", "en-US", "en"],
    "TR": ["tr-TR", "tr", "en-US", "en"],
    "SA": ["ar-SA", "ar", "en-US", "en"],
    "AE": ["ar-AE", "ar", "en-US", "en"],
    "IL": ["he-IL", "he", "en-US", "en"],
    "JP": ["ja-JP", "ja", "en-US", "en"],
    "KR": ["ko-KR", "ko", "en-US", "en"],
    "SG": ["zh-SG", "zh-CN", "zh", "en-US", "en"],
    "HK": ["zh-HK", "zh-CN", "zh", "en-US", "en"],
    "TW": ["zh-TW", "zh", "en-US", "en"],
    "TH": ["th-TH", "th", "en-US", "en"],
    "VN": ["vi-VN", "vi", "en-US", "en"],
    "MY": ["ms-MY", "ms", "zh-CN", "zh", "en-US", "en"],
    "ID": ["id-ID", "id", "en-US", "en"],
    "PH": ["en-PH", "en-US", "en", "tl-PH"],
    "IN": ["en-IN", "en-US", "en", "hi-IN"],
    "BR": ["pt-BR", "pt", "en-US", "en"],
    "MX": ["es-MX", "es", "en-US", "en"],
    "AU": ["en-AU", "en-US", "en"],
    "NZ": ["en-NZ", "en-US", "en"],
    "DZ": ["ar-DZ", "fr-DZ", "ar", "fr", "en-US", "en"],
    "MA": ["ar-MA", "fr-MA", "ar", "fr", "en-US", "en"],
    "EG": ["ar-EG", "ar", "en-US", "en"],
    "ZA": ["en-ZA", "en-US", "en"],
    "NG": ["en-NG", "en-US", "en"],
    "KE": ["en-KE", "sw-KE", "en-US", "en"],
    "QA": ["ar-QA", "ar", "en-US", "en"],
    "KW": ["ar-KW", "ar", "en-US", "en"],
    "PK": ["ur-PK", "en-PK", "en-US", "en"],
    "BD": ["bn-BD", "en-US", "en"],
    "KZ": ["kk-KZ", "ru", "en-US", "en"],
    "UZ": ["uz-UZ", "ru", "en-US", "en"],
    "CO": ["es-CO", "es", "en-US", "en"],
    "CL": ["es-CL", "es", "en-US", "en"],
    "PE": ["es-PE", "es", "en-US", "en"],
    "AR": ["es-AR", "es", "en-US", "en"],
}
_DEFAULT_COUNTRY = "US"


def _pick_timezone(country: str, ip_tz: str = "") -> str:
    tzs = _COUNTRY_PROFILES.get(country)
    if not tzs:
        # 未知国家：优先用 ip-api 返回的真实时区，避免"IP 在某国、时区却是美国"的矛盾信号
        if ip_tz:
            return ip_tz
        return "America/New_York"
    r = random.random()
    acc = 0.0
    for tz, w in tzs:
        acc += w
        if r <= acc:
            return tz
    return tzs[0][0]


def _pick_languages(country: str) -> list[str]:
    langs = _LANGUAGES_BY_COUNTRY.get(country)
    if not langs:
        langs = ["en-US", "en"]
    # 首语言固定，后续打乱 q 顺序避免模板化
    head = [langs[0]]
    tail = langs[1:]
    random.shuffle(tail)
    return head + tail


def _accept_language(langs: list[str]) -> str:
    parts = [langs[0]]
    for lang in langs[1:3]:
        parts.append(f"{lang};q=0.9")
    return ",".join(parts)


def _chrome_ua(ver: str) -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{ver}.0.0.0 Safari/537.36"
    )


def _firefox_ua(ver: str) -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:" + ver + ") "
        f"Gecko/20100101 Firefox/{ver}"
    )


def _safari_ua(ver: str, macos: str) -> str:
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X " + macos + ") "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        f"Version/{ver} Safari/605.1.15"
    )


def _fallbacks(impersonate: str, family: tuple) -> list[str]:
    names = [item["impersonate"] for item in family]
    others = [n for n in names if n != impersonate]
    random.shuffle(others)
    return [impersonate] + others[:2]


def generate_fingerprint(country_code: str | None = None, ip_tz: str = "") -> dict[str, Any]:
    """生成一套内部一致的随机浏览器指纹。

    country_code 为代理出口国家（None 时按美国画像）；ip_tz 为 ip-api 返回的真实时区，
    未知国家时用其兜底（而非回退美国时区）。
    """
    country = (country_code or _DEFAULT_COUNTRY).upper()
    tz = _pick_timezone(country, ip_tz)
    langs = _pick_languages(country)
    al = _accept_language(langs)
    locale = langs[0]

    # 选家族
    weights = [w for _, w, _ in _FAMILIES]
    family_name = random.choices([f for f, _, _ in _FAMILIES], weights=weights, k=1)[0]
    family = next(t for n, _, t in _FAMILIES if n == family_name)

    if family_name == "chrome":
        item = random.choice(_CHROME)
        ua = _chrome_ua(item["ver"])
        sec_ch_ua = (
            f'"Chromium";v="{item["ver"]}", "Google Chrome";v="{item["ver"]}", '
            f'"{item["grease"]}";v="{item["gv"]}"'
        )
        sec_ch_ua_platform = '"Windows"'
        sec_ch_ua_mobile = "?0"
        # Client Hints 全套字段（真实 Chrome 收到 Accept-CH 后回发；版本与主 sec-ch-ua 严格一致）
        ch_full = {
            "sec_ch_ua_full_version_list": (
                f'"Chromium";v="{item["full_ver"]}", "Google Chrome";v="{item["full_ver"]}", '
                f'"{item["grease"]}";v="{item["gv"]}.0.0.0"'
            ),
            "sec_ch_ua_arch": '"x86"',
            "sec_ch_ua_bitness": '"64"',
            "sec_ch_ua_model": '""',
            "sec_ch_ua_platform_version": '"15.0.0"',
            "sec_ch_ua_wow64": "?0",
        }
        screens = _WIN_SCREENS
        hw_key = "chrome"
    elif family_name == "firefox":
        item = random.choice(_FIREFOX)
        ua = _firefox_ua(item["ver"])
        sec_ch_ua = ""
        sec_ch_ua_platform = '"Windows"'
        sec_ch_ua_mobile = ""
        ch_full = {}
        screens = _WIN_SCREENS
        hw_key = "firefox"
    else:  # safari
        item = random.choice(_SAFARI)
        ua = _safari_ua(item["ver"], item["macos"])
        sec_ch_ua = ""
        sec_ch_ua_platform = '"macOS"'
        sec_ch_ua_mobile = ""
        ch_full = {}
        screens = _MAC_SCREENS
        hw_key = "safari"

    w, h = random.choice(screens)
    hw = _HARDWARE[hw_key]

    return {
        "browser_type": family_name,
        "impersonate": item["impersonate"],
        "fallback_impersonates": _fallbacks(item["impersonate"], family),
        "user_agent": ua,
        "sec_ch_ua": sec_ch_ua,
        "sec_ch_ua_mobile": sec_ch_ua_mobile,
        "sec_ch_ua_platform": sec_ch_ua_platform,
        **ch_full,
        "accept_language": al,
        "locale": locale,
        "timezone_id": tz,
        "viewport": {"width": w, "height": max(h - 40, 600)},
        "screen": [w, h],
        "navigator_platform": hw["navigator_platform"],
        "navigator_vendor": hw["navigator_vendor"],
        "hardware_concurrency": random.choice(hw["hardware_concurrency"]),
        "device_memory": random.choice(hw["device_memory"]) if hw["device_memory"] else None,
        "max_touch_points": hw["max_touch_points"],
        "device_pixel_ratio": random.choice(hw["device_pixel_ratio"]),
    }


def fingerprint_from_user_ua(
    user_agent: str, country_code: str | None = None, ip_tz: str = ""
) -> dict[str, Any]:
    """用户显式配置 UA 时：不随机 UA，其余（语言/时区/屏幕/硬件）仍按地理联动随机。

    从 _sentinel 借用版本映射避免循环导入，故在本地实现解析。
    """
    from ._sentinel import impersonate_for_ua

    country = (country_code or _DEFAULT_COUNTRY).upper()
    tz = _pick_timezone(country, ip_tz)
    langs = _pick_languages(country)
    hw = _HARDWARE["chrome"]
    w, h = random.choice(_WIN_SCREENS)
    # 解析 UA 大版本，优先用已知版本表的真实 full_ver / GREASE；未知按 131 兜底
    m = re.search(r"Chrome/(\d+)\.", user_agent)
    ver = m.group(1) if m else "131"
    item = next((c for c in _CHROME if c["ver"] == ver), None)
    if item:
        full_ver, grease, gv = item["full_ver"], item["grease"], item["gv"]
    else:
        full_ver, grease, gv = f"{ver}.0.0.0", "Not/A)Brand", "24"
    sec_ch_ua = f'"Chromium";v="{ver}", "Google Chrome";v="{ver}", "{grease}";v="{gv}"'
    sec_ch_ua_full_list = (
        f'"Chromium";v="{full_ver}", "Google Chrome";v="{full_ver}", '
        f'"{grease}";v="{gv}.0.0.0"'
    )
    return {
        "browser_type": "chrome_custom",
        "impersonate": impersonate_for_ua(user_agent),
        "fallback_impersonates": [impersonate_for_ua(user_agent)],
        "user_agent": user_agent,
        "sec_ch_ua": sec_ch_ua,
        "sec_ch_ua_full_version_list": sec_ch_ua_full_list,
        "sec_ch_ua_arch": '"x86"',
        "sec_ch_ua_bitness": '"64"',
        "sec_ch_ua_model": '""',
        "sec_ch_ua_platform_version": '"15.0.0"',
        "sec_ch_ua_wow64": "?0",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
        "accept_language": _accept_language(langs),
        "locale": langs[0],
        "timezone_id": tz,
        "viewport": {"width": w, "height": max(h - 40, 600)},
        "screen": [w, h],
        "navigator_platform": hw["navigator_platform"],
        "navigator_vendor": hw["navigator_vendor"],
        "hardware_concurrency": random.choice(hw["hardware_concurrency"]),
        "device_memory": random.choice((4, 8)),
        "max_touch_points": 0,
        "device_pixel_ratio": random.choice((1.0, 1.25, 1.5)),
    }


def detect_country(proxy_url: str | None, timeout: float = 8) -> tuple[str, str]:
    """经代理出口探测 (国家, 时区)（ip-api.com 免费版）。失败回退 ("US", "")。

    探到的国家/时区用于地理联动；探测请求走与注册相同的出口 IP。
    """
    try:
        from curl_cffi import requests as creq

        resp = creq.get(
            "http://ip-api.com/json/?fields=status,countryCode,timezone",
            impersonate="chrome131",
            timeout=timeout,
            proxy=proxy_url,
        )
        data = resp.json()
        if data.get("status") == "success" and re.match(r"^[A-Z]{2}$", str(data.get("countryCode", ""))):
            tz = str(data.get("timezone") or "").strip()
            return str(data["countryCode"]), tz
    except Exception:
        pass
    return _DEFAULT_COUNTRY, ""
