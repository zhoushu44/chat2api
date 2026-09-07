package image

import (
	"fmt"
	"os"
	"path/filepath"

	"chatgpt2api/internal/config"
)

// Storage 图片存储抽象，对等 image_storage_service.py
type Storage interface {
	Save(name string, data []byte) (string, error)
	Load(name string) ([]byte, error)
	Delete(name string) error
}

// safeJoin 本地路径拼接 + .. 上跳防护（路径须在 dir 内）。
func safeJoin(dir, name string) (string, error) {
	clean := safeRel(name)
	full := filepath.Join(dir, filepath.FromSlash(clean))
	absDir, err := filepath.Abs(dir)
	if err != nil {
		return "", err
	}
	absFull, err := filepath.Abs(full)
	if err != nil {
		return "", err
	}
	rel, err := filepath.Rel(absDir, absFull)
	if err != nil || rel == ".." || len(rel) > 2 && rel[:3] == "../" {
		return "", ErrUnsafePath
	}
	return full, nil
}

// ErrUnsafePath 越权路径。
var ErrUnsafePath = errUnsafePath()

func errUnsafePath() error {
	return fmt.Errorf("unsafe storage path")
}

type LocalStorage struct {
	Dir string
}

func NewLocal(dir string) *LocalStorage {
	_ = os.MkdirAll(dir, 0755)
	return &LocalStorage{Dir: dir}
}
func (s *LocalStorage) Save(name string, data []byte) (string, error) {
	path, err := safeJoin(s.Dir, name)
	if err != nil {
		return "", err
	}
	_ = os.MkdirAll(filepath.Dir(path), 0755)
	if err := os.WriteFile(path, data, 0644); err != nil {
		return "", err
	}
	return path, nil
}
func (s *LocalStorage) Load(name string) ([]byte, error) {
	path, err := safeJoin(s.Dir, name)
	if err != nil {
		return nil, err
	}
	return os.ReadFile(path)
}
func (s *LocalStorage) Delete(name string) error {
	path, err := safeJoin(s.Dir, name)
	if err != nil {
		return err
	}
	return os.Remove(path)
}

// WebDAVStorage 远端存储（P1.5：真实 WebDAV，替换旧 R2 假桩；Python 侧即 WebDAV，local/webdav/both 三模式）。
type WebDAVStorage struct {
	Client *WebDAVClient
	local  *LocalStorage // both 模式同时写本地
}

// NewWebDAVStorage 创建远端存储（localDir 空则纯远端，否则 both 模式）。
func NewWebDAVStorage(webdavURL, username, password, root, localDir string) *WebDAVStorage {
	var l *LocalStorage
	if localDir != "" {
		l = NewLocal(localDir)
	}
	return &WebDAVStorage{Client: NewWebDAVClient(webdavURL, username, password, root), local: l}
}

func (s *WebDAVStorage) Save(name string, data []byte) (string, error) {
	u, err := s.Client.Put(safeRel(name), data, "image/png")
	if err != nil {
		return "", err
	}
	if s.local != nil {
		_, _ = s.local.Save(name, data)
	}
	return u, nil
}
func (s *WebDAVStorage) Load(name string) ([]byte, error) {
	if s.local != nil {
		if b, err := s.local.Load(name); err == nil {
			return b, nil
		}
	}
	b, err := s.Client.Get(safeRel(name))
	if err != nil {
		return nil, err
	}
	if s.local != nil {
		_, _ = s.local.Save(name, b)
	}
	return b, nil
}
func (s *WebDAVStorage) Delete(name string) error {
	if s.local != nil {
		_ = s.local.Delete(name)
	}
	_, err := s.Client.Delete(safeRel(name))
	return err
}

// Test 连通性检查（对等 Python /api/image-storage/test）。
func (s *WebDAVStorage) Test() TestResult {
	return s.Client.Test()
}

// StorageFromConfig 按 image_storage 配置选择存储（P2.7：local|webdav|both）。
func StorageFromConfig(dataDir string, cfg *config.ImageStorageConfig) Storage {
	if cfg == nil || !cfg.Enabled || cfg.Mode == "" || cfg.Mode == "local" {
		return NewLocal(dataDir)
	}
	local := ""
	if cfg.Mode == "both" {
		local = dataDir
	}
	return NewWebDAVStorage(cfg.WebDAVURL, cfg.WebDAVUser, cfg.WebDAVPass, cfg.WebDAVRoot, local)
}
