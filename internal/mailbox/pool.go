package mailbox

import (
	"fmt"
	"sync"
	"time"
)

// Entry 微软邮箱池条目，对齐 abai MicrosoftMailboxModel
type Entry struct {
	ID           int       `json:"id"`
	Email        string    `json:"email"`
	EmailKey     string    `json:"email_key"`
	Password     string    `json:"password,omitempty"`
	ClientID     string    `json:"client_id"`
	RefreshToken string    `json:"refresh_token"`
	UseCount     int       `json:"use_count"`
	MaxUses      int       `json:"max_uses"` // 默认 6，对齐 abai MAX_OUTLOOK_SUBADDRESS_COUNT
	Status       string    `json:"status"`   // available | exhausted
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}

// Lease 租约，对齐 abai MicrosoftMailboxLease
type Lease struct {
	Token      string    `json:"lease_token"`
	MailboxID  int       `json:"mailbox_id"`
	AliasIndex int       `json:"alias_index"`
	Email      string    `json:"email"` // 生成的子邮箱 +tag
	Status     string    `json:"status"` // reserved | committed | released
	ExpiresAt  time.Time `json:"expires_at"`
}

// Pool 邮箱池，原子分配 + 租约管理
type Pool struct {
	mu      sync.Mutex
	entries map[int]*Entry
	leases  map[string]*Lease
	nextID  int
}

func NewPool() *Pool {
	return &Pool{entries: make(map[int]*Entry), leases: make(map[string]*Lease)}
}

// Import 批量导入，对齐 abai parse_local_ms_pool_rows
func (p *Pool) Import(rows []Entry) {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, r := range rows {
		key := fmt.Sprintf("%s", r.Email)
		// 去重
		dup := false
		for _, e := range p.entries {
			if e.EmailKey == key || e.Email == r.Email {
				dup = true
				break
			}
		}
		if dup {
			continue
		}
		p.nextID++
		e := r
		e.ID = p.nextID
		if e.MaxUses == 0 {
			e.MaxUses = 6
		}
		if e.Status == "" {
			e.Status = "available"
		}
		e.EmailKey = key
		e.CreatedAt = time.Now()
		e.UpdatedAt = time.Now()
		cp := e
		p.entries[cp.ID] = &cp
	}
}

// Reserve 原子分配一个可用邮箱的子地址，返回租约
func (p *Pool) Reserve() (*Lease, *Entry, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	var best *Entry
	for _, e := range p.entries {
		if e.Status != "available" {
			continue
		}
		if e.UseCount >= e.MaxUses {
			e.Status = "exhausted"
			continue
		}
		if best == nil || e.UseCount < best.UseCount {
			best = e
		}
	}
	if best == nil {
		return nil, nil, fmt.Errorf("邮箱池已耗尽")
	}
	aliasIdx := best.UseCount + 1
	subEmail := fmt.Sprintf("%s+%d@%s", splitLocal(best.Email), aliasIdx, splitDomain(best.Email))
	token := fmt.Sprintf("lease-%d-%d-%d", best.ID, aliasIdx, time.Now().UnixNano())
	lease := &Lease{
		Token:      token,
		MailboxID:  best.ID,
		AliasIndex: aliasIdx,
		Email:      subEmail,
		Status:     "reserved",
		ExpiresAt:  time.Now().Add(10 * time.Minute),
	}
	p.leases[token] = lease
	// 预占
	best.UseCount = aliasIdx
	best.UpdatedAt = time.Now()
	return lease, best, nil
}

// Commit 成功才提交，否则 Release
func (p *Pool) Commit(token string) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	l, ok := p.leases[token]
	if !ok {
		return fmt.Errorf("lease not found: %s", token)
	}
	l.Status = "committed"
	return nil
}

func (p *Pool) Release(token string) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	l, ok := p.leases[token]
	if !ok {
		return fmt.Errorf("lease not found: %s", token)
	}
	l.Status = "released"
	if e, ok := p.entries[l.MailboxID]; ok {
		// 回退 UseCount（仅 reserved 未 commit 时）
		if l.Status == "released" && e.UseCount == l.AliasIndex {
			e.UseCount--
			if e.Status == "exhausted" {
				e.Status = "available"
			}
		}
	}
	delete(p.leases, token)
	return nil
}

func (p *Pool) Stats() map[string]int {
	p.mu.Lock()
	defer p.mu.Unlock()
	total, avail, exhausted, reserved := len(p.entries), 0, 0, len(p.leases)
	for _, e := range p.entries {
		if e.Status == "available" {
			avail++
		} else if e.Status == "exhausted" {
			exhausted++
		}
	}
	return map[string]int{"total": total, "available": avail, "exhausted": exhausted, "reserved": reserved}
}

func splitLocal(email string) string {
	for i, c := range email {
		if c == '@' {
			return email[:i]
		}
	}
	return email
}
func splitDomain(email string) string {
	for i, c := range email {
		if c == '@' {
			return email[i+1:]
		}
	}
	return ""
}
