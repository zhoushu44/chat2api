package scheduler

import (
	"errors"
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

	recovered, removed := s.doDaily401()
	if removed != 1 || recovered != 0 {
		t.Fatalf("recovered=%d removed=%d want 0/1", recovered, removed)
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

// CheckValid 为 nil 时旧占位语义：返回 -1/-1，不崩。
func TestDoDaily401NoProbe(t *testing.T) {
	pool := account.NewPool(nil, 0)
	pool.Add(&account.Account{ID: "a1", Token: "t1", Email: "a@e.com", Status: account.StatusNormal})
	s := New(pool, 3, 4, "UTC", true)
	recovered, removed := s.doDaily401()
	if removed != -1 || recovered != -1 {
		t.Fatalf("recovered=%d removed=%d want -1/-1 (no probe)", recovered, removed)
	}
	if n := len(pool.List()); n != 1 {
		t.Fatalf("pool touched without probe: %d", n)
	}
}

// TE1：401 失败 + Recover 成功 → 账号保留在池、Token 回写、Status 正常。
func TestDoDaily401RecoverSuccess(t *testing.T) {
	pool := account.NewPool(nil, 0)
	acc := &account.Account{
		ID: "r1", Token: "t-old", Email: "r@e.com", Type: "Plus", SourceType: "web",
		Status: account.StatusNormal, Password: "pw", TOTPSecret: "SECRET",
	}
	pool.Add(acc)

	s := New(pool, 3, 4, "UTC", true)
	s.RecoveryEnabled = true
	// 旧 token 失效；新 token 有效
	s.CheckValid = func(a *account.Account) bool { return a.Token == "t-new" }
	var recoverCalls atomic.Int32
	s.Recover = func(a *account.Account) (string, string, error) {
		recoverCalls.Add(1)
		return "t-new", "sess-new", nil
	}

	recovered, removed := s.doDaily401()
	if recovered != 1 || removed != 0 {
		t.Fatalf("recovered=%d removed=%d want 1/0", recovered, removed)
	}
	if recoverCalls.Load() != 1 {
		t.Fatalf("recover calls=%d want 1", recoverCalls.Load())
	}
	list := pool.List()
	if len(list) != 1 {
		t.Fatalf("pool=%d want 1 (account should be revived)", len(list))
	}
	if list[0].Token != "t-new" {
		t.Fatalf("token=%s want t-new", list[0].Token)
	}
	if list[0].SessionToken != "sess-new" {
		t.Fatalf("session=%s want sess-new", list[0].SessionToken)
	}
	if list[0].Status != account.StatusNormal {
		t.Fatalf("status=%s want normal", list[0].Status)
	}
	// byToken 索引应指向新 token：Pick 能取到，且 Token 已轮换
	picked := pool.Pick(account.Selector{})
	if picked == nil {
		t.Fatalf("pool.Pick returned nil: byToken index not rebuilt")
	}
	if picked.Token != "t-new" {
		t.Fatalf("picked token=%s want t-new", picked.Token)
	}
}

// TE2：401 失败 + Recover 失败 → 账号被禁用 + 移出池。
func TestDoDaily401RecoverFail(t *testing.T) {
	dir := t.TempDir()
	svc := account.New(dir)
	pool := account.NewPool(nil, 0)
	acc := &account.Account{
		ID: "r2", Token: "t-old", Email: "r2@e.com", Type: "Plus", SourceType: "web",
		Status: account.StatusNormal, Password: "pw", TOTPSecret: "SECRET",
	}
	_ = svc.Add(acc)
	pool.Add(acc)

	s := New(pool, 3, 4, "UTC", true)
	s.Svc = svc
	s.RecoveryEnabled = true
	s.CheckValid = func(a *account.Account) bool { return false }
	s.Recover = func(a *account.Account) (string, string, error) {
		return "", "", errors.New("login failed")
	}

	recovered, removed := s.doDaily401()
	if recovered != 0 || removed != 1 {
		t.Fatalf("recovered=%d removed=%d want 0/1", recovered, removed)
	}
	if n := len(pool.List()); n != 0 {
		t.Fatalf("pool=%d want 0", n)
	}
	reloaded := account.New(dir)
	for _, a := range reloaded.List() {
		if a.Token == "t-old" && a.Status != account.StatusDisabled {
			t.Fatalf("account not persisted disabled: %+v", a)
		}
	}
}

// TE3：无 Password/TOTPSecret → 不调用 Recover，直接禁用。
func TestDoDaily401NoCredsSkipsRecover(t *testing.T) {
	pool := account.NewPool(nil, 0)
	acc := &account.Account{
		ID: "r3", Token: "t-old", Email: "r3@e.com", Type: "Plus", SourceType: "web",
		Status: account.StatusNormal, // 无 Password / TOTPSecret
	}
	pool.Add(acc)

	s := New(pool, 3, 4, "UTC", true)
	s.RecoveryEnabled = true // 启用恢复功能，否则会在无凭据前直接跳过
	s.CheckValid = func(a *account.Account) bool { return false }
	var recoverCalls atomic.Int32
	s.Recover = func(a *account.Account) (string, string, error) {
		recoverCalls.Add(1)
		return "t-new", "", nil
	}

	recovered, removed := s.doDaily401()
	if recovered != 0 || removed != 1 {
		t.Fatalf("recovered=%d removed=%d want 0/1", recovered, removed)
	}
	if recoverCalls.Load() != 0 {
		t.Fatalf("recover should NOT be called without creds, calls=%d", recoverCalls.Load())
	}
}

// TE4：Recover 返回新 token 但二次验活仍失败 → 仍禁用（防假复活）。
func TestDoDaily401RecoverThenStillDead(t *testing.T) {
	pool := account.NewPool(nil, 0)
	acc := &account.Account{
		ID: "r4", Token: "t-old", Email: "r4@e.com", Type: "Plus", SourceType: "web",
		Status: account.StatusNormal, Password: "pw", TOTPSecret: "SECRET",
	}
	pool.Add(acc)

	s := New(pool, 3, 4, "UTC", true)
	s.RecoveryEnabled = true
	s.CheckValid = func(a *account.Account) bool { return false } // 新旧都失败
	s.Recover = func(a *account.Account) (string, string, error) {
		return "t-new", "sess", nil
	}

	recovered, removed := s.doDaily401()
	if recovered != 0 || removed != 1 {
		t.Fatalf("recovered=%d removed=%d want 0/1", recovered, removed)
	}
	if n := len(pool.List()); n != 0 {
		t.Fatalf("pool=%d want 0", n)
	}
}

// TE5：Recover 为 nil → 完全保持改造前行为（回归）。
func TestDoDaily401NoRecoverHook(t *testing.T) {
	dir := t.TempDir()
	svc := account.New(dir)
	pool := account.NewPool(nil, 0)
	acc := &account.Account{
		ID: "r5", Token: "t-old", Email: "r5@e.com", Type: "Plus", SourceType: "web",
		Status: account.StatusNormal, Password: "pw", TOTPSecret: "SECRET",
	}
	_ = svc.Add(acc)
	pool.Add(acc)

	s := New(pool, 3, 4, "UTC", true)
	s.Svc = svc
	s.CheckValid = func(a *account.Account) bool { return false }
	// 不设置 s.Recover

	recovered, removed := s.doDaily401()
	if recovered != 0 || removed != 1 {
		t.Fatalf("recovered=%d removed=%d want 0/1", recovered, removed)
	}
}

// TE6：checkDaily 当天去重不被破坏。
func TestCheckDailyForTestDedup(t *testing.T) {
	pool := account.NewPool(nil, 0)
	s := New(pool, 3, 4, "UTC", true)
	now := time.Date(2026, 9, 13, 4, 0, 0, 0, time.UTC)
	if !s.CheckDailyForTest(now) {
		t.Fatal("first call should trigger")
	}
	if s.CheckDailyForTest(now) {
		t.Fatal("second call same day should not trigger")
	}
	next := now.Add(24 * time.Hour)
	if !s.CheckDailyForTest(next) {
		t.Fatal("next day should trigger")
	}
}

// TP1：RecoveryEnabled=false → 不尝试恢复，直接禁用（总开关生效）。
func TestDoDaily401RecoveryDisabled(t *testing.T) {
	pool := account.NewPool(nil, 0)
	acc := &account.Account{
		ID: "p1", Token: "t-old", Email: "p1@e.com", Status: account.StatusNormal,
		Password: "pw", TOTPSecret: "SECRET",
	}
	pool.Add(acc)

	s := New(pool, 3, 4, "UTC", true)
	s.RecoveryEnabled = false // 开关关闭
	s.CheckValid = func(a *account.Account) bool { return false }
	var calls atomic.Int32
	s.Recover = func(a *account.Account) (string, string, error) {
		calls.Add(1)
		return "t-new", "", nil
	}

	recovered, removed := s.doDaily401()
	if recovered != 0 || removed != 1 {
		t.Fatalf("recovered=%d removed=%d want 0/1", recovered, removed)
	}
	if calls.Load() != 0 {
		t.Fatalf("recover calls=%d want 0 (disabled)", calls.Load())
	}
}

// TP2：前两次 Recover 失败，第三次成功 → 复活且尝试 3 次（瞬断重试）。
func TestDoDaily401RecoverRetry(t *testing.T) {
	pool := account.NewPool(nil, 0)
	acc := &account.Account{
		ID: "p2", Token: "t-old", Email: "p2@e.com", Status: account.StatusNormal,
		Password: "pw", TOTPSecret: "SECRET",
	}
	pool.Add(acc)

	s := New(pool, 3, 4, "UTC", true)
	s.RecoveryEnabled = true
	s.CheckValid = func(a *account.Account) bool { return a.Token == "t-new" }
	var calls atomic.Int32
	s.Recover = func(a *account.Account) (string, string, error) {
		n := calls.Add(1)
		if n < 3 {
			return "", "", errors.New("TLS 瞬断")
		}
		return "t-new", "sess", nil
	}

	recovered, removed := s.doDaily401()
	if recovered != 1 || removed != 0 {
		t.Fatalf("recovered=%d removed=%d want 1/0", recovered, removed)
	}
	if calls.Load() != 3 {
		t.Fatalf("recover calls=%d want 3", calls.Load())
	}
}

// TP3：每次重试都调用 RotateProxy 换出口（坏线不粘住）。
func TestDoDaily401RotatesProxyPerAttempt(t *testing.T) {
	pool := account.NewPool(nil, 0)
	acc := &account.Account{
		ID: "p3", Token: "t-old", Email: "p3@e.com", Status: account.StatusNormal,
		Password: "pw", TOTPSecret: "SECRET",
	}
	pool.Add(acc)

	s := New(pool, 3, 4, "UTC", true)
	s.RecoveryEnabled = true
	s.RecoverAttempts = 3
	s.CheckValid = func(a *account.Account) bool { return false } // 永远失败 → 跑满重试
	var rotations atomic.Int32
	s.RotateProxy = func() string {
		rotations.Add(1)
		return "socks5://127.0.0.1:1080"
	}
	s.Recover = func(a *account.Account) (string, string, error) {
		return "", "", errors.New("fail")
	}

	recovered, removed := s.doDaily401()
	if recovered != 0 || removed != 1 {
		t.Fatalf("recovered=%d removed=%d want 0/1", recovered, removed)
	}
	if rotations.Load() != 3 {
		t.Fatalf("proxy rotations=%d want 3 (one per attempt)", rotations.Load())
	}
}

// TP4：tokenExpireAt 从 JWT payload 解出 exp；非 JWT 返回 0。
func TestTokenExpireAt(t *testing.T) {
	// {"exp": 2000000000} 的 base64url payload
	jwt := "eyJhbGciOiJIUzI1NiJ9." +
		"eyJleHAiOjIwMDAwMDAwMDB9." +
		"sig"
	if got := TokenExpireAtForTest(jwt); got != 2000000000 {
		t.Fatalf("exp=%d want 2000000000", got)
	}
	if got := TokenExpireAtForTest("not-a-jwt"); got != 0 {
		t.Fatalf("exp=%d want 0 for invalid token", got)
	}
	if got := TokenExpireAtForTest(""); got != 0 {
		t.Fatalf("exp=%d want 0 for empty", got)
	}
}

// TP5：恢复成功时刷新 TokenExpireAt（按新 AT 的 exp），避免下轮被提前判 401。
func TestRecoverRefreshesTokenExpireAt(t *testing.T) {
	pool := account.NewPool(nil, 0)
	acc := &account.Account{
		ID: "p5", Token: "t-old", Email: "p5@e.com", Status: account.StatusNormal,
		Password: "pw", TOTPSecret: "SECRET", TokenExpireAt: 1000, // 旧的已过期时间
	}
	pool.Add(acc)

	newJWT := "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjIwMDAwMDAwMDB9.sig"
	s := New(pool, 3, 4, "UTC", true)
	s.RecoveryEnabled = true
	s.CheckValid = func(a *account.Account) bool { return a.Token == newJWT }
	s.Recover = func(a *account.Account) (string, string, error) {
		return newJWT, "sess", nil
	}

	recovered, removed := s.doDaily401()
	if recovered != 1 || removed != 0 {
		t.Fatalf("recovered=%d removed=%d want 1/0", recovered, removed)
	}
	list := pool.List()
	if len(list) != 1 {
		t.Fatalf("pool=%d want 1", len(list))
	}
	if list[0].TokenExpireAt != 2000000000 {
		t.Fatalf("TokenExpireAt=%d want 2000000000 (refreshed)", list[0].TokenExpireAt)
	}
}

// TP6：恢复两次都「拿到新 AT 但二次验活失败」→ 最终禁用，且 token 还原。
func TestDoDaily401RecoverFakeReviveDisables(t *testing.T) {
	pool := account.NewPool(nil, 0)
	acc := &account.Account{
		ID: "p6", Token: "t-old", Email: "p6@e.com", Status: account.StatusNormal,
		Password: "pw", TOTPSecret: "SECRET",
	}
	pool.Add(acc)

	s := New(pool, 3, 4, "UTC", true)
	s.RecoveryEnabled = true
	s.RecoverAttempts = 2
	s.CheckValid = func(a *account.Account) bool { return false }
	s.Recover = func(a *account.Account) (string, string, error) {
		return "t-fake", "fake-sess", nil
	}

	recovered, removed := s.doDaily401()
	if recovered != 0 || removed != 1 {
		t.Fatalf("recovered=%d removed=%d want 0/1", recovered, removed)
	}
	if n := len(pool.List()); n != 0 {
		t.Fatalf("pool=%d want 0", n)
	}
}
