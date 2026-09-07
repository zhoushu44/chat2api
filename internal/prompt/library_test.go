package prompt

import (
	"os"
	"path/filepath"
	"testing"
)

// TestDefaultLibraryLoaded P1.3 验收：301 条默认库已 embed 并加载。
func TestDefaultLibraryLoaded(t *testing.T) {
	s := New()
	if n := s.Count(); n < 300 {
		t.Fatalf("default library count=%d, want >=300 (301 expected)", n)
	}
	// 抽查首条结构完整
	if p, ok := s.Get("glasses"); !ok {
		t.Fatal("glasses prompt missing")
	} else {
		if p.Title == "" || p.Prompt == "" || p.Category == "" {
			t.Fatalf("glasses prompt fields incomplete: %+v", p)
		}
		if !p.QuickAccess {
			t.Fatal("glasses should be quick_access")
		}
	}
}

// TestPromptPersistence P1.3：用户增改持久化（重启恢复）。
func TestPromptPersistence(t *testing.T) {
	dir := t.TempDir()
	s1 := NewWithDir(dir)
	p := &Prompt{ID: "custom-1", Title: "自定义", Prompt: "a cat in space", Category: "用户", Mode: "generate", SortOrder: 999}
	if err := s1.Add(p); err != nil {
		t.Fatal(err)
	}
	if err := s1.Delete("glasses"); err != nil {
		t.Fatal(err)
	}
	// 重启：新建实例从 dir 恢复
	s2 := NewWithDir(dir)
	if _, ok := s2.Get("custom-1"); !ok {
		t.Fatal("custom-1 not persisted")
	}
	if _, ok := s2.Get("glasses"); ok {
		t.Fatal("glasses should be deleted (deletion persisted)")
	}
	if n := s2.Count(); n != s1.Count() {
		t.Fatalf("count mismatch after restart: %d vs %d", s2.Count(), s1.Count())
	}
	_ = filepath.Join
	_ = os.ReadFile
}

// TestQueryFilter P1.3：分类/快捷过滤。
func TestQueryFilter(t *testing.T) {
	s := New()
	quick := s.Query("", "", true)
	if len(quick) == 0 {
		t.Fatal("no quick_access prompts")
	}
	for _, p := range quick {
		if !p.QuickAccess {
			t.Fatalf("non-quick prompt in quickOnly result: %s", p.ID)
		}
	}
	cats := s.Categories()
	if len(cats) == 0 {
		t.Fatal("no categories")
	}
	// 按 category 过滤结果都属于该分类
	for _, c := range cats {
		for _, p := range s.Query(c, "", false) {
			if p.Category != c {
				t.Fatalf("category filter broken: %s in %q", p.ID, c)
			}
		}
	}
}

// TestListSorted P1.3：按 sort_order 排序。
func TestListSorted(t *testing.T) {
	s := New()
	list := s.List()
	if len(list) < 300 {
		t.Fatalf("list len=%d", len(list))
	}
	for i := 1; i < len(list); i++ {
		if list[i].SortOrder < list[i-1].SortOrder {
			t.Fatalf("sort broken at %d: %d < %d", i, list[i].SortOrder, list[i-1].SortOrder)
		}
	}
}
