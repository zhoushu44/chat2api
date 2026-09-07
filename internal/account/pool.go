// Package account 号池管理。
package account

import (
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/sync/singleflight"
)

const (
	StatusNormal   = "正常"
	StatusLimited  = "限流"
	StatusDisabled = "失效"
)

type Account struct {
	ID               string            `json:"id"`
	Token            string            `json:"token"`
	Email            string            `json:"email"`
	Type             string            `json:"type"`
	SourceType       string            `json:"source_type"`
	Status           string            `json:"status"`
	Quota            int               `json:"quota"`
	QuotaUnknown     bool              `json:"quota_unknown"`
	PendingAuthScope bool              `json:"pending_auth_scope"`
	RefreshToken     string            `json:"refresh_token"`
	TokenExpireAt    int64             `json:"token_expire_at"`
	PlanType         string            `json:"plan_type"`
	FP               map[string]string `json:"fp"`
	LifecycleStatus string            `json:"lifecycle_status"`
	ValidityStatus  string            `json:"validity_status"`
	PlanState       string            `json:"plan_state"`
	DisplayStatus   string            `json:"display_status"`
	CheckedAt       int64             `json:"checked_at"`
	Summary         map[string]any    `json:"summary,omitempty"`
	nextAvailable int64
	inflight      int32
}

func (a *Account) Available() bool {
	if a.Status == StatusLimited || a.Status == StatusDisabled {
		return false
	}
	if a.PendingAuthScope {
		return false
	}
	if a.QuotaUnknown {
		return true
	}
	if a.Quota < 0 {
		return true
	}
	return a.Status == StatusNormal
}

const numShards = 16

type shard struct {
	order  []*Account
	cursor atomic.Uint64
}

type Pool struct {
	mu      sync.RWMutex
	byToken map[string]*Account
	shards  [numShards]shard
	cursor  atomic.Uint64
	refresh     singleflight.Group
	onRefresh   func(a *Account) (string, error)
	refreshLead time.Duration
}

func NewPool(onRefresh func(a *Account) (string, error), refreshLead time.Duration) *Pool {
	return &Pool{byToken: make(map[string]*Account), onRefresh: onRefresh, refreshLead: refreshLead}
}

func (p *Pool) Add(a *Account) {
	p.mu.Lock()
	defer p.mu.Unlock()
	// 同 ID 换 token：先清旧 token 条目（对等账号更新语义）
	for tok, old := range p.byToken {
		if tok != a.Token && old.ID != "" && old.ID == a.ID {
			delete(p.byToken, tok)
			p.removeFromShardsLocked(tok)
			break
		}
	}
	if old, ok := p.byToken[a.Token]; ok {
		// upsert：同 token 合并可变字段（原子计数保留）
		mergeAccountLocked(old, a)
		return
	}
	p.byToken[a.Token] = a
	idx := len(p.byToken) % numShards
	p.shards[idx].order = append(p.shards[idx].order, a)
}

// mergeAccountLocked 合并账号字段（inflight/nextAvailable 原子状态保留）。
func mergeAccountLocked(dst, src *Account) {
	dst.ID = src.ID
	dst.Token = src.Token
	dst.Email = src.Email
	dst.Type = src.Type
	dst.SourceType = src.SourceType
	dst.Status = src.Status
	dst.Quota = src.Quota
	dst.QuotaUnknown = src.QuotaUnknown
	dst.PendingAuthScope = src.PendingAuthScope
	dst.RefreshToken = src.RefreshToken
	dst.TokenExpireAt = src.TokenExpireAt
	dst.PlanType = src.PlanType
	dst.FP = src.FP
	dst.LifecycleStatus = src.LifecycleStatus
	dst.ValidityStatus = src.ValidityStatus
	dst.PlanState = src.PlanState
	dst.DisplayStatus = src.DisplayStatus
	dst.CheckedAt = src.CheckedAt
	dst.Summary = src.Summary
}

// List 快照（读锁）。
func (p *Pool) List() []*Account {
	p.mu.RLock()
	defer p.mu.RUnlock()
	out := make([]*Account, 0, len(p.byToken))
	for _, a := range p.byToken {
		out = append(out, a)
	}
	return out
}

// Remove 按 token 移除（管理删除/禁用同步）。
func (p *Pool) Remove(token string) bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	if _, ok := p.byToken[token]; !ok {
		return false
	}
	delete(p.byToken, token)
	p.removeFromShardsLocked(token)
	return true
}

func (p *Pool) removeFromShardsLocked(token string) {
	for i := range p.shards {
		ord := p.shards[i].order
		kept := ord[:0]
		for _, a := range ord {
			if a.Token != token {
				kept = append(kept, a)
			}
		}
		// 清尾部避免泄漏
		for j := len(kept); j < len(ord); j++ {
			ord[j] = nil
		}
		p.shards[i].order = kept
	}
}

