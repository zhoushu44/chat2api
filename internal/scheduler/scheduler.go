package scheduler

import (
	"log"
	"sync"
	"time"

	"chatgpt2api/internal/account"
)

// Scheduler 对齐 abai core/scheduler.py
// - 每天 Hour 点创建一次 401 验活（并发 Concurrency）
// - 每小时扫描 trial 到期
type Scheduler struct {
	Pool        *account.Pool
	Scheduler   *account.Scheduler
	Hour        int
	Concurrency int
	Enabled     bool
	Timezone    *time.Location

	mu            sync.Mutex
	running       bool
	stopCh        chan struct{}
	lastDailyDate string
}

func New(pool *account.Pool, hour, concurrency int, tz string, enabled bool) *Scheduler {
	loc := time.UTC
	if tz != "" {
		if l, err := time.LoadLocation(tz); err == nil {
			loc = l
		} else if tz == "Asia/Shanghai" {
			loc = time.FixedZone("CST", 8*3600)
		}
	}
	if hour < 0 {
		hour = 0
	}
	if hour > 23 {
		hour = 23
	}
	if concurrency < 1 {
		concurrency = 1
	}
	if concurrency > 200 {
		concurrency = 200
	}
	return &Scheduler{
		Pool:        pool,
		Scheduler:   &account.Scheduler{Pool: pool},
		Hour:        hour,
		Concurrency: concurrency,
		Enabled:     enabled,
		Timezone:    loc,
		stopCh:      make(chan struct{}),
	}
}

func (s *Scheduler) Start() {
	s.mu.Lock()
	if s.running {
		s.mu.Unlock()
		return
	}
	s.running = true
	s.mu.Unlock()
	go s.loop()
	log.Printf("[Scheduler] 已启动，每天 %02d:00 401验活，并发 %d %s", s.Hour, s.Concurrency, map[bool]string{true: "", false: "（已关闭）"}[s.Enabled])
}

func (s *Scheduler) Stop() {
	s.mu.Lock()
	if !s.running {
		s.mu.Unlock()
		return
	}
	s.running = false
	s.mu.Unlock()
	close(s.stopCh)
}

func (s *Scheduler) loop() {
	ticker := time.NewTicker(60 * time.Second)
	defer ticker.Stop()
	// 立即执行一次 trial 扫描
	s.checkTrial()
	for {
		select {
		case <-s.stopCh:
			return
		case <-ticker.C:
			s.checkTrial()
			s.checkDaily()
		}
	}
}

func (s *Scheduler) checkTrial() {
	n := s.Scheduler.CheckTrialExpiry(time.Now())
	if n > 0 {
		log.Printf("[Scheduler] %d 个 trial 已到期", n)
	}
}

func (s *Scheduler) checkDaily() {
	if !s.Enabled {
		return
	}
	now := time.Now().In(s.Timezone)
	if now.Hour() < s.Hour {
		return
	}
	date := now.Format("2006-01-02")
	s.mu.Lock()
	if s.lastDailyDate == date {
		s.mu.Unlock()
		return
	}
	s.mu.Unlock()
	// 触发 401 验活：此处仅日志 + 标记，实际验活由 account.Pool 配合外部 checkValid 实现
	log.Printf("[Scheduler] 触发 %s 的 401验活，并发 %d", date, s.Concurrency)
	s.mu.Lock()
	s.lastDailyDate = date
	s.mu.Unlock()
	// 可扩展：遍历 Pool 中 lifecycle=registered/trial/subscribed 的账号，异步 checkValid
}

// CheckDailyForTest 供单测：传入指定时间判断是否触发
func (s *Scheduler) CheckDailyForTest(now time.Time) bool {
	if !s.Enabled {
		return false
	}
	locNow := now.In(s.Timezone)
	if locNow.Hour() < s.Hour {
		return false
	}
	date := locNow.Format("2006-01-02")
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.lastDailyDate == date {
		return false
	}
	s.lastDailyDate = date
	return true
}
