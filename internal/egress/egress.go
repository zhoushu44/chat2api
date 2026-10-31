// Package egress 为每个账号分配固定出口 IP。
//
// 背景：所有账号共用一个出口时，OpenAI 会对该 IP 限流（429），
// 高并发下大量请求失败，账号被误判。改为「按账号固定一个 warp 粘性会话」，
// 把负载分散到多个出口 IP。
//
// 实现：warp 池 API 通过 sid 参数实现粘性会话——同一个 sid 复用同一个出口。
// 因此用「账号 ID 哈希」生成稳定 sid，即可让同一账号始终走同一出口。
package egress

import (
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

// Service 账号出口分配器。
type Service struct {
	mu      sync.RWMutex
	enabled bool
	poolURL string
	apiKey  string
	ttl     time.Duration
	client  *http.Client

	cache sync.Map // sid -> *entry
}

type entry struct {
	proxy string
	exp   time.Time
}

// New 创建出口分配服务。poolURL 形如：
//
//	http://172.17.0.1:4433/api/proxies?num=1&type=json&format=n&sid={sid}&time=20
//
// 其中 {sid} 会被替换为账号稳定会话 ID；若不含 {sid} 则自动追加。
func New(poolURL, apiKey string) *Service {
	return &Service{
		poolURL: strings.TrimSpace(poolURL),
		apiKey:  strings.TrimSpace(apiKey),
		ttl:     5 * time.Minute,
		client:  &http.Client{Timeout: 12 * time.Second},
	}
}

// SetEnabled 运行时开关（设置页热更）。
func (s *Service) SetEnabled(v bool) {
	if s == nil {
		return
	}
	s.mu.Lock()
	s.enabled = v
	s.mu.Unlock()
}

// Enabled 当前是否启用。
func (s *Service) Enabled() bool {
	if s == nil {
		return false
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.enabled
}

// Configured 是否具备可用配置（URL 非空）。
func (s *Service) Configured() bool {
	if s == nil {
		return false
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.poolURL != ""
}

// SidFor 账号 → 稳定会话 ID（同一账号永远同一个 sid，从而同一个出口）。
func SidFor(accountID string) string {
	sum := sha1.Sum([]byte("chat2api-egress:" + accountID))
	return "acct" + hex.EncodeToString(sum[:6])
}

// ProxyFor 返回该账号应使用的代理地址；返回空串表示沿用全局代理。
// 容量保护：如果池子可用代理不足，回落到全局代理而不是卡死。
func (s *Service) ProxyFor(accountID string) string {
	if s == nil || accountID == "" {
		return ""
	}
	if !s.Enabled() || !s.Configured() {
		return ""
	}
	sid := SidFor(accountID)
	if v, ok := s.cache.Load(sid); ok {
		e := v.(*entry)
		if time.Now().Before(e.exp) {
			return e.proxy
		}
	}
	proxy, err := s.fetch(sid)
	if err != nil || proxy == "" {
		// 取不到就退回全局代理，不阻断主流程
		return ""
	}
	// 缩短 TTL：5 分钟而非 30 分钟，让代理更快回收给其他账号用
	s.cache.Store(sid, &entry{proxy: proxy, exp: time.Now().Add(5 * time.Minute)})
	return proxy
}

func (s *Service) fetch(sid string) (string, error) {
	target := s.poolURL
	if strings.Contains(target, "{sid}") {
		target = strings.ReplaceAll(target, "{sid}", sid)
	} else {
		sep := "?"
		if strings.Contains(target, "?") {
			sep = "&"
		}
		target = fmt.Sprintf("%s%ssid=%s&type=json", target, sep, url.QueryEscape(sid))
	}

	req, err := http.NewRequest(http.MethodGet, target, nil)
	if err != nil {
		return "", err
	}
	if s.apiKey != "" {
		if strings.HasPrefix(strings.ToLower(s.apiKey), "bearer ") {
			req.Header.Set("Authorization", s.apiKey)
		} else {
			req.Header.Set("X-API-Key", s.apiKey)
		}
	}
	resp, err := s.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("egress pool status %d", resp.StatusCode)
	}
	var payload struct {
		Code string `json:"code"`
		Data struct {
			Proxies []struct {
				Proxy          string `json:"proxy"`
				ProxyWhitelist string `json:"proxy_whitelist"`
				ExpiresAt      string `json:"expires_at"`
			} `json:"proxies"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return "", err
	}
	if len(payload.Data.Proxies) == 0 {
		return "", fmt.Errorf("egress pool returned no proxy")
	}
	p := payload.Data.Proxies[0]
	out := p.Proxy
	if out == "" {
		out = p.ProxyWhitelist
	}
	return out, nil
}

// Reset 清空缓存（切换开关或换池时调用）。
func (s *Service) Reset() {
	if s == nil {
		return
	}
	s.cache = sync.Map{}
}

// Release 释放账号占用的 warp 池会话（避免 in_use 泄漏）。
// warp 池的 /api/proxies 是「获取=占用」，需要调 /api/pool/release 释放。
// 请求完成后调用，best-effort 不阻断主流程。
func (s *Service) Release(accountID string) {
	if s == nil || accountID == "" {
		return
	}
	if !s.Enabled() || !s.Configured() {
		return
	}
	sid := SidFor(accountID)
	// 从缓存中删除（下次取会重新获取）
	s.cache.Delete(sid)
	// 异步通知 warp 池释放
	go s.callRelease(sid)
}

func (s *Service) callRelease(sid string) {
	// warp 池的 /api/pool/release 需要 POST body {"session_id":"xxx"}
	target := strings.Replace(s.poolURL, "/api/proxies", "/api/pool/release", 1)
	// 清理 query params，只保留基础 URL
	if idx := strings.Index(target, "?"); idx > 0 {
		target = target[:idx]
	}
	body := fmt.Sprintf(`{"session_id":"%s"}`, sid)
	req, err := http.NewRequest(http.MethodPost, target, strings.NewReader(body))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if s.apiKey != "" {
		if strings.HasPrefix(strings.ToLower(s.apiKey), "bearer ") {
			req.Header.Set("Authorization", s.apiKey)
		} else {
			req.Header.Set("X-API-Key", s.apiKey)
		}
	}
	resp, err := s.client.Do(req)
	if err != nil {
		return
	}
	resp.Body.Close()
}
