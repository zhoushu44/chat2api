package register

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

// testClient 指向 httptest 假 RegiForge 的客户端（默认 env 配置保留，便于断言默认值）。
func testClient(srv *httptest.Server) *Client {
	c := NewClientFromEnv()
	c.BaseURL = srv.URL
	c.HTTP = srv.Client()
	return c
}

func TestCreateTask(t *testing.T) {
	var got map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/tasks" || r.Method != http.MethodPost {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		if ct := r.Header.Get("Content-Type"); ct != "application/json" {
			t.Errorf("Content-Type = %q", ct)
		}
		_ = json.NewDecoder(r.Body).Decode(&got)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"task_id":"task-123"}`))
	}))
	defer srv.Close()

	id, err := testClient(srv).CreateTask(7, 2)
	if err != nil {
		t.Fatal(err)
	}
	if id != "task-123" {
		t.Fatalf("task_id = %q", id)
	}
	// payload 字段对等 Python _start_task_locked
	want := map[string]any{
		"project_id": "chatgpt_register", "captcha_id": "turnstile.browser_manual",
		"email_id": "mailnest", "proxy_id": "wary", "sms_id": "",
		"total": float64(7), "start": float64(1), "concurrency": float64(2),
		"stagger": float64(0), "headless": false,
	}
	for k, v := range want {
		if got[k] != v {
			t.Fatalf("payload[%s] = %v, want %v (full: %v)", k, got[k], v, got)
		}
	}
}

func TestCreateTask_Errors(t *testing.T) {
	// 500 分支
	srv500 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("boom"))
	}))
	defer srv500.Close()
	if _, err := testClient(srv500).CreateTask(1, 1); err == nil {
		t.Fatal("500 should return error")
	}
	// 空 task_id 分支
	srvEmpty := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srvEmpty.Close()
	if _, err := testClient(srvEmpty).CreateTask(1, 1); err == nil {
		t.Fatal("empty task_id should return error")
	}
}

func TestGetTask(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/tasks/task-1" || r.Method != http.MethodGet {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"done":6,"ok":5,"failed":1,"total":10,"state":"running"}`))
	}))
	defer srv.Close()
	st, err := testClient(srv).GetTask("task-1")
	if err != nil {
		t.Fatal(err)
	}
	if st.Done != 6 || st.OK != 5 || st.Failed != 1 || st.Total != 10 {
		t.Fatalf("status = %+v", st)
	}
	if st.Finished() {
		t.Fatal("running should not be finished")
	}
	if st.Running() != 4 { // total-done
		t.Fatalf("running = %d, want 4", st.Running())
	}
	if got := st.SuccessRate(); got < 83.3 || got > 83.4 {
		t.Fatalf("success_rate = %v, want ~83.3", got)
	}
	// 结束态分支
	for _, state := range []string{"done", "failed", "stopped", "cancelled"} {
		s := TaskStatus{Total: 10, Done: 3, State: state}
		if !s.Finished() || s.Running() != 0 {
			t.Fatalf("state %s should be finished with running=0", state)
		}
	}
	if (TaskStatus{}).SuccessRate() != 0 {
		t.Fatal("zero ok+failed should give rate 0")
	}
}

func TestGetLogs_StopTask(t *testing.T) {
	var stopCalls int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/tasks/task-1/logs":
			_, _ = w.Write([]byte(`{"lines":["a","b"]}`))
		case r.URL.Path == "/api/tasks/task-1/stop" && r.Method == http.MethodPost:
			stopCalls++
			_, _ = w.Write([]byte(`{}`))
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
	}))
	defer srv.Close()
	c := testClient(srv)
	lines, err := c.GetLogs("task-1")
	if err != nil || len(lines) != 2 || lines[0] != "a" {
		t.Fatalf("lines = %v, err = %v", lines, err)
	}
	if err := c.StopTask("task-1"); err != nil {
		t.Fatal(err)
	}
	if stopCalls != 1 {
		t.Fatalf("stop calls = %d", stopCalls)
	}
	// 404 分支
	srv404 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv404.Close()
	if _, err := testClient(srv404).GetTask("nope"); err == nil {
		t.Fatal("404 should return error")
	}
}

