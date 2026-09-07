package db

import "testing"

func TestDB_CRUD(t *testing.T) {
	s, _ := New(t.TempDir())
	_ = s.Set("k", map[string]int{"a": 1})
	v, _ := s.Get("k")
	if v == nil {
		t.Fatal()
	}
	_ = s.Delete("k")
	if _, err := s.Get("k"); err == nil {
		t.Fatal("should not found")
	}
}
