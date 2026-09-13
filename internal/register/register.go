package register

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type State string

const (
	Pending  State = "pending"
	Sent     State = "sent"
	Verified State = "verified"
	Failed   State = "failed"
)

type Task struct {
	ID    string `json:"id"`
	Email string `json:"email"`
	State State  `json:"state"`
	Error string `json:"error,omitempty"`
}

// ---------- 任务参数（对等 Python register_service._default_config） ----------

type MailConfig struct {
	Providers           []map[string]any `json:"providers"`
	ApiUseRegisterProxy bool             `json:"api_use_register_proxy"`
	RequestTimeout      int              `json:"request_timeout,omitempty"`
	WaitTimeout         int              `json:"wait_timeout,omitempty"`
	WaitInterval        int              `json:"wait_interval,omitempty"`
	UserAgent           string           `json:"user_agent,omitempty"`
}

type Stats struct {
	Success          int     `json:"success"`
	Fail             int     `json:"fail"`
	Done             int     `json:"done"`
	Running          int     `json:"running"`
	Threads          int     `json:"threads"`
	ElapsedSeconds   float64 `json:"elapsed_seconds"`
	AvgSeconds       float64 `json:"avg_seconds"`
	SuccessRate      float64 `json:"success_rate"`
	CurrentQuota     int     `json:"current_quota"`
	CurrentAvailable int     `json:"current_available"`
	TaskID           string  `json:"task_id,omitempty"`
	JobID            string  `json:"job_id,omitempty"`
	TargetPool       int     `json:"target_pool,omitempty"`
	StartedAt        string  `json:"started_at,omitempty"`
	UpdatedAt        string  `json:"updated_at,omitempty"`
	FinishedAt       string  `json:"finished_at,omitempty"`
}

type LogEntry struct {
	Time  string `json:"time"`
	Text  string `json:"text"`
	Level string `json:"level"`
}

// Config 注册任务参数，字段名与 Python 版 register.json 保持一致
type Config struct {
	Mail               MailConfig        `json:"mail"`
	Proxy              string            `json:"proxy"`
	Total              int               `json:"total"`
	Threads            int               `json:"threads"`
	Mode               string            `json:"mode"` // total | quota | available
	TargetQuota        int               `json:"target_quota"`
	TargetAvailable    int               `json:"target_available"`
	CheckInterval      int               `json:"check_interval"`
	AutoRefill         bool              `json:"auto_refill"`          // 自动注册开关（任务参数）
	AutoRefillInterval int               `json:"auto_refill_interval"` // 自动注册巡检间隔（秒）
	Enabled            bool              `json:"enabled"`
	Channel            map[string]string `json:"channel"`
	Stats              Stats             `json:"stats"`
	Logs               []LogEntry        `json:"logs"` // 仅内存展示，持久化时另存
	AutoFollow         bool              `json:"auto_follow,omitempty"`
	// 连续失败熔断：开关 + 连续失败轮次上限（达到后自动停止并关闭自动注册）
	MaxFailEnabled bool `json:"max_fail_enabled"`
	MaxFailRounds  int  `json:"max_fail_rounds"`
}

// Service 注册服务，包含简易状态机 + 任务参数持久化 + 自动注册巡检
type Service struct {
	mu       sync.RWMutex
	tasks    map[string]*Task
	dir      string
	cfg      Config
	logs     []LogEntry
	pollDone chan struct{}
	starting bool
	// 连续失败轮次计数（内存态，成功一轮即清零；不持久化）
	consecutiveFail int
	// Forge RegiForge 任务桥接客户端（R3 真实链路；测试可用 SetClient 注入 httptest 指向）
	Forge *Client
	// 可注入：账号池数量查询，默认读 accounts.json
	poolFunc func() int
}

func placeholderMailProvider() map[string]any {
	return map[string]any{
		"id":             "regiforge-mailnest",
		"enable":         true,
		"type":           "mailnest",
		"key_mode":       "public",
		"api_base":       "https://mailnest.top",
		"api_key":        "sk_xUAC_ZsIAXtDKHZzkJhpXx8QtxrorY8ASgc3xwZIoQ8",
		"default_domain": "",
		"local_compose":  false,
	}
}

