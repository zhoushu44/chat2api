package scheduler

import (
	"sync/atomic"
	"testing"
	"time"

	"chatgpt2api/internal/account"
)

// doDaily401 应移除探测失败的号：标失效 + 落盘 + 移池；健康号保留。
func TestDoDaily401RemovesDead(t *testing.T) {
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

	if removed := s.doDaily401(); removed != 1 {
		t.Fatalf("removed=%d want 1", removed)
	}
	if n := len(pool.List()); n != 1 {
		t.Fatalf("pool=%d want 1", n)
	}
	for _, a := range pool.List() {
		if a.Token != "t-alive" {
			t.Fatalf("dead still pooled: %s", a.Token)
		}
	}
	reloaded := account.New(dir)
	for _, a := range reloaded.List() {
		if a.Token == "t-dead" && a.Status != account.StatusDisabled {
			t.Fatalf("dead not persisted disabled: %+v", a)
		}
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
