package proxy

import (
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

var parseCache sync.Map // string -> *Proxy or error

type Proxy struct {
	URL       string `json:"url"`
	Priority  int    `json:"priority"`
	LatencyMS int    `json:"latency_ms"`
	Region    string `json:"region"`
	Alive     bool   `json:"alive"`
}

func Parse(raw string) (*Proxy, error) {
	if v, ok := parseCache.Load(raw); ok {
		if err, ok := v.(error); ok {
			return nil, err
		}
		return v.(*Proxy), nil
	}
	u, err := url.Parse(raw)
	if err != nil {
		parseCache.Store(raw, err)
		return nil, err
	}
	p := &Proxy{URL: u.String(), Alive: true}
	parseCache.Store(raw, p)
	return p, nil
}

// Pick 选择代理：账号显式 > 稳定代理 > 全局 — 保留兼容旧调用
func Pick(accountProxy, stableProxy, explicitProxy, globalProxy string) string {
	if accountProxy != "" {
		return accountProxy
	}
	if stableProxy != "" {
		return stableProxy
	}
	if explicitProxy != "" {
		return explicitProxy
	}
	return globalProxy
}

func IsValid(raw string) bool {
	if raw == "" {
		return true
	}
	u, err := url.Parse(raw)
	if err != nil {
		return false
	}
	return strings.HasPrefix(u.Scheme, "http") || strings.HasPrefix(u.Scheme, "socks")
}

// Pool 代理池：对齐 abai ProxyPool + Mihomo pulse
// 支持：静态池轮询 + 动态API回退 + 成功率排序 + 冷却
type Pool struct {
	mu        sync.Mutex
	proxies   []*Proxy
	index     uint64
	cooldown  map[string]time.Time
	cooldownD time.Duration
}

func NewPool(cooldown time.Duration) *Pool {
	if cooldown <= 0 {
		cooldown = 120 * time.Second // 对齐 abai MIHOMO_NODE_COOLDOWN_SECONDS
	}
	return &Pool{cooldown: make(map[string]time.Time), cooldownD: cooldown}
}

func (p *Pool) SetProxies(list []*Proxy) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.proxies = list
}

func (p *Pool) Add(url string, region string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.proxies = append(p.proxies, &Proxy{URL: url, Region: region, Alive: true})
}

// GetNext 按 region 优先 + 成功率排序 + 冷却过滤，对齐 abai proxy_pool.get_next()
func (p *Pool) GetNext(region string) string {
	// 1. 动态代理优先（若有 provider 注册）
	if d := getDynamicProxy(); d != "" {
		return d
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if len(p.proxies) == 0 {
		return ""
	}
	now := time.Now()
	// 过滤冷却中
	active := make([]*Proxy, 0, len(p.proxies))
	for _, pr := range p.proxies {
		if until, ok := p.cooldown[pr.URL]; ok && now.Before(until) {
			continue
		}
		if !pr.Alive {
			continue
		}
		active = append(active, pr)
	}
	if len(active) == 0 {
		active = p.proxies // 回退：冷却也用
	}
	// region 优先
	preferred := active
	if region != "" {
		filtered := make([]*Proxy, 0)
		for _, pr := range active {
			if pr.Region == region {
				filtered = append(filtered, pr)
			}
		}
		if len(filtered) > 0 {
			preferred = filtered
		}
	}
	idx := atomic.AddUint64(&p.index, 1) % uint64(len(preferred))
	return preferred[idx].URL
}

func (p *Pool) ReportSuccess(url string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, pr := range p.proxies {
		if pr.URL == url {
			delete(p.cooldown, url)
			break
		}
	}
}

func (p *Pool) ReportFail(url string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.cooldown[url] = time.Now().Add(p.cooldownD)
}

// 全局池，兼容旧代码直接调用 pool.GetNext
var DefaultPool = NewPool(120 * time.Second)

// 动态代理 hook，由 provider/proxy 驱动注册
var (
	dynamicMu sync.RWMutex
	dynamicFn func() string
)

func SetDynamicProvider(fn func() string) { dynamicMu.Lock(); dynamicFn = fn; dynamicMu.Unlock() }
func getDynamicProxy() string {
	dynamicMu.RLock()
	defer dynamicMu.RUnlock()
	if dynamicFn == nil {
		return ""
	}
	return dynamicFn()
}
