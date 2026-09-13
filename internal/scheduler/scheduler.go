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
	Pool       *account.Pool
	Scheduler  *account.Scheduler
	Svc        *account.Service              // 可选：验活失效账号落盘（StatusDisabled）
	CheckValid func(a *account.Account) bool // 可选：验活探测；nil 时仅日志占位
	// Recover 可选：401 验活失败后的协议登录恢复（邮箱+密码+TOTP 换新 AT）。
	// 返回新 access_token / session_token；err != nil 表示恢复失败。
	// nil 时退化为旧行为（直接禁用）。
	Recover     func(a *account.Account) (newToken, newSession string, err error)
	// RecoveryEnabled 协议恢复总开关（账号页/配置控制）：关闭后 401 失效直接禁用，不尝试恢复
	RecoveryEnabled bool
	// RecoverAttempts 恢复重试次数（含首次）；<=0 时默认 3。
	// 网络约 5% 概率瞬断，重试可避免「好账号被一次抖动误杀」。
	RecoverAttempts int
	// RotateProxy 每次重试前换出口（对接代理池）；返回空串表示沿用原代理。
	RotateProxy func() string
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

// SetEnabled 运行时开关（账号页「每日401验活+协议恢复」开关调用）。
func (s *Scheduler) SetEnabled(v bool) {
	s.mu.Lock()
	s.Enabled = v
	s.mu.Unlock()
}

// SetRecoveryEnabled 运行时开关：协议登录恢复（账号页细粒度开关）。
func (s *Scheduler) SetRecoveryEnabled(v bool) {
	s.mu.Lock()
	s.RecoveryEnabled = v
	s.mu.Unlock()
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
	recovered, removed := s.doDaily401()
	log.Printf("[Scheduler] %s 401验活完成，恢复 %d，失效移除 %d", date, recovered, removed)
	s.mu.Lock()
	s.lastDailyDate = date
	s.mu.Unlock()
}

// doDaily401 真实验活：CheckValid 探测失败 → 先尝试协议登录恢复（有 password+TOTP 时）
// → 恢复成功且二次验活通过则保留在池；否则标失效 + 落盘 + 移出池。
// 返回 (恢复数, 移除数)；CheckValid 为 nil 时返回 (-1, -1)（占位未接线，兼容旧行为日志）。
func (s *Scheduler) doDaily401() (recovered, removed int) {
	if s.Pool == nil {
		return -1, -1
	}
	if s.CheckValid == nil {
		return -1, -1
	}
	accs := s.Pool.List()
	concurrency := s.Concurrency
	if concurrency < 1 {
		concurrency = 1
	}
	sem := make(chan struct{}, concurrency)
	var recN, remN atomic.Int32
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
			// 401 失效：有恢复凭据 + 开关开启时先尝试协议登录恢复（不等邮箱 OTP）
			if s.RecoveryEnabled && s.Recover != nil && acc.Password != "" && acc.TOTPSecret != "" {
				if s.recoverAccount(acc) {
					recN.Add(1)
					return
				}
			}
			log.Printf("[Scheduler] 401验活失败，移除账号 %s", acc.Email)
			acc.Status = account.StatusDisabled
			if s.Svc != nil {
				_ = s.Svc.Add(acc)
			}
			s.Pool.Remove(acc.Token)
			remN.Add(1)
		}(a)
	}
	wg.Wait()
	return int(recN.Load()), int(remN.Load())
}

// recoverAccount 协议登录恢复（带换线重试 + 二次验活 + 过期时间刷新）。
// 成功返回 true；失败返回 false（调用方走禁用）。token 变更索引在 Pool 内重建。
func (s *Scheduler) recoverAccount(acc *account.Account) bool {
	attempts := s.RecoverAttempts
	if attempts <= 0 {
		attempts = 3
	}
	oldToken := acc.Token
	oldSession := acc.SessionToken
	for i := 0; i < attempts; i++ {
		// 每次重试前换出口（首次也用健康出口，避免把坏线带进恢复）。
		// 选中的出口由 Recover 内部读取（经 RotateProxy 注入），此处只负责触发轮换。
		if s.RotateProxy != nil {
			_ = s.RotateProxy()
		}
		newToken, newSession, err := s.Recover(acc)
		if err != nil || newToken == "" {
			if err != nil {
				log.Printf("[Scheduler] 401恢复第 %d/%d 次失败 %s: %v", i+1, attempts, acc.Email, err)
			}
			continue
		}
		acc.Token = newToken
		if newSession != "" {
			acc.SessionToken = newSession
		}
		// 二次验活：防「假复活」（新 token 拿不到用）
		if !s.CheckValid(acc) {
			acc.Token = oldToken
			acc.SessionToken = oldSession
			log.Printf("[Scheduler] 401恢复后二次验活仍失败（第 %d/%d 次），重试 %s", i+1, attempts, acc.Email)
			continue
		}
		acc.Status = account.StatusNormal
		// 刷新过期时间：新 AT 是刚签发的，按 JWT exp 更新，避免下轮被提前判 401
		acc.TokenExpireAt = tokenExpireAt(newToken)
		// Token 变了，Pool 内部 byToken 索引需重建：先删旧再加新
		s.Pool.Remove(oldToken)
		s.Pool.Add(acc)
		if s.Svc != nil {
			_ = s.Svc.Add(acc)
		}
		log.Printf("[Scheduler] 401恢复成功，账号复活 %s（第 %d 次尝试）", acc.Email, i+1)
		return true
	}
	acc.Token = oldToken
	acc.SessionToken = oldSession
	return false
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
