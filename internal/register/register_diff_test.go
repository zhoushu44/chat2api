package register

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// seedAccounts 写入账号池文件（map 格式），供统计口径测试。
func seedAccounts(t *testing.T, dir string, accounts map[string]any) {
	t.Helper()
	b, err := json.Marshal(accounts)
	if err != nil {
		t.Fatalf("marshal accounts: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "accounts.json"), b, 0644); err != nil {
		t.Fatalf("write accounts: %v", err)
	}
}

// newPlanForge 起一个假 RegiForge，仅记录创建的任务数量并回固定 task_id。
func newPlanForge(t *testing.T) (*httptest.Server, *int) {
	t.Helper()
	creates := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/config" {
			_, _ = w.Write([]byte(`{}`))
			return
		}
		creates++
		_, _ = w.Write([]byte(`{"task_id":"task-plan"}`))
	}))
	return srv, &creates
}

// TestDiff_NotAutoRefill 未勾选自动注册：三种模式都按填的数量注册一轮，不补差额。
func TestDiff_NotAutoRefill(t *testing.T) {
	cases := []struct {
		name   string
		mode   string
		update map[string]any
		want   int
	}{
		{"total", "total", map[string]any{"mode": "total", "total": 50, "auto_refill": false}, 50},
		{"available", "available", map[string]any{"mode": "available", "target_available": 50, "auto_refill": false}, 50},
		{"quota", "quota", map[string]any{"mode": "quota", "target_quota": 500, "auto_refill": false}, 500},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			// 池里有 30 个正常账号，若不补差额仍应注册目标数量
			seedAccounts(t, dir, map[string]any{
				"a1": map[string]any{"status": "正常", "quota": 10},
			})
			s := NewWithDir(dir)
			srv, creates := newPlanForge(t)
			defer srv.Close()
			s.SetClient(testClient(srv))
			s.Update(tc.update)
			cfg := s.Start()
			if *creates != 1 {
				t.Fatalf("should create 1 task, got %d", *creates)
			}
			if cfg.Stats.Running != tc.want {
				t.Fatalf("plan = %d, want %d", cfg.Stats.Running, tc.want)
			}
			s.Stop()
		})
	}
}

// TestDiff_AutoRefill 勾选自动注册：三种模式都按各自口径补差额。
func TestDiff_AutoRefill(t *testing.T) {
	t.Run("total_减所有账号数", func(t *testing.T) {
		dir := t.TempDir()
		// 30 个账号（20 正常 + 10 失效）→ total 只数总条数
		accounts := map[string]any{}
		for i := 0; i < 20; i++ {
			accounts[string(rune('a'+i))] = map[string]any{"status": "正常", "quota": 5}
		}
		for i := 0; i < 10; i++ {
			accounts["x"+string(rune('a'+i))] = map[string]any{"status": "失效", "quota": 0}
		}
		seedAccounts(t, dir, accounts)
		s := NewWithDir(dir)
		srv, _ := newPlanForge(t)
		defer srv.Close()
		s.SetClient(testClient(srv))
		s.Update(map[string]any{"mode": "total", "total": 50, "auto_refill": true})
		cfg := s.Start()
		if cfg.Stats.Running != 20 { // 50 - 30
			t.Fatalf("plan = %d, want 20", cfg.Stats.Running)
		}
		s.Stop()
	})

	t.Run("available_减正常账号数", func(t *testing.T) {
		dir := t.TempDir()
		accounts := map[string]any{}
		for i := 0; i < 20; i++ {
			accounts[string(rune('a'+i))] = map[string]any{"status": "正常", "quota": 5}
		}
		for i := 0; i < 10; i++ {
			accounts["x"+string(rune('a'+i))] = map[string]any{"status": "失效", "quota": 0}
		}
		seedAccounts(t, dir, accounts)
		s := NewWithDir(dir)
		srv, _ := newPlanForge(t)
		defer srv.Close()
		s.SetClient(testClient(srv))
		s.Update(map[string]any{"mode": "available", "target_available": 50, "auto_refill": true})
		cfg := s.Start()
		if cfg.Stats.Running != 30 { // 50 - 20（失效号不计）
			t.Fatalf("plan = %d, want 30", cfg.Stats.Running)
		}
		s.Stop()
	})

	t.Run("quota_减正常账号额度之和", func(t *testing.T) {
		dir := t.TempDir()
		seedAccounts(t, dir, map[string]any{
			"a1": map[string]any{"status": "正常", "quota": 100},
			"a2": map[string]any{"status": "正常", "quota": 200},
			"a3": map[string]any{"status": "限流", "quota": 999},  // 非正常，不计
			"a4": map[string]any{"status": "正常", "quota": -1},  // 无限额度哨兵，按 0 计
		})
		s := NewWithDir(dir)
		srv, _ := newPlanForge(t)
		defer srv.Close()
		s.SetClient(testClient(srv))
		s.Update(map[string]any{"mode": "quota", "target_quota": 500, "auto_refill": true})
		cfg := s.Start()
		if cfg.Stats.Running != 200 { // 500 - (100+200)
			t.Fatalf("plan = %d, want 200", cfg.Stats.Running)
		}
		s.Stop()
	})
}

