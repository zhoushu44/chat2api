package protocol

// 对等 services/protocol/openai_v1_response.py
type ResponseRequest struct {
	Model string `json:"model"`
	Input string `json:"input"`
	Tools []struct {
		Type string `json:"type"`
	} `json:"tools"`
}

func HasImageTool(req ResponseRequest) bool {
	for _, t := range req.Tools {
		if t.Type == "image_generation" {
			return true
		}
	}
	return false
}
