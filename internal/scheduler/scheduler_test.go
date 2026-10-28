package scheduler

import (
	"sync/atomic"
	"testing"
	"time"

	"chatgpt2api/internal/account"
)

// doDaily401 未接重登链路时：验活失败 → 待重登（移出调度但不清池、不判死）。
func TestDoDaily401MarksNeedReloginWhenNoReloginHook(t *testing.T) {
	dir := t.TempDir()
	svc := account.New(dir)
	dead := &account.Account{ID: "dead1", Token: "t-dead", Email: "dead@e.com", Type: "Plus", SourceType: "web", Status: account.StatusNormal}
	alive := &account.Account{ID: "alive1", Token: "t-alive", Email: "alive@e.com", Type: "Plus", SourceType: "web", Status: account.StatusNormal}
	_ = svc.Add(dead)
	_ = svc.Add(alive)

	pool := account.NewPool(nil, 0)
	pool.Add(dead)
	pool.Add(alive)

	var checked atomic.Int32
	s := New(pool, 3, 4, "UTC", true)
	s.Svc = svc
	s.CheckValid = func(a *account.Account) bool {
		checked.Add(1)
		return a.Token == "t-alive"
	}

	// 未接 Relogin：不应判死号，removed 应为 0
	if removed := s.doDaily401(); removed != 0 {
		t.Fatalf("removed=%d want 0 (未接重登链路不应判死)", removed)
	}
	if n := len(pool.List()); n != 1 {
		t.Fatalf("pool=%d want 1（待重登已移出调度）", n)
	}
	// 落盘状态应是「待重登」而不是「失效」
	reloaded := account.New(dir)
	for _, a := range reloaded.List() {
		if a.Token == "t-dead" {
			if a.Status != account.StatusNeedRelogin {
				t.Fatalf("dead status=%q want 待重登（不应误清为真死号）", a.Status)
			}
			if a.IsDead() {
				t.Fatal("待重登账号不应被 IsDead 判为真死号")
			}
			if !a.IsReloginable() {
				t.Fatal("待重登账号应被 IsReloginable 识别")
			}
		}
	}
}

// 接入重登链路后：重登识别失败才判真死号。
func TestDoDaily401MarksDeadOnlyAfterReloginFails(t *testing.T) {
	dir := t.TempDir()
	svc := account.New(dir)
	dead := &account.Account{ID: "dead1", Token: "t-dead", Email: "dead@e.com", Type: "Plus", SourceType: "web", Status: account.StatusNormal}
	pool := account.NewPool(nil, 0)
	pool.Add(dead)
	_ = svc.Add(dead)

	s := New(pool, 3, 4, "UTC", true)
	s.Svc = svc
	s.CheckValid = func(a *account.Account) bool { return false } // 全部验活失败
	s.Relogin = func(a *account.Account) (string, bool) {
		return "", false // 重登识别失败
	}

	if removed := s.doDaily401(); removed != 1 {
		t.Fatalf("removed=%d want 1（重登失败应判死号）", removed)
	}
	reloaded := account.New(dir)
	for _, a := range reloaded.List() {
		if a.Token == "t-dead" && a.Status != account.StatusDisabled {
			t.Fatalf("status=%q want 失效（重登识别失败）", a.Status)
		}
	}
}

// 重登成功：账号恢复正常并保留在池中。
func TestDoDaily401ReloginSuccessRestoresAccount(t *testing.T) {
	dir := t.TempDir()
	svc := account.New(dir)
	acc := &account.Account{ID: "r1", Token: "t-old", Email: "r@e.com", Type: "Plus", SourceType: "web", Status: account.StatusNormal}
	pool := account.NewPool(nil, 0)
	pool.Add(acc)
	_ = svc.Add(acc)

	s := New(pool, 3, 4, "UTC", true)
	s.Svc = svc
	s.CheckValid = func(a *account.Account) bool { return false }
	s.Relogin = func(a *account.Account) (string, bool) {
		return "t-new", true // 重登拿到新 token
	}

	if removed := s.doDaily401(); removed != 0 {
		t.Fatalf("removed=%d want 0（重登成功不应判死）", removed)
	}
	// 池内应换成新 token
	found := false
	for _, a := range pool.List() {
		if a.Token == "t-new" && a.Status == account.StatusNormal {
			found = true
		}
	}
	if !found {
		t.Fatal("重登成功后池内应包含新 token 且状态为正常")
	}
}

// CheckValid 为 nil 时旧占位语义：返回 -1，不崩。
func TestDoDaily401NoProbe(t *testing.T) {
	pool := account.NewPool(nil, 0)
	pool.Add(&account.Account{ID: "a1", Token: "t1", Email: "a@e.com", Status: account.StatusNormal})
	s := New(pool, 3, 4, "UTC", true)
	if removed := s.doDaily401(); removed != -1 {
		t.Fatalf("removed=%d want -1 (no probe)", removed)
	}
	if n := len(pool.List()); n != 1 {
		t.Fatalf("pool touched without probe: %d", n)
	}
}

var _ = time.Now