// TestPoll_MapsProgress 真实轮询映射：done/ok/failed/state→stats，远端日志去重追加，结束后停用。
func TestPoll_MapsProgress(t *testing.T) {
	dir := t.TempDir()
	s := NewWithDir(dir)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/tasks":
			_, _ = w.Write([]byte(`{"task_id":"task-p"}`))
		case "/api/config":
			_, _ = w.Write([]byte(`{}`))
		case "/api/tasks/task-p":
			_, _ = w.Write([]byte(`{"done":3,"ok":2,"failed":1,"total":3,"state":"done"}`))
		case "/api/tasks/task-p/logs":
			_, _ = w.Write([]byte(`{"lines":["line1","line2"]}`))
		default:
			t.Errorf("unexpected %s", r.URL.Path)
		}
	}))
	defer srv.Close()
	s.SetClient(testClient(srv))
	s.SetPoolFunc(func() int { return 0 })
	s.Update(map[string]any{"total": 3, "threads": 1, "mode": "quota", "target_quota": 3})
	s.Start()
	deadline := time.Now().Add(10 * time.Second)
	for {
		cfg := s.GetConfig()
		if !cfg.Enabled && cfg.Stats.FinishedAt != "" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("poll did not finish: %+v", cfg.Stats)
		}
		time.Sleep(50 * time.Millisecond)
	}
	cfg := s.GetConfig()
	if cfg.Stats.Done != 3 || cfg.Stats.Success != 2 || cfg.Stats.Fail != 1 || cfg.Stats.Running != 0 {
		t.Fatalf("stats = %+v", cfg.Stats)
	}
	if cfg.Stats.SuccessRate != 66.7 { // round1(200/3)
		t.Fatalf("rate = %v, want 66.7", cfg.Stats.SuccessRate)
	}
	found := false
	for _, l := range cfg.Logs {
		if l.Text == "line1" {
			found = true
		}
	}
	if !found {
		t.Fatalf("logs missing remote lines: %+v", cfg.Logs)
	}
}

// TestMaybeContinue 自动补号：池不足→真实创建新任务；达标→不再创建。
func TestMaybeContinue(t *testing.T) {
	s := NewWithDir(t.TempDir())
	var creates int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/tasks" && r.Method == http.MethodPost:
			creates++
			_, _ = w.Write([]byte(`{"task_id":"task-c"}`))
		case r.URL.Path == "/api/config":
			_, _ = w.Write([]byte(`{}`))
		case r.URL.Path == "/api/tasks/task-c/logs":
			_, _ = w.Write([]byte(`{"lines":[]}`))
		case r.URL.Path == "/api/tasks/task-c":
			_, _ = w.Write([]byte(`{"done":0,"ok":0,"failed":0,"total":7,"state":"running"}`))
		case r.URL.Path == "/api/tasks/task-c/stop":
			_, _ = w.Write([]byte(`{}`))
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
	}))
	defer srv.Close()
	s.SetClient(testClient(srv))
	pool := 3
	s.SetPoolFunc(func() int { return pool })
	s.Update(map[string]any{"total": 10, "threads": 1, "mode": "total", "auto_refill": true})
	s.Start() // 差额 7，真实创建第 1 个任务
	if creates != 1 {
		t.Fatalf("creates = %d, want 1", creates)
	}
	s.maybeContinue() // 池仍不足 → 补号第 2 个任务
	if creates != 2 {
		t.Fatalf("creates = %d, want 2 (refill)", creates)
	}
	pool = 10
	s.maybeContinue() // 达标 → 不再创建
	if creates != 2 {
		t.Fatalf("creates = %d, want still 2", creates)
	}
	s.Stop()
}