func runtimeChannel() map[string]string {
	base := os.Getenv("REGIFORGE_BASE_URL")
	if base == "" {
		base = "http://regiforge:8787"
	}
	return map[string]string{
		"email_id":   envOr("REGIFORGE_EMAIL_ID", "mailnest"),
		"proxy_id":   envOr("REGIFORGE_PROXY_ID", "wary"),
		"captcha_id": envOr("REGIFORGE_CAPTCHA_ID", "turnstile.browser_manual"),
		"base_url":   strings.TrimRight(base, "/"),
	}
}

// mailnestPatch 从本地邮箱 provider 配置中提取 mailnest 参数，
// 用于推送给 RegiForge（使其 config.json 的 email.mailnest 与页面配置一致）。
// 仅当 api_key 非空时才返回，避免用空值覆盖 RegiForge 已有配置。
func mailnestPatch(providers []map[string]any) map[string]any {
	for _, p := range providers {
		if p == nil {
			continue
		}
		if id, _ := p["id"].(string); id != "regiforge-mailnest" {
			if t, _ := p["type"].(string); t != "mailnest" {
				continue
			}
		}
		if enable, ok := p["enable"].(bool); ok && !enable {
			continue
		}
		apiKey, _ := p["api_key"].(string)
		if strings.TrimSpace(apiKey) == "" {
			continue // 空 key 不推送，避免覆盖 RegiForge 侧配置
		}
		baseURL, _ := p["api_base"].(string)
		if strings.TrimSpace(baseURL) == "" {
			baseURL = "https://mailnest.top"
		}
		patch := map[string]any{
			"api_key":  apiKey,
			"base_url": strings.TrimRight(strings.TrimSpace(baseURL), "/"),
		}
		if domain, _ := p["default_domain"].(string); strings.TrimSpace(domain) != "" {
			patch["default_domain"] = domain
		}
		return map[string]any{"email": map[string]any{"mailnest": patch}}
	}
	return nil
}

// proxyPatch 根据代理环境变量构造 RegiForge 的 proxy 配置补丁。
//
// 背景：注册必须走非 CN 出口，否则 OpenAI 直接 403。RegiForge 的 config.json
// 需要存在对应 proxy_id 的定义（如 wary），否则会静默退化成直连。
// 这里从环境变量读取代理池地址，保证与部署环境一致；未配置则返回 nil（不动远端）。
func proxyPatch() map[string]any {
	apiURL := strings.TrimSpace(os.Getenv("REGIFORGE_PROXY_API_URL"))
	if apiURL == "" {
		return nil
	}
	wary := map[string]any{"api_url": apiURL}
	if key := strings.TrimSpace(os.Getenv("REGIFORGE_PROXY_API_KEY")); key != "" {
		wary["api_key"] = key
	}
	return map[string]any{"proxy": map[string]any{"wary": wary}}
}

// exportPatch 构造 RegiForge 的 export.chatgpt2api 配置补丁，
// 让注册成功的账号自动导入 chat2api 账号池（POST {base_url}/api/accounts）。
// 两者同处于单镜像容器内，通过 REGIFORGE_EXPORT_BASE_URL 指向本服务 3077 端口。
// 未配置 admin_password 时返回 nil（不动远端，避免空密码覆盖）。
func exportPatch() map[string]any {
	baseURL := strings.TrimSpace(os.Getenv("REGIFORGE_EXPORT_BASE_URL"))
	adminPW := strings.TrimSpace(os.Getenv("REGIFORGE_EXPORT_ADMIN_PASSWORD"))
	if baseURL == "" || adminPW == "" {
		return nil
	}
	return map[string]any{
		"export": map[string]any{
			"chatgpt2api": map[string]any{
				"base_url":       strings.TrimRight(baseURL, "/"),
				"admin_password": adminPW,
			},
		},
	}
}

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func defaults() Config {
	return Config{
		Mail: MailConfig{
			Providers:           []map[string]any{placeholderMailProvider()},
			ApiUseRegisterProxy: true,
			RequestTimeout:      30,
			WaitTimeout:         30,
			WaitInterval:        2,
		},
		Proxy:              "",
		Total:              500,
		Threads:            2,
		Mode:               "total",
		TargetQuota:        100,
		TargetAvailable:    10,
		CheckInterval:      5,
		AutoRefill:         false,
		AutoRefillInterval: 300,
		MaxFailEnabled:     false,
		MaxFailRounds:      10,
		Enabled:            false,
		Channel:            runtimeChannel(),
		Stats: Stats{
			Threads: 2,
		},
		Logs: []LogEntry{},
	}
}

