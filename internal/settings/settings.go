// Package settings 负责控制台「系统设置」页面的持久化。
//
// 与 internal/config 的分工：
//   - config.Config 来自启动参数 / config.json / 环境变量，是启动期的配置来源；
//   - settings.Store 保存控制台面板写入的覆盖项，落盘到 <dataDir>/settings.json。
//
// 两层在 config.Load 中合并：settings.json 存在时覆盖 config.Config 的对应字段，
// 从而让「面板保存 → 重启/热加载后仍生效」成立。
//
// 落盘格式与前端 settingsApi 的请求体一致（顶层扁平键 + 嵌套段），
// 因此 GET 直接回读该文件即可，无需再做形状转换。
package settings

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// Filename 设置文件名（位于 DataDir 下）。
const Filename = "settings.json"

// Data 面板设置的原始 JSON 对象。用 map 保存以保证前端的任意键（含未来的新字段）
// 都能原样落盘，不会因为结构体字段缺失而丢数据。
type Data map[string]any

// Store 设置存储：内存快照 + 原子落盘。
type Store struct {
	mu   sync.RWMutex
	path string
	data Data
}

// NewStore 创建存储；dir 为空时使用 "./data"。
// 文件不存在或损坏时以空设置启动（读取侧由 config 的默认值兜底）。
func NewStore(dir string) *Store {
	if strings.TrimSpace(dir) == "" {
		dir = "./data"
	}
	s := &Store{path: filepath.Join(dir, Filename), data: Data{}}
	if raw, err := os.ReadFile(s.path); err == nil {
		var loaded Data
		if json.Unmarshal(raw, &loaded) == nil && loaded != nil {
			s.data = loaded
		}
	}
	return s
}

// Path 返回落盘路径。
func (s *Store) Path() string {
	if s == nil {
		return ""
	}
	return s.path
}

// Snapshot 返回设置深拷贝（调用方可安全修改，不影响内部状态）。
func (s *Store) Snapshot() Data {
	if s == nil {
		return Data{}
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	return clone(s.data)
}

// Save 整体替换设置并原子落盘。
func (s *Store) Save(next Data) error {
	if s == nil {
		return nil
	}
	if next == nil {
		next = Data{}
	}
	s.mu.Lock()
	s.data = clone(next)
	payload := clone(s.data)
	path := s.path
	s.mu.Unlock()

	raw, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// clone 通过 JSON 往返做深拷贝，避免嵌套 map/slice 被共享。
func clone(in Data) Data {
	if len(in) == 0 {
		return Data{}
	}
	raw, err := json.Marshal(in)
	if err != nil {
		return Data{}
	}
	var out Data
	if json.Unmarshal(raw, &out) != nil || out == nil {
		return Data{}
	}
	return out
}
