package account

import (
	"testing"
	"time"
)

// TestWatcherRenewAndPersist P2.6c：临期 token 续期并持久化回 Service。
func TestWatcherRenewAndPersist(t *testing.T) {
	dir := t.TempDir()
	svc := New(dir)
	// refreshLead=1h；账号 30 分钟后过期 → 触发续期
	pool := NewPool(func(a *Account) (string, error) {
		return "new-token-1", nil
	}, time.Hour)
	acc := &Account{ID: "a1", Email: "a@x.com", Token: "old-token", Status: StatusNormal, TokenExpireAt: time.Now().Add(30 * time.Minute).Unix()}
	if err := svc.Add(acc); err != nil {
		t.Fatal(err)
	}
	pool.Add(acc)
	w := NewWatcher(svc, pool, time.Hour)
	renewed, added, removed := w.RunOnce()
	if renewed != 1 {
		t.Fatalf("renewed=%d", renewed)
	}
	if added != 0 || removed != 0 {
		t.Fatalf("added=%d removed=%d", added, removed)
	}
	// pool 内 token 已更新且可按新 token 移除
	if !pool.Remove("new-token-1") {
		t.Fatal("renewed token not indexed")
	}
	// Service 持久化了新 token（重启可见）
	svc2 := New(dir)
	found := false
	for _, a := range svc2.List() {
		if a.ID == "a1" && a.Token == "new-token-1" {
			found = true
		}
	}
	if !found {
		t.Fatal("renewed token not persisted")
	}
}

// TestWatcherSyncAddRemove P2.6c：Service 新增 → Pool；Service 删除/禁用 → Pool 移除。
func TestWatcherSyncAddRemove(t *testing.T) {
	dir := t.TempDir()
	svc := New(dir)
	pool := NewPool(nil, 0)
	w := NewWatcher(svc, pool, time.Hour)
	// Service 有、Pool 无 → 加入
	a1 := &Account{ID: "a1", Token: "t1", Status: StatusNormal}
	if err := svc.Add(a1); err != nil {
		t.Fatal(err)
	}
	_, added, _ := w.RunOnce()
	if added != 1 {
		t.Fatalf("added=%d", added)
	}
	if len(pool.List()) != 1 {
		t.Fatal("pool missing synced account")
	}
	// Service 删除 → Pool 移除
	if err := svc.Delete("a1"); err != nil {
		t.Fatal(err)
	}
	_, _, removed := w.RunOnce()
	if removed != 1 {
		t.Fatalf("removed=%d", removed)
	}
	if len(pool.List()) != 0 {
		t.Fatal("pool not cleaned")
	}
}

// TestWatcherDisabledRemoved P2.6c：禁用账号移出号池。
func TestWatcherDisabledRemoved(t *testing.T) {
	dir := t.TempDir()
	svc := New(dir)
	pool := NewPool(nil, 0)
	a1 := &Account{ID: "a1", Token: "t1", Status: StatusNormal}
	_ = svc.Add(a1)
	pool.Add(a1)
	// 禁用（Update 语义：同 ID Add 覆盖）
	_ = svc.Add(&Account{ID: "a1", Token: "t1", Status: StatusDisabled})
	w := NewWatcher(svc, pool, time.Hour)
	_, _, removed := w.RunOnce()
	if removed != 1 || len(pool.List()) != 0 {
		t.Fatalf("disabled not removed: removed=%d pool=%d", removed, len(pool.List()))
	}
}

// TestPoolUpsert P2.6c：同 token Add 合并字段（Update 后 pool 可见新状态）。
func TestPoolUpsert(t *testing.T) {
	pool := NewPool(nil, 0)
	pool.Add(&Account{ID: "a1", Token: "t1", Status: StatusNormal})
	pool.Add(&Account{ID: "a1", Token: "t1", Status: StatusDisabled})
	if len(pool.List()) != 1 {
		t.Fatalf("pool size=%d", len(pool.List()))
	}
	if pool.List()[0].Status != StatusDisabled {
		t.Fatal("upsert did not refresh status")
	}
	// 同 ID 换 token：旧条目清理
	pool.Add(&Account{ID: "a1", Token: "t2", Status: StatusNormal})
	if len(pool.List()) != 1 || pool.List()[0].Token != "t2" {
		t.Fatalf("token change not reindexed: %+v", pool.List())
	}
	if pool.Remove("t1") {
		t.Fatal("stale token still indexed")
	}
}

// TestWatcherStartStop P2.6c：后台循环启停。
func TestWatcherStartStop(t *testing.T) {
	dir := t.TempDir()
	svc := New(dir)
	pool := NewPool(nil, 0)
	w := NewWatcher(svc, pool, 20*time.Millisecond)
	ticks := make(chan struct{}, 10)
	w.OnTick = func(renewed, added, removed int) {
		ticks <- struct{}{}
	}
	w.Start()
	w.Start() // 幂等
	select {
	case <-ticks:
	case <-time.After(2 * time.Second):
		t.Fatal("watcher tick missing")
	}
	w.Stop()
	w.Stop() // 幂等
}