func normalize(raw Config) Config {
	cfg := defaults()
	// total
	if raw.Total > 0 {
		cfg.Total = raw.Total
	}
	if cfg.Total < 1 {
		cfg.Total = 1
	}
	if raw.Threads > 0 {
		cfg.Threads = raw.Threads
	}
	if cfg.Threads < 1 {
		cfg.Threads = 1
	}
	m := strings.TrimSpace(raw.Mode)
	if m == "quota" || m == "available" || m == "total" {
		cfg.Mode = m
	}
	if raw.TargetQuota > 0 {
		cfg.TargetQuota = raw.TargetQuota
	}
	if raw.TargetAvailable > 0 {
		cfg.TargetAvailable = raw.TargetAvailable
	}
	if raw.CheckInterval > 0 {
		cfg.CheckInterval = raw.CheckInterval
	}
	if cfg.CheckInterval < 1 {
		cfg.CheckInterval = 5
	}
	cfg.AutoRefill = raw.AutoRefill
	interval := raw.AutoRefillInterval
	if interval == 0 {
		interval = 300
	}
	if interval < 30 {
		interval = 30
	}
	if interval > 3600 {
		interval = 3600
	}
	cfg.AutoRefillInterval = interval
	cfg.MaxFailEnabled = raw.MaxFailEnabled
	rounds := raw.MaxFailRounds
	if rounds <= 0 {
		rounds = 10
	}
	if rounds < 1 {
		rounds = 1
	}
	if rounds > 1000 {
		rounds = 1000
	}
	cfg.MaxFailRounds = rounds
	cfg.Proxy = strings.TrimSpace(raw.Proxy)
	cfg.Enabled = raw.Enabled
	cfg.AutoFollow = raw.AutoFollow
	if raw.Mail.Providers != nil {
		// 固定占位，不受前端传入影响（对等 Python _fixed_mail_providers）
		cfg.Mail.Providers = []map[string]any{placeholderMailProvider()}
	}
	// 保留 ApiUseRegisterProxy 若显式传入
	if raw.Mail.ApiUseRegisterProxy != cfg.Mail.ApiUseRegisterProxy {
		// 若 raw 来自持久化且为 false，则尊重 false
		// 由于 defaults 为 true，只有 raw 显式 false 时才覆盖
		cfg.Mail.ApiUseRegisterProxy = raw.Mail.ApiUseRegisterProxy
	}
	cfg.Channel = runtimeChannel()
	// stats 保留运行时字段
	if raw.Stats.Threads != 0 {
		cfg.Stats = raw.Stats
		cfg.Stats.Threads = cfg.Threads
	} else {
		cfg.Stats.Threads = cfg.Threads
	}
	return cfg
}

func nowISO() string { return time.Now().UTC().Format(time.RFC3339Nano) }

// New 兼容旧测试：无参内存版
func New() *Service {
	return NewWithDir("")
}

