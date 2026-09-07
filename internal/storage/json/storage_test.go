package jsonstorage

import "testing"

func TestJSON_CRUD(t *testing.T) {
	s, _ := New(t.TempDir())
	defer s.Close()
	if err := s.Set("k1", map[string]string{"a": "b"}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Get("k1"); err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	for i := 0; i < 10; i++ {
		go func(n int) { _ = s.Set("k", n); done <- struct{}{} }(i)
	}
	for i := 0; i < 10; i++ {
		<-done
	}
	if _, err := s.List(); err != nil {
		t.Fatal(err)
	}
}
