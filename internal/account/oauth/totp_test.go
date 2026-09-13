package oauth

import (
	"testing"
	"time"
)

// TC1：RFC6238 附录 B 标准测试向量（HMAC-SHA1，T=59 期望 94287082）。
// 本项目只取后 6 位：94287082 -> 287082。
func TestTOTPAtRFC6238Vector(t *testing.T) {
	// RFC6238 附录 B 的种子为 ASCII "12345678901234567890"
	// Base32 编码后为 GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ
	secret := "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
	got, err := TOTPAt(secret, time.Unix(59, 0))
	if err != nil {
		t.Fatalf("TOTPAt err: %v", err)
	}
	if got != "287082" {
		t.Fatalf("totp=%s want 287082 (RFC6238 T=59 -> 94287082)", got)
	}
}

// TC2：含空格 / 小写 secret 能正常解析（与无空格大写等价）。
func TestTOTPSecretNormalize(t *testing.T) {
	base := "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
	at := time.Unix(1234567890, 0)
	want, err := TOTPAt(base, at)
	if err != nil {
		t.Fatalf("baseline err: %v", err)
	}
	variants := []string{
		"gezdgnbvgy3tqojqgezdgnbvgy3tqojq",
		"GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ",
		"GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ====",
	}
	for _, v := range variants {
		got, err := TOTPAt(v, at)
		if err != nil {
			t.Fatalf("variant %q err: %v", v, err)
		}
		if got != want {
			t.Fatalf("variant %q totp=%s want %s", v, got, want)
		}
	}
}

// TC3：非法 Base32 secret 返回 error，不 panic。
func TestTOTPInvalidSecret(t *testing.T) {
	bad := []string{"", "   ", "!!!not-base32!!!", "0O1I"}
	for _, s := range bad {
		if _, err := TOTPNow(s); err == nil {
			t.Fatalf("secret %q should error", s)
		}
	}
}

// TC4：输出恒为 6 位数字，且同一 30s 窗口内稳定。
func TestTOTPFormatStable(t *testing.T) {
	secret := "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
	// 1700000000 落在 30s 窗口中间；取窗口起点与其 +29s 应同码
	t1 := time.Unix((1700000000/30)*30, 0)
	t2 := t1.Add(29 * time.Second) // 同一 30s 窗口
	c1, err := TOTPAt(secret, t1)
	if err != nil {
		t.Fatal(err)
	}
	c2, err := TOTPAt(secret, t2)
	if err != nil {
		t.Fatal(err)
	}
	if c1 != c2 {
		t.Fatalf("same window should match: %s vs %s", c1, c2)
	}
	if len(c1) != 6 {
		t.Fatalf("code len=%d want 6", len(c1))
	}
	for _, r := range c1 {
		if r < '0' || r > '9' {
			t.Fatalf("code %s not all digits", c1)
		}
	}
}
