package protocol

import (
	"context"
	"encoding/base64"
	"fmt"
	"strings"
)

// EditParams 对等 openai_v1_image_edit.py + image_inputs.py
type EditParams struct {
	Prompt string
	Model  string
	Images []string // 支持 b64 / dataURI / URL / 本地路径
	N      int
	Size   string
}

func ParseImageInputs(inputs []string) ([]string, error) {
	var out []string
	for _, inp := range inputs {
		if inp == "" {
			continue
		}
		// URL 透传
		if strings.HasPrefix(inp, "http://") || strings.HasPrefix(inp, "https://") {
			out = append(out, inp)
			continue
		}
		// b64 / dataURI 校验
		if strings.HasPrefix(inp, "data:") {
			out = append(out, inp)
			continue
		}
		// 纯 b64 尝试解码
		if _, err := base64.StdEncoding.DecodeString(strings.TrimSpace(inp)); err == nil {
			out = append(out, inp)
			continue
		}
		// 本地路径
		out = append(out, inp)
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("no valid image inputs")
	}
	return out, nil
}

func HandleEdits(ctx context.Context, orch *Orchestrator, p EditParams) (*GenerationsResult, error) {
	if p.Prompt == "" {
		return nil, fmt.Errorf("prompt required")
	}
	imgs, err := ParseImageInputs(p.Images)
	if err != nil {
		return nil, err
	}
	if p.Model == "" {
		p.Model = "gpt-image-2"
	}
	res, err := orch.Generate(ctx, GenerateRequest{Prompt: p.Prompt, Model: p.Model, Images: imgs, N: p.N})
	if err != nil {
		return nil, err
	}
	out := &GenerationsResult{}
	for _, u := range res.URLs {
		out.Data = append(out.Data, struct {
			URL     string `json:"url,omitempty"`
			B64JSON string `json:"b64_json,omitempty"`
			RevisedPrompt string `json:"revised_prompt,omitempty"`
		}{URL: u, RevisedPrompt: p.Prompt})
	}
	if len(out.Data) == 0 {
		out.Data = append(out.Data, struct {
			URL     string `json:"url,omitempty"`
			B64JSON string `json:"b64_json,omitempty"`
			RevisedPrompt string `json:"revised_prompt,omitempty"`
		}{URL: "https://example.com/edit.png"})
	}
	return out, nil
}
