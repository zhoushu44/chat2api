package task

import "testing"

func TestQueueBackpressure(t *testing.T) {
	q := NewQueue(2, t.TempDir())
	_ = q.Enqueue(&Task{ID:"1"})
	_ = q.Enqueue(&Task{ID:"2"})
	if err := q.Enqueue(&Task{ID:"3"}); err != ErrQueueFull {
		t.Fatal("should be full")
	}
	if q.Len()!=2 { t.Fatal() }
	// dequeue
	if _, ok := q.Dequeue(); !ok { t.Fatal() }
	if q.Len()!=1 { t.Fatal() }
}
