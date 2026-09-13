## 商汤 SenseNova 注册

1. 选择短信服务 `jichisms`，填写疾驰短信 `fcToken` 和商汤项目 SID。
2. 选择验证码服务 `slider.sensenova`；仅在 SenseNova 要求图片滑块时调用。
3. 选择代理；无需代理可选择 `none`。
4. 保存配置后启动任务。

流程通过 OAuth2 PKCE、短信验证完成注册，并产出 SenseNova API Key。

### 重试与退避

- 任意步骤失败后自动从 OAuth challenge 重新注册，最多 3 次（可配置）。
- 普通失败：退避 `10 × attempt` 秒（上限 30s）。
- 商汤频率限制（`operationTooFrequently`）：至少等待 30s。
- 短信取码超时：释放号码后重新取号。
- 重试前自动释放上一轮手机号，避免疾驰号码泄漏。
