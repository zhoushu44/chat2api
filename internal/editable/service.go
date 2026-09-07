package editable

import (
	"fmt"
	"strings"
)

// 对等 services/editable_file_task_service.py
// 简化：PPT/PSD 逆向导出桩

type ExportResult struct {
	ConversationID string
	PrimaryPath    string
	ZipPath        string
}

func ExportPPT(prompt string, images []string) (*ExportResult, error) {
	if prompt == "" {
		return nil, fmt.Errorf("prompt required")
	}
	// 桩：返回模拟路径
	return &ExportResult{
		ConversationID: "conv-edit-" + prompt[:4],
		PrimaryPath:    "/tmp/ppt.pptx",
		ZipPath:        "/tmp/ppt.zip",
	}, nil
}

func ExportPSD(prompt string, images []string) (*ExportResult, error) {
	if strings.Contains(prompt, "psd") {
		return &ExportResult{ConversationID: "conv-psd", PrimaryPath: "/tmp/psd.psd"}, nil
	}
	return ExportPPT(prompt, images)
}
