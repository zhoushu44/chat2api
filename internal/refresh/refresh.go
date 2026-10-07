// Package refresh 账号额度刷新服务（对等 Python refresh_accounts）。
//
// 语义：并发对每个账号探测远程图片额度（POST /backend-api/conversation/init），
// 成功则回写 Account.Quota（号池 + 持久化），失败记入 errors 不阻断整批。
// 进度可轮询：POST /api/accounts/refresh 返回 progress_id，
// GET /api/accounts/refresh/progress/:id 查询（前端 refreshAndPoll 契约）。
package refresh

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/backend"
	"github.com/google/uuid"
)

// Probe 单号探测函数（生产环境为 backend.FetchAccountQuota；测试注入 mock）。
// 返回 (quota, planType, err)；err 非 nil 表示探测失败（401/网络）。
type Probe func(ctx context.Context, acc *account.Account) (backend.AccountQuota, error)

// Service 刷新服务：进度注册表 + 并发执行。
type Service struct {
	Accounts *account.Service
	Pool     *account.Pool
	Probe    Probe // 可注入；nil 时用真实 backend 探测
	Proxy    string
	// Concurrency 并发上限（<=0 时默认 8）。
	Concurrency int

	mu        sync.Mutex
	progresses map[string]*Progress
}

// Progress 一次刷新任务的进度快照（前端 AccountRefreshProgress 契约）。
type Progress struct {
	ID            string    `json:"-"`
	Total         int       `json:"total"`
	Processed     int       `json:"processed"`
	Done          bool      `json:"done"`
	Error         string    `json:"error,omitempty"`
	StatusCounts  map[string]int `json:"status_counts,omitempty"`
	TotalQuota    int       `json:"total_quota,omitempty"`
	Refreshed     int       `json:"refreshed"`
	Errors        []map[string]any `json:"errors,omitempty"`
	Items         []map[string]any `json:"items,omitempty"`
	StartedAt     time.Time `json:"-"`
}

// NewService 创建刷新服务。
func NewService(accounts *account.Service, pool *account.Pool, proxy string) *Service {
	return &Service{
		Accounts:  accounts,
		Pool:      pool,
		Proxy:     proxy,
		progresses: make(map[string]*Progress),
	}
}

// progressEntry 内部可变进度（含锁）。
type progressEntry struct {
	mu sync.Mutex
	p  *Progress
}

var (
	regMu   sync.Mutex
	registry = make(map[string]*progressEntry)
)

// RefreshAll 刷新全部账号；返回 progress_id 供轮询。
// all=true 或 tokens 为空时刷新号池全部；否则只刷指定 token。
func (s *Service) RefreshAll(ctx context.Context, tokens []string) (string, error) {
	if s.Accounts == nil && s.Pool == nil {
		return "", fmt.Errorf("no account store configured")
	}
	// 目标账号：优先精确 token 匹配，否则全量
	var targets []*account.Account
	seen := make(map[string]bool)
	if len(tokens) > 0 {
		want := make(map[string]bool, len(tokens))
		for _, t := range tokens {
			want[t] = true
		}
		for _, a := range s.listAll() {
			if want[a.Token] && !seen[a.Token] {
				targets = append(targets, a)
				seen[a.Token] = true
			}
		}
	} else {
		for _, a := range s.listAll() {
			if !seen[a.Token] {
				targets = append(targets, a)
				seen[a.Token] = true
			}
		}
	}

	id := uuid.NewString()[:8]
	entry := &progressEntry{p: &Progress{
		ID:        id,
		Total:     len(targets),
		StartedAt: time.Now(),
		StatusCounts: map[string]int{},
	}}
	regMu.Lock()
	registry[id] = entry
	// 进度注册表防泄漏：超过 100 条时清理已完成且超过 1 小时的
	if len(registry) > 100 {
		for k, v := range registry {
			v.mu.Lock()
			done := v.p.Done
			old := time.Since(v.p.StartedAt) > time.Hour
			v.mu.Unlock()
			if done && old {
				delete(registry, k)
			}
		}
	}
	regMu.Unlock()

	if len(targets) == 0 {
		entry.mu.Lock()
		entry.p.Done = true
		entry.mu.Unlock()
		return id, nil
	}

	go s.run(ctx, entry, targets)
	return id, nil
}

