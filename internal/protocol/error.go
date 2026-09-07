package protocol

import "fmt"

// 对等 services/protocol/error_response.py
func ErrorResponse(code, message string) map[string]any {
	return map[string]any{
		"error": map[string]any{
			"code":    code,
			"message": message,
			"type":    "api_error",
		},
	}
}

func InvalidRequest(msg string) map[string]any {
	return ErrorResponse("invalid_request", msg)
}

func ServerError(msg string) map[string]any {
	return ErrorResponse("server_error", fmt.Sprintf("server error: %s", msg))
}
