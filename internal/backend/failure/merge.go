package failure

// MergeMessageFailure 对等 image_failure.py merge_message_failure
func MergeMessageFailure(a, b *ImageFailure) *ImageFailure {
	if a == nil {
		return b
	}
	if b == nil {
		return a
	}
	// 优先级：account > transient > request > internal
	priority := map[string]int{"account": 3, "transient": 2, "request": 1, "internal": 0}
	if priority[a.Scope] >= priority[b.Scope] {
		return a
	}
	return b
}