// TestRefillCheck 巡检五分支：关/运行中/non-total/达标不补；空闲+total+不足才补。
func TestRefillCheck(t *testing.T) {
	newSvc := func(pool int, updates map[string]any) (*Service, *int) {
		s := NewWithDir(t.TempDir())
		var creates int
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			switch {
			case r.URL.Path == "/api/tasks" && r.Method == http.MethodPost:
				creates++
				_, _ = w.Write([]byte(`{"task_id":"task-r"}`))
			case r.URL.Path == "/api/config":
				_, _ = w.Write([]byte(`{}`))
			case r.URL.Path == "/api/tasks/task-r/logs":
				_, _ = w.Write([]byte(`{"lines":[]}`))
			case r.URL.Path == "/api/tasks/task-r":
				_, _ = w.Write([]byte(`{"done":0,"ok":0,"failed":0,"total":5,"state":"running"}`))
			case r.URL.Path == "/api/tasks/task-r/stop":
				_, _ = w.Write([]byte(`{}`))
			default:
				t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
			}
		}))
		t.Cleanup(srv.Close)
		s.SetClient(testClient(srv))
		s.SetPoolFunc(func() int { return pool })
		s.Update(updates)
		return s, &creates
	}
	// 1. 开关关闭 → 不补
	s, creates := newSvc(0, map[string]any{"total": 5, "mode": "total", "auto_refill": false})
	s.refillCheck()
	if *creates != 0 {
		t.Fatalf("disabled refill should not create, got %d", *creates)
	}
	// 2. 有运行任务 → 不补（先 Start 占住）
	s2, creates2 := newSvc(0, map[string]any{"total": 5, "threads": 1, "mode": "quota", "target_quota": 5})
	s2.Start()
	if *creates2 != 1 {
		t.Fatalf("setup start creates = %d", *creates2)
	}
	s2.refillCheck() // quota 模式 + 运行中 → 不补
	if *creates2 != 1 {
		t.Fatalf("running task should not refill, got %d", *creates2)
	}
	s2.Stop()
	// 3. 空闲+total+不足 → 补 1 个
	s3, creates3 := newSvc(2, map[string]any{"total": 5, "threads": 1, "mode": "total", "auto_refill": true})
	s3.refillCheck()
	if *creates3 != 1 {
		t.Fatalf("idle total refill creates = %d, want 1", *creates3)
	}
	s3.Stop()
	// 4. 达标 → 静默不补
	s4, creates4 := newSvc(5, map[string]any{"total": 5, "mode": "total", "auto_refill": true})
	s4.refillCheck()
	if *creates4 != 0 {
		t.Fatalf("satisfied pool should not refill, got %d", *creates4)
	}
}

// TestStop_Reset 真实停止：Stop/Reset 各调一次远端 stop，本地停用+清状态。
func TestStop_Reset(t *testing.T) {
	s := NewWithDir(t.TempDir())
	var stops []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/tasks" && r.Method == http.MethodPost:
			_, _ = w.Write([]byte(`{"task_id":"task-s"}`))
		case r.URL.Path == "/api/config":
			_, _ = w.Write([]byte(`{}`))
		case r.URL.Path == "/api/tasks/task-s/stop" && r.Method == http.MethodPost:
			stops = append(stops, "task-s")
			_, _ = w.Write([]byte(`{}`))
		case r.URL.Path == "/api/tasks/task-s":
			_, _ = w.Write([]byte(`{"done":0,"ok":0,"failed":0,"total":2,"state":"running"}`))
		case r.URL.Path == "/api/tasks/task-s/logs":
			_, _ = w.Write([]byte(`{"lines":[]}`))
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
	}))
	defer srv.Close()
	s.SetClient(testClient(srv))
	s.SetPoolFunc(func() int { return 0 })
	s.Update(map[string]any{"total": 2, "threads": 1, "mode": "quota", "target_quota": 2})
	s.Start()
	s.Stop()
	if len(stops) != 1 {
		t.Fatalf("stop calls = %d, want 1", len(stops))
	}
	if cfg := s.GetConfig(); cfg.Enabled {
		t.Fatal("should be disabled after Stop")
	}
	s.Start()
	s.Reset()
	if len(stops) != 2 {
		t.Fatalf("stop calls = %d, want 2 (reset)", len(stops))
	}
	cfg := s.GetConfig()
	if cfg.Enabled || cfg.Stats.TaskID != "" || cfg.Stats.Running != 0 {
		t.Fatalf("should be cleared after Reset: %+v", cfg.Stats)
	}
}

// waitRunning 等待轮询 goroutine 因 Enabled=false 退出（sleep 一个轮询周期）。
func waitRunning(t *testing.T, s *Service) {
	t.Helper()
	s.mu.RLock()
	interval := s.cfg.CheckInterval
	s.mu.RUnlock()
	if interval <= 0 {
		interval = 1
	}
	time.Sleep(time.Duration(interval+1) * time.Second)
}

