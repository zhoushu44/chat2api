package scheduler

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// settingsFilename 调度器运行时设置（账号页开关控制），持久化到 DataDir。
const settingsFilename = "scheduler_settings.json"

type schedulerSettings struct {
	// DailyCheckEnabled 每日 401 验活 + 协议登录恢复总开关
	DailyCheckEnabled *bool `json:"daily_check_enabled"`
}

// LoadPersistedEnabled 读取持久化设置；无文件或未设置时返回 defEnabled,false。
func LoadPersistedEnabled(dir string, defEnabled bool) (bool, bool) {
	if dir == "" {
		return defEnabled, false
	}
	b, err := os.ReadFile(filepath.Join(dir, settingsFilename))
	if err != nil {
		return defEnabled, false
	}
	var st schedulerSettings
	if err := json.Unmarshal(b, &st); err != nil || st.DailyCheckEnabled == nil {
		return defEnabled, false
	}
	return *st.DailyCheckEnabled, true
}

// SavePersistedEnabled 落盘开关状态（原子写，与其他服务同款）。
func SavePersistedEnabled(dir string, enabled bool) error {
	if dir == "" {
		return os.ErrNotExist
	}
	b, err := json.Marshal(schedulerSettings{DailyCheckEnabled: &enabled})
	if err != nil {
		return err
	}
	tmp := filepath.Join(dir, settingsFilename+".tmp")
	if err := os.WriteFile(tmp, b, 0644); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(dir, settingsFilename))
}