// run 并发执行刷新。
func (s *Service) run(ctx context.Context, entry *progressEntry, targets []*account.Account) {
	concurrency := s.Concurrency
	if concurrency <= 0 {
		concurrency = 8
	}
	sem := make(chan struct{}, concurrency)
	var wg sync.WaitGroup
	var mu sync.Mutex // 保护 entry.p 内部字段聚合写
	var refreshed int
	var totalQuota int
	var errs []map[string]any
	var items []map[string]any

	for _, acc := range targets {
		wg.Add(1)
		go func(a *account.Account) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			probe := s.Probe
			if probe == nil {
				probe = s.defaultProbe
			}
			probeCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
			q, err := probe(probeCtx, a)
			cancel()

			mu.Lock()
			defer mu.Unlock()
			entry.mu.Lock()
			entry.p.Processed++
			entry.mu.Unlock()

			if err != nil {
				errs = append(errs, map[string]any{"token": maskToken(a.Token), "error": err.Error()})
				entry.mu.Lock()
				entry.p.StatusCounts["error"] = entry.p.StatusCounts["error"] + 1
				entry.mu.Unlock()
				return
			}
			// 回写额度（Quota + 可选 PlanType）
			a.Quota = q.Quota
			if q.PlanType != "" {
				a.PlanType = q.PlanType
			}
			a.CheckedAt = time.Now().Unix()
			if s.Pool != nil {
				s.Pool.Add(a)
			}
			if s.Accounts != nil {
				_ = s.Accounts.Add(a)
			}
			refreshed++
			totalQuota += q.Quota
			items = append(items, map[string]any{
				"email":  a.Email,
				"token":  maskToken(a.Token),
				"quota":  q.Quota,
			})
			entry.mu.Lock()
			entry.p.StatusCounts["ok"] = entry.p.StatusCounts["ok"] + 1
			entry.mu.Unlock()
		}(acc)
	}
	wg.Wait()

	entry.mu.Lock()
	entry.p.Refreshed = refreshed
	entry.p.TotalQuota = totalQuota
	entry.p.Errors = errs
	entry.p.Items = items
	entry.p.Done = true
	entry.mu.Unlock()
}

// GetProgress 查询进度（前端轮询入口）。不存在或已清理返回 nil。
func GetProgress(id string) *Progress {
	regMu.Lock()
	entry, ok := registry[id]
	regMu.Unlock()
	if !ok {
		return nil
	}
	entry.mu.Lock()
	defer entry.mu.Unlock()
	return entry.p
}

// defaultProbe 生产探测：NewBackend + FetchAccountQuota。
func (s *Service) defaultProbe(ctx context.Context, acc *account.Account) (backend.AccountQuota, error) {
	be, err := backend.NewBackend(acc.Token, acc.FP, s.Proxy)
	if err != nil {
		return backend.AccountQuota{}, err
	}
	return be.FetchAccountQuota(ctx)
}

// listAll 合并号池与持久化账号（去重按 token）。
func (s *Service) listAll() []*account.Account {
	var out []*account.Account
	seen := make(map[string]bool)
	if s.Pool != nil {
		for _, a := range s.Pool.List() {
			if a.Token != "" && !seen[a.Token] {
				out = append(out, a)
				seen[a.Token] = true
			}
		}
	}
	if s.Accounts != nil {
		for _, a := range s.Accounts.List() {
			if a.Token != "" && !seen[a.Token] {
				out = append(out, a)
				seen[a.Token] = true
			}
		}
	}
	return out
}

// maskToken 输出脱敏 token（错误信息不落完整凭据）。
func maskToken(t string) string {
	if len(t) <= 12 {
		return "****"
	}
	return t[:6] + "..." + t[len(t)-4:]
}

// RunPeriodic 周期同步（refresh_account_interval_minute 驱动；分钟 <=0 时默认 60）。
// 每次：全量探测 + 回写；失败只记日志（对齐 Python 后台每小时同步语义）。
// 返回停止通道。
func (s *Service) RunPeriodic(ctx context.Context, intervalMinutes int) {
	if intervalMinutes <= 0 {
		intervalMinutes = 60
	}
	interval := time.Duration(intervalMinutes) * time.Minute
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				id, err := s.RefreshAll(ctx, nil)
				if err != nil {
					log.Printf("[refresh] periodic refresh failed: %v", err)
					continue
				}
				// 等待完成（简化：轮询 registry）
				deadline := time.Now().Add(30 * time.Minute)
				for time.Now().Before(deadline) {
					p := GetProgress(id)
					if p == nil || p.Done {
						break
					}
					time.Sleep(2 * time.Second)
				}
				if p := GetProgress(id); p != nil {
					log.Printf("[refresh] periodic done: refreshed=%d errors=%d total_quota=%d", p.Refreshed, len(p.Errors), p.TotalQuota)
				}
			}
		}
	}()
}

// ProgressJSON 进度序列化（供 handler 直接输出）。
func ProgressJSON(p *Progress) map[string]any {
	if p == nil {
		return map[string]any{"total": 0, "processed": 0, "done": true}
	}
	b, _ := json.Marshal(p)
	var out map[string]any
	_ = json.Unmarshal(b, &out)
	return out
}
