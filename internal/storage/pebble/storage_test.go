package pebble

import "testing"

func TestPebble_Batch(t *testing.T) {
	s, _ := New(t.TempDir())
	for i := 0; i < 2500; i++ {
		_ = s.Set("k", i)
	}
	if v, _ := s.Get("k"); v.(int) != 2499 {
		t.Fatal()
	}
	if _, err := s.List(); err != nil {
		t.Fatal()
	}
}