// TestStop_DisablesAutoRefill 停止应一并关闭自动注册，避免巡检重新拉起任务。
func TestStop_DisablesAutoRefill(t *testing.T) {
	s := NewWithDir(t.TempDir())
	var creates int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/tasks" && r.Method == http.MethodPost:
			creates++
			_, _ = w.Write([]byte(`{"task_id":"task-ar"}`))
		case r.URL.Path == "/api/config":
			_, _ = w.Write([]byte(`{}`))
		case r.URL.Path == "/api/tasks/task-ar/stop":
			_, _ = w.Write([]byte(`{}`))
		case r.URL.Path == "/api/tasks/task-ar/logs":
			_, _ = w.Write([]byte(`{"lines":[]}`))
		case r.URL.Path == "/api/tasks/task-ar":
			_, _ = w.Write([]byte(`{"done":0,"ok":0,"failed":0,"total":2,"state":"running"}`))
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
	}))
	defer srv.Close()
	s.SetClient(testClient(srv))
	s.SetPoolFunc(func() int { return 0 })
	s.Update(map[string]any{"total": 2, "threads": 1, "mode": "total", "auto_refill": true, "check_interval": 1})
	s.Start()
	if creates != 1 {
		t.Fatalf("start creates = %d, want 1", creates)
	}
	cfg := s.Stop()
	if cfg.AutoRefill {
		t.Fatal("Stop should disable auto_refill")
	}
	// 等待 pollLoop goroutine 退出，避免测试结束后仍写临时目录（Windows 清理竞态）
	waitRunning(t, s)
	// 停止后巡检不得再补号
	s.refillCheck()
	if creates != 1 {
		t.Fatalf("refillCheck after Stop creates = %d, want still 1", creates)
	}
}

