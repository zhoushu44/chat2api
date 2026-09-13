package oauth

import (
	"encoding/json"
	"fmt"
	"io"
	"net/url"
	"regexp"
	"strings"

	"chatgpt2api/internal/backend"
	"chatgpt2api/internal/backend/antibot"

	"github.com/google/uuid"
	fhttp "github.com/bogdanfinn/fhttp"
	tls_client "github.com/bogdanfinn/tls-client"
	"github.com/bogdanfinn/tls-client/profiles"
)

// 对等探针 regiforge/scripts/probe_login_browser.py 已验证的协议登录全链路：
//   1. GET  chatgpt.com/api/auth/csrf
//   2. POST chatgpt.com/api/auth/signin/openai（form: csrfToken, callbackUrl）
//   3. GET  auth.openai.com/api/accounts/authorize?...（NextAuth 生成的 state）
//   4. POST auth.openai.com/api/accounts/authorize/continue {"username":{"kind":"email","value"}}
//   5. POST auth.openai.com/api/accounts/password/verify {"password"}
//   6. POST auth.openai.com/api/accounts/mfa/issue_challenge {"id","type":"totp"}
//   7. POST auth.openai.com/api/accounts/mfa/verify {"id","type":"totp","code"}
//   8. GET  chatgpt.com/api/auth/callback/openai?code=oaistb_ac_...
//   9. GET  chatgpt.com/api/auth/session → accessToken（新 AT）
const (
	loginChatBase = "https://chatgpt.com"
	loginAuthBase = "https://auth.openai.com"
	loginUA       = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

var mfaChallengeIDRe = regexp.MustCompile(`mfa-challenge/([0-9a-fA-F]{16,64})`)

// LoginResult 协议登录结果。
type LoginResult struct {
	AccessToken string
	// SessionToken 新的 NextAuth session cookie（__Secure-next-auth.session-token），
	// 供上层替换旧 session_token；未取到为空串。
	SessionToken string
}

// LoginWithPassword 用「邮箱 + 密码 + TOTP」走协议登录换新 AT（不等邮箱 OTP）。
// 失败返回非空 error；成功返回 session 里的 accessToken。
func LoginWithPassword(email string, password string, totpSecret string, proxy string, logFn func(string)) (*LoginResult, error) {
	httpClient, err := backend.NewClient(profiles.Chrome_110, proxy)
	if err != nil {
		return nil, fmt.Errorf("client: %w", err)
	}
	c := &loginClient{http: httpClient, refer: loginChatBase + "/", log: logFn}

	// 1) csrf
	csrf, err := c.getString(loginChatBase + "/api/auth/csrf")
	if err != nil {
		return nil, fmt.Errorf("csrf: %w", err)
	}
	var csrfBody struct {
		CSRFToken string `json:"csrfToken"`
	}
	if err := json.Unmarshal([]byte(csrf), &csrfBody); err != nil {
		return nil, fmt.Errorf("csrf 解析: %w (body=%s)", err, cut(csrf, 200))
	}
	c.log(fmt.Sprintf("csrf=%s…", cut(csrfBody.CSRFToken, 10)))

	// 2) NextAuth signin → 302 到 authorize
	resp, err := c.formPost(loginChatBase+"/api/auth/signin/openai",
		"csrfToken="+csrfBody.CSRFToken+"&callbackUrl=%2F")
	if err != nil {
		return nil, fmt.Errorf("signin: %w", err)
	}
	authorizeURL := ""
	if resp.StatusCode >= 300 && resp.StatusCode < 400 {
		authorizeURL = resp.Header.Get("Location")
	}
	if authorizeURL == "" {
		body, _ := readBody(resp)
		return nil, fmt.Errorf("signin 未返回 302 (HTTP %d, body=%s)", resp.StatusCode, cut(body, 300))
	}
	c.log("authorize url ok")

	// 3) 打开 authorize，建立 auth.openai.com 会话（SPA 落地 /log-in）
	if err := c.navFollow(authorizeURL); err != nil {
		return nil, fmt.Errorf("authorize: %w", err)
	}

	// 4) 提交邮箱
	if _, err := c.postJSON(loginAuthBase+"/api/accounts/authorize/continue",
		`{"username":{"kind":"email","value":"`+email+`"}}`); err != nil {
		return nil, fmt.Errorf("邮箱提交: %w", err)
	}

	// 5) 提交密码；响应里带 mfa 挑战 id（落地 /mfa-challenge/<id>）
	c.refer = loginAuthBase + "/log-in/password"
	pwResp, err := c.postJSONRaw(loginAuthBase+"/api/accounts/password/verify",
		`{"password":`+mustJSON(password)+`}`)
	if err != nil {
		return nil, fmt.Errorf("密码提交: %w", err)
	}
	pwBody, _ := readBody(pwResp)
	if pwResp.StatusCode != 200 {
		return nil, fmt.Errorf("密码提交失败 HTTP %d body=%s", pwResp.StatusCode, cut(pwBody, 300))
	}
	m := mfaChallengeIDRe.FindStringSubmatch(pwBody)
	challengeID := ""
	if len(m) == 2 {
		challengeID = m[1]
	}

	// 6~7) TOTP（账号未开 2FA 时跳过）
	continueURL := ""
	if challengeID != "" {
		if _, err := c.postJSON(loginAuthBase+"/api/accounts/mfa/issue_challenge",
			`{"id":"`+challengeID+`","type":"totp","force_fresh_challenge":false}`); err != nil {
			return nil, fmt.Errorf("mfa/issue_challenge: %w", err)
		}
		code, err := TOTPNow(totpSecret)
		if err != nil {
			return nil, fmt.Errorf("TOTP 生成: %w", err)
		}
		body, err := c.postJSON(loginAuthBase+"/api/accounts/mfa/verify",
			`{"id":"`+challengeID+`","type":"totp","code":"`+code+`"}`)
		if err != nil {
			return nil, fmt.Errorf("mfa/verify: %w", err)
		}
		// mfa/verify 响应带 continue_url（chatgpt callback 带 code）
		var mv struct {
			ContinueURL string `json:"continue_url"`
		}
		_ = json.Unmarshal([]byte(body), &mv)
		continueURL = strings.ReplaceAll(mv.ContinueURL, "\\/", "/")
	}

	// 8) 打 callback（NextAuth 换 code → 落 session cookie）
	callbackURL := continueURL
	if callbackURL == "" {
		callbackURL = authorizeURL // 无 2FA 时走原路径重打 authorize
	}
	if err := c.followToCallback(callbackURL); err != nil {
		return nil, fmt.Errorf("callback: %w", err)
	}

	// 9) session → 新 AT
	sessBody, err := c.getString(loginChatBase + "/api/auth/session")
	if err != nil {
		return nil, fmt.Errorf("session: %w", err)
	}
	var sess map[string]any
	if err := json.Unmarshal([]byte(sessBody), &sess); err != nil {
		return nil, fmt.Errorf("session 解析: %w (body=%s)", err, cut(sessBody, 200))
	}
	at, _ := sess["accessToken"].(string)
	if at == "" {
		// 兼容部分版本字段名
		at, _ = sess["access_token"].(string)
	}
	if at == "" {
		return nil, fmt.Errorf("session 无 accessToken (body=%s)", cut(sessBody, 200))
	}
	return &LoginResult{AccessToken: at, SessionToken: c.sessionCookie()}, nil
}

// sessionCookie 从 jar 里取 NextAuth session token（换到的门卡）。
func (c *loginClient) sessionCookie() string {
	jar := c.http.GetCookieJar()
	if jar == nil {
		return ""
	}
	u, err := url.Parse(loginChatBase + "/")
	if err != nil {
		return ""
	}
	for _, name := range []string{"__Secure-next-auth.session-token", "next-auth.session-token"} {
		for _, ck := range jar.Cookies(u) {
			if ck.Name == name && ck.Value != "" {
				return ck.Value
			}
		}
	}
	return ""
}

// ── 底层会话 ─────────────────────────────────────────────────────

type loginClient struct {
	http  tls_client.HttpClient
	refer string
	log   func(string)
}

func (c *loginClient) stdHeaders(method, accept, refer, origin string) fhttp.Header {
	h := fhttp.Header{}
	h.Set("User-Agent", loginUA)
	h.Set("Accept", accept)
	h.Set("Accept-Language", "en-US,en;q=0.9")
	h.Set("Referer", refer)
	if origin != "" {
		h.Set("Origin", origin)
	}
	if method != "GET" {
		h.Set("Sec-Ch-Ua", `"Not_A Brand";v="8", "Chromium";v="131", "Google Chrome";v="131"`)
		h.Set("Sec-Fetch-Site", "same-origin")
	}
	return h
}

func (c *loginClient) getString(url string) (string, error) {
	req, _ := fhttp.NewRequest("GET", url, nil)
	req.Header = c.stdHeaders("GET", "application/json", c.refer, "")
	resp, err := c.http.Do(req)
	if err != nil {
		return "", err
	}
	body, _ := readBody(resp)
	c.refer = url
	if resp.StatusCode != 200 {
		return string(body), fmt.Errorf("HTTP %d body=%s", resp.StatusCode, cut(string(body), 200))
	}
	return string(body), nil
}

func (c *loginClient) formPost(url, form string) (*fhttp.Response, error) {
	req, _ := fhttp.NewRequest("POST", url, strings.NewReader(form))
	h := c.stdHeaders("POST", "application/x-www-form-urlencoded", loginChatBase+"/", loginChatBase)
	h.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header = h
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	_, _ = readBody(resp)
	c.refer = url
	return resp, nil
}

// navFollow 像 SPA 导航一样跟随重定向直到 200 HTML（建立 auth 会话 cookie）。
func (c *loginClient) navFollow(url string) error {
	for i := 0; i < 8; i++ {
		req, _ := fhttp.NewRequest("GET", url, nil)
		req.Header = c.stdHeaders("GET", "text/html,application/xhtml+xml", c.refer, "")
		resp, err := c.http.Do(req)
		if err != nil {
			return err
		}
		_, _ = readBody(resp)
		c.refer = url
		if resp.StatusCode >= 300 && resp.StatusCode < 400 {
			loc := resp.Header.Get("Location")
			if loc == "" {
				return fmt.Errorf("HTTP %d 无 Location", resp.StatusCode)
			}
			url = absURL(loc, url)
			continue
		}
		if resp.StatusCode == 200 {
			return nil
		}
		return fmt.Errorf("HTTP %d (%s)", resp.StatusCode, cut(url, 100))
	}
	return fmt.Errorf("重定向超过 8 跳 (%s)", cut(url, 100))
}

// followToCallback 重新打 authorize，跟随到 chatgpt callback（自动翻成 session cookie）。
func (c *loginClient) followToCallback(authorizeURL string) error {
	for i := 0; i < 8; i++ {
		req, _ := fhttp.NewRequest("GET", authorizeURL, nil)
		req.Header = c.stdHeaders("GET", "text/html,application/xhtml+xml", c.refer, "")
		resp, err := c.http.Do(req)
		if err != nil {
			return err
		}
		_, _ = readBody(resp)
		loc := resp.Header.Get("Location")
		c.refer = authorizeURL
		if loc == "" {
			// 200：NextAuth 可能已落（或已处理完）session cookie，交给后续 /api/auth/session 验证
			return nil
		}
		authorizeURL = absURL(loc, authorizeURL)
		if strings.Contains(authorizeURL, loginChatBase+"/api/auth/callback") {
			// 打 callback（NextAuth 换 code → session cookie），跟随最终 302 到 /
			for j := 0; j < 5; j++ {
				req2, _ := fhttp.NewRequest("GET", authorizeURL, nil)
				req2.Header = c.stdHeaders("GET", "text/html,application/xhtml+xml", loginChatBase+"/", "")
				resp2, err := c.http.Do(req2)
				if err != nil {
					return err
				}
				_, _ = readBody(resp2)
				loc2 := resp2.Header.Get("Location")
				if loc2 == "" {
					return nil // 200 HTML，session 已落
				}
				authorizeURL = absURL(loc2, authorizeURL)
			}
			return nil
		}
	}
	return fmt.Errorf("authorize 重定向未到 callback： %s", cut(authorizeURL, 120))
}

func (c *loginClient) postJSON(url, body string) (string, error) {
	resp, err := c.postJSONRaw(url, body)
	if err != nil {
		return "", err
	}
	respBody, _ := readBody(resp)
	str := string(respBody)
	c.log(cut(url[len(loginAuthBase):], 40) + " -> " + cut(str, 260))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return str, fmt.Errorf("HTTP %d body=%s", resp.StatusCode, cut(str, 300))
	}
	c.refer = url
	// OpenAI auth API 失败常返 200；仅当 error 字段非空才判定失败
	var payload map[string]any
	if err := json.Unmarshal([]byte(str), &payload); err == nil {
		if ev, ok := payload["error"]; ok && ev != nil {
			return str, fmt.Errorf("响应含 error(200): %s", cut(str, 200))
		}
	}
	return str, nil
}

