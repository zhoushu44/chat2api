// Package prompt 提示词库（P1.3：301 条默认库 embed + 持久化 CRUD）。
// 对等 prompt_library_service.py + default_prompt_library.json。
package prompt

import (
	"embed"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"sync"
)

//go:embed default_prompt_library.json
var defaultLibraryFS embed.FS

// Prompt 对等 default_prompt_library.json 单条结构（全字段）。
type Prompt struct {
	ID          string `json:"id"`
	Title       string `json:"title"`
	Description string `json:"description,omitempty"`
	Mode        string `json:"mode,omitempty"` // edit | generate
	ImageCount  string `json:"image_count,omitempty"`
	ImageSize   string `json:"image_size,omitempty"`
	Icon        string `json:"icon,omitempty"`
	QuickAccess bool   `json:"quick_access,omitempty"`
	SortOrder   int    `json:"sort_order,omitempty"`
	Category    string `json:"category,omitempty"`
	SubCategory string `json:"sub_category,omitempty"`
	Preview     string `json:"preview,omitempty"`
	Prompt      string `json:"prompt"`
	Author      string `json:"author,omitempty"`
	Link        string `json:"link,omitempty"`
}

type libraryFile struct {
	Source  string    `json:"source"`
	Version string    `json:"version"`
	Prompts []*Prompt `json:"prompts"`
}

// Service 提示词库：默认库（embed）+ 用户增改（JSON 持久化覆盖）。
// 删除默认库条目时写 tombstone（deleted ids），重启后不复活。
type Service struct {
	mu       sync.RWMutex
	prompts  map[string]*Prompt
	deleted  map[string]bool // tombstone：被删除的默认库 ID
	dir      string
}

// New 创建服务：加载默认库，再叠加 dir/prompts.json 的用户数据。
func New() *Service {
	return NewWithDir("")
}

// NewWithDir 指定持久化目录（空串则纯内存）。
func NewWithDir(dir string) *Service {
	s := &Service{prompts: make(map[string]*Prompt), deleted: make(map[string]bool), dir: dir}
	s.loadDefaults()
	if dir != "" {
		s.loadOverrides()
	}
	return s
}

// loadDefaults 解析 embed 的 301 条默认库。
// 数据来源混合两种 schema：早期条目带 id，后续 290 条无 id（以 title 为标识）——
// 对齐 Python prompt_library_service 的 slug 化处理：无 id 时由 title 生成。
func (s *Service) loadDefaults() {
	b, err := defaultLibraryFS.ReadFile("default_prompt_library.json")
	if err != nil {
		return
	}
	var lib libraryFile
	if err := json.Unmarshal(b, &lib); err != nil {
		return
	}
	for _, p := range lib.Prompts {
		if p.ID == "" {
			p.ID = TitleSlug(p.Title)
		}
		if p.ID != "" {
			s.prompts[p.ID] = p
		}
	}
}

// TitleSlug title → 稳定 ID（对齐 Python slugify：非字母数字折叠为 -，压缩连续 -）。
// 中文标题保留原字符（与 Python unicodedata 处理一致），仅替换分隔符。
func TitleSlug(title string) string {
	if title == "" {
		return ""
	}
	out := make([]rune, 0, len(title))
	lastDash := false
	for _, r := range title {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9',
			r >= '\u4e00' && r <= '\u9fff': // CJK 统一表意文字
			out = append(out, r)
			lastDash = false
		default:
			if !lastDash && len(out) > 0 {
				out = append(out, '-')
				lastDash = true
			}
		}
	}
	// 去尾部 -
	if len(out) > 0 && out[len(out)-1] == '-' {
		out = out[:len(out)-1]
	}
	return string(out)
}

// loadOverrides 用户覆盖/新增/删除记录。
// 文件 schema：{"prompts": [...], "deleted_ids": [...]}，同 ID 覆盖默认，deleted_ids 为 tombstone。
func (s *Service) loadOverrides() {
	b, err := os.ReadFile(filepath.Join(s.dir, "prompts.json"))
	if err != nil {
		return
	}
	var state struct {
		Prompts    []*Prompt `json:"prompts"`
		DeletedIDs []string  `json:"deleted_ids"`
	}
	if err := json.Unmarshal(b, &state); err != nil {
		return
	}
	for _, id := range state.DeletedIDs {
		s.deleted[id] = true
		delete(s.prompts, id)
	}
	for _, p := range state.Prompts {
		if p.ID == "" {
			p.ID = TitleSlug(p.Title)
		}
		if p.ID != "" {
			s.prompts[p.ID] = p
			delete(s.deleted, p.ID) // 重新添加则清除 tombstone
		}
	}
}

// flush 持久化状态（存活条目 + tombstone）。
func (s *Service) flush() error {
	if s.dir == "" {
		return nil
	}
	state := struct {
		Prompts    []*Prompt `json:"prompts"`
		DeletedIDs []string  `json:"deleted_ids"`
	}{Prompts: s.listLocked()}
	for id := range s.deleted {
		state.DeletedIDs = append(state.DeletedIDs, id)
	}
	if state.DeletedIDs == nil {
		state.DeletedIDs = []string{}
	}
	b, err := json.Marshal(state)
	if err != nil {
		return err
	}
	tmp := filepath.Join(s.dir, "prompts.json.tmp")
	if err := os.WriteFile(tmp, b, 0644); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(s.dir, "prompts.json"))
}

func (s *Service) listLocked() []*Prompt {
	out := make([]*Prompt, 0, len(s.prompts))
	for _, v := range s.prompts {
		out = append(out, v)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].SortOrder != out[j].SortOrder {
			return out[i].SortOrder < out[j].SortOrder
		}
		return out[i].ID < out[j].ID
	})
	return out
}

// Add 新增/覆盖一条（持久化）。
func (s *Service) Add(p *Prompt) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if p.ID == "" {
		return ErrIDRequired
	}
	s.prompts[p.ID] = p
	return s.flush()
}

// Get 按 ID 查询。
func (s *Service) Get(id string) (*Prompt, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	p, ok := s.prompts[id]
	return p, ok
}

// List 全量（按 sort_order 排序）。
func (s *Service) List() []*Prompt {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.listLocked()
}

// Query 分类过滤（对齐 Python list 过滤参数：category/quick_access/mode）。
func (s *Service) Query(category, mode string, quickOnly bool) []*Prompt {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []*Prompt
	for _, p := range s.listLocked() {
		if category != "" && p.Category != category {
			continue
		}
		if mode != "" && p.Mode != mode {
			continue
		}
		if quickOnly && !p.QuickAccess {
			continue
		}
		out = append(out, p)
	}
	return out
}

// Categories 去重分类列表。
func (s *Service) Categories() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	seen := make(map[string]bool)
	for _, p := range s.prompts {
		if p.Category != "" {
			seen[p.Category] = true
		}
	}
	out := make([]string, 0, len(seen))
	for c := range seen {
		out = append(out, c)
	}
	sort.Strings(out)
	return out
}

// Delete 删除（持久化；默认库条目删除后写 tombstone，重启不复活）。
func (s *Service) Delete(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.prompts, id)
	s.deleted[id] = true
	return s.flush()
}

// Count 条目数。
func (s *Service) Count() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.prompts)
}

// ErrIDRequired id 缺失。
var ErrIDRequired = &Error{Msg: "prompt id required"}

// Error 服务错误。
type Error struct{ Msg string }

func (e *Error) Error() string { return e.Msg }
