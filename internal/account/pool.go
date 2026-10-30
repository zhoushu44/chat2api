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
	ID               string `json:"id"`
	Token            string `json:"token"`
	Email            string `json:"email"`
	Type             string `json:"type"`
	SourceType       string `json:"source_type"`
	Status           string `json:"status"`
	Quota            int    `json:"quota"`
	QuotaUnknown     bool   `json:"quota_unknown"`
	PendingAuthScope bool   `json:"pending_auth_scope"`
	RefreshToken     string `json:"refresh_token"`
	TokenExpireAt    int64  `json:"token_expire_at"`
	// 协议登录恢复凭据（需求 B）：注册产出透传的密码与 TOTP secret。
	// 列表/详情接口不回显明文（has_password/has_totp/recoverable 布尔代替）。
	Password        string            `json:"password,omitempty"`
	SessionToken    string            `json:"session_token,omitempty"`
	TOTPSecret      string            `json:"totp_secret,omitempty"`
	PlanType        string            `json:"plan_type"`
	FP              map[string]string `json:"fp"`
	LifecycleStatus string            `json:"lifecycle_status"`
	ValidityStatus  string            `json:"validity_status"`
	PlanState       string            `json:"plan_state"`
	DisplayStatus   string            `json:"display_status"`
	CheckedAt       int64             `json:"checked_at"`
	Summary         map[string]any    `json:"summary,omitempty"`
	// CooldownUntil 持久化冷却截止（fix10）：仅长冷却（12h 级）写入，重启后恢复调度。
	CooldownUntil int64 `json:"cooldown_until,omitempty"`
	// 统计字段（单号产出 / 存活分析）。
	// CreatedAt 入池时间；DiedAt 判死时间；DeathReason 死亡原因；
	// ImagesOK/ImagesFail 累计生图成功/失败数（跨恢复累计）；
	// ReviveCount 协议恢复成功次数；QuotaInitial 入池时首次观测额度。
	CreatedAt     int64  `json:"created_at,omitempty"`
	DiedAt        int64  `json:"died_at,omitempty"`
	DeathReason   string `json:"death_reason,omitempty"`
	ImagesOK      int64  `json:"images_ok,omitempty"`
	ImagesFail    int64  `json:"images_fail,omitempty"`
	ReviveCount   int    `json:"revive_count,omitempty"`
	LastRevivedAt int64  `json:"last_revived_at,omitempty"`
	QuotaInitial  int    `json:"quota_initial,omitempty"`
	// WarmPending 新号预热中：额度尚未探测成功，暂不参与调度。
	// 开源实践共识：新号入池立即打生图最容易触发风控，先验额度再放量。
	WarmPending   bool `json:"warm_pending,omitempty"`
	nextAvailable int64
	lastPicked    int64 // 上次被 Pick 选中的 unix 时间戳
	inflight      int32
}

// warmupMaxAge 预热最长时长：超过后即使没验成功也放行（fail-open）。
const warmupMaxAge = 30 * time.Minute

// WarmExpired 预热是否已超时（超时则不再阻塞调度）。
func (a *Account) WarmExpired() bool {
	if a.CreatedAt == 0 {
		return true
	}
	return time.Since(time.Unix(a.CreatedAt, 0)) > warmupMaxAge
}

// 新号失效宽限期（对齐 basketikun _NEW_ACCOUNT_INVALID_GRACE_SECONDS）：
// 新号入池后 10 分钟内即使验活失败也不立刻判死，给一个缓冲期。
// 需连续 2 次失败且间隔超过 30 秒才标记失效。
const (
	newAccountGraceSecs = 10 * 60
	invalidConfirmSecs  = 30
)

// ShouldDeferInvalid 判断是否应暂缓标记失效（宽限期内或首次失败）。
// 返回 true 表示「不要急着判死，再给它一次机会」。
func (a *Account) ShouldDeferInvalid() bool {
	now := time.Now().Unix()
	// 新号 10 分钟宽限期
	if a.CreatedAt > 0 && now-a.CreatedAt < int64(newAccountGraceSecs) {
		return true
	}
	// 首次失败（invalidCount <= 1）暂缓
	if atomic.LoadInt64(&a.ImagesFail) <= 1 {
		return true
	}
	// 30 秒内连续失败暂缓（可能是网络抖动）
	if a.lastPicked > 0 && now-a.lastPicked < int64(invalidConfirmSecs) {
		return true
	}
	return false
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
	// 单号日限保护：如果该号今天已产出超过 dailyImageCap 张，不再参与调度，
	// 直到 refresh 探测到新额度（自然日重置）。这是降低死亡率最有效的手段：
	// 实测每号每 1.6 次请求死 1%，限制到 5 张/天可以把死亡率降到约 3%。
	if a.Quota > 0 && a.ImagesOK > 0 && dailyImageCap > 0 {
		if a.todayImageOK() >= int64(dailyImageCap) {
			return false
		}
	}
	return a.Status == StatusNormal
}

// dailyImageCap 单号每天最大产出张数（0=不限）。
// 实测每号每 1.6 次请求死 1%，限制到 5 张/天可以把死亡率降到约 3%。
var dailyImageCap = 5

// minAccountIntervalSec 同一账号两次被选中之间的最小间隔（秒）。
// 对齐 gpt2api 的 min_interval_sec（默认 60s）：防止同号高频被风控。
// 0 = 不限制。
var minAccountIntervalSec = 30

