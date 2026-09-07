package logsvc

import "time"

// ImageAttempt 对等 log_service.py 的 image_attempts 链路
type ImageAttempt struct {
	AccountID string    `json:"account_id"`
	StartAt   time.Time `json:"start_at"`
	EndAt     time.Time `json:"end_at"`
	Code      string    `json:"code"`
	Success   bool      `json:"success"`
}

// LoggedCall 已在 logsvc.go 定义，此处扩展
func (s *Service) AddAttempt(callID string, attempt ImageAttempt) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, c := range s.buf {
		if c.ID == callID {
			c.Attempts = append(c.Attempts, Attempt{AccountID: attempt.AccountID, Code: attempt.Code})
			break
		}
	}
}