// NewWithDir 带持久化目录的构造，dir 为 DataDir
func NewWithDir(dir string) *Service {
	s := &Service{
		tasks: make(map[string]*Task),
		dir:   dir,
		cfg:   defaults(),
		logs:  []LogEntry{},
	}
	if dir != "" {
		_ = os.MkdirAll(dir, 0755)
		if b, err := os.ReadFile(filepath.Join(dir, "register.json")); err == nil {
			var raw Config
			if json.Unmarshal(b, &raw) == nil {
				s.cfg = normalize(raw)
				// logs 不持久化到 cfg.Logs，单独读取若存在
				if len(raw.Logs) > 0 {
					s.logs = raw.Logs
					if len(s.logs) > 300 {
						s.logs = s.logs[len(s.logs)-300:]
					}
				}
			}
		}
	}
	s.poolFunc = s.defaultPoolFunc
	s.Forge = NewClientFromEnv()
	// 后台自动注册巡检常驻
	go s.refillLoop()
	// 若之前有运行中任务，尝试恢复轮询（简化：仅标记 enabled）
	if s.cfg.Enabled && s.cfg.Stats.TaskID != "" {
		go s.pollLoop(s.cfg.Stats.TaskID)
	}
	return s
}

func (s *Service) defaultPoolFunc() int {
	if s.dir == "" {
		return 0
	}
	b, err := os.ReadFile(filepath.Join(s.dir, "accounts.json"))
	if err != nil {
		return 0
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err == nil {
		return len(m)
	}
	// 尝试数组格式
	var arr []any
	if err := json.Unmarshal(b, &arr); err == nil {
		return len(arr)
	}
	return 0
}

// SetClient 注入 RegiForge 客户端（测试用 httptest server 指向）
func (s *Service) SetClient(c *Client) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.Forge = c
}

// currentForge 快照当前 RegiForge 客户端（nil 时回退默认 env 构造，防空指针）
func (s *Service) currentForge() *Client {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if s.Forge == nil {
		return NewClientFromEnv()
	}
	return s.Forge
}

// SetPoolFunc 注入账号池数量查询（测试用）
func (s *Service) SetPoolFunc(fn func() int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.poolFunc = fn
}

func (s *Service) saveLocked() {
	if s.dir == "" {
		return
	}
	// 合并 logs 到 cfg 副本再落盘
	clone := s.cfg
	clone.Logs = s.logs
	if len(clone.Logs) > 300 {
		clone.Logs = clone.Logs[len(clone.Logs)-300:]
	}
	b, _ := json.MarshalIndent(clone, "", "  ")
	tmp := filepath.Join(s.dir, "register.json.tmp")
	_ = os.WriteFile(tmp, b, 0644)
	_ = os.Rename(tmp, filepath.Join(s.dir, "register.json"))
}

func (s *Service) appendLogLocked(text, level string) {
	if level == "" {
		level = "info"
	}
	s.logs = append(s.logs, LogEntry{Time: nowISO(), Text: text, Level: level})
	if len(s.logs) > 300 {
		s.logs = s.logs[len(s.logs)-300:]
	}
}

func (s *Service) AppendLog(text, level string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.appendLogLocked(text, level)
	s.saveLocked()
}

// ---------- 旧 Task 状态机（保持兼容） ----------

func (s *Service) Create(email string) *Task {
	s.mu.Lock()
	defer s.mu.Unlock()
	t := &Task{ID: fmt.Sprintf("reg-%d", len(s.tasks)+1), Email: email, State: Pending}
	s.tasks[t.ID] = t
	return t
}
func (s *Service) Advance(id string, to State) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	t, ok := s.tasks[id]
	if !ok {
		return fmt.Errorf("not found")
	}
	t.State = to
	return nil
}
func (s *Service) Get(id string) (*Task, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	t, ok := s.tasks[id]
	return t, ok
}

// ---------- 新 Config / 任务参数 ----------

func (s *Service) GetConfig() Config {
	s.mu.RLock()
	defer s.mu.RUnlock()
	clone := s.cfg
	clone.Logs = append([]LogEntry(nil), s.logs...)
	// 确保 channel 实时
	clone.Channel = runtimeChannel()
	if len(clone.Logs) > 300 {
		clone.Logs = clone.Logs[len(clone.Logs)-300:]
	}
	return clone
}

