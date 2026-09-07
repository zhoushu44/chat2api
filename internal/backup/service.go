package backup

import (
	"fmt"
	"time"
)

// 对等 services/backup_service.py R2 备份调度桩
type Service struct {
	Endpoint string
	Bucket   string
}

func New(endpoint, bucket string) *Service {
	return &Service{Endpoint: endpoint, Bucket: bucket}
}

func (s *Service) Backup(dataDir string) error {
	// 桩：模拟上传
	_ = dataDir
	time.Sleep(10 * time.Millisecond)
	return nil
}

func (s *Service) Schedule(interval time.Duration, fn func() error) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for range ticker.C {
			_ = fn()
		}
	}()
}

var _ = fmt.Sprintf
