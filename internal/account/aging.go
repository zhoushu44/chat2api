package account

import (
	"time"
)

// 养号系统（对齐 lzA6/GPT-Codex-image-2api 的 account_aging）：
// 新号入池后进入「养号期」，前几天不参与生图调度，只做额度探测。
// 这直接降低新号死亡率：实测新号最脆弱的是头几分钟被直接打生图请求。

// AgingConfig 养号配置（通过 config.json 的 account_aging 段注入）。
type AgingConfig struct {
	Enabled         bool `json:"enabled"`
	Days            int  `json:"days"`              // 养号天数（默认 1）
	NoAPIDays       int  `json:"no_api_days"`       // 前 N 天完全不参与调度（默认 0，即第一天就可以用但受限）
	LowFreqDays     int  `json:"low_freq_days"`     // 前 N 天低频（调度优先级降低）
	AutoApplyToNew  bool `json:"auto_apply_to_new"` // 自动应用到新号
}

var defaultAging = AgingConfig{
	Enabled:        false,
	Days:           1,
	NoAPIDays:      0,
	LowFreqDays:    1,
	AutoApplyToNew: true,
}

// SetAgingConfig 运行时调整养号参数。
func SetAgingConfig(cfg AgingConfig) {
	if cfg.Days > 0 {
		defaultAging.Days = cfg.Days
	}
	if cfg.NoAPIDays >= 0 {
		defaultAging.NoAPIDays = cfg.NoAPIDays
	}
	if cfg.LowFreqDays >= 0 {
		defaultAging.LowFreqDays = cfg.LowFreqDays
	}
	defaultAging.Enabled = cfg.Enabled
	defaultAging.AutoApplyToNew = cfg.AutoApplyToNew
}

// IsAging 判断账号是否处于养号期（不参与调度）。
// 养号期内只做额度探测（refresh），不做生图。
func (a *Account) IsAging() bool {
	if !defaultAging.Enabled || defaultAging.NoAPIDays <= 0 {
		return false
	}
	if a.CreatedAt == 0 {
		return false // 历史号无创建时间，不养
	}
	ageHours := time.Since(time.Unix(a.CreatedAt, 0)).Hours()
	ageDays := int(ageHours / 24)
	return ageDays < defaultAging.NoAPIDays
}

// IsLowFreq 判断账号是否处于低频期（调度优先级降低，但仍可用）。
func (a *Account) IsLowFreq() bool {
	if !defaultAging.Enabled || defaultAging.LowFreqDays <= 0 {
		return false
	}
	if a.CreatedAt == 0 {
		return false
	}
	ageHours := time.Since(time.Unix(a.CreatedAt, 0)).Hours()
	ageDays := int(ageHours / 24)
	return ageDays < defaultAging.LowFreqDays
}
