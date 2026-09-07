package utils

import (
	"encoding/json"
	"log"
	"os"
)

// 对等 utils/log.py 结构化日志
var logger = log.New(os.Stderr, "", log.LstdFlags)

func Info(fields map[string]any) {
	b, _ := json.Marshal(fields)
	logger.Println(string(b))
}

func Warn(fields map[string]any) {
	fields["level"] = "warn"
	Info(fields)
}

func Error(fields map[string]any) {
	fields["level"] = "error"
	Info(fields)
}
