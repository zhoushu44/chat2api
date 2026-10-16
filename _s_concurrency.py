# -*- coding: utf-8 -*-
"""高并发生图压测：并发数阶梯递增，统计成功率/耗时/归因"""
import sys, json, time, base64, threading
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

AUTH = "Bearer zs1236547"

def gen_prompt(i):
    return "a flat minimalist icon of a %s, single color background, vector style" % [
        "camera", "coffee cup", "mountain", "book", "rocket", "umbrella",
        "headphone", "piano", "leaf", "cloud", "anchor", "compass",
        "lightbulb", "key", "clock", "envelope", "globe", "flag",
        "star", "heart"][i % 20]

def one_image(idx):
    """发一次生图，返回 (idx, http_code, ok, duration)"""
    body = json.dumps({"model": "gpt-image-2", "prompt": gen_prompt(idx),
                       "n": 1, "size": "1024x1024"})
    b64 = base64.b64encode(body.encode()).decode()
    t0 = time.time()
    o, e = run('docker exec chatgpt2api-14 sh -c "echo %s | base64 -d > /tmp/img_%d.json && curl -s -o /tmp/img_%d.out -w \\"%%{http_code}\\" -X POST http://127.0.0.1:3077/v1/images/generations -H \\"Authorization: %s\\" -H \\"Content-Type: application/json\\" -d @/tmp/img_%d.json"' % (b64, idx, idx, AUTH, idx), timeout=300)
    dur = time.time() - t0
    code = o.strip()
    ok = False
    if code == "200":
        o2, _ = run('docker exec chatgpt2api-14 sh -c "head -c 300 /tmp/img_%d.out"' % idx, timeout=30)
        ok = '"b64_json"' in o2
    return idx, code, ok, dur

def bench(concurrency, total):
    print("\n===== 并发 %d，总 %d 张 =====" % (concurrency, total))
    results = [None] * total
    lock = threading.Lock()
    done_count = [0]
    t0 = time.time()

    def worker(slot):
        for i in range(slot, total, concurrency):
            try:
                results[i] = one_image(i)
            except Exception as exc:
                results[i] = (i, "EXC:" + str(exc)[:60], False, 0)
            with lock:
                done_count[0] += 1
                if done_count[0] % 5 == 0 or done_count[0] == total:
                    print("  进度 %d/%d (%.0fs)" % (done_count[0], total, time.time() - t0))

    threads = [threading.Thread(target=worker, args=(s,)) for s in range(concurrency)]
    for t in threads: t.start()
    for t in threads: t.join()
    wall = time.time() - t0

    oks = [r for r in results if r and r[2]]
    codes = {}
    for r in results:
        if r:
            codes[r[1]] = codes.get(r[1], 0) + 1
    durs = sorted(r[3] for r in results if r)
    print("  结果: %d/%d 成功 | 耗时 %.0fs | 单张 p50=%.0fs p95=%.0fs | code 分布 %s" % (
        len(oks), total, wall,
        durs[len(durs)//2] if durs else 0, durs[int(len(durs)*0.95)] if durs else 0,
        codes))
    return len(oks), total

if __name__ == "__main__":
    # 阶梯：并发 5 → 10 → 20
    for c, n in [(5, 10), (10, 20), (20, 40)]:
        ok, total = bench(c, n)
        if ok < total * 0.5:
            print("  ⚠️ 成功率过低，停止加压")
            break
        time.sleep(3)
    print("\n压测完成")
