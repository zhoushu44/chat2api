package scheduler

import (
	"encoding/base64"
	"encoding/json"
	"strings"
)

// tokenExpireAt 从 JWT access_token 的 payload 解出 exp（秒级时间戳）。
// 解析失败返回 0（调用方视为「未知」，不影响恢复结果）。
func tokenExpireAt(token string) int64 {
	parts := strings.Split(token, ".")
	if len(parts) < 2 {
		return 0
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		// 兼容带 padding 的变体
		if payload, err = base64.URLEncoding.DecodeString(parts[1]); err != nil {
			return 0
		}
	}
	var claims struct {
		Exp int64 `json:"exp"`
	}
	if err := json.Unmarshal(payload, &claims); err != nil {
		return 0
	}
	if claims.Exp <= 0 {
		return 0
	}
	return claims.Exp
}

// TokenExpireAtForTest 供单测直接验证 exp 解析。
func TokenExpireAtForTest(token string) int64 { return tokenExpireAt(token) }
