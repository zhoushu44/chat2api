package account

import "time"

// Scheduler 对齐 abai core/scheduler.py 的 trial 到期检查 + 401 验活触发器
type Scheduler struct {
	Pool *Pool
}

// CheckTrialExpiry 扫描 trial 到期账号，更新 lifecycle
func (s *Scheduler) CheckTrialExpiry(now time.Time) int {
	if s.Pool == nil {
		return 0
	}
	s.Pool.mu.Lock()
	defer s.Pool.mu.Unlock()
	updated := 0
	nowUnix := now.Unix()
	for _, a := range s.Pool.byToken {
		if a.LifecycleStatus != "trial" {
			continue
		}
		// summary 中 trial_end_time
		if a.Summary == nil {
			continue
		}
		var end int64
		switch v := a.Summary["trial_end_time"].(type) {
		case float64:
			end = int64(v)
		case int64:
			end = v
		case int:
			end = int64(v)
		}
		if end != 0 && end < nowUnix {
			a.LifecycleStatus = "expired"
			a.DisplayStatus = "expired"
			updated++
		}
	}
	return updated
}

// Needs401Check 是否需要创建 401 验活任务（对齐 DAILY_401_CHECK_HOUR）
func Needs401Check(hour int, now time.Time) bool {
	return now.Hour() >= hour
}