func (s *Service) Update(updates map[string]any) Config {
	s.mu.Lock()
	defer s.mu.Unlock()
	// 将 updates 合并到 cfg
	b, _ := json.Marshal(s.cfg)
	var base map[string]any
	_ = json.Unmarshal(b, &base)
	for k, v := range updates {
		// 仅允许白名单字段
		switch k {
		case "total", "threads", "mode", "target_quota", "target_available", "check_interval", "auto_refill", "auto_refill_interval", "proxy", "mail", "enabled", "channel", "auto_follow", "max_fail_enabled", "max_fail_rounds":
			base[k] = v
		}
	}
	var merged Config
	nb, _ := json.Marshal(base)
	_ = json.Unmarshal(nb, &merged)
	s.cfg = normalize(merged)
	s.appendLogLocked(fmt.Sprintf("配置已更新 auto_refill=%v interval=%d total=%d threads=%d mode=%s", s.cfg.AutoRefill, s.cfg.AutoRefillInterval, s.cfg.Total, s.cfg.Threads, s.cfg.Mode), "info")
	s.saveLocked()
	clone := s.cfg
	clone.Logs = append([]LogEntry(nil), s.logs...)
	return clone
}

func (s *Service) Start() Config {
	s.mu.Lock()
	// 若已有任务运行，忽略
	if s.cfg.Enabled && s.cfg.Stats.Running > 0 {
		s.appendLogLocked("已有任务在运行，忽略重复启动", "yellow")
		s.saveLocked()
		clone := s.cfg
		clone.Logs = append([]LogEntry(nil), s.logs...)
		s.mu.Unlock()
		return clone
	}
	mode := s.cfg.Mode
	total := s.cfg.Total
	threads := s.cfg.Threads
	target := total
	plan := total
	switch mode {
	case "quota":
		plan = s.cfg.TargetQuota
		target = plan
	case "available":
		plan = s.cfg.TargetAvailable
		target = plan
	default:
		// total 模式：差额补齐
		poolTotal := 0
		if s.poolFunc != nil {
			poolTotal = s.poolFunc()
		}
		plan = total - poolTotal
		if plan <= 0 {
			s.cfg.Enabled = false
			s.appendLogLocked(fmt.Sprintf("账号池已达目标：总数 %d >= %d，无需注册", poolTotal, total), "green")
			s.saveLocked()
			clone := s.cfg
			clone.Logs = append([]LogEntry(nil), s.logs...)
			s.mu.Unlock()
			return clone
		}
		s.appendLogLocked(fmt.Sprintf("账号池当前 %d，目标 %d，计划注册 %d 个", poolTotal, total, plan), "yellow")
	}
	s.mu.Unlock()
	return s.startTask(plan, threads, mode, target)
}

