package register

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestRegister(t *testing.T) {
	s := New()
	task := s.Create("test@example.com")
	if task.State != Pending {
		t.Fatal()
	}
	_ = s.Advance(task.ID, Sent)
	if got, _ := s.Get(task.ID); got.State != Sent {
		t.Fatal()
	}
	_ = s.Advance(task.ID, Verified)
	if got, _ := s.Get(task.ID); got.State != Verified {
		t.Fatal()
	}
}

func TestAutoRefillConfig(t *testing.T) {
	s := NewWithDir(t.TempDir())
	cfg := s.GetConfig()
	if cfg.AutoRefill != false {
		t.Fatalf("default auto_refill should be false, got %v", cfg.AutoRefill)
	}
	if cfg.AutoRefillInterval != 300 {
		t.Fatalf("default interval 300, got %d", cfg.AutoRefillInterval)
	}
	if cfg.Total != 500 {
		t.Fatalf("default total 500, got %d", cfg.Total)
	}

	// 开启自动注册开关
	updated := s.Update(map[string]any{"auto_refill": true, "auto_refill_interval": 60, "total": 10})
	if !updated.AutoRefill {
		t.Fatal("auto_refill should be true after update")
	}
	if updated.AutoRefillInterval != 60 {
		t.Fatalf("interval 60, got %d", updated.AutoRefillInterval)
	}
	// 边界：小于30应截断到30
	updated = s.Update(map[string]any{"auto_refill_interval": 5})
	if updated.AutoRefillInterval != 30 {
		t.Fatalf("interval clamp 30, got %d", updated.AutoRefillInterval)
	}
	// 大于3600截断
	updated = s.Update(map[string]any{"auto_refill_interval": 9999})
	if updated.AutoRefillInterval != 3600 {
		t.Fatalf("interval clamp 3600, got %d", updated.AutoRefillInterval)
	}

	// 持久化校验
	s2 := NewWithDir(s.GetConfig().Channel["base_url"]) // dummy, use same dir via direct path
	// 重新从同一目录加载
	dir := t.TempDir()
	s3 := NewWithDir(dir)
	s3.Update(map[string]any{"auto_refill": true, "auto_refill_interval": 120})
	s4 := NewWithDir(dir)
	if !s4.GetConfig().AutoRefill || s4.GetConfig().AutoRefillInterval != 120 {
		t.Fatalf("persisted config not reloaded: %+v", s4.GetConfig())
	}
	_ = s2
}

func TestAutoRefillStartPlan(t *testing.T) {
	dir := t.TempDir()
	s := NewWithDir(dir)
	// R3.4 真链路：Start 经 Client.CreateTask 调假 RegiForge
	var creates int
	forgeSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		creates++
		_, _ = w.Write([]byte(`{"task_id":"task-7"}`))
	}))
	defer forgeSrv.Close()
	s.SetClient(testClient(forgeSrv))
	s.SetPoolFunc(func() int { return 3 })
	s.Update(map[string]any{"total": 10, "threads": 2, "mode": "total", "auto_refill": true})
	// Start 应计算差额 10-3=7 并真实创建任务
	cfg := s.Start()
	if creates != 1 {
		t.Fatalf("regiforge creates = %d, want 1", creates)
	}
	if cfg.Stats.TaskID != "task-7" {
		t.Fatalf("task_id = %q, want task-7 (no fake local id)", cfg.Stats.TaskID)
	}
	if cfg.Stats.Running != 7 {
		t.Fatalf("plan should be 7, got %d", cfg.Stats.Running)
	}
	if !cfg.Enabled {
		t.Fatal("enabled should be true")
	}
	if cfg.Stats.TargetPool != 10 {
		t.Fatalf("target pool 10, got %d", cfg.Stats.TargetPool)
	}
	s.Stop()

	// RegiForge 不可达时 Start 只记红日志，不伪造任务
	s2 := NewWithDir(t.TempDir())
	bad := NewClientFromEnv()
	bad.BaseURL = "http://127.0.0.1:1"
	s2.SetClient(bad)
	s2.SetPoolFunc(func() int { return 0 })
	s2.Update(map[string]any{"total": 2, "mode": "quota", "target_quota": 2})
	cfgBad := s2.Start()
	if cfgBad.Enabled {
		t.Fatal("should not enable when RegiForge unreachable")
	}
	if cfgBad.Stats.TaskID != "" {
		t.Fatalf("task_id should be empty on failure, got %q", cfgBad.Stats.TaskID)
	}

	// 当池已满时 Start 应直接返回无需注册（用新服务隔离状态）
	s3 := NewWithDir(t.TempDir())
	s3.SetPoolFunc(func() int { return 10 })
	s3.Update(map[string]any{"total": 10, "mode": "total", "auto_refill": true})
	cfg2 := s3.Start()
	if cfg2.Enabled {
		t.Fatal("should not enable when pool already full")
	}
	// 不应产生新任务，Running 保持 0
	if cfg2.Stats.Running != 0 {
		t.Fatalf("should not have running task when pool full, got %d", cfg2.Stats.Running)
	}
}
