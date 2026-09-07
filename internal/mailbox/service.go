package mailbox

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
)

type Service struct {
	mu   sync.RWMutex
	pool *Pool
	dir  string
}

func NewService(dir string) *Service {
	s := &Service{pool: NewPool(), dir: dir}
	if dir != "" {
		_ = os.MkdirAll(dir, 0755)
		if b, err := os.ReadFile(filepath.Join(dir, "mailboxes.json")); err == nil {
			var entries []Entry
			if json.Unmarshal(b, &entries) == nil {
				s.pool.Import(entries)
			}
		}
	}
	return s
}

func (s *Service) Import(entries []Entry) {
	s.pool.Import(entries)
	s.flush()
}

func (s *Service) Reserve() (*Lease, *Entry, error) { return s.pool.Reserve() }
func (s *Service) Commit(token string) error        { return s.pool.Commit(token) }
func (s *Service) Release(token string) error       { return s.pool.Release(token) }
func (s *Service) Stats() map[string]int            { return s.pool.Stats() }

func (s *Service) flush() {
	if s.dir == "" {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	// 持久化 entries
	entries := make([]Entry, 0, len(s.pool.entries))
	for _, e := range s.pool.entries {
		entries = append(entries, *e)
	}
	b, _ := json.MarshalIndent(entries, "", "  ")
	tmp := filepath.Join(s.dir, "mailboxes.json.tmp")
	_ = os.WriteFile(tmp, b, 0644)
	_ = os.Rename(tmp, filepath.Join(s.dir, "mailboxes.json"))
}
