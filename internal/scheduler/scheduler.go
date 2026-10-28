package scheduler

import (
	"log"
	"sync"
	"sync/atomic"
	"time"

	"chatgpt2api/internal/account"
)

// Scheduler 对齐 abai core/scheduler.py
// - 每天 Hour 点创建一次 401 验活（并发 Concurrency）
// - 每小时扫描 trial 到期
type Scheduler struct {
	Pool        *account.Pool
	Scheduler   *account.Scheduler
	Svc         *account.Service            // 可选：验活失效账号落盘（StatusDisabled）
	CheckValid  func(a *account.Account) bool // 可选：验活探测；nil 时仅日志占位
	// Relogin 重登识别钩子：对验活失败的账号尝试重新登录换取新 token。
	// 返回 (新 token, 是否重登成功)。只有该钩子明确判定重登失败，账号才标真死号；
	// 钩子为 nil（未实现重登链路）时，账号标「待重登」而非直接判死。
	// 这样可以避免「没有 refresh_token / 重登未接线」的账号被误清。
	Relogin     func(a *account.Account) (newToken string, ok bool)
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
	// 触发 401 验活
	removed := s.doDaily401()
	log.Printf("[Scheduler] %s 401验活完成，失效移除 %d", date, removed)
	s.mu.Lock()
	s.lastDailyDate = date
	s.mu.Unlock()
}

// doDaily401 真实验活：CheckValid 探测失败的账号先标「待重登」并尝试重登识别，
// 只有 Relogin 明确返回失败才标真死号（StatusDisabled）。
// 返回移除数（真死号数）；CheckValid 为 nil 时返回 -1（占位未接线，兼容旧行为日志）。
func (s *Scheduler) doDaily401() int {
	if s.Pool == nil {
		return -1
	}
	if s.CheckValid == nil {
		return -1
	}
	accs := s.Pool.List()
	concurrency := s.Concurrency
	if concurrency < 1 {
		concurrency = 1
	}
	sem := make(chan struct{}, concurrency)
	var removed atomic.Int32
	var wg sync.WaitGroup
	for _, a := range accs {
		wg.Add(1)
		go func(acc *account.Account) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			if s.CheckValid(acc) {
				return
			}
			// 验活失败：先进入「待重登」，不要直接判死。
			acc.Status = account.StatusNeedRelogin
			// 有重登链路则尝试识别
			if s.Relogin != nil {
				newToken, ok := s.Relogin(acc)
				if ok && newToken != "" {
					oldToken := acc.Token
					acc.Token = newToken
					acc.Status = account.StatusNormal
					if s.Svc != nil {
						_ = s.Svc.Add(acc)
					}
					// 更新池内索引键
					s.Pool.Remove(oldToken)
					s.Pool.Add(acc)
					log.Printf("[Scheduler] %s 重登成功，已恢复正常", acc.Email)
					return
				}
				// 重登识别失败：这才判真死号
				log.Printf("[Scheduler] %s 重登失败，判定死号并移除", acc.Email)
				acc.Status = account.StatusDisabled
				if s.Svc != nil {
					_ = s.Svc.Add(acc)
				}
				s.Pool.Remove(acc.Token)
				removed.Add(1)
				return
			}
			// 重登链路未接线：保留「待重登」，不调度但也不清池
			log.Printf("[Scheduler] %s 验活失败，标记待重登（未接重登链路，不清池）", acc.Email)
			if s.Svc != nil {
				_ = s.Svc.Add(acc)
			}
			s.Pool.Remove(acc.Token)
		}(a)
	}
	wg.Wait()
	return int(removed.Load())
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
