package task

import "testing"

func TestTaskLifecycle(t *testing.T) {
	s := New(t.TempDir())
	defer s.Close()
	task := s.Create("t1")
	if task.Status != Queued {
		t.Fatal()
	}
	s.Update("t1", Running, nil, "")
	s.Update("t1", Success, "ok", "")
	if got, _ := s.Get("t1"); got.Status != Success {
		t.Fatal()
	}
	s.Flush()
	s2 := New(s.dir)
	defer s2.Close()
	if got, _ := s2.Get("t1"); got.Status != Success {
		t.Fatalf("restore failed")
	}
	s.Create("t2")
	s.Update("t2", Error, nil, "timeout")
	if !s.CanResumePoll("t2") {
		t.Fatal("should resume")
	}
}
