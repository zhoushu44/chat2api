package scheduler

import (
	"errors"
	"log"
	"sync"
	"sync/atomic"
	"time"

	"chatgpt2api/internal/account"
)

// ErrVerifyNetwork 验活探测的网络类错误（DNS/超时/TLS/代理断连/非 401 403 上游响应）。
// CheckValid 返回本错误时语义为「无法确认死活」：调用方跳过该账号——
// 不标失效、不删除、不恢复、不计移除数，留待下一轮再探。
var ErrVerifyNetwork = errors.New("verify network error")

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
	Relogin     func(a *account.Account) (newToken string, ok bool)
	// Recover 协议登录恢复钩子（22.0 恢复）：邮箱+密码+TOTP 换新 AT。
	// 与 Relogin 的区别：Relogin 是「探测能通就复活」（refresh.go 机制），
	// Recover 是「用密码+TOTP 真正重新登录拿新 AT」。优先走 Recover。
	Recover     func(a *account.Account) (newToken, newSession string, err error)
	// RecoveryEnabled 协议恢复总开关（账号页/配置控制）：关闭后 401 失效直接禁用，不尝试恢复
	RecoveryEnabled bool
	// RecoverAttempts 恢复重试次数（含首次）；<=0 时默认 3。
	RecoverAttempts int
	// RotateProxy 每次重试前换出口（对接代理池）；返回空串表示沿用原代理。
	RotateProxy func() string
	// AutoRemoveInvalid 自动移除不可恢复账号：验活失败且协议恢复也失败时，
	// 直接从持久化存储删除账号记录。
	AutoRemoveInvalid bool
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

// SetEnabled 运行时开关（账号页「每日401验活」开关调用）。
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

// SetAutoRemoveInvalid 运行时开关：自动移除不可恢复账号。
func (s *Scheduler) SetAutoRemoveInvalid(v bool) {
	s.mu.Lock()
	s.AutoRemoveInvalid = v
	s.mu.Unlock()
	log.Printf("[Scheduler] 自动移除不可恢复账号：%v", v)
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

// doDaily401 真实验活：CheckValid 探测失败的账号按以下优先级处理：
//  1. 有密码+TOTP 且恢复开关开启 → 走协议登录恢复（Recover），成功则复活
//  2. 无凭据或恢复失败 → 标「待重登」，尝试 Relogin（额度探测复活）
//  3. Relogin 也失败 → 才判真死号（StatusDisabled）
// 返回移除数（真死号数）；CheckValid 为 nil 时返回 -1。
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

			// 优先级 1：有密码+TOTP 且恢复开关开启 → 协议登录恢复（真正重新登录拿新 AT）
			recoverable := s.RecoveryEnabled && s.Recover != nil && acc.Password != "" && acc.TOTPSecret != ""
			if recoverable {
				if s.recoverAccount(acc) {
					return // 恢复成功，账号已复活
				}
				// 恢复尝试穷尽仍失败，继续走 Relogin 探测（不直接判死）
			}

			// 优先级 2：Relogin 额度探测复活（refresh.go 机制：能通就证明存活）
			if s.Relogin != nil {
				newToken, ok := s.Relogin(acc)
				if ok && newToken != "" {
					oldToken := acc.Token
					acc.Token = newToken
					acc.Status = account.StatusNormal
					if s.Svc != nil {
						_ = s.Svc.Add(acc)
					}
					s.Pool.Remove(oldToken)
					s.Pool.Add(acc)
					log.Printf("[Scheduler] %s 额度探测复活，已恢复正常", acc.Email)
					return
				}
				// Relogin 也失败：这才判真死号
				log.Printf("[Scheduler] %s 重登识别失败，判定死号并移除", acc.Email)
				acc.Status = account.StatusDisabled
				if s.AutoRemoveInvalid && s.Svc != nil {
					// 只自动删除「确认真死号」：协议恢复与额度探测均失败。
					// 待重登、生图失效、正常账号绝不进入此分支。
					if err := s.Svc.Delete(acc.ID); err != nil {
						log.Printf("[Scheduler] 自动删除失败 %s: %v", acc.Email, err)
						_ = s.Svc.Add(acc)
					} else {
						log.Printf("[Scheduler] 已自动删除真死号 %s", acc.Email)
					}
				} else if s.Svc != nil {
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

// recoverAccount 协议登录恢复（带换线重试 + 二次验活 + 过期时间刷新）。
// 成功返回 true；失败返回 false（调用方继续走 Relogin 或判死）。token 变更索引在 Pool 内重建。
func (s *Scheduler) recoverAccount(acc *account.Account) bool {
	attempts := s.RecoverAttempts
	if attempts <= 0 {
		attempts = 3
	}
	oldToken := acc.Token
	oldSession := acc.SessionToken
	for i := 0; i < attempts; i++ {
		if s.RotateProxy != nil {
			_ = s.RotateProxy()
		}
		newToken, newSession, err := s.Recover(acc)
		if err != nil || newToken == "" {
			if err != nil {
				log.Printf("[Scheduler] 协议恢复第 %d/%d 次失败 %s: %v", i+1, attempts, acc.Email, err)
			}
			continue
		}
		acc.Token = newToken
		if newSession != "" {
			acc.SessionToken = newSession
		}
		// 二次验活：防「假复活」
		if !s.CheckValid(acc) {
			acc.Token = oldToken
			acc.SessionToken = oldSession
			log.Printf("[Scheduler] 协议恢复后二次验活仍失败（第 %d/%d 次），重试 %s", i+1, attempts, acc.Email)
			continue
		}
		acc.Status = account.StatusNormal
		acc.TokenExpireAt = tokenExpireAt(newToken)
		// 统计：记一次复活（清死亡标记、复活数 +1、刷新额度起点）
		s.Pool.RecordRevive(acc)
		s.Pool.Remove(oldToken)
		s.Pool.Add(acc)
		if s.Svc != nil {
			_ = s.Svc.Add(acc)
		}
		log.Printf("[Scheduler] 协议恢复成功，账号复活 %s（第 %d 次尝试）", acc.Email, i+1)
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
