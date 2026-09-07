package logsvc

import (
	"sync"
	"time"
)

type RuntimeLog struct {
	At      time.Time `json:"at"`
	Message string    `json:"message"`
}

type RuntimeService struct {
	mu   sync.RWMutex
	logs []RuntimeLog
}

func NewRuntime() *RuntimeService {
	return &RuntimeService{}
}

func (s *RuntimeService) Add(msg string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.logs = append(s.logs, RuntimeLog{At: time.Now(), Message: msg})
	if len(s.logs) > 1000 {
		s.logs = s.logs[1:]
	}
}

func (s *RuntimeService) List() []RuntimeLog {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]RuntimeLog, len(s.logs))
	copy(out, s.logs)
	return out
}