func (s *Service) startTask(plan, threads int, mode string, target int) Config {
	s.mu.Lock()
	if s.starting {
		clone := s.cfg
		clone.Logs = append([]LogEntry(nil), s.logs...)
		s.mu.Unlock()
		return clone
	}
	s.starting = true
	s.mu.Unlock()
	defer func() {
		s.mu.Lock()
		s.starting = false
		s.mu.Unlock()
	}()
	forge := s.currentForge()
	// 创建任务前，先把页面/环境配置推送到 RegiForge，否则：
	//   - 邮箱 api_key 为空 → 报“未配置 api_key”
	//   - 代理 proxy_id 未定义 → 静默直连，CN 出口被 OpenAI 403
	//   - export.chatgpt2api 未配置 → 注册成功账号无法自动入库
	s.mu.RLock()
	patches := []map[string]any{mailnestPatch(s.cfg.Mail.Providers), proxyPatch(), exportPatch()}
	s.mu.RUnlock()
	for _, patch := range patches {
		if patch == nil {
			continue
		}
		if err := forge.SyncConfig(patch); err != nil {
			s.AppendLog(fmt.Sprintf("同步配置到 RegiForge 失败：%v", err), "red")
		}
	}
	// 真实链路：调 RegiForge 创建任务（对等 Python _start_task_locked POST /api/tasks）；
	// 失败只记红日志，不伪造本地 task_id
	taskID, err := forge.CreateTask(plan, threads)
	if err != nil {
		s.mu.Lock()
		defer s.mu.Unlock()
		s.appendLogLocked(fmt.Sprintf("创建 RegiForge 任务失败：%v", err), "red")
		s.saveLocked()
		clone := s.cfg
		clone.Logs = append([]LogEntry(nil), s.logs...)
		return clone
	}
	s.mu.Lock()
	s.cfg.Enabled = true
	s.cfg.AutoFollow = (mode == "total")
	s.cfg.Stats = Stats{
		JobID:      taskID,
		TaskID:     taskID,
		Running:    plan,
		Threads:    threads,
		TargetPool: target,
		StartedAt:  nowISO(),
		UpdatedAt:  nowISO(),
	}
	s.logs = append(s.logs, LogEntry{Time: nowISO(), Text: "———— 新任务开始 ————", Level: "info"})
	s.appendLogLocked(fmt.Sprintf("任务已创建 task_id=%s total=%d threads=%d mode=%s auto_refill=%v", taskID, plan, threads, mode, s.cfg.AutoRefill), "green")
	s.saveLocked()
	clone := s.cfg
	clone.Logs = append([]LogEntry(nil), s.logs...)
	s.mu.Unlock()
	go s.pollLoop(taskID)
	return clone
}

func (s *Service) pollLoop(taskID string) {
	forge := s.currentForge()
	// 真实链路：立即首轮询（对等 Python _poll spawn 后直接 GET），之后按 check_interval 休眠
	for {
		st, err := forge.GetTask(taskID)
		if err != nil {
			s.mu.Lock()
			// 任务已失效（404/失联）：按 Python _poll 异常分支停用，避免空转
			if s.cfg.Stats.TaskID == taskID {
				s.cfg.Enabled = false
				s.appendLogLocked(fmt.Sprintf("轮询 RegiForge 异常：%v", err), "red")
				s.saveLocked()
			}
			s.mu.Unlock()
			return
		}
		s.mu.Lock()
		if s.cfg.Stats.TaskID != taskID || !s.cfg.Enabled {
			s.mu.Unlock()
			return
		}
		s.applyStatusLocked(st)
		s.appendTaskLogsLocked(forge, taskID)
		s.saveLocked()
		finished := st.Finished()
		state := st.State
		s.mu.Unlock()
		if finished {
			s.mu.Lock()
			s.cfg.Enabled = false
			s.cfg.Stats.FinishedAt = nowISO()
			level := "yellow"
			if state == "done" && s.cfg.Stats.Fail == 0 {
				level = "green"
			}
			s.appendLogLocked(fmt.Sprintf("RegiForge 任务结束：state=%s ok=%d failed=%d", state, s.cfg.Stats.Success, s.cfg.Stats.Fail), level)
			// 连续失败熔断：本轮全部失败则计数 +1，有成功则清零
			tripped := false
			if state != "stopped" {
				if s.cfg.Stats.Success == 0 {
					s.consecutiveFail++
					if s.cfg.MaxFailEnabled && s.consecutiveFail >= s.cfg.MaxFailRounds {
						s.cfg.AutoRefill = false
						s.cfg.AutoFollow = false
						tripped = true
						s.appendLogLocked(fmt.Sprintf("连续失败 %d 轮，已达上限 %d，自动停止注册并关闭自动注册", s.consecutiveFail, s.cfg.MaxFailRounds), "red")
					} else if s.cfg.MaxFailEnabled {
						s.appendLogLocked(fmt.Sprintf("本轮注册全部失败，连续失败 %d/%d 轮", s.consecutiveFail, s.cfg.MaxFailRounds), "red")
					}
				} else {
					s.consecutiveFail = 0
				}
			}
			s.saveLocked()
			s.mu.Unlock()
			if state == "stopped" {
				s.AppendLog("任务已停止", "yellow")
				return
			}
			if tripped {
				if taskID != "" {
					if err := forge.StopTask(taskID); err != nil {
						s.AppendLog(fmt.Sprintf("停止请求失败：%v", err), "red")
					}
				}
				return
			}
			s.maybeContinue()
			return
		}
		interval := 5
		s.mu.RLock()
		if s.cfg.CheckInterval > 0 {
			interval = s.cfg.CheckInterval
		}
		s.mu.RUnlock()
		time.Sleep(time.Duration(interval) * time.Second)
	}
}

