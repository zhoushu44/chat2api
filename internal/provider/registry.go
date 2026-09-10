package provider

import (
	"fmt"
	"sync"
)

// Type 逻辑分类，对齐 abai: mailbox / captcha / proxy
type Type string

const (
	TypeMailbox Type = "mailbox"
	TypeCaptcha Type = "captcha"
	TypeProxy   Type = "proxy"
)

// Definition 静态定义，对齐 abai ProviderDefinitionModel
type Definition struct {
	Key         string     `json:"key"`          // driver_type, e.g. local_ms_pool / api_mailbox / mihomo
	Label       string     `json:"label"`
	Description string     `json:"description"`
	DriverType  string     `json:"driver_type"`
	Category    string     `json:"category"` // free | selfhost | custom
	Enabled     bool       `json:"enabled"`
	IsBuiltin   bool       `json:"is_builtin"`
	Fields      []FieldDef `json:"fields,omitempty"` // 配置字段 schema，前端按此动态渲染（可扩展）
}

// FieldDef 单个配置字段定义：后续加新 provider 时只需在 LoadAll 带上 Fields，前端自动渲染
type FieldDef struct {
	Name        string `json:"name"`                   // 字段名，对应 Setting.Config 的 key
	Label       string `json:"label"`                  // 显示名
	InputType   string `json:"input_type"`             // text | secret | url
	Required    bool   `json:"required"`
	Placeholder  string `json:"placeholder,omitempty"`
	Description string `json:"description,omitempty"`
}

// Setting 运行时配置，对齐 abai ProviderSettingModel
type Setting struct {
	Type      Type            `json:"provider_type"`
	Key       string          `json:"provider_key"`
	Enabled   bool            `json:"enabled"`
	IsDefault bool            `json:"is_default"`
	Config    map[string]any  `json:"config"`
	Auth      map[string]any  `json:"auth"`
	Meta      map[string]any  `json:"meta"`
}

var (
	mu       sync.RWMutex
	defs     = map[Type]map[string]*Definition{} // type -> key -> def
	settings = map[Type]map[string]*Setting{}
	once     sync.Once
)

// Register 注册一个 Definition，类似 abai @register_provider
func Register(t Type, d Definition) {
	mu.Lock()
	defer mu.Unlock()
	if _, ok := defs[t]; !ok {
		defs[t] = map[string]*Definition{}
	}
	if d.Key == "" {
		d.Key = d.DriverType
	}
	if d.DriverType == "" {
		d.DriverType = d.Key
	}
	cp := d
	defs[t][cp.Key] = &cp
}

// ListDefinitions 返回某类全部定义
func ListDefinitions(t Type) []*Definition {
	mu.RLock()
	defer mu.RUnlock()
	m := defs[t]
	out := make([]*Definition, 0, len(m))
	for _, v := range m {
		cp := *v
		out = append(out, &cp)
	}
	return out
}

// GetDefinition 单个
func GetDefinition(t Type, key string) (*Definition, bool) {
	mu.RLock()
	defer mu.RUnlock()
	m, ok := defs[t]
	if !ok {
		return nil, false
	}
	d, ok := m[key]
	if !ok {
		return nil, false
	}
	cp := *d
	return &cp, true
}

// UpsertSetting 增/改运行时配置
func UpsertSetting(s Setting) {
	mu.Lock()
	defer mu.Unlock()
	if _, ok := settings[s.Type]; !ok {
		settings[s.Type] = map[string]*Setting{}
	}
	cp := s
	settings[s.Type][cp.Key] = &cp
}

// GetSetting 查询
func GetSetting(t Type, key string) (*Setting, bool) {
	mu.RLock()
	defer mu.RUnlock()
	m, ok := settings[t]
	if !ok {
		return nil, false
	}
	s, ok := m[key]
	if !ok {
		return nil, false
	}
	cp := *s
	return &cp, true
}

// ListSettings 列出某类全部 Setting
func ListSettings(t Type) []*Setting {
	mu.RLock()
	defer mu.RUnlock()
	m := settings[t]
	out := make([]*Setting, 0, len(m))
	for _, v := range m {
		cp := *v
		out = append(out, &cp)
	}
	return out
}