// RenewExpiring 扫描并刷新临期 token（加锁读 token 前后对比，返回实际更新的账号）。
func (p *Pool) RenewExpiring() []*Account {
	p.mu.RLock()
	accs := make([]*Account, 0, len(p.byToken))
	for _, a := range p.byToken {
		accs = append(accs, a)
	}
	p.mu.RUnlock()
	var renewed []*Account
	for _, a := range accs {
		p.mu.RLock()
		before := a.Token
		p.mu.RUnlock()
		if err := p.EnsureFreshToken(a); err != nil {
			continue
		}
		p.mu.RLock()
		after := a.Token
		p.mu.RUnlock()
		if after != before && after != "" {
			renewed = append(renewed, a)
		}
	}
	return renewed
}

type Selector struct {
	PlanTypes   []string
	SourceType  string
	Excluded    map[string]bool
	MaxInflight int
}

func (p *Pool) Pick(sel Selector) *Account {
	p.mu.RLock()
	total := len(p.byToken)
	p.mu.RUnlock()
	if total == 0 {
		return nil
	}
	global := p.cursor.Add(1)
	for s := 0; s < numShards; s++ {
		shardIdx := (int(global) + s) % numShards
		sh := &p.shards[shardIdx]
		n := len(sh.order)
		if n == 0 {
			continue
		}
		start := sh.cursor.Add(1)
		now := time.Now().Unix()
		for i := 0; i < n; i++ {
			a := sh.order[(start+uint64(i))%uint64(n)]
			if sel.Excluded[a.Token] {
				continue
			}
			if !matchPlan(a, sel.PlanTypes) || !matchSource(a, sel.SourceType) {
				continue
			}
			if !a.Available() {
				continue
			}
			if na := atomic.LoadInt64(&a.nextAvailable); na > now {
				continue
			}
			max := sel.MaxInflight
			if max <= 0 {
				max = 1
			}
			for {
				cur := atomic.LoadInt32(&a.inflight)
				if cur >= int32(max) {
					break
				}
				if atomic.CompareAndSwapInt32(&a.inflight, cur, cur+1) {
					return a
				}
			}
		}
	}
	return nil
}

func (p *Pool) Release(a *Account) { atomic.AddInt32(&a.inflight, -1) }
func (p *Pool) Cooldown(a *Account, until time.Time) { atomic.StoreInt64(&a.nextAvailable, until.Unix()) }
func (p *Pool) EnsureFreshToken(a *Account) error {
	if a.TokenExpireAt == 0 || time.Now().Add(p.refreshLead).Unix() < a.TokenExpireAt {
		return nil
	}
	if p.onRefresh == nil {
		return nil
	}
	_, err, _ := p.refresh.Do(a.Token, func() (any, error) {
		newToken, err := p.onRefresh(a)
		if err != nil {
			return "", err
		}
		if newToken != "" {
			p.mu.Lock()
			oldToken := a.Token
			a.Token = newToken
			// token 变更后重建索引键（否则 Remove/去重失效）
			if oldToken != newToken {
				delete(p.byToken, oldToken)
				p.byToken[newToken] = a
				// shards 内指针相同，无需移动
			}
			p.mu.Unlock()
		}
		return newToken, nil
	})
	return err
}
func matchPlan(a *Account, plans []string) bool {
	if len(plans) == 0 {
		return true
	}
	for _, p := range plans {
		if normalizePlan(p) != "" && normalizePlan(p) == normalizePlan(a.Type) {
			return true
		}
	}
	return false
}
func matchSource(a *Account, source string) bool {
	if source == "" {
		return true
	}
	return normalizeSource(a.SourceType) == normalizeSource(source)
}
func normalizePlan(v string) string {
	compact := ""
	for _, r := range v {
		if r != '-' && r != '_' && r != ' ' {
			compact += string(r)
		}
	}
	aliases := map[string]string{"free": "free", "plus": "Plus", "pro": "Pro", "prolite": "ProLite", "team": "Team", "business": "Team", "enterprise": "Enterprise"}
	if s, ok := aliases[compact]; ok {
		return s
	}
	return compact
}
func normalizeSource(v string) string {
	switch v {
	case "codex", "cpa", "cpa_json", "remote_cpa", "sub2api":
		return "codex"
	default:
		return "web"
	}
}
func (a *Account) MarkChecked(valid bool, planState string, summary map[string]any) {
	a.CheckedAt = time.Now().Unix()
	if valid {
		a.ValidityStatus = "valid"
	} else {
		a.ValidityStatus = "invalid"
	}
	if planState != "" {
		a.PlanState = planState
	}
	if summary != nil {
		if a.Summary == nil {
			a.Summary = map[string]any{}
		}
		for k, v := range summary {
			a.Summary[k] = v
		}
	}
}
func (a *Account) IsExpired() bool { return a.LifecycleStatus == "expired" || a.PlanState == "expired" }
