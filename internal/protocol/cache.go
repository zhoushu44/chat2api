package protocol

import (
	"sync"
	"time"
)

// Cache 对等 services/protocol/chat_completion_cache.py
// 简单 TTL LRU，key 为 prompt hash
type Cache struct {
	mu   sync.RWMutex
	data map[string]*entry
	ttl  time.Duration
}

type entry struct {
	Value any
	At    time.Time
}

func NewCache(ttl time.Duration) *Cache {
	if ttl == 0 {
		ttl = 5 * time.Minute
	}
	c := &Cache{data: make(map[string]*entry), ttl: ttl}
	go c.cleanup()
	return c
}

func (c *Cache) Get(key string) (any, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	e, ok := c.data[key]
	if !ok || time.Since(e.At) > c.ttl {
		return nil, false
	}
	return e.Value, true
}

func (c *Cache) Set(key string, val any) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.data[key] = &entry{Value: val, At: time.Now()}
}

func (c *Cache) cleanup() {
	ticker := time.NewTicker(c.ttl)
	defer ticker.Stop()
	for range ticker.C {
		cutoff := time.Now().Add(-c.ttl)
		c.mu.Lock()
		for k, e := range c.data {
			if e.At.Before(cutoff) {
				delete(c.data, k)
			}
		}
		c.mu.Unlock()
	}
}