// applyStatusLocked 将 RegiForge 状态映射到本地 stats（调用方须持有写锁，对等 Python _bump）。
func (s *Service) applyStatusLocked(st TaskStatus) {
	s.cfg.Stats.Done = st.Done
	s.cfg.Stats.Success = st.OK
	s.cfg.Stats.Fail = st.Failed
	s.cfg.Stats.Running = st.Running()
	s.cfg.Stats.SuccessRate = round1(st.SuccessRate())
	s.cfg.Stats.UpdatedAt = nowISO()
	if elapsed := time.Since(parseTime(s.cfg.Stats.StartedAt)).Seconds(); elapsed > 0 {
		s.cfg.Stats.ElapsedSeconds = round1(elapsed)
	}
	if s.cfg.Stats.Success > 0 {
		s.cfg.Stats.AvgSeconds = round1(s.cfg.Stats.ElapsedSeconds / float64(s.cfg.Stats.Success))
	}
}

// appendTaskLogsLocked 拉取远端日志尾部去重追加（调用方须持有写锁，对等 Python 取后 15 行）。
func (s *Service) appendTaskLogsLocked(forge *Client, taskID string) {
	lines, err := forge.GetLogs(taskID)
	if err != nil || len(lines) == 0 {
		return
	}
	if len(lines) > 15 {
		lines = lines[len(lines)-15:]
	}
	for _, line := range lines {
		dup := false
		start := 0
		if len(s.logs) > 60 {
			start = len(s.logs) - 60
		}
		for _, existing := range s.logs[start:] {
			if existing.Text == line {
				dup = true
				break
			}
		}
		if !dup {
			s.appendLogLocked(line, "info")
		}
	}
}

func round1(f float64) float64 { return float64(int(f*10+0.5)) / 10 }

func parseTime(v string) time.Time {
	t, _ := time.Parse(time.RFC3339Nano, v)
	if t.IsZero() {
		t, _ = time.Parse(time.RFC3339, v)
	}
	if t.IsZero() {
		return time.Now()
	}
	return t
}

func (s *Service) maybeContinue() {
	s.mu.RLock()
	follow := s.cfg.AutoFollow
	mode := s.cfg.Mode
	target := s.cfg.Stats.TargetPool
	if target == 0 {
		target = s.cfg.Total
	}
	threads := s.cfg.Threads
	s.mu.RUnlock()
	// 二次校验：AutoFollow 已被 Stop/熔断清掉时不得续跑
	if !follow || mode != "total" || target <= 0 {
		return
	}
	s.mu.RLock()
	stopped := !s.cfg.AutoFollow || s.cfg.Stats.TaskID == ""
	s.mu.RUnlock()
	if stopped {
		return
	}
	poolTotal := 0
	if s.poolFunc != nil {
		poolTotal = s.poolFunc()
	}
	if poolTotal >= target {
		s.mu.Lock()
		s.appendLogLocked(fmt.Sprintf("账号池已达目标 %d >= %d，自动注册完成", poolTotal, target), "green")
		s.saveLocked()
		s.mu.Unlock()
		return
	}
	plan := target - poolTotal
	s.mu.Lock()
	s.appendLogLocked(fmt.Sprintf("账号池 %d < 目标 %d，自动补号 %d 个", poolTotal, target, plan), "yellow")
	s.mu.Unlock()
	s.startTask(plan, threads, "total", target)
}

