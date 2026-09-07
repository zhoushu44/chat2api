package utils

import (
	"encoding/json"
	"fmt"
)

// 对等 utils/diagnostics.py
func DiagnosticExcerpt2(v any, limit int) string {
	var s string
	switch x := v.(type) {
	case string:
		s = x
	case error:
		s = x.Error()
	default:
		b, _ := json.Marshal(x)
		s = string(b)
	}
	if len(s) > limit {
		return s[:limit] + "..."
	}
	return s
}

func MustJSON(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

var _ = fmt.Sprintf
