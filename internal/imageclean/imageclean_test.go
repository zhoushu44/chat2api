package imageclean

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestCleanupOnceRemovesExpiredDirs(t *testing.T) {
	dir := t.TempDir()
	root := filepath.Join(dir, "images")
	oldDir := filepath.Join(root, time.Now().AddDate(0, 0, -30).Format("20060102"))
	newDir := filepath.Join(root, time.Now().Format("20060102"))
	otherDir := filepath.Join(root, "not-a-date")
	for _, d := range []string{oldDir, newDir, otherDir} {
		if err := os.MkdirAll(filepath.Join(d, "sub"), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(d, "a.png"), []byte("x"), 0644); err != nil {
			t.Fatal(err)
		}
	}
	c := &Cleaner{DataDir: dir, RetentionDays: func() int { return 15 }}
	removed := c.CleanupOnce()
	if removed != 1 {
		t.Fatalf("removed=%d, want 1（只删过期目录）", removed)
	}
	if _, err := os.Stat(oldDir); !os.IsNotExist(err) {
		t.Errorf("过期目录未删除")
	}
	if _, err := os.Stat(newDir); err != nil {
		t.Errorf("当日目录被误删: %v", err)
	}
	if _, err := os.Stat(otherDir); err != nil {
		t.Errorf("非日期目录被误删: %v", err)
	}
}

func TestRetentionDaysFallback(t *testing.T) {
	c := &Cleaner{RetentionDays: func() int { return 0 }}
	if got := c.retentionDays(); got != 15 {
		t.Fatalf("默认保留天数=%d, want 15", got)
	}
	c2 := &Cleaner{RetentionDays: func() int { return 3 }}
	if got := c2.retentionDays(); got != 3 {
		t.Fatalf("注入保留天数=%d, want 3", got)
	}
}

func TestCleanupMissingDirNoError(t *testing.T) {
	c := &Cleaner{DataDir: filepath.Join(t.TempDir(), "nope")}
	if got := c.CleanupOnce(); got != 0 {
		t.Fatalf("空目录 removed=%d, want 0", got)
	}
}
