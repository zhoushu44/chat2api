package refresh

import (
	"context"
	"errors"
	"testing"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/backend"
)

// newTestService 构造带 mock probe 的刷新服务。
func newTestService(dir string, probe Probe, accounts ...*account.Account) *Service {
	svc := account.New(dir)
	for _, a := range accounts {
		_ = svc.Add(a)
	}
	pool := account.NewPool(nil, 0)
	for _, a := range svc.List() {
		pool.Add(a)
	}
	return &Service{
		Accounts:   svc,
		Pool:       pool,
		Probe:      probe,
		Concurrency: 4,
	}
}

// TR1：刷新成功 → Quota 回写号池 + 持久化，进度完成。
func TestRefreshAllWritesQuota(t *testing.T) {
	svc := newTestService(t.TempDir(),
		func(ctx context.Context, a *account.Account) (backend.AccountQuota, error) {
			return backend.AccountQuota{OK: true, Quota: 42, PlanType: "Plus"}, nil
		},
		&account.Account{Token: "tok-a", Email: "a@a.com", Status: account.StatusNormal},
		&account.Account{Token: "tok-b", Email: "b@a.com", Status: account.StatusNormal},
	)

	id, err := svc.RefreshAll(context.Background(), nil)
	if err != nil {
		t.Fatalf("RefreshAll: %v", err)
	}
	// 等完成
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if p := GetProgress(id); p != nil && p.Done {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	p := GetProgress(id)
	if p == nil || !p.Done {
		t.Fatalf("progress not done: %+v", p)
	}
	if p.Total != 2 || p.Processed != 2 || p.Refreshed != 2 {
		t.Fatalf("progress = %+v", p)
	}
	if p.TotalQuota != 84 {
		t.Fatalf("TotalQuota = %d want 84", p.TotalQuota)
	}
	// 号池回写
	for _, a := range svc.Pool.List() {
		if a.Quota != 42 {
			t.Errorf("pool quota %s = %d want 42", a.Email, a.Quota)
		}
		if a.PlanType != "Plus" {
			t.Errorf("plan %s = %q want Plus", a.Email, a.PlanType)
		}
	}
	// 持久化回写（Service.Add 落盘）
	for _, a := range svc.Accounts.List() {
		if a.Quota != 42 {
			t.Errorf("persisted quota %s = %d want 42", a.Email, a.Quota)
		}
	}
}

// TR2：单号失败不阻断整批，errors 记录且脱敏。
func TestRefreshAllPartialError(t *testing.T) {
	svc := newTestService(t.TempDir(),
		func(ctx context.Context, a *account.Account) (backend.AccountQuota, error) {
			if a.Token == "tok-bad" {
				return backend.AccountQuota{}, errors.New("401 unauthorized")
			}
			return backend.AccountQuota{OK: true, Quota: 10}, nil
		},
		&account.Account{Token: "tok-good", Email: "g@a.com", Status: account.StatusNormal},
		&account.Account{Token: "tok-bad", Email: "b@a.com", Status: account.StatusNormal},
	)

	id, _ := svc.RefreshAll(context.Background(), nil)
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if p := GetProgress(id); p != nil && p.Done {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	p := GetProgress(id)
	if p.Refreshed != 1 {
		t.Fatalf("Refreshed = %d want 1", p.Refreshed)
	}
	if len(p.Errors) != 1 {
		t.Fatalf("Errors = %+v want 1", p.Errors)
	}
	if p.Errors[0]["error"] != "401 unauthorized" {
		t.Fatalf("error = %v", p.Errors[0]["error"])
	}
	tok, _ := p.Errors[0]["token"].(string)
	if tok == "tok-bad" || len(tok) > 16 {
		t.Fatalf("token not masked: %q", tok)
	}
	// 失败号 quota 不动（保持 0）
	for _, a := range svc.Pool.List() {
		if a.Token == "tok-bad" && a.Quota != 0 {
			t.Errorf("failed account quota mutated: %d", a.Quota)
		}
	}
}

// TR3：指定 tokens 只刷匹配号。
func TestRefreshAllFiltered(t *testing.T) {
	svc := newTestService(t.TempDir(),
		func(ctx context.Context, a *account.Account) (backend.AccountQuota, error) {
			return backend.AccountQuota{OK: true, Quota: 7}, nil
		},
		&account.Account{Token: "tok-1", Email: "1@a.com", Status: account.StatusNormal},
		&account.Account{Token: "tok-2", Email: "2@a.com", Status: account.StatusNormal},
		&account.Account{Token: "tok-3", Email: "3@a.com", Status: account.StatusNormal},
	)

	id, _ := svc.RefreshAll(context.Background(), []string{"tok-2"})
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if p := GetProgress(id); p != nil && p.Done {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	p := GetProgress(id)
	if p.Total != 1 {
		t.Fatalf("Total = %d want 1 (filtered)", p.Total)
	}
	// 未刷新的号 quota 仍为 0
	for _, a := range svc.Pool.List() {
		if a.Token == "tok-1" && a.Quota != 0 {
			t.Errorf("tok-1 quota should stay 0, got %d", a.Quota)
		}
		if a.Token == "tok-2" && a.Quota != 7 {
			t.Errorf("tok-2 quota = %d want 7", a.Quota)
		}
	}
}

// TR4：无限额度哨兵（quota=-1）保留。
func TestRefreshAllUnlimitedSentinel(t *testing.T) {
	svc := newTestService(t.TempDir(),
		func(ctx context.Context, a *account.Account) (backend.AccountQuota, error) {
			return backend.AccountQuota{OK: true, Quota: -1}, nil
		},
		&account.Account{Token: "tok-pro", Email: "p@a.com", Status: account.StatusNormal},
	)

	id, _ := svc.RefreshAll(context.Background(), nil)
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if p := GetProgress(id); p != nil && p.Done {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	for _, a := range svc.Pool.List() {
		if a.Quota != -1 {
			t.Errorf("quota = %d want -1 (unlimited sentinel)", a.Quota)
		}
	}
}

// TR5：GetProgress 未知 id → nil（handler 视为完成）。
func TestGetProgressUnknown(t *testing.T) {
	if p := GetProgress("no-such-id"); p != nil {
		t.Fatalf("unknown id should return nil, got %+v", p)
	}
}

// TR6：空账号列表 → 立即完成，不 panic。
func TestRefreshAllEmpty(t *testing.T) {
	svc := newTestService(t.TempDir(), nil)
	id, err := svc.RefreshAll(context.Background(), nil)
	if err != nil {
		t.Fatalf("RefreshAll: %v", err)
	}
	p := GetProgress(id)
	if p == nil || !p.Done {
		t.Fatalf("empty refresh should be done instantly: %+v", p)
	}
}
