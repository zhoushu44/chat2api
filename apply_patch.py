#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用 chat2api 真实 2K/4K 补丁（幂等，可重复执行）"""
import os, shutil, re, sys, time, subprocess

SRC = "/tmp/c2a-push"
BK  = "/tmp/c2a-push.bak-%s" % time.strftime("%Y%m%d-%H%M%S")

def log(m): print(m, flush=True)

# ---------- 0. 备份 ----------
if not os.path.exists(BK):
    shutil.copytree(SRC, BK, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", ".gocache", "chatgpt2api-go"))
    log("[0] 备份源码 -> %s" % BK)
else:
    log("[0] 备份已存在 %s" % BK)

# ---------- 1. 覆盖 superres 包三个文件 ----------
targets = {
    "internal/superres/plan.go":    "/tmp/patch_plan.go",
    "internal/superres/client.go":  "/tmp/patch_client.go",
    "internal/superres/enhance.go": "/tmp/patch_enhance.go",
    "internal/superres/wire.go":    "/tmp/patch_wire.go",
}
for dst_rel, src in targets.items():
    dst = os.path.join(SRC, dst_rel)
    if not os.path.exists(src):
        log("[1] 缺少 %s，跳过" % src); continue
    shutil.copyfile(src, dst)
    log("[1] 覆盖 %s (%d bytes)" % (dst_rel, os.path.getsize(dst)))

# ---------- 2. config.go: 增加 DisableExactSize ----------
cfg_path = os.path.join(SRC, "internal/config/config.go")
txt = open(cfg_path, encoding="utf-8").read()
orig = txt

# 2.1 struct 字段
anchor = '''	// 转码质量 60~95（默认 85）。
	OutputQuality int `json:"output_quality"`
}'''
repl = '''	// 转码质量 60~95（默认 85）。
	OutputQuality int `json:"output_quality"`
	// 精确尺寸开关：默认 false = 超分后追加 imageMogr2/thumbnail/WxH! 严格缩放到请求尺寸；
	// 置 true 则保持旧行为（成品尺寸为 源图×factor 的近似值）。
	DisableExactSize bool `json:"disable_exact_size"`
}'''
if "DisableExactSize" not in txt:
    if anchor in txt:
        txt = txt.replace(anchor, repl, 1)
        log("[2.1] SuperResolutionConfig 已增加 DisableExactSize")
    else:
        log("[2.1] !! 未找到 struct 锚点，跳过")
else:
    log("[2.1] DisableExactSize 已存在，跳过")

# 2.2 applySuperResolution 热更
anchor2 = '''	if v, ok := m["output_quality"].(float64); ok {
		cfg.SuperResolution.OutputQuality = int(v)
	}
}'''
repl2 = '''	if v, ok := m["output_quality"].(float64); ok {
		cfg.SuperResolution.OutputQuality = int(v)
	}
	// 精确尺寸开关（面板/脚本可热更；缺省保持当前值）
	if v, ok := m["disable_exact_size"].(bool); ok {
		cfg.SuperResolution.DisableExactSize = v
	}
}'''
if 'm["disable_exact_size"]' not in txt:
    if anchor2 in txt:
        txt = txt.replace(anchor2, repl2, 1)
        log("[2.2] applySuperResolution 已支持 disable_exact_size")
    else:
        log("[2.2] !! 未找到热更锚点，跳过")
else:
    log("[2.2] 热更已存在，跳过")

if txt != orig:
    open(cfg_path, "w", encoding="utf-8").write(txt)
    log("[2] config.go 已更新")
else:
    log("[2] config.go 无变化")

# ---------- 3. 语法自检 ----------
log("\n[3] gofmt 检查")
r = subprocess.run(["gofmt", "-l", "internal/superres/", "internal/config/"],
                   cwd=SRC, capture_output=True, text=True)
out = (r.stdout or "") + (r.stderr or "")
log("  gofmt 未格式化文件: %s" % (out.strip() or "(无，全部合规)"))

# ---------- 4. 打印关键改动确认 ----------
log("\n[4] 关键改动确认")
for f, pats in [
    ("internal/superres/plan.go", ["upscaleCeiling", "Exact", "maxPixels && !isAlias"]),
    ("internal/superres/client.go", ["buildPostProcessRule", "thumbnail/%dx%d!", "disable_exact_size"]),
    ("internal/config/config.go", ["DisableExactSize"]),
]:
    p = os.path.join(SRC, f)
    t = open(p, encoding="utf-8").read()
    log("  %s:" % f)
    for pat in pats:
        log("    %-28s %s" % (pat, "存在" if pat in t else "缺失"))
log("\nDONE")