func (s *Service) Stop() Config {
	s.mu.Lock()
	taskID := s.cfg.Stats.TaskID
	s.cfg.Enabled = false
	s.cfg.AutoFollow = false
	// 停止即彻底停止：一并关闭自动注册，避免 refillLoop 下一轮巡检重新拉起任务
	wasAutoRefill := s.cfg.AutoRefill
	s.cfg.AutoRefill = false
	s.consecutiveFail = 0
	if wasAutoRefill {
		s.appendLogLocked("已同时关闭自动注册，避免巡检重新拉起任务", "yellow")
	}
	s.appendLogLocked("正在停止任务", "yellow")
	s.saveLocked()
	clone := s.cfg
	clone.Logs = append([]LogEntry(nil), s.logs...)
	s.mu.Unlock()
	// 真实链路：停止远端 RegiForge 任务（对等 Python stop）；失败记红但本地已停用
	if taskID != "" {
		if err := s.currentForge().StopTask(taskID); err != nil {
			s.AppendLog(fmt.Sprintf("停止请求失败：%v", err), "red")
		}
	}
	return clone
}

func (s *Service) Reset() Config {
	s.mu.Lock()
	taskID := ""
	if s.cfg.Enabled {
		taskID = s.cfg.Stats.TaskID
	}
	s.logs = []LogEntry{}
	s.cfg.Enabled = false
	s.cfg.AutoFollow = false
	// 重置同样关闭自动注册并清零连续失败计数
	s.cfg.AutoRefill = false
	s.consecutiveFail = 0
	s.cfg.Stats = Stats{Threads: s.cfg.Threads, UpdatedAt: nowISO()}
	s.saveLocked()
	s.mu.Unlock()
	// 运行中则先停远端任务（对等 Python reset），避免清掉 task_id 后 stop 失效
	if taskID != "" {
		if err := s.currentForge().StopTask(taskID); err != nil {
			s.AppendLog(fmt.Sprintf("reset 停止任务失败：%v", err), "red")
		} else {
			s.AppendLog(fmt.Sprintf("reset 前已停止任务 %s", taskID), "yellow")
		}
	}
	s.mu.Lock()
	s.appendLogLocked("已重置", "info")
	s.saveLocked()
	clone := s.cfg
	clone.Logs = append([]LogEntry(nil), s.logs...)
	s.mu.Unlock()
	return clone
}

// ---------- 自动注册巡检 ----------

func (s *Service) refillLoop() {
	for {
		interval := 30
		s.mu.RLock()
		iv := s.cfg.AutoRefillInterval
		if iv >= 30 && iv <= 3600 {
			interval = iv
		}
		s.mu.RUnlock()
		// 限制最大 300s 睡眠，对等 Python min(interval,300)
		sleep := interval
		if sleep > 300 {
			sleep = 300
		}
		time.Sleep(time.Duration(sleep) * time.Second)
		s.refillCheck()
	}
}

func (s *Service) refillCheck() {
	s.mu.RLock()
	if !s.cfg.AutoRefill {
		s.mu.RUnlock()
		return
	}
	if s.cfg.Enabled {
		s.mu.RUnlock()
		return
	}
	if s.cfg.Mode != "total" {
		s.mu.RUnlock()
		return
	}
	total := s.cfg.Total
	threads := s.cfg.Threads
	poolFunc := s.poolFunc
	s.mu.RUnlock()
	poolTotal := 0
	if poolFunc != nil {
		poolTotal = poolFunc()
	}
	plan := total - poolTotal
	if plan <= 0 {
		return
	}
	s.mu.Lock()
	s.appendLogLocked(fmt.Sprintf("自动注册巡检：账号池当前 %d < 目标 %d，自动补齐 %d 个", poolTotal, total, plan), "yellow")
	s.mu.Unlock()
	s.startTask(plan, threads, "total", total)
}
