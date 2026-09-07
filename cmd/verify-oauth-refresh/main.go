// Command verify-oauth-refresh:验证 OAuth 账号自动刷新是否生效。
// 对等 scripts/verify_oauth_refresh.py：默认只读诊断（JWT exp 剩余有效期、refresh_token 有无）；
// --force 对带 refresh_token 的账号真实走一次 Auth0 refresh_token grant。
package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"chatgpt2api/internal/account"
)

const (
	oauthTokenURL = "https://auth.openai.com/oauth/token"
	oauthClientID = "app_2SKx67EdpoN0G6j64rFvigXD"
)

// jwtExp 解析 JWT exp（秒级时间戳；失败返回 0）。
func jwtExp(token string) int64 {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return 0
	}
	payload := parts[1]
	if m := len(payload) % 4; m != 0 {
		payload += strings.Repeat("=", 4-m)
	}
	b, err := base64.URLEncoding.DecodeString(payload)
	if err != nil {
		return 0
	}
	var claims struct {
		Exp int64 `json:"exp"`
	}
	if err := json.Unmarshal(b, &claims); err != nil {
		return 0
	}
	return claims.Exp
}

func fmtRemaining(sec int64, ok bool) string {
	if !ok {
		return "无法解析 exp"
	}
	if sec <= 0 {
		return fmt.Sprintf("已过期 %dh", -sec/3600)
	}
	return fmt.Sprintf("%dh%02dm 后过期", sec/3600, (sec%3600)/60)
}

func dataDir() string {
	if d := os.Getenv("CHATGPT2API_DATA_DIR"); d != "" {
		return d
	}
	return "./data"
}

// refreshOnce 真实走一次 refresh_token grant，返回新 access_token。
func refreshOnce(refreshToken string) (string, error) {
	form := url.Values{
		"grant_type":    {"refresh_token"},
		"refresh_token": {refreshToken},
		"client_id":     {oauthClientID},
	}
	req, err := http.NewRequest("POST", oauthTokenURL, bytes.NewBufferString(form.Encode()))
	if err != nil {
		return "", err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")
	client := &http.Client{Timeout: 60 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	var data map[string]any
	_ = json.Unmarshal(b, &data)
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(b)))
	}
	access, _ := data["access_token"].(string)
	if strings.TrimSpace(access) == "" {
		return "", fmt.Errorf("no access_token in response")
	}
	return access, nil
}

func main() {
	force := flag.Bool("force", false, "真正触发一次刷新（默认只读诊断）")
	flag.Parse()

	svc := account.New(dataDir())
	accs := svc.List()
	fmt.Printf("账号总数: %d\n\n", len(accs))
	var refreshable []*account.Account
	for _, a := range accs {
		exp := jwtExp(a.Token)
		remaining := exp - time.Now().Unix()
		hasRT := strings.TrimSpace(a.RefreshToken) != ""
		if hasRT {
			refreshable = append(refreshable, a)
		}
		fmt.Printf("- email=%s\n", orUnknown(a.Email))
		fmt.Printf("    access_token[:20]   = %s...\n", safePrefix(a.Token, 20))
		fmt.Printf("    距过期              = %s\n", fmtRemaining(remaining, exp > 0))
		fmt.Printf("    refresh_token       = %s\n", map[bool]string{true: "有 ✅", false: "无 ❌（无法自动刷新）"}[hasRT])
		fmt.Printf("    token_expire_at     = %d\n", a.TokenExpireAt)
		fmt.Println()
	}
	if !*force {
		return
	}
	if len(refreshable) == 0 {
		fmt.Println("没有带 refresh_token 的账号，无法验证刷新。")
		return
	}
	fmt.Println("============================================================")
	fmt.Printf("开始对 %d 个账号 force 刷新（真实调用 OpenAI）...\n\n", len(refreshable))
	ok := 0
	for _, a := range refreshable {
		newToken, err := refreshOnce(a.RefreshToken)
		if err != nil {
			fmt.Printf("- %s: 失败: %v\n", orUnknown(a.Email), err)
			continue
		}
		a.Token = newToken
		if err := svc.Add(a); err != nil {
			fmt.Printf("- %s: 换出成功但落盘失败: %v\n", orUnknown(a.Email), err)
			continue
		}
		fmt.Printf("- %s: 成功 ✅\n", orUnknown(a.Email))
		ok++
	}
	fmt.Printf("\n成功 %d/%d\n", ok, len(refreshable))
}

func orUnknown(s string) string {
	if strings.TrimSpace(s) == "" {
		return "(未知)"
	}
	return s
}

func safePrefix(s string, n int) string {
	if len(s) < n {
		return s
	}
	return s[:n]
}
