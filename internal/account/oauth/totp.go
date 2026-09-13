package oauth

import (
	"crypto/hmac"
	"crypto/sha1"
	"encoding/base32"
	"encoding/binary"
	"fmt"
	"strings"
	"time"
)

// TOTPNow 生成当前 30 秒窗口的 6 位 TOTP 码（RFC 6238，HMAC-SHA1）。
// 用于 AT 失效时走「邮箱+密码+TOTP」协议登录恢复（不等邮箱 OTP）。
// 移植自 regiforge _totp_now，行为需与 Python 侧逐位一致。
func TOTPNow(secret string) (string, error) {
	return TOTPAt(secret, time.Now())
}

// TOTPAt 生成指定时间的 TOTP 码（便于测试）。
func TOTPAt(secret string, t time.Time) (string, error) {
	key, err := decodeBase32Secret(secret)
	if err != nil {
		return "", err
	}
	if len(key) == 0 {
		return "", fmt.Errorf("totp: empty secret")
	}
	var buf [8]byte
	// 30 秒步长
	binary.BigEndian.PutUint64(buf[:], uint64(t.Unix()/30))

	mac := hmac.New(sha1.New, key)
	mac.Write(buf[:])
	digest := mac.Sum(nil)

	// 动态截断（RFC 4226）
	offset := digest[len(digest)-1] & 0x0F
	code := (int(digest[offset])&0x7F)<<24 |
		int(digest[offset+1])<<16 |
		int(digest[offset+2])<<8 |
		int(digest[offset+3])
	return fmt.Sprintf("%06d", code%1000000), nil
}

// decodeBase32Secret 解析 Base32 secret（容忍空格、小写、无填充）。
func decodeBase32Secret(secret string) ([]byte, error) {
	s := strings.ToUpper(strings.ReplaceAll(strings.TrimSpace(secret), " ", ""))
	s = strings.TrimRight(s, "=")
	if s == "" {
		return nil, fmt.Errorf("totp: empty secret")
	}
	key, err := base32.StdEncoding.WithPadding(base32.NoPadding).DecodeString(s)
	if err != nil {
		return nil, fmt.Errorf("totp: invalid base32 secret: %w", err)
	}
	return key, nil
}
