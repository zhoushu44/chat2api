# NVIDIA HTTP 模式 L4 升级状态

## 🎯 目标

将 **nvidia_build HTTP 模式** 提升到 **L4**（Web 控制台批量并发）

## 📊 当前状态

### ✅ 已完成
- ✅ HTTP 注册引擎框架完整实现 (`steps/_http_engine.py`)
- ✅ 双模式架构支持 (`project.py`)
- ✅ UI 配置完成 (`ui/schema.json`)
- ✅ curl_cffi 依赖已安装
- ✅ 基础测试通过 (`test_http_simple.py`)

### ⚠️ 待完成
- ⚠️ **需要抓包分析实际 URL 和字段**
- ⚠️ **需要 Web 服务启动并测试**
- ⚠️ **需要逐级验收 L1→L2→L3→L4**

## 📋 L4 升级流程

### L1: 成功（单个账号）
```bash
register_mode = "http"
total = 1
concurrency = 1
headless = false
```
**验收标准**: `status=ok` 且有 `apikey`

**状态**: 📋 待测试

### L2: 稳定（5 个账号）
```bash
register_mode = "http"
total = 5
concurrency = 1
```
**验收标准**: 成功率 ≥80%

**状态**: 📋 待测试

### L3: 批量并发
```bash
register_mode = "http"
total = 10
concurrency = 2→N
```
**验收标准**: 成功率较 L2 跌幅 ≤15%

**状态**: 📋 待测试

### L4: Web 控制台批量并发
```bash
# 从 Web 控制台启动
/projects/nvidia_build
→ register_mode = "http"
→ total = 10
→ concurrency = 2
→ 点击「启动任务」
```
**验收标准**: 同 L3 成功率，且从 Web 控制台启动

**状态**: 📋 待测试

## 🔧 下一步

### 1. 启动 Web 服务

```bash
# 检查 Web 服务入口
python -m uvicorn web.app:app --reload
# 或
python web/app.py
```

### 2. 用 browser 模式跑一次，抓包分析

```bash
# 设置 browser 模式
register_mode = "browser"

# 运行单个账号测试
python projects/nvidia_build/test_one_account.py

# 观察网络请求，记录：
# - build.nvidia.com 的 key 参数
# - 邮箱提交的实际 URL
# - 注册表单的字段名
# - OTP 提交的端点
# - Post-Verification 流程的 URL
```

### 3. 更新 HTTP 引擎

编辑 `projects/nvidia_build/steps/_http_engine.py`：

```python
# 更新 URL
NVGS_BASE = "https://login.nvidia.com"  # 实际 URL
CLOUDACCOUNTS_BASE = "https://cloudaccounts.nvidia.com"

# 更新字段
form_data = {
    "email": email,
    "registration_password": password,
    # 根据抓包结果更新
}
```

### 4. 逐级验收

```bash
# L1 测试
python projects/nvidia_build/_test_l1_http.py

# L2 测试（total=5）
# 修改配置，运行 5 个账号

# L3 测试（concurrency=2）
# 修改配置，提高并发

# L4 测试（Web 控制台）
# 打开 Web 控制台，点击「启动任务」
```

## 📁 相关文件

```
projects/nvidia_build/
├── steps/
│   └── _http_engine.py          [✅] HTTP 注册引擎（框架完整）
├── project.py                   [✅] 双模式路由
├── ui/
│   └── schema.json              [✅] UI 配置
├── _test_l1_http.py             [✅] L1 验收测试脚本
├── test_http_simple.py          [✅] 基础测试
├── test_http_register_full.py   [✅] 完整测试
└── L4_UPGRADE_STATUS.md         [✅] 本文档
```

## 💡 关键障碍

### HTTP 模式当前问题

1. **build.nvidia.com 返回空 HTML (HTTP 202)**
   - Cloudflare 保护
   - curl_cffi 无法执行 JS 挑战

2. **NVGS 返回 403**
   - key 参数无效
   - 需要有效的 session Cookie

### 解决方案

**方案 A: 混合模式**（推荐）
- 用 browser 模式处理前 3 步（Cloudflare + 邮箱提交）
- 提取 key 和 Cookie
- 切换到 HTTP 模式处理后 4 步（注册 + OTP + API Key）

**方案 B: 纯 HTTP 模式**（需要抓包）
- 抓包分析完整流程
- 更新所有 URL 和字段
- 处理 Cloudflare 挑战

## 🚀 快速开始

### 立即可用（Browser 模式）

```bash
# Web 控制台
/projects/nvidia_build → register_mode="browser" → 启动任务
```

### 未来使用（HTTP 模式 L4）

```bash
# 1. 启动 Web 服务
python -m uvicorn web.app:app --reload

# 2. 用 browser 模式跑一次，抓包
python projects/nvidia_build/test_browser_capture.py

# 3. 更新 HTTP 引擎配置
# 编辑 projects/nvidia_build/steps/_http_engine.py

# 4. 运行 L1 测试
python projects/nvidia_build/_test_l1_http.py

# 5. 逐级验收 L2→L3→L4
```

## 📞 需要帮助？

查看以下文档：
- `USAGE_GUIDE.md` - HTTP 模式使用指南
- `TEST_REPORT.md` - 测试结果报告
- `HTTP_MODE_COMPLETE.md` - 完整实现报告

---

**更新日期**: 2026-08-03  
**状态**: 框架完整，待抓包验证和逐级验收  
**下一步**: 启动 Web 服务 → 抓包分析 → 更新配置 → 逐级测试