// DefaultSetting 返回 IsDefault 的配置（用于 Pick 回退）
func DefaultSetting(t Type) (*Setting, bool) {
	mu.RLock()
	defer mu.RUnlock()
	for _, s := range settings[t] {
		if s.Enabled && s.IsDefault {
			cp := *s
			return &cp, true
		}
	}
	// 回退：第一个 Enabled
	for _, s := range settings[t] {
		if s.Enabled {
			cp := *s
			return &cp, true
		}
	}
	return nil, false
}

// LoadAll 预置内置 Provider，对齐 abai load_all() 扫描
func LoadAll() {
	once.Do(func() {
		// mailbox
		Register(TypeMailbox, Definition{Key: "local_ms_pool", Label: "本地微软邮箱池", DriverType: "local_ms_pool", Category: "selfhost", Enabled: true, IsBuiltin: true, Description: "导入 Outlook/Hotmail + Graph 读码，原子分配"})
		Register(TypeMailbox, Definition{Key: "api_mailbox", Label: "API 邮箱池", DriverType: "api_mailbox", Category: "custom", Enabled: true, IsBuiltin: true, Description: "每行邮箱+验证码API，支持轮询/复用"})
		Register(TypeMailbox, Definition{Key: "domain_imap", Label: "自有域名 IMAP 全收", DriverType: "domain_imap", Category: "selfhost", Enabled: true, IsBuiltin: true})
		Register(TypeMailbox, Definition{Key: "domain_inbucket", Label: "自有域名 Inbucket", DriverType: "domain_inbucket", Category: "selfhost", Enabled: true, IsBuiltin: true})
		Register(TypeMailbox, Definition{Key: "icloud_hme", Label: "iCloud Hide My Email", DriverType: "icloud_hme", Category: "custom", Enabled: true, IsBuiltin: true})
		Register(TypeMailbox, Definition{Key: "mailnest", Label: "迈巢邮箱", DriverType: "mailnest", Category: "selfhost", Enabled: true, IsBuiltin: true, Description: "迈巢 mailnest 邮箱 API（url + api_key）", Fields: []FieldDef{
			{Name: "url", Label: "API 地址", InputType: "url", Required: true, Placeholder: "http://mailnest:port"},
			{Name: "api_key", Label: "API Key", InputType: "secret", Required: true},
		}})
		// proxy
		Register(TypeProxy, Definition{Key: "mihomo", Label: "Mihomo 订阅池", DriverType: "mihomo", Category: "selfhost", Enabled: true, IsBuiltin: true, Description: "Clash/Mihomo 订阅，节点测速+脉冲调度"})
		Register(TypeProxy, Definition{Key: "api_extract", Label: "动态IP提取 API", DriverType: "api_extract", Category: "custom", Enabled: true, IsBuiltin: true})
		Register(TypeProxy, Definition{Key: "static_pool", Label: "静态代理池", DriverType: "static_pool", Category: "custom", Enabled: true, IsBuiltin: true})
		Register(TypeProxy, Definition{Key: "warp", Label: "Warp 代理", DriverType: "warp", Category: "selfhost", Enabled: true, IsBuiltin: true, Description: "自托管 warp-pool（socks5/http 代理 url）", Fields: []FieldDef{
			{Name: "url", Label: "代理地址", InputType: "url", Required: true, Placeholder: "socks5://warp-proxy:1080 或 http://host:8118"},
			{Name: "key", Label: "认证(可选)", InputType: "secret", Required: false},
		}})
		// captcha
		Register(TypeCaptcha, Definition{Key: "local_solver", Label: "本地 Camoufox Solver", DriverType: "local_solver", Category: "selfhost", Enabled: true, IsBuiltin: true})
		Register(TypeCaptcha, Definition{Key: "yescaptcha", Label: "YesCaptcha", DriverType: "yescaptcha", Category: "custom", Enabled: true, IsBuiltin: true})
		Register(TypeCaptcha, Definition{Key: "twocaptcha", Label: "2Captcha", DriverType: "twocaptcha", Category: "custom", Enabled: true, IsBuiltin: true})
		Register(TypeCaptcha, Definition{Key: "manual", Label: "人工处理", DriverType: "manual", Category: "free", Enabled: true, IsBuiltin: true})
	})
}

// Validate 检查是否注册过
func Validate(t Type, key string) error {
	if _, ok := GetDefinition(t, key); !ok {
		return fmt.Errorf("未注册的 provider: %s/%s", t, key)
	}
	return nil
}
