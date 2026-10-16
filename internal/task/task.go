package task

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type Status string

const (
	Queued  Status = "queued"
	Running Status = "running"
	Success Status = "success"
	Error   Status = "error"
)

type Task struct {
	ID        string    `json:"id"`
	Status    Status    `json:"status"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
	Result    any       `json:"result,omitempty"`
	Error     string    `json:"error,omitempty"`
	CanResume bool      `json:"can_resume_poll"`
}

type Service struct {
	mu       sync.RWMutex
	dir      string
	tasks    map[string]*Task
	dirty    bool
	flushCh  chan struct{}
	stopCh   chan struct{}
}

func New(dir string) *Service {
	s := &Service{dir: dir, tasks: make(map[string]*Task), flushCh: make(chan struct{}, 1), stopCh: make(chan struct{})}
	_ = os.MkdirAll(dir, 0755)
	// 尝试读取，带 500ms 重试以兼容批量异步落盘
	for i := 0; i < 5; i++ {
		if b, err := os.ReadFile(filepath.Join(dir, "tasks.json")); err == nil {
			_ = json.Unmarshal(b, &s.tasks)
			break
		}
		if i < 4 {
			time.Sleep(50 * time.Millisecond)
		}
	}
	go s.flushLoop()
	return s
}

func (s *Service) flushLoop() {
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

func (s *Service) doFlush() {
	s.mu.Lock()
	if !s.dirty {
		s.mu.Unlock()
		return
	}
	// 拷贝快照，避免持锁期间 Marshal
	snap := make(map[string]*Task, len(s.tasks))
	for k, v := range s.tasks {
		snap[k] = v
	}
	s.dirty = false
	s.mu.Unlock()
	b, _ := json.Marshal(snap)
	tmp := filepath.Join(s.dir, "tasks.json.tmp")
	_ = os.WriteFile(tmp, b, 0644)
	_ = os.Rename(tmp, filepath.Join(s.dir, "tasks.json"))
}

func (s *Service) Flush() {
	s.doFlush()
}

func (s *Service) Close() {
	select {
	case <-s.stopCh:
		// 已关闭
	default:
		close(s.stopCh)
	}
	s.doFlush()
}
func (s *Service) Create(id string) *Task {
	s.mu.Lock()
	t := &Task{ID: id, Status: Queued, CreatedAt: time.Now(), UpdatedAt: time.Now(), CanResume: true}
	s.tasks[id] = t
	s.dirty = true
	s.mu.Unlock()
	select {
	case s.flushCh <- struct{}{}:
	default:
	}
	return t
}
func (s *Service) Update(id string, status Status, result any, errMsg string) {
	s.mu.Lock()
	if t, ok := s.tasks[id]; ok {
		t.Status = status
		t.Result = result
		t.Error = errMsg
		t.UpdatedAt = time.Now()
		s.dirty = true
	}
	s.mu.Unlock()
	select {
	case s.flushCh <- struct{}{}:
	default:
	}
}
func (s *Service) Get(id string) (*Task, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	t, ok := s.tasks[id]
	return t, ok
}
func (s *Service) List() []*Task {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]*Task, 0, len(s.tasks))
	for _, v := range s.tasks {
		out = append(out, v)
	}
	return out
}
func (s *Service) CanResumePoll(id string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if t, ok := s.tasks[id]; ok {
		return t.CanResume && t.Status == Error
	}
	return false
}
