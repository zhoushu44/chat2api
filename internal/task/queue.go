package task

import (
	"errors"
	"sync"
)

var ErrQueueFull = errors.New("queue full: backpressure 429")

type Queue struct {
	mu      sync.Mutex
	cap     int
	pending []*Task
	spillDir string
}

func NewQueue(cap int, spillDir string) *Queue {
	return &Queue{cap: cap, spillDir: spillDir}
}

func (q *Queue) Enqueue(t *Task) error {
	q.mu.Lock()
	defer q.mu.Unlock()
	if len(q.pending) >= q.cap {
		// spill to disk (append to spill file)
		// 简化：直接返回429，让调用方重试
		return ErrQueueFull
	}
	q.pending = append(q.pending, t)
	return nil
}
func (q *Queue) Dequeue() (*Task, bool) {
	q.mu.Lock()
	defer q.mu.Unlock()
	if len(q.pending)==0 { return nil,false }
	t := q.pending[0]
	q.pending = q.pending[1:]
	return t,true
}
func (q *Queue) Len() int {
	q.mu.Lock()
	defer q.mu.Unlock()
	return len(q.pending)
}
