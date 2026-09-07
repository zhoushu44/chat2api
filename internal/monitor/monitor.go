package monitor

import (
	"sync"
	"sync/atomic"
	"time"
)

type Event struct {
	TaskID    string    `json:"task_id"`
	Stage     string    `json:"stage"`
	At        time.Time `json:"at"`
	Detail    string    `json:"detail"`
}

type Service struct {
	mu      sync.RWMutex
	subs    map[chan Event]struct{}
	ring    []Event
	cap     int
	writeIdx atomic.Uint64
	ttl     time.Duration
}

func New(ttl time.Duration) *Service {
	if ttl == 0 {
		ttl = 5 * time.Minute
	}
	s := &Service{subs: make(map[chan Event]struct{}), ring: make([]Event, 10000), cap: 10000, ttl: ttl}
	go s.cleanupLoop()
	return s
}
func (s *Service) Publish(e Event) {
	e.At = time.Now()
	idx := s.writeIdx.Add(1) % uint64(s.cap)
	s.ring[idx] = e
	s.mu.RLock()
	for ch := range s.subs {
		select {
		case ch <- e:
		default:
		}
	}
	s.mu.RUnlock()
}
func (s *Service) Subscribe() (chan Event, func()) {
	ch := make(chan Event, 100)
	s.mu.Lock()
	s.subs[ch]=struct{}{}
	s.mu.Unlock()
	return ch, func(){ s.mu.Lock(); delete(s.subs,ch); close(ch); s.mu.Unlock() }
}
func (s *Service) Events() []Event {
	cutoff := time.Now().Add(-s.ttl)
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []Event
	for i := 0; i < s.cap; i++ {
		e := s.ring[i]
		if !e.At.IsZero() && e.At.After(cutoff) {
			out = append(out, e)
		}
	}
	return out
}
func (s *Service) cleanupLoop() {
	// 环形覆盖自动淘汰，无需主动清理；仅定期触发 GC 提示
	ticker := time.NewTicker(s.ttl)
	defer ticker.Stop()
	for range ticker.C {
		// 空操作，保留接口兼容
	}
}