// TestDiff_AutoRefill_Reached 已达标时不创建任务。
func TestDiff_AutoRefill_Reached(t *testing.T) {
	dir := t.TempDir()
	seedAccounts(t, dir, map[string]any{
		"a1": map[string]any{"status": "正常", "quota": 50},
		"a2": map[string]any{"status": "正常", "quota": 50},
	})
	s := NewWithDir(dir)
	srv, creates := newPlanForge(t)
	defer srv.Close()
	s.SetClient(testClient(srv))
	s.Update(map[string]any{"mode": "available", "target_available": 2, "auto_refill": true})
	cfg := s.Start()
	if *creates != 0 {
		t.Fatalf("should not create task when target reached, got %d", *creates)
	}
	if cfg.Enabled {
		t.Fatal("should not enable when target reached")
	}
}

// TestStopThenRestart 回归：Stop 关闭 stopCh 后必须重建，否则下次 Start 轮询协程
// 在 sleepOrStop 立即退出，状态永久卡住（线上真实 bug）。
func TestStopThenRestart(t *testing.T) {
	dir := t.TempDir()
	var creates int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/config":
			_, _ = w.Write([]byte(`{}`))
		case r.URL.Path == "/api/tasks" && r.Method == http.MethodPost:
			creates++
			_, _ = w.Write([]byte(`{"task_id":"task-r"}`))
		case r.URL.Path == "/api/tasks/task-r":
			// 永远 running，靠 Stop 结束
			_, _ = w.Write([]byte(`{"done":0,"ok":0,"failed":0,"total":5,"state":"running"}`))
		case r.URL.Path == "/api/tasks/task-r/logs":
			_, _ = w.Write([]byte(`{"lines":[]}`))
		case r.URL.Path == "/api/tasks/task-r/stop":
			_, _ = w.Write([]byte(`{}`))
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
	}))
	defer srv.Close()
	s := NewWithDir(dir)
	s.SetClient(testClient(srv))
	s.Update(map[string]any{"mode": "total", "total": 5, "threads": 1, "auto_refill": false, "check_interval": 1})
	// 第一次启动后停止
	cfg := s.Start()
	if !cfg.Enabled {
		t.Fatal("first start should enable")
	}
	s.Stop()
	if s.GetConfig().Enabled {
		t.Fatal("should be disabled after stop")
	}
	// 第二次启动：轮询必须存活（若 stopCh 未重建，pollLoop 立即退出，Enabled 会被清掉）
	cfg = s.Start()
	if !cfg.Enabled {
		t.Fatal("second start should enable (stopCh must be rebuilt after Stop)")
	}
	// 轮询至少要跑过一轮（拿到远端状态 Running=5）才证明协程活着
	deadline := time.Now().Add(5 * time.Second)
	for {
		if s.GetConfig().Stats.Running == 5 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("poll loop dead after restart: running=%d", s.GetConfig().Stats.Running)
		}
		time.Sleep(50 * time.Millisecond)
	}
	s.Stop()
	if creates != 2 {
		t.Fatalf("creates = %d, want 2", creates)
	}
}
