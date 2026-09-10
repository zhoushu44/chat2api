package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"golang.org/x/net/proxy"
)

type testResult struct {
	OK      bool   `json:"ok"`
	Message string `json:"message"`
	Detail  any    `json:"detail,omitempty"`
}

// testProxyWarp 测代理连通：经代理 GET 公网测出口 IP + 延迟（支持 http/socks5）
func testProxyWarp(cfg map[string]any) testResult {
	raw, _ := cfg["url"].(string)
	if raw == "" {
		return testResult{OK: false, Message: "url 为空"}
	}
	u, err := url.Parse(raw)
	if err != nil {
		return testResult{OK: false, Message: "url 解析失败: " + err.Error()}
	}
	client := &http.Client{Timeout: 10 * time.Second}
	switch u.Scheme {
	case "http", "https":
		client.Transport = &http.Transport{Proxy: http.ProxyURL(u)}
	case "socks5":
		dialer, err := proxy.FromURL(u, proxy.Direct)
		if err != nil {
			return testResult{OK: false, Message: "socks5 dialer 失败: " + err.Error()}
		}
		client.Transport = &http.Transport{DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
			return dialer.Dial(network, addr)
		}}
	default:
		return testResult{OK: false, Message: "不支持的 scheme: " + u.Scheme + "（支持 http/socks5）"}
	}
	start := time.Now()
	resp, err := client.Get("https://api.ipify.org/?format=json")
	latency := time.Since(start).Milliseconds()
	if err != nil {
		return testResult{OK: false, Message: "代理请求失败: " + err.Error()}
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
	var out map[string]any
	_ = json.Unmarshal(body, &out)
	ip, _ := out["ip"].(string)
	return testResult{OK: resp.StatusCode == 200, Message: "连通", Detail: map[string]any{"exit_ip": ip, "latency_ms": latency, "status": resp.StatusCode}}
}

// testMailboxMailnest 测迈巢邮箱：用 url+api_key 调 API 验证 key
func testMailboxMailnest(cfg map[string]any) testResult {
	base, _ := cfg["url"].(string)
	apiKey, _ := cfg["api_key"].(string)
	if base == "" || apiKey == "" {
		return testResult{OK: false, Message: "url 或 api_key 为空"}
	}
	base = strings.TrimRight(base, "/")
	client := &http.Client{Timeout: 10 * time.Second}
	req, err := http.NewRequest(http.MethodGet, base+"/health", nil)
	if err != nil {
		return testResult{OK: false, Message: "请求构造失败: " + err.Error()}
	}
	req.Header.Set("Authorization", "Bearer "+apiKey)
	req.Header.Set("X-API-Key", apiKey)
	start := time.Now()
	resp, err := client.Do(req)
	latency := time.Since(start).Milliseconds()
	if err != nil {
		return testResult{OK: false, Message: "请求失败: " + err.Error()}
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
	return testResult{OK: resp.StatusCode < 500, Message: fmt.Sprintf("HTTP %d", resp.StatusCode), Detail: map[string]any{"latency_ms": latency, "status": resp.StatusCode, "body_preview": string(body)}}
}
