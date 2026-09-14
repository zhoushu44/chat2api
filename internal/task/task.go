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

// Asset 单张结果图（对等前端 ImageTaskAsset）。
type Asset struct {
	URL           string `json:"url,omitempty"`
	Path          string `json:"path,omitempty"`
	B64JSON       string `json:"b64_json,omitempty"`
	RevisedPrompt string `json:"revised_prompt,omitempty"`
}

type Task struct {
	ID        string    `json:"id"`
	Status    Status    `json:"status"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`

	// 图像任务元信息（前端 ImageTasks 页契约）
	Mode     string `json:"mode,omitempty"`
	Model    string `json:"model,omitempty"`
	N        int    `json:"n,omitempty"`
	Size     string `json:"size,omitempty"`
	Quality  string `json:"quality,omitempty"`
	Stage    string `json:"stage,omitempty"`
	Progress string `json:"progress,omitempty"`

	ConversationID string  `json:"conversation_id,omitempty"`
	Data           []Asset `json:"data,omitempty"`
	Usage          any     `json:"usage,omitempty"`

	Error            string `json:"error,omitempty"`
	ErrorCode        string `json:"error_code,omitempty"`
	Reason           string `json:"reason,omitempty"`
	UpstreamErrorTyp string `json:"upstream_error_type,omitempty"`

	DurationMS int64 `json:"duration_ms,omitempty"`
	ElapsedSec float64 `json:"elapsed_secs,omitempty"`

	Result    any    `json:"result,omitempty"`
	CanResume bool   `json:"can_resume_poll"`
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

// Save 新建/覆盖任务（图像任务入口，携带完整元信息）。
func (s *Service) Save(t *Task) *Task {
	if t.CreatedAt.IsZero() {
		t.CreatedAt = time.Now()
	}
	t.UpdatedAt = time.Now()
	s.mu.Lock()
	s.tasks[t.ID] = t
	s.dirty = true
	s.mu.Unlock()
	select {
	case s.flushCh <- struct{}{}:
	default:
	}
	return t
}

// UpdateFunc 原子更新任务（持写锁调用 fn）。
func (s *Service) UpdateFunc(id string, fn func(t *Task)) {
	s.mu.Lock()
	if t, ok := s.tasks[id]; ok {
		fn(t)
		t.UpdatedAt = time.Now()
		s.dirty = true
	}
	s.mu.Unlock()
	select {
	case s.flushCh <- struct{}{}:
	default:
	}
}

func (s *Service) Update(id string, status Status, result any, errMsg string) {
	s.UpdateFunc(id, func(t *Task) {
		t.Status = status
		t.Result = result
		t.Error = errMsg
	})
}
func (s *Service) Get(id string) (*Task, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	t, ok := s.tasks[id]
	return t, ok
}

// ListByIDs 按 id 集合取任务；ids 为空返回全部。
func (s *Service) ListByIDs(ids []string) []*Task {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if len(ids) == 0 {
		out := make([]*Task, 0, len(s.tasks))
		for _, v := range s.tasks {
			out = append(out, v)
		}
		return out
	}
	out := make([]*Task, 0, len(ids))
	for _, id := range ids {
		if t, ok := s.tasks[id]; ok {
			out = append(out, t)
		}
	}
	return out
}

func (s *Service) List() []*Task {
	return s.ListByIDs(nil)
}
func (s *Service) CanResumePoll(id string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if t, ok := s.tasks[id]; ok {
		return t.CanResume && t.Status == Error
	}
	return false
}

// MarkResumable 恢复轮询：重置为 queued 并允许继续等待（前端 resume-poll 入口）。
func (s *Service) MarkResumable(id string) (*Task, bool) {
	var out *Task
	s.mu.Lock()
	if t, ok := s.tasks[id]; ok {
		t.Status = Queued
		t.Stage = "queued"
		t.Progress = ""
		t.Error = ""
		t.ErrorCode = ""
		t.CanResume = true
		t.UpdatedAt = time.Now()
		s.dirty = true
		out = t
	}
	s.mu.Unlock()
	if out == nil {
		return nil, false
	}
	select {
	case s.flushCh <- struct{}{}:
	default:
	}
	return out, true
}
