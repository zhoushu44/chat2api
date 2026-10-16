package logsvc

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type LoggedCall struct {
	ID        string    `json:"id"`
	Prompt    string    `json:"prompt"`
	Model     string    `json:"model"`
	Status    string    `json:"status"`
	CreatedAt time.Time `json:"created_at"`
	Attempts  []Attempt `json:"attempts"`
}

type Attempt struct {
	AccountID string `json:"account_id"`
	Code      string `json:"code"`
}

// Service 调用日志：内存环形缓冲 + JSONL 落盘（P1.7，对等 log_service image attempts）。
// dir 为空则纯内存；否则 Add 追加 JSONL，启动时从尾部恢复最近 cap 条。
type Service struct {
	mu   sync.RWMutex
	buf  []*LoggedCall
	cap  int
	dir  string
	file *os.File
}

const logFileName = "image_attempts.jsonl"

func New(cap int) *Service {
	if cap == 0 {
		cap = 1000
	}
	return &Service{cap: cap}
}

// NewWithDir 持久化服务（目录不存在则创建）。
func NewWithDir(dir string, cap int) *Service {
	if cap == 0 {
		cap = 1000
	}
	s := &Service{cap: cap, dir: dir}
	if dir == "" {
		return s
	}
	_ = os.MkdirAll(dir, 0755)
	s.recoverTail()
	f, err := os.OpenFile(filepath.Join(dir, logFileName), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err == nil {
		s.file = f
	}
	return s
}

// recoverTail 从 JSONL 尾部恢复最近 cap 条（对等 Python 启动加载）。
func (s *Service) recoverTail() {
	f, err := os.Open(filepath.Join(s.dir, logFileName))
	if err != nil {
		return
	}
	defer f.Close()
	var lines []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1024*1024), 1024*1024)
	for sc.Scan() {
		lines = append(lines, sc.Text())
		if len(lines) > s.cap {
			lines = lines[len(lines)-s.cap:]
		}
	}
	for _, ln := range lines {
		var c LoggedCall
		if err := json.Unmarshal([]byte(ln), &c); err == nil && c.ID != "" {
			s.buf = append(s.buf, &c)
		}
	}
}

func (s *Service) Add(call *LoggedCall) {
	b, _ := json.Marshal(call)
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.buf) >= s.cap {
		s.buf = s.buf[1:]
	}
	s.buf = append(s.buf, call)
	// JSONL 追加落盘（对等 log_service add 落盘）
	if s.file != nil {
		_, _ = s.file.Write(append(b, '\n'))
	}
}
func (s *Service) List() []*LoggedCall {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]*LoggedCall, len(s.buf))
	copy(out, s.buf)
	return out
}
func (s *Service) Get(id string) (*LoggedCall, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, c := range s.buf {
		if c.ID == id {
			return c, true
		}
	}
	return nil, false
}

// Close 关闭落盘文件（优雅退出时调用）。
func (s *Service) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.file != nil {
		err := s.file.Close()
		s.file = nil
		return err
	}
	return nil
}
