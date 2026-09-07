package backup

import "time"

// 对等 backup_service.py R2 调度
type Scheduler struct {
	Interval time.Duration
	Fn       func() error
}

func NewScheduler(interval time.Duration, fn func() error) *Scheduler {
	return &Scheduler{Interval: interval, Fn: fn}
}

func (s *Scheduler) Start() {
	ticker := time.NewTicker(s.Interval)
	go func() {
		for range ticker.C {
			_ = s.Fn()
		}
	}()
}
