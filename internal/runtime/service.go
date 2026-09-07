package runtime

import (
	"sync"
	"time"
)

type Log struct {
	At      time.Time `json:"at"`
	Level   string    `json:"level"`
	Message string    `json:"message"`
}

type Service struct {
	mu   sync.RWMutex
	logs []Log
	cap  int
}

func New(cap int) *Service {
	if cap == 0 {
		cap = 1000
	}
	return &Service{cap: cap}
}

func (s *Service) Add(level, msg string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.logs) >= s.cap {
		s.logs = s.logs[1:]
	}
	s.logs = append(s.logs, Log{At: time.Now(), Level: level, Message: msg})
}

func (s *Service) List() []Log {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Log, len(s.logs))
	copy(out, s.logs)
	return out
}