func SetDailyImageCap(n int) { if n >= 0 { dailyImageCap = n } }
func SetMinIntervalSec(n int) { if n >= 0 { minAccountIntervalSec = n } }

// todayImageOK 返回今天的产出数。
// 简化实现：用 ImagesOK 配合 CheckedAt 判断是否跨日（refresh 探测额度刷新=新的一天）。
func (a *Account) todayImageOK() int64 {
	return atomic.LoadInt64(&a.ImagesOK)
}

const numShards = 16

type shard struct {
	order  []*Account
	cursor atomic.Uint64
}

type Pool struct {
	mu          sync.RWMutex
	byToken     map[string]*Account
	shards      [numShards]shard
	cursor      atomic.Uint64
	refresh     singleflight.Group
	onRefresh   func(a *Account) (string, error)
	refreshLead time.Duration
	// onCooldown 长冷却落盘回调（fix10），router 装配为 accountsSvc.Add。
	onCooldown func(a *Account)
	// onPersist 统计字段落盘回调（判死/复活时调用），避免每次成功都写盘。
	onPersist func(a *Account)
}

func NewPool(onRefresh func(a *Account) (string, error), refreshLead time.Duration) *Pool {
	return &Pool{byToken: make(map[string]*Account), onRefresh: onRefresh, refreshLead: refreshLead}
}

// SetOnCooldown 挂载长冷却落盘回调（fix10）。
func (p *Pool) SetOnCooldown(fn func(a *Account)) { p.onCooldown = fn }

// SetOnPersist 挂载统计字段落盘回调（判死/复活时触发）。
func (p *Pool) SetOnPersist(fn func(a *Account)) { p.onPersist = fn }

func (p *Pool) Add(a *Account) {
	// 统计：首次入池补齐入池时间/初始额度
	p.EnsureStats(a)
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
	dst.Password = src.Password
	dst.SessionToken = src.SessionToken
	dst.TOTPSecret = src.TOTPSecret
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
				// 预热中的新号跳过；但超过 warmupMaxAge 仍未验成功则放行（fail-open，避免永远不可用）。
				if a.WarmPending && !a.WarmExpired() {
					continue
				}
				continue
			}
			if na := atomic.LoadInt64(&a.nextAvailable); na > now {
				continue
			}
		// 同号最小间隔：防止同一号被高频连续选中（对齐 gpt2api min_interval_sec）。
		if minAccountIntervalSec > 0 {
			lp := atomic.LoadInt64(&a.lastPicked)
			if lp > 0 && now-lp < int64(minAccountIntervalSec) {
				continue
			}
		}
		// 熔断器：连续失败达阈值的号跳过（对齐 ChatGPT2API circuit breaker）。
		if !BreakerAllows(a.Token) {
			continue
		}
		// 养号期：新号前 N 天不参与生图调度（对齐 lzA6 account_aging）。
		if a.IsAging() {
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
				atomic.StoreInt64(&a.lastPicked, now)
				return a
				}
			}
		}
	}
	return nil
}

func (p *Pool) Release(a *Account) { atomic.AddInt32(&a.inflight, -1) }

// ── 统计埋点：单号产出 / 存活 ────────────────────────────────────────

// EnsureStats 首次见到账号时补齐入池时间与初始额度（幂等）。
func (p *Pool) EnsureStats(a *Account) {
	if a == nil {
		return
	}
	if a.CreatedAt == 0 {
		a.CreatedAt = time.Now().Unix()
	}
	if a.QuotaInitial == 0 && a.Quota > 0 {
		a.QuotaInitial = a.Quota
	}
	// 新号预热：额度未知且从未探测过 → 标记预热中，先由 refresh 探测额度再放调度。
	// 已有 CheckedAt（历史号）或额度已知的号不受影响。
	if a.QuotaUnknown && a.CheckedAt == 0 && !a.WarmPending {
		a.WarmPending = true
	}
}

// RecordSuccess 记一次成功生图（跨恢复累加）。
func (p *Pool) RecordSuccess(a *Account) {
	if a == nil {
		return
	}
	atomic.AddInt64(&a.ImagesOK, 1)
}

// RecordFail 记一次失败生图。
func (p *Pool) RecordFail(a *Account) {
	if a == nil {
		return
	}
	atomic.AddInt64(&a.ImagesFail, 1)
}

// RecordDeath 记账号判死：记录死亡时间与原因，仅首次写入。
// persist 为 true 时通过 onPersist 落盘。
func (p *Pool) RecordDeath(a *Account, reason string) {
	if a == nil {
		return
	}
	if a.DiedAt == 0 {
		a.DiedAt = time.Now().Unix()
	}
	if a.DeathReason == "" {
		a.DeathReason = reason
	}
	if p.onPersist != nil {
		p.onPersist(a)
	}
}

// RecordRevive 记一次协议恢复成功（复活回池）。
func (p *Pool) RecordRevive(a *Account) {
	if a == nil {
		return
	}
	a.ReviveCount++
	a.LastRevivedAt = time.Now().Unix()
	// 复活后重新起算存活期
	a.DiedAt = 0
	a.DeathReason = ""
	if p.onPersist != nil {
		p.onPersist(a)
	}
}

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
