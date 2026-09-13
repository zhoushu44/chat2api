# Debug Session: chatgpt2api-zero-quota
- **Status**: [OPEN]
- **Issue**: 通过 Web 控制台导入 ChatGPT 账号后，账号显示正常但额度为 0；此前直接导入测试账号有额度。
- **Debug Server**: 待启动
- **Log File**: `.dbg/trae-debug-log-chatgpt2api-zero-quota.ndjson`

## Reproduction Steps
1. 在 Web 控制台选择 ChatGPT 最近产出。
2. 填写 chatgpt2api 根地址和管理员密钥。
3. 点击“导入到 chatgpt2api”。
4. 在 chatgpt2api 后台查看账号额度。

## Hypotheses & Verification
| ID | Hypothesis | Likelihood | Effort | Evidence |
|----|------------|------------|--------|----------|
| A | Web 导入的凭据不是完整 accessToken | Medium | Low | Pending |
| B | Web 导入请求的 type/source_type 与直接导入不同 | Medium | Low | Pending |
| C | chatgpt2api 刷新额度请求失败，失败状态被显示为 0 | High | Medium | Pending |
| D | 后续账号 JWT 声明或套餐确实没有额度 | Medium | Low | Pending |
| E | 导入后的刷新时机或缓存导致暂时显示 0 | Low | Medium | Pending |

## Log Evidence
等待运行时复现。

## Verification Conclusion
已确认并修复一个独立问题：ChatGPT Provider 原先仅以 `added > 0` 判定成功，账号已存在时服务端返回 `skipped=1`，导致 `consumed_credentials` 为空，Web 控制台不会清理对应产出。现改为 `added + skipped == 输入数量` 且无错误时清理。
额度为 0 的根因仍需按原运行时日志复现确认。
