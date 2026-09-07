// Package auth 多密钥鉴权体系（P2.6）：对等 services/auth_service.py。
// 角色 admin/user；密钥仅存 sha256 hash；JSON 持久化；authenticate 更新 last_used_at（60s 节流落盘）。
package auth

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
)

// Role 角色。
type Role string

const (
	RoleAdmin Role = "admin"
	RoleUser  Role = "user"
)

// Item 密钥条目（公开视图不含 key_hash）。
type Item struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Role       Role   `json:"role"`
	KeyHash    string `json:"key_hash,omitempty"`
	Enabled    bool   `json:"enabled"`
	CreatedAt  string `json:"created_at"`
	LastUsedAt string `json:"last_used_at,omitempty"`
}

// PublicItem 公开视图（对等 _public_item）。
func (i Item) PublicItem() map[string]any {
	return map[string]any{
		"id":           i.ID,
		"name":         i.Name,
		"role":         string(i.Role),
		"enabled":      i.Enabled,
		"created_at":   i.CreatedAt,
		"last_used_at": nilStr(i.LastUsedAt),
	}
}

func nilStr(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// Service 多密钥服务。
type Service struct {
	mu       sync.Mutex
	dir      string
	items    []Item
	lastFlush map[string]time.Time
	adminKey string // 管理员主密钥（冲突检测用）
}

// New 纯内存服务；NewWithDir 带持久化。
func New() *Service {
	return &Service{lastFlush: map[string]time.Time{}}
}

// NewWithDir 持久化目录 + 管理员主密钥（冲突检测）。
func NewWithDir(dir, adminKey string) *Service {
	s := New()
	s.dir = dir
	s.adminKey = adminKey
	if dir != "" {
		_ = os.MkdirAll(dir, 0755)
		s.items = s.load()
	}
	return s
}

const fileName = "auth_keys.json"

func hashKey(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

func (s *Service) load() []Item {
	b, err := os.ReadFile(filepath.Join(s.dir, fileName))
	if err != nil {
		return nil
	}
	var raw []Item
	if err := json.Unmarshal(b, &raw); err != nil {
		return nil
	}
	var out []Item
	for _, item := range raw {
		if n := normalizeItem(item); n != nil {
			out = append(out, *n)
		}
	}
	return out
}

func normalizeItem(raw Item) *Item {
	role := Role(strings.ToLower(strings.TrimSpace(string(raw.Role))))
	if role != RoleAdmin && role != RoleUser {
		return nil
	}
	if strings.TrimSpace(raw.KeyHash) == "" {
		return nil
	}
	if strings.TrimSpace(raw.ID) == "" {
		raw.ID = uuid.NewString()[:12]
	}
	if strings.TrimSpace(raw.Name) == "" {
		raw.Name = defaultName(role)
	}
	if strings.TrimSpace(raw.CreatedAt) == "" {
		raw.CreatedAt = time.Now().UTC().Format(time.RFC3339)
	}
	raw.Role = role
	return &raw
}

func defaultName(role Role) string {
	if role == RoleAdmin {
		return "管理员密钥"
	}
	return "普通用户"
}

func (s *Service) saveLocked() {
	if s.dir == "" {
		return
	}
	b, err := json.Marshal(s.items)
	if err != nil {
		return
	}
	tmp := filepath.Join(s.dir, fileName+".tmp")
	if err := os.WriteFile(tmp, b, 0644); err != nil {
		return
	}
	_ = os.Rename(tmp, filepath.Join(s.dir, fileName))
}

// ListKeys 列表（对等 list_keys，可按角色过滤）。
func (s *Service) ListKeys(role Role) []map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.dir != "" {
		s.items = s.load()
	}
	var out []map[string]any
	for _, item := range s.items {
		if role != "" && item.Role != role {
			continue
		}
		out = append(out, item.PublicItem())
	}
	if out == nil {
		out = []map[string]any{}
	}
	return out
}

func (s *Service) hasHashLocked(hash, excludeID string) bool {
	for _, item := range s.items {
		if excludeID != "" && item.ID == excludeID {
			continue
		}
		if item.KeyHash != "" && hmac.Equal([]byte(item.KeyHash), []byte(hash)) {
			return true
		}
	}
	return false
}

func (s *Service) buildHashLocked(rawKey, excludeID string) (string, error) {
	candidate := strings.TrimSpace(rawKey)
	if candidate == "" {
		return "", &ValueError{Msg: "请输入新的专用密钥"}
	}
	if s.adminKey != "" && hmac.Equal([]byte(candidate), []byte(s.adminKey)) {
		return "", &ValueError{Msg: "这个密钥和管理员密钥冲突了，请换一个新的密钥"}
	}
	hash := hashKey(candidate)
	if s.hasHashLocked(hash, excludeID) {
		return "", &ValueError{Msg: "这个专用密钥已经存在，请换一个新的密钥"}
	}
	return hash, nil
}

func (s *Service) hasNameLocked(name string, role Role, excludeID string) bool {
	candidate := strings.TrimSpace(name)
	if candidate == "" {
		return false
	}
	for _, item := range s.items {
		if excludeID != "" && item.ID == excludeID {
			continue
		}
		if role != "" && item.Role != role {
			continue
		}
		if strings.TrimSpace(item.Name) == candidate {
			return true
		}
	}
	return false
}

func (s *Service) buildNameLocked(name string, role Role, excludeID string) (string, error) {
	candidate := strings.TrimSpace(name)
	if candidate == "" {
		base := defaultName(role)
		if !s.hasNameLocked(base, role, excludeID) {
			return base, nil
		}
		for suffix := 2; ; suffix++ {
			c := base + " " + itoa(suffix)
			if !s.hasNameLocked(c, role, excludeID) {
				return c, nil
			}
		}
	}
	if s.hasNameLocked(candidate, role, excludeID) {
		return "", &ValueError{Msg: "这个名称已经在使用中了，换一个更容易区分的名称吧"}
	}
	return candidate, nil
}

func itoa(n int) string {
	return strconv.Itoa(n)
}

// CreateKey 创建密钥（对等 create_key；返回公开条目 + 原始密钥明文，仅此一次可见）。
func (s *Service) CreateKey(role Role, name string) (map[string]any, string, error) {
	if role != RoleAdmin && role != RoleUser {
		return nil, "", &ValueError{Msg: "role must be admin or user"}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.dir != "" {
		s.items = s.load()
	}
	normalizedName, err := s.buildNameLocked(name, role, "")
	if err != nil {
		return nil, "", err
	}
	var rawKey, keyHash string
	for {
		rawKey = "sk-" + randomURLSafe(24)
		var err error
		keyHash, err = s.buildHashLocked(rawKey, "")
		if err == nil {
			break
		}
	}
	item := Item{
		ID:        uuid.NewString()[:12],
		Name:      normalizedName,
		Role:      role,
		KeyHash:   keyHash,
		Enabled:   true,
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	}
	s.items = append(s.items, item)
	s.saveLocked()
	return item.PublicItem(), rawKey, nil
}

func randomURLSafe(n int) string {
	const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
	b := make([]byte, n)
	_, _ = rand.Read(b)
	for i := range b {
		b[i] = chars[int(b[i])%len(chars)]
	}
	return string(b)
}

// KeyUpdate 更新字段（name/enabled/key 全可选）。
type KeyUpdate struct {
	Name    *string
	Enabled *bool
	Key     *string
}

// UpdateKey 更新密钥（对等 update_key；找不到返回 nil, nil）。
func (s *Service) UpdateKey(keyID string, updates KeyUpdate, role Role) (map[string]any, error) {
	id := strings.TrimSpace(keyID)
	if id == "" {
		return nil, nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.dir != "" {
		s.items = s.load()
	}
	for i, item := range s.items {
		if item.ID != id {
			continue
		}
		if role != "" && item.Role != role {
			return nil, nil
		}
		next := item
		nextRole := RoleUser
		if item.Role == RoleAdmin {
			nextRole = RoleAdmin
		}
		if updates.Name != nil {
			name, err := s.buildNameLocked(*updates.Name, nextRole, id)
			if err != nil {
				return nil, err
			}
			next.Name = name
		}
		if updates.Enabled != nil {
			next.Enabled = *updates.Enabled
		}
		if updates.Key != nil {
			hash, err := s.buildHashLocked(*updates.Key, id)
			if err != nil {
				return nil, err
			}
			next.KeyHash = hash
		}
		s.items[i] = next
		s.saveLocked()
		return next.PublicItem(), nil
	}
	return nil, nil
}

// DeleteKey 删除（对等 delete_key）。
func (s *Service) DeleteKey(keyID string, role Role) bool {
	id := strings.TrimSpace(keyID)
	if id == "" {
		return false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.dir != "" {
		s.items = s.load()
	}
	before := len(s.items)
	kept := s.items[:0]
	for _, item := range s.items {
		if item.ID == id && (role == "" || item.Role == role) {
			continue
		}
		kept = append(kept, item)
	}
	// 清零尾部（复用底层数组时避免泄漏引用——此处为值类型，无需）
	s.items = kept
	if len(s.items) == before {
		return false
	}
	s.saveLocked()
	return true
}

// Authenticate 校验密钥（对等 authenticate；更新 last_used_at，60s 节流落盘）。
func (s *Service) Authenticate(rawKey string) map[string]any {
	candidate := strings.TrimSpace(rawKey)
	if candidate == "" {
		return nil
	}
	candidateHash := hashKey(candidate)
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, item := range s.items {
		if !item.Enabled {
			continue
		}
		if item.KeyHash == "" || !hmac.Equal([]byte(item.KeyHash), []byte(candidateHash)) {
			continue
		}
		now := time.Now().UTC()
		s.items[i].LastUsedAt = now.Format(time.RFC3339)
		if last, ok := s.lastFlush[item.ID]; !ok || now.Sub(last) >= time.Minute {
			s.saveLocked()
			s.lastFlush[item.ID] = now
		}
		return s.items[i].PublicItem()
	}
	return nil
}

// ValueError 业务校验错误（对等 ValueError → 400）。
type ValueError struct{ Msg string }

func (e *ValueError) Error() string { return e.Msg }
