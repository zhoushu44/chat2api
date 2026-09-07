package logsvc

import (
	"testing"
	"time"
)

func TestLogsvc(t *testing.T) {
	s := New(2)
	s.Add(&LoggedCall{ID: "1", Prompt: "a"})
	s.Add(&LoggedCall{ID: "2"})
	s.Add(&LoggedCall{ID: "3"})
	if len(s.List()) != 2 {
		t.Fatal("ring buffer failed")
	}
	if _, ok := s.Get("1"); ok {
		t.Fatal("should evicted")
	}
}

// TestPersistAndRestart P1.7 验收：JSONL 落盘 + 重启恢复（修复前仅内存）。
func TestPersistAndRestart(t *testing.T) {
	dir := t.TempDir()
	s1 := NewWithDir(dir, 100)
	s1.Add(&LoggedCall{ID: "a", Prompt: "cat", Model: "gpt-image-2", Status: "success", CreatedAt: time.Now()})
	s1.Add(&LoggedCall{ID: "b", Prompt: "dog", Model: "gpt-image-2", Status: "error", CreatedAt: time.Now()})
	if err := s1.Close(); err != nil {
		t.Fatal(err)
	}
	// 重启：新实例恢复
	s2 := NewWithDir(dir, 100)
	list := s2.List()
	if len(list) != 2 {
		t.Fatalf("recovered=%d want 2", len(list))
	}
	if _, ok := s2.Get("a"); !ok {
		t.Fatal("call a missing after restart")
	}
	if _, ok := s2.Get("b"); !ok {
		t.Fatal("call b missing after restart")
	}
	_ = s2.Close()
}

// TestRecoverTailCap P1.7：恢复不超过 cap（尾部读取）。
func TestRecoverTailCap(t *testing.T) {
	dir := t.TempDir()
	s1 := NewWithDir(dir, 2)
	for _, id := range []string{"1", "2", "3", "4"} {
		s1.Add(&LoggedCall{ID: id})
	}
	_ = s1.Close()
	s2 := NewWithDir(dir, 2)
	list := s2.List()
	if len(list) != 2 {
		t.Fatalf("recovered=%d want 2", len(list))
	}
	if _, ok := s2.Get("3"); !ok {
		t.Fatal("tail call 3 missing")
	}
	if _, ok := s2.Get("4"); !ok {
		t.Fatal("tail call 4 missing")
	}
	_ = s2.Close()
}
