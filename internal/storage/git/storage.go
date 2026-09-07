package gitstorage

import "sync"

type Store struct {
	mu   sync.RWMutex
	data map[string]any
}

func New(dataDir string) (*Store, error) {
	return &Store{data: make(map[string]any)}, nil
}
func (s *Store) Get(key string) (any, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	v, ok := s.data[key]
	if !ok {
		return nil, errNotFound("not found")
	}
	return v, nil
}
func (s *Store) Set(key string, value any) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data[key] = value
	return nil
}
func (s *Store) Delete(key string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.data, key)
	return nil
}
func (s *Store) List() (map[string]any, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make(map[string]any, len(s.data))
	for k, v := range s.data {
		out[k] = v
	}
	return out, nil
}
func (s *Store) Close() error { return nil }

type errNotFound string

func (e errNotFound) Error() string { return string(e) }
