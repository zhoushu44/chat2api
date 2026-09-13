// 真实验证测试：用真实账号跑协议登录。
// 触发方式（不设环境变量则跳过）：
//   CHAT2API_RECOVERY_TEST="email:password:totp_secret" CHAT2API_RECOVERY_PROXY="socks5://..." \
//     go test ./internal/account/oauth -run TestRecoveryLoginReal -v
package oauth

import (
	"os"
	"strings"
	"testing"
)

func TestRecoveryLoginReal(t *testing.T) {
	cred := os.Getenv("CHAT2API_RECOVERY_TEST")
	if cred == "" {
		t.Skip("未设 CHAT2API_RECOVERY_TEST，跳过真实验证")
	}
	parts := strings.SplitN(cred, ":", 3)
	if len(parts) != 3 {
		t.Fatalf("格式应为 email:password:totp_secret")
	}
	res, err := LoginWithPassword(parts[0], parts[1], parts[2], os.Getenv("CHAT2API_RECOVERY_PROXY"), func(s string) {
		t.Logf("[flow] %s", s)
	})
	if err != nil {
		t.Fatalf("登录失败: %v", err)
	}
	if len(res.AccessToken) < 100 {
		t.Fatalf("AT 过短: %d", len(res.AccessToken))
	}
	t.Logf("新 AT 长度=%d 前缀=%s…", len(res.AccessToken), res.AccessToken[:20])
}
