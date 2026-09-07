package jsonstorage

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type Store struct {
	mu      sync.RWMutex
	path    string
	data    map[string]json.RawMessage
	dirty   bool
	flushCh chan struct{}
	stopCh  chan struct{}
}

func New(dataDir string) (*Store, error) {
	path := filepath.Join(dataDir, "storage.json")
	s := &Store{path: path, data: make(map[string]json.RawMessage), flushCh: make(chan struct{}, 1), stopCh: make(chan struct{})}
	if b, err := os.ReadFile(path); err == nil {
		_ = json.Unmarshal(b, &s.data)
	}
	go s.flushLoop()
	return s, nil
}

func (s *Store) flushLoop() {
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			s.doFlush()
		case <-s.flushCh:
			s.doFlush()
		case <-s.stopCh:
			s.doFlush()
			return
		}
	}
}

func (s *Store) doFlush() {
	s.mu.Lock()
	if !s.dirty {
		s.mu.Unlock()
		return
	}
	snap := make(map[string]json.RawMessage, len(s.data))
	for k, v := range s.data {
		snap[k] = v
	}
	s.dirty = false
	s.mu.Unlock()
	_ = os.MkdirAll(filepath.Dir(s.path), 0755)
	b, _ := json.Marshal(snap)
	tmp := s.path + ".tmp"
	_ = os.WriteFile(tmp, b, 0644)
	_ = os.Rename(tmp, s.path)
}
func (s *Store) Get(key string) (any, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	v, ok := s.data[key]
	if !ok {
		return nil, os.ErrNotExist
	}
	var out any
	if err := json.Unmarshal(v, &out); err != nil {
		return nil, err
	}
	return out, nil
}
func (s *Store) Set(key string, value any) error {
	s.mu.Lock()
	b, _ := json.Marshal(value)
	s.data[key] = b
	s.dirty = true
	s.mu.Unlock()
	select {
	case s.flushCh <- struct{}{}:
	default:
	}
	return nil
}
func (s *Store) Delete(key string) error {
	s.mu.Lock()
	delete(s.data, key)
	s.dirty = true
	s.mu.Unlock()
	select {
	case s.flushCh <- struct{}{}:
	default:
	}
	return nil
}
func (s *Store) List() (map[string]any, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make(map[string]any, len(s.data))
	for k, v := range s.data {
		var val any
		_ = json.Unmarshal(v, &val)
		out[k] = val
	}
	return out, nil
}
func (s *Store) Close() error {
	select {
	case <-s.stopCh:
	default:
		close(s.stopCh)
	}
	// 同步最后一次落盘
	s.doFlush()
	return nil
}
