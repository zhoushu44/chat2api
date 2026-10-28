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
	// StatusNeedRelogin 需重新登录：access_token 已失效（401/403），
	// 但在完成一次重新登录并再次验活失败之前，不算真死号。
	// 不依赖 refresh_token：本池账号本来就没有 refresh_token，
	// 自动重登应由现有登录链路完成，而不是伪造 OAuth 刷新流程。
	StatusNeedRelogin = "待重登"
	// StatusImageBlocked 可登录但不能出图：/me 验活通过，
	// 实际生图却持续返回文本/额度/工具错误。与 token 失效、真死号分开记录。
	StatusImageBlocked = "生图失效"
)

// IsReloginable 表示账号应先尝试自动重登，而不是直接当死号清除。
// 注意：有没有 refresh_token 不是判据；本池多数账号本来就没有。
func (a *Account) IsReloginable() bool {
	return a != nil && a.Status == StatusNeedRelogin
}

// IsDead 仅表示真死号：已经完成重新登录识别，或账号明确被封/不存在。
// 只有待重登状态本身不能判定死号。
func (a *Account) IsDead() bool {
	if a == nil {
		return false
	}
	return a.Status == StatusDisabled
}

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
	// CooldownUntil 持久化冷却截止（fix10）：仅长冷却（12h 级）写入，重启后恢复调度。
	CooldownUntil   int64             `json:"cooldown_until,omitempty"`
	nextAvailable   int64
	inflight        int32
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
	// onCooldown 长冷却落盘回调（fix10），router 装配为 accountsSvc.Add。
	onCooldown func(a *Account)
}

func NewPool(onRefresh func(a *Account) (string, error), refreshLead time.Duration) *Pool {
	return &Pool{byToken: make(map[string]*Account), onRefresh: onRefresh, refreshLead: refreshLead}
}

// SetOnCooldown 挂载长冷却落盘回调（fix10）。
func (p *Pool) SetOnCooldown(fn func(a *Account)) { p.onCooldown = fn }

func (p *Pool) Add(a *Account) {
	// fix10：装载时恢复持久化冷却（重启不失忆）
	if a.CooldownUntil > 0 {
		now := time.Now().Unix()
		if a.CooldownUntil > now {
			atomic.StoreInt64(&a.nextAvailable, a.CooldownUntil)
		} else {
			a.CooldownUntil = 0 // 过期清除
		}
	}
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
	// fix10：持久化冷却字段随 upsert 合并
	dst.CooldownUntil = src.CooldownUntil
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

// Cooldown 账号冷却。fix10：长冷却（>5min）同步落盘，重启后由 Add 恢复。
func (p *Pool) Cooldown(a *Account, until time.Time) {
	ts := until.Unix()
	// CAS 取 max：短冷却不缩短既有长冷却
	for {
		cur := atomic.LoadInt64(&a.nextAvailable)
		if cur >= ts {
			return
		}
		if atomic.CompareAndSwapInt64(&a.nextAvailable, cur, ts) {
			break
		}
	}
	// 仅长冷却落盘，避免 30s 级短冷却高频写 accounts.json
	if ts <= time.Now().Add(5*time.Minute).Unix() {
		return
	}
	a.CooldownUntil = ts
	if cb := p.onCooldown; cb != nil {
		cb(a) // svc.Add 独立锁，安全
	}
}
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
