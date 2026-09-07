package db

import "sync"

type DBStorage struct {
	mu   sync.RWMutex
	data map[string]any
}

func New(dataDir string) (*DBStorage, error) {
	return &DBStorage{data: make(map[string]any)}, nil
}
func (s *DBStorage) Get(key string) (any, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	v, ok := s.data[key]
	if !ok {
		return nil, ErrNotFound
	}
	return v, nil
}
func (s *DBStorage) Set(key string, value any) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data[key] = value
	return nil
}
func (s *DBStorage) Delete(key string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.data, key)
	return nil
}
func (s *DBStorage) List() (map[string]any, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make(map[string]any, len(s.data))
	for k, v := range s.data {
		out[k] = v
	}
	return out, nil
}
func (s *DBStorage) Close() error { return nil }

var ErrNotFound = errNotFound("not found")

type errNotFound string

func (e errNotFound) Error() string { return string(e) }
