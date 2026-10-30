package account

import (
	"sync"
	"time"
)

// CircuitBreaker 账号级熔断器：连续失败达阈值后隔离一段时间，半开探测恢复。
// 对齐 ChatGPT2API 的 circuit breaker（5 fails → 30s break → 3 successes to recover）。
type CircuitBreaker struct {
	mu          sync.RWMutex
	failures    map[string]*breakerState // token → state
	threshold   int                     // 连续失败阈值（默认 5）
	breakTime   time.Duration           // 隔离时长（默认 30s）
	halfOpenReq int                     // 半开状态需要的连续成功数（默认 3）
}

type breakerState struct {
	consecutiveFails int
	breakUntil       time.Time
	halfOpenSuccess  int
}

var defaultBreaker = &CircuitBreaker{
	failures:    make(map[string]*breakerState),
	threshold:   5,
	breakTime:   30 * time.Second,
	halfOpenReq: 3,
}

// SetCircuitBreakerConfig 运行时调整熔断参数。
func SetCircuitBreakerConfig(threshold int, breakSec, halfOpenReq int) {
	if threshold > 0 {
		defaultBreaker.threshold = threshold
	}
	if breakSec > 0 {
		defaultBreaker.breakTime = time.Duration(breakSec) * time.Second
	}
	if halfOpenReq > 0 {
		defaultBreaker.halfOpenReq = halfOpenReq
	}
}

// BreakerAllows 检查账号是否被熔断（不允许参与调度）。
func BreakerAllows(token string) bool {
	return defaultBreaker.allows(token)
}

// BreakerRecordSuccess 记录一次成功（半开状态下计数+1，达到阈值则恢复）。
func BreakerRecordSuccess(token string) {
	defaultBreaker.recordSuccess(token)
}

// BreakerRecordFailure 记录一次失败（连续达阈值则熔断）。
func BreakerRecordFailure(token string) {
	defaultBreaker.recordFailure(token)
}

func (b *CircuitBreaker) allows(token string) bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	s, ok := b.failures[token]
	if !ok {
		return true
	}
	if s.breakUntil.IsZero() {
		return true
	}
	// 熔断期满 → 半开（允许通过，等成功/失败判定）
	return time.Now().After(s.breakUntil)
}

func (b *CircuitBreaker) recordSuccess(token string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	s, ok := b.failures[token]
	if !ok {
		return
	}
	if !s.breakUntil.IsZero() {
		// 半开状态：成功计数
		s.halfOpenSuccess++
		if s.halfOpenSuccess >= b.halfOpenReq {
			// 恢复：清零
			s.consecutiveFails = 0
			s.breakUntil = time.Time{}
			s.halfOpenSuccess = 0
		}
	} else {
		// 正常状态：清零
		s.consecutiveFails = 0
	}
}

func (b *CircuitBreaker) recordFailure(token string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	s, ok := b.failures[token]
	if !ok {
		s = &breakerState{}
		b.failures[token] = s
	}
	s.consecutiveFails++
	s.halfOpenSuccess = 0 // 半开失败 → 重置
	if s.consecutiveFails >= b.threshold {
		s.breakUntil = time.Now().Add(b.breakTime)
	}
}