// TestMaxFailCircuitBreaker 连续失败达上限后自动停止并关闭自动注册；有成功则清零。
// 通过可控的远端状态依次驱动 3 轮：失败、失败（熔断）、成功（清零）。
func TestMaxFailCircuitBreaker(t *testing.T) {
	dir := t.TempDir()
	s := NewWithDir(dir)
	// 预置账号池：正常账号额度已满足 target_quota，使 maybeContinue 判定「已达标」不自动续跑，
	// 从而可逐轮手动驱动熔断测试（新语义下 auto_refill=true 会按模式补差额）。
	if err := os.WriteFile(filepath.Join(dir, "accounts.json"),
		[]byte(`{"a1":{"status":"正常","quota":100}}`), 0644); err != nil {
		t.Fatalf("seed accounts: %v", err)
	}
	var mu sync.Mutex
	var creates, stops int
	// 每轮任务返回的状态由 round 控制：0=running（保持不结束），>0=failed 轮次
	state := `{"done":0,"ok":0,"failed":0,"total":2,"state":"running"}`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/tasks" && r.Method == http.MethodPost:
			mu.Lock()
			creates++
			mu.Unlock()
			_, _ = w.Write([]byte(`{"task_id":"task-mf"}`))
		case r.URL.Path == "/api/config":
			_, _ = w.Write([]byte(`{}`))
		case r.URL.Path == "/api/tasks/task-mf/stop":
			mu.Lock()
			stops++
			mu.Unlock()
			_, _ = w.Write([]byte(`{}`))
		case r.URL.Path == "/api/tasks/task-mf/logs":
			_, _ = w.Write([]byte(`{"lines":[]}`))
		case r.URL.Path == "/api/tasks/task-mf":
			mu.Lock()
			cur := state
			mu.Unlock()
			_, _ = w.Write([]byte(cur))
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
	}))
	defer srv.Close()
	s.SetClient(testClient(srv))
	s.SetPoolFunc(func() int { return 0 })
	// 用 quota 模式（AutoFollow=false）避免任务结束后自动续跑，便于逐轮驱动
	s.Update(map[string]any{"mode": "quota", "target_quota": 2, "threads": 1, "auto_refill": true,
		"max_fail_enabled": true, "max_fail_rounds": 2})

	// 等待 pollLoop 处理完一轮（consecutiveFail 达到 want）
	waitFail := func(want int) {
		t.Helper()
		deadline := time.Now().Add(3 * time.Second)
		for time.Now().Before(deadline) {
			s.mu.RLock()
			got := s.consecutiveFail
			s.mu.RUnlock()
			if got >= want {
				return
			}
			time.Sleep(5 * time.Millisecond)
		}
		t.Fatalf("timeout waiting consecutiveFail >= %d", want)
	}
	waitIdle := func() {
		t.Helper()
		deadline := time.Now().Add(3 * time.Second)
		for time.Now().Before(deadline) {
			if !s.GetConfig().Enabled {
				return
			}
			time.Sleep(5 * time.Millisecond)
		}
		t.Fatal("timeout waiting idle")
	}

	// 第 1 轮：全部失败，未达上限 → auto_refill 保持
	mu.Lock()
	state = `{"done":2,"ok":0,"failed":2,"total":2,"state":"done"}`
	mu.Unlock()
	// 直接调 startTask 驱动单轮：账号池额度已达标，Start 会判定无需注册而提前返回
	s.startTask(2, 1, "quota", 2)
	waitFail(1)
	waitIdle()
	if !s.GetConfig().AutoRefill {
		t.Fatal("auto_refill should stay on before reaching the limit")
	}

	// 第 2 轮：再次全部失败，达到上限 2 → 熔断：关 auto_refill
	s.startTask(2, 1, "quota", 2) // 手动再起一轮（账号池已达标，不会自动续跑）
	waitFail(2)
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) && s.GetConfig().AutoRefill {
		time.Sleep(5 * time.Millisecond)
	}
	cfg := s.GetConfig()
	if cfg.AutoRefill {
		t.Fatal("reaching the limit should disable auto_refill")
	}
	if cfg.Enabled || cfg.AutoFollow {
		t.Fatalf("reaching the limit should stop the task: enabled=%v follow=%v", cfg.Enabled, cfg.AutoFollow)
	}

	// 熔断后巡检不得再补号
	mu.Lock()
	before := creates
	mu.Unlock()
	s.refillCheck()
	mu.Lock()
	after := creates
	mu.Unlock()
	if after != before {
		t.Fatalf("refillCheck after trip creates = %d, want %d", after, before)
	}

	// 成功后计数清零：预置非零计数，跑一轮全成功应清零
	mu.Lock()
	state = `{"done":2,"ok":2,"failed":0,"total":2,"state":"done"}`
	mu.Unlock()
	s.mu.Lock()
	s.consecutiveFail = 5
	s.mu.Unlock()
	s.Update(map[string]any{"auto_refill": true, "mode": "quota", "target_quota": 2})
	s.startTask(2, 1, "quota", 2) // 账号池已达标，手动驱动单轮成功
	deadline = time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if !s.GetConfig().Enabled {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	waitFail(0) // consecutiveFail 归零（waitFail 语义为 >= want）
	s.mu.RLock()
	finalFail := s.consecutiveFail
	s.mu.RUnlock()
	if finalFail != 0 {
		t.Fatalf("success round should reset consecutiveFail, got %d", finalFail)
	}
}

// TestStop_Reset_AutoFollowCleared 校验 Stop 后 maybeContinue 不会续跑（二次校验）。
func TestMaybeContinue_StopsAfterStop(t *testing.T) {
	s := NewWithDir(t.TempDir())
	var creates int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/tasks" && r.Method == http.MethodPost:
			creates++
			_, _ = w.Write([]byte(`{"task_id":"task-c"}`))
		case r.URL.Path == "/api/config":
			_, _ = w.Write([]byte(`{}`))
		case r.URL.Path == "/api/tasks/task-c/stop":
			_, _ = w.Write([]byte(`{}`))
		case r.URL.Path == "/api/tasks/task-c/logs":
			_, _ = w.Write([]byte(`{"lines":[]}`))
		case r.URL.Path == "/api/tasks/task-c":
			_, _ = w.Write([]byte(`{"done":0,"ok":0,"failed":0,"total":5,"state":"running"}`))
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
	}))
	defer srv.Close()
	s.SetClient(testClient(srv))
	s.SetPoolFunc(func() int { return 0 })
	s.Update(map[string]any{"total": 5, "threads": 1, "mode": "total", "auto_refill": true})
	s.Start()
	if creates != 1 {
		t.Fatalf("start creates = %d, want 1", creates)
	}
	s.Stop()
	s.maybeContinue()
	if creates != 1 {
		t.Fatalf("maybeContinue after Stop creates = %d, want still 1", creates)
	}
}