func (c *loginClient) postJSONRaw(url, body string) (*fhttp.Response, error) {
	req, _ := fhttp.NewRequest("POST", url, strings.NewReader(body))
	h := c.stdHeaders("POST", "application/json",
		c.referOr(loginAuthBase+"/log-in"), loginAuthBase)
	h.Set("Content-Type", "application/json")
	// OpenAI auth API（除 signin 外）要求 sentinel token 头（浏览器每次都带）
	if strings.Contains(url, loginAuthBase+"/api/accounts/") {
		gen := antibot.NewSentinelTokenGenerator(uuid.NewString(), loginUA)
		h.Set("openai-sentinel-token", gen.GenerateRequirementsToken())
	}
	req.Header = h
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	return resp, nil
}

func (c *loginClient) referOr(fallback string) string {
	if c.refer == "" {
		return fallback
	}
	return c.refer
}

// ── 工具 ─────────────────────────────────────────────────────────

func absURL(loc, base string) string {
	if strings.HasPrefix(loc, "http://") || strings.HasPrefix(loc, "https://") {
		return loc
	}
	if strings.HasPrefix(loc, "/") {
		if u := strings.Index(base[8:], "/"); u >= 0 {
			return base[:8+u] + loc
		}
		return base + loc
	}
	return loc
}

func readBody(resp *fhttp.Response) (string, error) {
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	_ = resp.Body.Close()
	return string(b), nil
}

func cut(s string, n int) string {
	if len(s) > n {
		return s[:n] + "…"
	}
	return s
}

func mustJSON(s string) string {
	j, err := json.Marshal(s)
	if err != nil {
		return `""`
	}
	return string(j)
}


