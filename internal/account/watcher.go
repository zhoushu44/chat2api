package account

import (
	"sync"
	"time"
)

// Watcher 账号生命周期 watcher（P2.6c）：对等 Python start_account_lifecycle_watcher 的核心循环。
// 每轮：临期 token 续期并持久化 + Service→Pool 同步（新增加入、删除/禁用移除）。
type Watcher struct {
	svc      *Service
	pool     *Pool
	interval time.Duration
	stopCh   chan struct{}
	wg       sync.WaitGroup
	mu       sync.Mutex
	running  bool
	// OnTick 每轮回调（测试/观测用，可为 nil）
	OnTick func(renewed, added, removed int)
}

// NewWatcher 创建 watcher（interval<=0 则默认 5 分钟）。
func NewWatcher(svc *Service, pool *Pool, interval time.Duration) *Watcher {
	if interval <= 0 {
		interval = 5 * time.Minute
	}
	return &Watcher{svc: svc, pool: pool, interval: interval, stopCh: make(chan struct{})}
}

// Start 启动后台循环（幂等）。
func (w *Watcher) Start() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.running {
		return
	}
	w.running = true
	w.wg.Add(1)
	go w.loop()
}

// Stop 停止并等待退出（幂等）。
func (w *Watcher) Stop() {
	w.mu.Lock()
	if !w.running {
		w.mu.Unlock()
		return
	}
	w.running = false
	close(w.stopCh)
	w.mu.Unlock()
	w.wg.Wait()
}

func (w *Watcher) loop() {
	defer w.wg.Done()
	ticker := time.NewTicker(w.interval)
	defer ticker.Stop()
	for {
		select {
		case <-w.stopCh:
			return
		case <-ticker.C:
			renewed, added, removed := w.RunOnce()
			if w.OnTick != nil {
				w.OnTick(renewed, added, removed)
			}
		}
	}
}

// RunOnce 执行一轮：续期 + 同步。返回 (续期数, 新增数, 移除数)。
func (w *Watcher) RunOnce() (renewed, added, removed int) {
	if w.svc == nil || w.pool == nil {
		return 0, 0, 0
	}
	// 1. 临期续期并持久化
	for _, a := range w.pool.RenewExpiring() {
		_ = w.svc.Add(a)
		renewed++
	}
	// 2. Service→Pool 同步
	stored := w.svc.List()
	storedByID := make(map[string]*Account, len(stored))
	for _, a := range stored {
		if a.ID != "" {
			storedByID[a.ID] = a
		}
	}
	pooled := w.pool.List()
	pooledByID := make(map[string]*Account, len(pooled))
	for _, a := range pooled {
		if a.ID != "" {
			pooledByID[a.ID] = a
		}
	}
	for id, a := range storedByID {
		if _, ok := pooledByID[id]; !ok {
			// 失效号不加回（除名语义：只在池内被移除后保持移除）
			if a.Status == StatusDisabled {
				continue
			}
			w.pool.Add(a)
			added++
		}
	}
	for id, a := range pooledByID {
		s, ok := storedByID[id]
		if !ok || (s != nil && s.Status == StatusDisabled) {
			if w.pool.Remove(a.Token) {
				removed++
			}
		}
	}
	return renewed, added, removed
}
