package storage

import (
	"fmt"
	"os"

	"chatgpt2api/internal/storage/db"
	gitstorage "chatgpt2api/internal/storage/git"
	jsonstorage "chatgpt2api/internal/storage/json"
	"chatgpt2api/internal/storage/pebble"
)

func init() {
	Register("json", func(dir string) (Storage, error) { return jsonstorage.New(dir) })
	Register("sqlite", func(dir string) (Storage, error) { return db.New(dir) })
	Register("postgres", func(dir string) (Storage, error) { return db.New(dir) })
	Register("git", func(dir string) (Storage, error) { return gitstorage.New(dir) })
	Register("pebble", func(dir string) (Storage, error) { return pebble.New(dir) })
}

// NewFromEnv 根据 STORAGE_BACKEND 环境变量创建
func NewFromEnv(dataDir string) (Storage, error) {
	backend := os.Getenv("STORAGE_BACKEND")
	if backend == "" {
		backend = "json"
	}
	f := GetFactory(backend)
	if f == nil {
		return nil, fmt.Errorf("unknown storage backend %s", backend)
	}
	return f(dataDir)
}
