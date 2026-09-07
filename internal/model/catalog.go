// Package model 模型目录（P1.4：对齐 Python model_catalog_service.py）。
// 默认值使用 Python 侧 FALLBACK_* 常量（gpt-5 系，而非旧 gpt-4o/o1/o3）；
// 优先级：显式配置 > 账号派生 > fallback（与 Python 一致）。
package model

import (
	"strings"
	"sync"
)

// FallbackChatModels 对等 Python FALLBACK_CHAT_MODELS。
var FallbackChatModels = []string{
	"auto",
	"gpt-5",
	"gpt-5-1",
	"gpt-5-2",
	"gpt-5-3",
	"gpt-5-3-mini",
	"gpt-5-5",
	"gpt-5-mini",
}

// FallbackImageModels 对等 Python FALLBACK_IMAGE_MODELS。
var FallbackImageModels = []string{
	"gpt-image-2",
}

// CodexImageModel codex 生图模型（对等 helper.CODEX_IMAGE_MODEL）。
const CodexImageModel = "codex-gpt-image-2"

// Catalog 模型目录。
type Catalog struct {
	mu          sync.RWMutex
	ChatModels  []string `json:"chat_models"`
	ImageModels []string `json:"image_models"`
	Source      string   `json:"image_source"` // config | accounts | fallback
}

// New 默认目录（fallback，与 Python 一致）。
func New() *Catalog {
	return &Catalog{
		ChatModels:  append([]string(nil), FallbackChatModels...),
		ImageModels: append([]string(nil), FallbackImageModels...),
		Source:      "fallback",
	}
}

// SetConfigured 显式配置覆盖（对等 settings.model_catalog.chat_models 等）。
func (c *Catalog) SetConfigured(chat, image []string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(chat) > 0 {
		c.ChatModels = unique(chat)
	}
	if len(image) > 0 {
		c.ImageModels = unique(image)
	}
	if len(chat) > 0 || len(image) > 0 {
		c.Source = "config"
	}
}

// DeriveFromAccounts 从账号派生 image 模型（对等 _image_models_from_accounts）。
// planTypes：plan_type → 账号数；有 codex 账号则加 codex-gpt-image-2 与 plan 前缀变体。
func (c *Catalog) DeriveFromAccounts(planTypes map[string]int, hasCodex bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	chat := append([]string(nil), FallbackChatModels...)
	imageModels := append([]string(nil), FallbackImageModels...)
	if hasCodex {
		imageModels = append(imageModels, CodexImageModel)
		for plan, n := range planTypes {
			if n > 0 && plan != "" {
				cand := strings.ToLower(plan) + "-" + CodexImageModel
				if !contains(imageModels, cand) {
					imageModels = append(imageModels, cand)
				}
			}
		}
	}
	c.ChatModels = chat
	c.ImageModels = unique(imageModels)
	c.Source = "accounts"
}

// List 全量去重（对等 get_model_catalog 的 all_models）。
func (c *Catalog) List() []string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return unique(append(append([]string(nil), c.ChatModels...), c.ImageModels...))
}

// Snapshot 供 /api/model-catalog 返回（含来源标记）。
func (c *Catalog) Snapshot() map[string]any {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return map[string]any{
		"chat_models":  append([]string(nil), c.ChatModels...),
		"image_models": append([]string(nil), c.ImageModels...),
		"all_models": unique(append(append([]string(nil), c.ChatModels...),
			c.ImageModels...)),
		"image_source": c.Source,
	}
}

func (c *Catalog) AddChat(model string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !contains(c.ChatModels, model) {
		c.ChatModels = append(c.ChatModels, model)
	}
}

func unique(in []string) []string {
	seen := make(map[string]bool, len(in))
	out := make([]string, 0, len(in))
	for _, v := range in {
		v = strings.TrimSpace(v)
		if v == "" || seen[v] {
			continue
		}
		seen[v] = true
		out = append(out, v)
	}
	return out
}

func contains(in []string, v string) bool {
	for _, x := range in {
		if x == v {
			return true
		}
	}
	return false
}
