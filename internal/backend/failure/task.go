package failure

import "strings"

// 对等 image_failure.py 的 task 分类
func ClassifyTask(task map[string]any) *ImageFailure {
	status, _ := task["status"].(string)
	errMsg, _ := task["error"].(string)
	lower := strings.ToLower(status + " " + errMsg)
	switch {
	case strings.Contains(lower, "quota"):
		f := New("image_quota_exhausted", task)
		return &f
	case strings.Contains(lower, "policy"):
		f := New("content_policy_violation", task)
		return &f
	case strings.Contains(lower, "timeout"):
		f := New("image_poll_timeout", task)
		return &f
	case strings.Contains(lower, "tool"):
		f := New("image_tool_error", task)
		return &f
	default:
		return nil
	}
}

func Merge(a, b *ImageFailure) *ImageFailure {
	if a == nil {
		return b
	}
	if b == nil {
		return a
	}
	// 优先级：account > transient > request
	if a.Scope == "account" {
		return a
	}
	if b.Scope == "account" {
		return b
	}
	return a
}
