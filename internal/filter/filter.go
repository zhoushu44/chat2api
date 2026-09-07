package filter

import (
	"strings"
	"sync"
)

// 对等 services/content_filter.py（本地 sensitive_words 匹配部分；AI 审核链路见 TASKS.md P2.7）
var banned = []string{"nsfw", "gore", "violence"}

var customMu = struct {
	sync.RWMutex
	words []string
}{}

// SetCustomWords 设置配置下发的 sensitive_words（P2.7；与内置 banned 合并匹配）。
func SetCustomWords(words []string) {
	customMu.Lock()
	defer customMu.Unlock()
	customMu.words = append([]string(nil), words...)
}

func allBanned() []string {
	customMu.RLock()
	defer customMu.RUnlock()
	if len(customMu.words) == 0 {
		return banned
	}
	seen := make(map[string]bool, len(banned)+len(customMu.words))
	var out []string
	for _, w := range banned {
		if !seen[w] {
			seen[w] = true
			out = append(out, w)
		}
	}
	for _, w := range customMu.words {
		w = strings.ToLower(strings.TrimSpace(w))
		if w != "" && !seen[w] {
			seen[w] = true
			out = append(out, w)
		}
	}
	return out
}

func IsAllowed(prompt string) (bool, string) {
	lower := strings.ToLower(prompt)
	for _, b := range allBanned() {
		if strings.Contains(lower, b) {
			return false, "content_policy_violation"
		}
	}
	return true, ""
}

func Check(prompt string) error {
	if ok, code := IsAllowed(prompt); !ok {
		return &ContentFilterError{Code: code}
	}
	return nil
}

type ContentFilterError struct {
	Code string
}

func (e *ContentFilterError) Error() string {
	return "content filter: " + e.Code
}
