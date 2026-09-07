package monitor

import "testing"

func TestMonitor(t *testing.T) {
	s := New(0)
	ch, unsub := s.Subscribe()
	defer unsub()
	s.Publish(Event{TaskID:"t1", Stage:"generating"})
	e := <-ch
	if e.TaskID != "t1" { t.Fatal() }
	if len(s.Events())!=1 { t.Fatal() }
}
