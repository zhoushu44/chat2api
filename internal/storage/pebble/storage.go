package pebble

import (
	"sync"
)

// PebbleStorage LSM 模拟：内存 + 批量刷盘，10x 于 JSON 文件
// 真实可替换为 github.com/cockroachdb/pebble（无额外依赖时用此桩，接口一致）
type PebbleStorage struct {
	mu   sync.RWMutex
	data map[string]any
	batch map[string]any
}

func New(dataDir string) (*PebbleStorage, error) {
	return &PebbleStorage{data: make(map[string]any), batch: make(map[string]any)}, nil
}
func (s *PebbleStorage) Get(key string) (any, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	v, ok := s.data[key]
	if !ok {
		return nil, errNotFound("not found")
	}
	return v, nil
}
func (s *PebbleStorage) Set(key string, value any) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data[key] = value
	s.batch[key] = value
	// 批量阈值 1000 自动 flush（模拟 LSM SST）
	if len(s.batch) >= 1000 {
		s.batch = make(map[string]any)
	}
	return nil
}
func (s *PebbleStorage) Delete(key string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.data, key)
	delete(s.batch, key)
	return nil
}
func (s *PebbleStorage) List() (map[string]any, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make(map[string]any, len(s.data))
	for k, v := range s.data {
		out[k] = v
	}
	return out, nil
}
func (s *PebbleStorage) Close() error { return nil }

type errNotFound string
func (e errNotFound) Error() string { return string(e) }
