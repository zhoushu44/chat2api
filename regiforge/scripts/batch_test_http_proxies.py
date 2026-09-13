"""批量测试 HTTP 代理文件，筛选出可用于 ChatGPT 注册的代理。

升级：增加 CSRF 和风控测试，过滤掉会被 403 拦截的代理

用法：
    python scripts\batch_test_http_proxies.py proxies.txt --output usable_proxies.txt --workers 50 --sample 40000

输出：
    - usable_proxies.txt: 可用的代理列表
    - test_report.json: 详细测试报告
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlsplit

from curl_cffi import requests


class TestResult(TypedDict):
    proxy: str
    host: str
    auth_ok: bool
    sentinel_ok: bool
    chat_ok: bool
    csrf_ok: bool  # 新增：CSRF 端点测试
    auth_code: int | str
    sentinel_code: int | str
    chat_code: int | str
    csrf_code: int | str  # 新增：CSRF 状态码
    latency_ms: int
    fully_usable: bool
    risk_score: int  # 新增：风控评分（0=最佳，3=最差）


TEST_URLS = {
    "auth": "https://auth.openai.com/authorize",
    "sentinel": "https://sentinel.openai.com/backend-api/sentinel/sdk.js",
    "chat": "https://chatgpt.com/",
}
# 新增：CSRF 测试端点（注册流程关键节点）
CSRF_URL = "https://chatgpt.com/api/auth/csrf"


def test_proxy(proxy: str, timeout: int = 12) -> TestResult:
    """测试单个代理对 4 个端点的连通性 + 风控检测。
    
    测试顺序：
    1. auth.openai.com/authorize - 基础连通性
    2. sentinel.openai.com - Sentinel SDK
    3. chatgpt.com - 主页
    4. chatgpt.com/api/auth/csrf - CSRF（关键！很多代理在这里被 403）
    """
    parsed = urlsplit(proxy)
    host = parsed.hostname or "unknown"

    result = TestResult(
        proxy=proxy,
        host=host,
        auth_ok=False,
        sentinel_ok=False,
        chat_ok=False,
        csrf_ok=False,
        auth_code="ERR",
        sentinel_code="ERR",
        chat_code="ERR",
        csrf_code="ERR",
        latency_ms=0,
        fully_usable=False,
        risk_score=0,
    )

    codes = {}
    start = time.time()

    # 测试基础 3 端点
    for name, url in TEST_URLS.items():
        try:
            r = requests.get(url, proxy=proxy, impersonate="chrome", timeout=timeout, allow_redirects=True)
            codes[name] = r.status_code
        except Exception as e:
            codes[name] = f"ERR:{type(e).__name__}"
    
    # 额外测试 CSRF 端点（最关键的风控检测点）
    try:
        r = requests.get(CSRF_URL, proxy=proxy, impersonate="chrome", timeout=timeout)
        codes["csrf"] = r.status_code
        # 检查响应内容是否包含有效的 CSRF token
        try:
            data = r.json()
            if isinstance(data, dict) and "csrfToken" in data and len(data.get("csrfToken", "")) > 10:
                result["csrf_ok"] = True
            else:
                # JSON 格式正确但没有 csrfToken，可能是重定向或错误
                if r.status_code == 200:
                    result["csrf_ok"] = False  # 返回格式不对
        except:
            # 非 JSON 响应，检查是否 CF 拦截页面
            body = (r.text or "").lower()
            if "just a moment" in body or "cloudflare" in body or r.status_code == 403:
                result["csrf_ok"] = False
                result["risk_score"] += 2  # CF 拦截，高风险
    except Exception as e:
        codes["csrf"] = f"ERR:{type(e).__name__}"
        if "timed out" in str(e).lower():
            result["risk_score"] += 1  # 超时，中风险

    elapsed = int((time.time() - start) * 1000)
    result["latency_ms"] = elapsed

    # 判断各端点是否通过
    for name in ["auth", "sentinel", "chat"]:
        code = codes.get(name, 0)
        if isinstance(code, int) and 200 <= code < 400:
            result[f"{name}_ok"] = True
            result[f"{name}_code"] = code
        else:
            result[f"{name}_code"] = code
            result["risk_score"] += 1  # 端点失败增加风险分
    
    # CSRF 端点单独处理
    csrf_code = codes.get("csrf", 0)
    if isinstance(csrf_code, int):
        result["csrf_code"] = csrf_code
        if result["csrf_ok"]:
            pass  # 已通过
        elif csrf_code == 403:
            result["risk_score"] += 3  # 403 直接高风险
        elif csrf_code >= 400:
            result["risk_score"] += 2  # 其他错误
    else:
        result["csrf_code"] = csrf_code
        result["risk_score"] += 2  # 网络错误

    # 四个端点都通过才算完全可用（含 CSRF）
    result["fully_usable"] = all([
        result["auth_ok"], 
        result["sentinel_ok"], 
        result["chat_ok"],
        result["csrf_ok"]  # 新增：CSRF 必须通过
    ])
    
    # 更新判断逻辑
    result["auth_ok"] = result.get("auth_ok", False) or (isinstance(result["auth_code"], int) and 200 <= result["auth_code"] < 400)
    result["sentinel_ok"] = result.get("sentinel_ok", False) or (isinstance(result["sentinel_code"], int) and 200 <= result["sentinel_code"] < 400)
    result["chat_ok"] = result.get("chat_ok", False) or (isinstance(result["chat_code"], int) and 200 <= result["chat_code"] < 400)
    # csrf_ok 已在上面设置

    return result


def load_proxies(path: Path, sample: int | None = None) -> list[str]:
    """加载代理文件，可选抽样。"""
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    # 过滤出 HTTP/HTTPS 代理
    http_lines = [line for line in lines if line.lower().startswith(("http://", "https://"))]
    if sample and len(http_lines) > sample:
        import random
        http_lines = random.sample(http_lines, sample)
    return http_lines


def main():
    parser = argparse.ArgumentParser(description="批量测试 HTTP 代理")
    parser.add_argument("input", type=Path, help="代理文件路径")
    parser.add_argument("--output", "-o", type=Path, default=Path("usable_proxies.txt"), help="输出文件路径")
    parser.add_argument("--report", "-r", type=Path, default=Path("test_report.json"), help="测试报告路径")
    parser.add_argument("--workers", "-w", type=int, default=50, help="并发线程数")
    parser.add_argument("--timeout", "-t", type=int, default=12, help="单个请求超时秒数")
    parser.add_argument("--sample", "-s", type=int, help="抽样测试数量（不填则全测）")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"❌ 文件不存在：{args.input}")
        sys.exit(1)

    print(f"[INFO] 加载代理文件：{args.input}")
    proxies = load_proxies(args.input, args.sample)
    print(f"[INFO] 加载 {len(proxies)} 条 HTTP/HTTPS 代理")

    if not proxies:
        print("[ERROR] 没有找到 HTTP/HTTPS 格式的代理")
        sys.exit(1)

    results: list[TestResult] = []
    completed = 0
    usable_count = 0
    auth_pass = 0
    sentinel_pass = 0
    chat_pass = 0
    csrf_pass = 0  # 新增：CSRF 通过数
    low_risk_count = 0  # risk_score=0 的优质代理

    print(f"[INFO] 开始测试（并发={args.workers}, 超时={args.timeout}s）...")
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(test_proxy, p, args.timeout): p for p in proxies}

        for future in as_completed(futures):
            completed += 1
            try:
                result = future.result()
                results.append(result)

                if result["fully_usable"]:
                    usable_count += 1
                    if result.get("risk_score", 0) == 0:
                        low_risk_count += 1
                if result["auth_ok"]:
                    auth_pass += 1
                if result["sentinel_ok"]:
                    sentinel_pass += 1
                if result["chat_ok"]:
                    chat_pass += 1
                if result["csrf_ok"]:
                    csrf_pass += 1

                # 进度汇报
                if completed % 100 == 0 or completed == len(proxies):
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    print(f"  进度：{completed}/{len(proxies)} ({completed/len(proxies)*100:.1f}%) | "
                          f"可用：{usable_count}(低风险{low_risk_count}) | CSRF 通过：{csrf_pass} | 速率：{rate:.1f} 个/秒")

            except Exception as e:
                proxy = futures[future]
                print(f"[WARN] 测试失败：{proxy} - {e}")

    total_elapsed = time.time() - start_time

    # 保存可用代理
    usable_proxies = [r["proxy"] for r in results if r["fully_usable"]]
    args.output.write_text("\n".join(usable_proxies) + "\n", encoding="utf-8")
    print(f"\n[OK] 可用代理已保存：{args.output} ({len(usable_proxies)} 条)")

    # 保存详细报告
    report = {
        "summary": {
            "tested": len(results),
            "fully_usable": usable_count,
            "low_risk_usable": low_risk_count,  # 新增：低风险代理数
            "auth_pass": auth_pass,
            "sentinel_pass": sentinel_pass,
            "chat_pass": chat_pass,
            "csrf_pass": csrf_pass,  # 新增：CSRF 通过数
            "total_elapsed_seconds": round(total_elapsed, 2),
            "rate_per_second": round(len(results) / total_elapsed if total_elapsed > 0 else 0, 2),
        },
        "usable_proxies": [
            {
                "proxy": r["proxy"],
                "host": r["host"],
                "latency_ms": r["latency_ms"],
                "risk_score": r.get("risk_score", 0),
                "codes": {
                    "auth": r["auth_code"],
                    "sentinel": r["sentinel_code"],
                    "chat": r["chat_code"],
                    "csrf": r["csrf_code"],
                }
            }
            for r in results if r["fully_usable"]
        ],
    }
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] 测试报告已保存：{args.report}")

    # 打印摘要
    print("\n" + "=" * 60)
    print("测试结果摘要（升级：含 CSRF 风控检测）")
    print("=" * 60)
    print(f"测试总数：{len(results)}")
    print(f"完全可用（4 端点均通过 + 无风控）：{usable_count} ({usable_count/len(results)*100:.2f}%)")
    print(f"  低风险优质代理（risk_score=0）：{low_risk_count} ({low_risk_count/len(results)*100:.2f}%)")
    print(f"  - auth.openai.com 通过：{auth_pass} ({auth_pass/len(results)*100:.2f}%)")
    print(f"  - sentinel.openai.com 通过：{sentinel_pass} ({sentinel_pass/len(results)*100:.2f}%)")
    print(f"  - chatgpt.com 通过：{chat_pass} ({chat_pass/len(results)*100:.2f}%)")
    print(f"  - CSRF 端点通过：{csrf_pass} ({csrf_pass/len(results)*100:.2f}%) ⭐ 关键指标")
    print(f"总耗时：{total_elapsed:.2f} 秒")
    print(f"测试速率：{len(results)/total_elapsed:.2f} 个/秒")
    print("=" * 60)

    # 输出前 10 个低风险优质代理
    low_risk_proxies = [r for r in results if r["fully_usable"] and r.get("risk_score", 0) == 0]
    if low_risk_proxies:
        print("\n前 10 个低风险优质代理（强烈推荐）：")
        for i, r in enumerate(low_risk_proxies[:10], 1):
            print(f"  {i}. {r['proxy']} (延迟:{r['latency_ms']}ms)")
    elif usable_proxies:
        print("\n前 10 个可用代理（含中等风险）：")
        for i, p in enumerate(usable_proxies[:10], 1):
            print(f"  {i}. {p}")

    return usable_count


if __name__ == "__main__":
    count = main()
    sys.exit(0 if count > 0 else 1)
