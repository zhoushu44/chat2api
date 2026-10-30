package backend

import (
	"strings"
	"testing"
)

// TestStableDeviceID 防止「同一账号每次请求换设备 ID」的回归。
// 该问题会让上游把同一 token 视为「换了台机器」，容易判 credential sharing 并 revoke。
func TestStableDeviceID(t *testing.T) {
	a1 := FingerprintForAccount("user@example.com")
	a2 := FingerprintForAccount("user@example.com")
	if a1.OaiDeviceID != a2.OaiDeviceID {
		t.Fatalf("same account must keep device id: %s vs %s", a1.OaiDeviceID, a2.OaiDeviceID)
	}
	if a1.OaiSessionID != a2.OaiSessionID {
		t.Fatalf("same account must keep session id: %s vs %s", a1.OaiSessionID, a2.OaiSessionID)
	}
	b := FingerprintForAccount("other@example.com")
	if b.OaiDeviceID == a1.OaiDeviceID {
		t.Fatal("different accounts should have different device ids")
	}
	// 形态仍是 UUID（36 字符、4 个连字符）
	if len(a1.OaiDeviceID) != 36 {
		t.Fatalf("device id should look like uuid, got %q", a1.OaiDeviceID)
	}
}

// TestSecChUaMatchesUA 防止「UA 是 Edge/Mac，Sec-Ch-Ua 写 Chrome」的自相矛盾。
func TestSecChUaMatchesUA(t *testing.T) {
	fp := FingerprintForAccount("edge-user@example.com")
	if fp.SecChUa == "" {
		t.Skip("profile is firefox; no sec-ch-ua expected")
	}
	// Sec-Ch-Ua 的版本必须能在这个 UA 里找到同主版本
	major := uaMajorVersion(fp.UserAgent)
	if !strings.Contains(fp.SecChUa, major) {
		t.Fatalf("sec-ch-ua %q does not match UA major %q (UA=%s)", fp.SecChUa, major, fp.UserAgent)
	}
}
