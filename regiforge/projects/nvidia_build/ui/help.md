# NVIDIA Build 面板说明

## 做什么

自动注册 [build.nvidia.com](https://build.nvidia.com) 账号，并尽量拿到 AI Playground 的 `nvapi-` Key。

## 推荐组合

| 能力 | 选择 |
|------|------|
| 验证码 | `hcaptcha / CaptchaRun` |
| 邮箱 | Cloudflare Worker |
| 代理 | `socks5`，输入 SOCKS5 链接；留空直连 |

## 配置

- **注册密码**：项目字段，保存到 `projects.nvidia_build.password`
- **CaptchaRun / Worker / 代理**：右侧 Provider 配置区；代理可选手填 `socks5://`，留空即直连
- **浏览器底座**：`browser_backend` / `browser_channel`（与 Grok、ChatGPT 字段风格一致）

## 成熟度与任务参数

| 阶段 | 参数 | 说明 |
|------|------|------|
| 当前确认 | `total=1`、`concurrency=1`、`stagger=0` | 一次真实页面单账号成功，仅证明 L1 |
| L2 | `concurrency=1`、`total≥5` | 同配置成功率需达到 80% |
| L3 | 从 `concurrency=2` 逐级提高 | 仅在 L2 通过后进行批量并发验收 |
| 浏览器底座 | `patchright` 或留空跟随全局 | 与 Playwright 可切换；当前不据单次成功推导批量能力 |

注意事项：
- step03 失败时，正式编排会重跑 step01–03，最多两轮。
- 每个并发账号使用独立 Chrome 会话；资源和风控表现需在 L3 验收时实测。
- CaptchaRun 解题时延与服务状态有关，不在文档中承诺固定耗时。

## 步骤

页面「项目步骤」来自 `ui/schema.json`，与 `steps/stepNN_*.py` 对应。
更细的选择器与踩坑见项目根目录 `STEPS.md`。

## 产出

- 行格式：`email|nvapi-...`（与全局导出约定一致：`email|credential`）
- 路径：全局 `ui.keys_output_dir` — 留空为 `data/keys/nvidia_build/api_keys.txt`；自定义文件夹为 `<文件夹>/nvidia_build_api_keys.txt`
- 左侧「最近产出」与导出区读取同一文件

## 导出 / 导入账号池（三项目共用）

控制台左侧 **导出 / 导入账号池**（与 ChatGPT、Grok 同一块 UI）：

| 目标 | 参数要点 |
|------|----------|
| `file` | 文件夹路径 + 文件名 |
| `sub2api` | 根地址、管理员令牌、账号模板（`$email` / `$credential`） |
| `grok2api` | 根地址、JWT、账号类型（NVIDIA 场景较少用） |

参数写在 `export.<id>`，点「导出当前产出」走 `POST /api/export`。
