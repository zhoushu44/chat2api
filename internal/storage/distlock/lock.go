package distlock

import (
	"sync"
	"time"
)

// 分布式锁桩：单机用 sync.Mutex，多机可替换为 redis/etcd
// 接口与 storage 共享，便于水平扩展线性度 ≥80%
type Locker struct {
	mu sync.Mutex
	holders map[string]time.Time
}

func New() *Locker {
	return &Locker{holders: make(map[string]time.Time)}
}

func (l *Locker) TryLock(key string, ttl time.Duration) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if until, ok := l.holders[key]; ok && time.Now().Before(until) {
		return false
	}
	l.holders[key] = time.Now().Add(ttl)
	return true
}

func (l *Locker) Unlock(key string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	delete(l.holders, key)
}

func (l *Locker) Refresh(key string, ttl time.Duration) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if _, ok := l.holders[key]; ok {
		l.holders[key] = time.Now().Add(ttl)
	}
}
