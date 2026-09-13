# projects/zcode_register

## 职责

以有头浏览器完成 Z.ai / ZCode OAuth 页直注册：用户名+邮箱+密码 → 阿里云滑块（yydsocr 识别 + 非线性映射拖动）→ 邮箱验证链接 → 设置密码完成注册，产出 accessToken（JWT）。

## 包含

| 文件/子目录 | 说明 |
|-------------|------|
| `project.py` | `PROJECT` 入口，使用 `RegisterDebug` 编排 6 步，`extra` 落盘 `user_id` |
| `steps/` | 打开 OAuth 页、填表、滑块提交、邮箱验证、完成注册、提取 token 的编号步骤 |
| `ui/schema.json` | Web 字段、Provider 白名单、步骤与产出规划（含导出 JSON 与表格列） |
| `ui/help.md` | 控制台使用说明 |

## Provider 依赖

| 能力 | Provider |
|------|----------|
| 验证码 | `slider.aliyun`（yydsocr + 非线性映射，与 tokenrhythm 同款） |
| 邮箱 | 功能级全局下拉（`allowed_email_ids=[]`），默认走 `mailnest`（project_code=z-ai001） |
| 代理 | `none` / `socks5` / `manual_socks5` / `api_socks5` / `clash` |

项目内不复制邮箱/代理/打码实现，一律 `ctx.email` / `ctx.proxy` / `ctx.captcha`。

## 产出

- `data/keys/zcode_register/api_keys.txt`
- 行格式：`email|accessToken`
- `accounts.jsonl` `extra`：`source_type=web`、`user_id`（JWT payload 解码）

## 踩坑

- concurrency>2 会触发 Z.ai 服务端限流（「验证服务不可用」/「正在创建账号」挂起），批量建议 concurrency≤2。
- OAuth client_id / redirect_uri 来自 zcode 官方登录入口，勿改。

## 相关

- [步骤说明](steps/README.md)
- [UI 规划](ui/README.md)
- [阿里云滑块](../../captcha/slider/aliyun/README.md)
- [MailNest](../../mailsys/mailnest/README.md)
