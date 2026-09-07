package provider

import (
	"context"
	"fmt"
	"sync"
	"time"
)

// Mailbox 统一邮箱接口，对齐 abai Core/BaseMailbox
type Mailbox interface {
	// GetCode 拉取验证码，keyword 为空表示不过滤主题
	GetCode(ctx context.Context, email string, keyword string, timeout time.Duration) (string, error)
}

// Factory 工厂函数类型
type MailboxFactory func(cfg map[string]any) (Mailbox, error)

var (
	mailboxMu       sync.RWMutex
	mailboxFactories = map[string]MailboxFactory{}
)

// RegisterMailbox 注册邮箱驱动
func RegisterMailbox(driver string, f MailboxFactory) {
	mailboxMu.Lock()
	defer mailboxMu.Unlock()
	mailboxFactories[driver] = f
}

// CreateMailbox 按 Setting 创建实例
func CreateMailbox(setting *Setting) (Mailbox, error) {
	if setting == nil {
		return nil, fmt.Errorf("mailbox setting is nil")
	}
	mailboxMu.RLock()
	f, ok := mailboxFactories[setting.Key]
	if !ok {
		f, ok = mailboxFactories[setting.Config["driver_type"].(string)]
	}
	mailboxMu.RUnlock()
	if !ok {
		return nil, fmt.Errorf("未注册的 mailbox driver: %s", setting.Key)
	}
	return f(setting.Config)
}

// Lease 租约，对齐 abai MicrosoftMailboxLease
type Lease struct {
	Token      string
	MailboxID  int
	Email      string
	AliasIndex int
	Status     string // reserved | committed | released
	ExpiresAt  time.Time
}
