package protocol

import (
	"context"
	"encoding/base64"
	"fmt"
)

// GenerationsParams 对等 openai_v1_image_generations.py 入参
type GenerationsParams struct {
	Prompt         string `json:"prompt"`
	Model          string `json:"model"`
	N              int    `json:"n"`
	Size           string `json:"size"`
	ResponseFormat string `json:"response_format"` // b64_json | url
}

// GenerationsResult 对等 OpenAI 返回
type GenerationsResult struct {
	Created int64 `json:"created"`
	Data    []struct {
		URL           string `json:"url,omitempty"`
		B64JSON       string `json:"b64_json,omitempty"`
		RevisedPrompt string `json:"revised_prompt,omitempty"`
	} `json:"data"`
}

// generationsDataItem 构造单个 data 条目。
func generationsDataItem(url, b64, revised string) (struct {
	URL           string `json:"url,omitempty"`
	B64JSON       string `json:"b64_json,omitempty"`
	RevisedPrompt string `json:"revised_prompt,omitempty"`
}, error) {
	return struct {
		URL           string `json:"url,omitempty"`
		B64JSON       string `json:"b64_json,omitempty"`
		RevisedPrompt string `json:"revised_prompt,omitempty"`
	}{URL: url, B64JSON: b64, RevisedPrompt: revised}, nil
}

// HandleGenerations 生图协议转换：prompt -> orchestrator -> OpenAI 格式（P1.2 修复）。
// b64_json 模式使用 orchestrator 下载的图片字节做真实 base64 编码（修复前编码的是 URL 字符串）。
func HandleGenerations(ctx context.Context, orch *Orchestrator, p GenerationsParams) (*GenerationsResult, error) {
	if p.Prompt == "" {
		return nil, fmt.Errorf("prompt required")
	}
	if p.Model == "" {
		p.Model = "gpt-image-2"
	}
	if p.N == 0 {
		p.N = 1
	}
	if p.N > 4 {
		p.N = 4
	}
	if p.ResponseFormat == "" {
		p.ResponseFormat = "b64_json"
	}
	res, err := orch.Generate(ctx, GenerateRequest{Prompt: p.Prompt, Model: p.Model, N: p.N})
	if err != nil {
		return nil, err
	}
	out := &GenerationsResult{Created: 0}
	// 结果截取/补齐到 N：优先 B64（已下载字节），其次 URL
	for i := 0; i < p.N; i++ {
		url, b64 := "", ""
		if p.ResponseFormat == "b64_json" {
			if i < len(res.B64) {
				b64 = string(res.B64[i]) // orchestrator 已下载并编码的真实图片数据
			}
		} else {
			if i < len(res.URLs) {
				url = res.URLs[i]
			}
		}
		if b64 == "" && url == "" {
			return nil, fmt.Errorf("upstream returned %d images, want %d", len(res.B64)+len(res.URLs), p.N)
		}
		item, _ := generationsDataItem(url, b64, p.Prompt)
		out.Data = append(out.Data, item)
	}
	return out, nil
}

// encodeImageB64 供测试与上层复用：图片字节 → base64。
func encodeImageB64(data []byte) string {
	return base64.StdEncoding.EncodeToString(data)
}
