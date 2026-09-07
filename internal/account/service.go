package account

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
)

func NormalizeSourceType(s string) string {
	switch s {
	case "codex", "web": return s
	default: return "web"
	}
}
func NormalizeAccountType(s string) string {
	switch s {
	case "Plus","Team","Pro","Free": return s
	default: return "Plus"
	}
}

type Service struct {
	mu   sync.RWMutex
	dir  string
	accounts map[string]*Account
}

func New(dir string) *Service {
	s := &Service{dir: dir, accounts: make(map[string]*Account)}
	_ = os.MkdirAll(dir, 0755)
	if b, err := os.ReadFile(filepath.Join(dir, "accounts.json")); err == nil {
		_ = json.Unmarshal(b, &s.accounts)
	}
	return s
}
func (s *Service) Add(a *Account) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if a.ID == "" {
		a.ID = a.Email
	}
	if a.ID == "" && len(a.Token) >= 8 {
		a.ID = a.Token[:8]
	} else if a.ID == "" {
		a.ID = a.Token
	}
	if a.ID == "" {
		a.ID = "acc"
	}
	s.accounts[a.ID]=a
	return s.flush()
}
func (s *Service) Get(id string) (*Account, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	a, ok := s.accounts[id]
	return a, ok
}
func (s *Service) List() []*Account {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]*Account, 0, len(s.accounts))
	for _, v := range s.accounts { out=append(out, v) }
	return out
}
func (s *Service) Delete(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.accounts, id)
	return s.flush()
}
func (s *Service) flush() error {
	b, _ := json.Marshal(s.accounts)
	tmp := filepath.Join(s.dir, "accounts.json.tmp")
	_ = os.WriteFile(tmp, b, 0644)
	return os.Rename(tmp, filepath.Join(s.dir, "accounts.json"))
}
