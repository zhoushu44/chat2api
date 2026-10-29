package settings

import (
	"os"
	"path/filepath"
	"testing"
)

func TestNewStoreMissingFileStartsEmpty(t *testing.T) {
	dir := t.TempDir()
	s := NewStore(dir)
	if got := len(s.Snapshot()); got != 0 {
		t.Fatalf("expected empty settings, got %d keys", got)
	}
	if s.Path() != filepath.Join(dir, Filename) {
		t.Fatalf("unexpected path: %s", s.Path())
	}
}

func TestSaveThenLoad(t *testing.T) {
	dir := t.TempDir()
	s := NewStore(dir)
	if err := s.Save(Data{"base_url": "https://a.example", "image_retention_days": 7}); err != nil {
		t.Fatalf("save: %v", err)
	}
	// 落盘后重新打开应能读回
	reopened := NewStore(dir)
	snap := reopened.Snapshot()
	if snap["base_url"] != "https://a.example" {
		t.Fatalf("base_url=%v", snap["base_url"])
	}
	if snap["image_retention_days"] != float64(7) {
		t.Fatalf("image_retention_days=%v (%T)", snap["image_retention_days"], snap["image_retention_days"])
	}
}

func TestSaveIsAtomicAndReplaces(t *testing.T) {
	dir := t.TempDir()
	s := NewStore(dir)
	if err := s.Save(Data{"base_url": "a"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Save(Data{"image_retention_days": 3}); err != nil {
		t.Fatal(err)
	}
	snap := s.Snapshot()
	if _, ok := snap["base_url"]; ok {
		t.Fatal("second save should fully replace previous settings")
	}
	if _, err := os.Stat(filepath.Join(dir, Filename+".tmp")); !os.IsNotExist(err) {
		t.Fatal("temp file should be renamed away")
	}
}

func TestSnapshotIsDeepCopy(t *testing.T) {
	s := NewStore(t.TempDir())
	if err := s.Save(Data{"image_storage": map[string]any{"mode": "local"}}); err != nil {
		t.Fatal(err)
	}
	snap := s.Snapshot()
	snap["image_storage"].(map[string]any)["mode"] = "webdav"
	if got := s.Snapshot()["image_storage"].(map[string]any)["mode"]; got != "local" {
		t.Fatalf("snapshot mutation leaked into store: %v", got)
	}
}

func TestCorruptedFileFallsBackToEmpty(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, Filename), []byte("{not json"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := len(NewStore(dir).Snapshot()); got != 0 {
		t.Fatalf("expected empty settings on corrupt file, got %d", got)
	}
}
