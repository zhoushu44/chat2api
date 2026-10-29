package admin

import (
	"net/http"
	"sort"

	"chatgpt2api/internal/account"

	"github.com/gin-gonic/gin"
)

// AccountCleanupRequest 账号清理开关。
// invalid=true：清理「已禁用」账号；rate_limited=true：清理「限流」账号。
// 待重登/生图失效永远不会被清理——它们仍可能恢复，不属于真死号。
type AccountCleanupRequest struct {
	AutoRemoveInvalid     bool `json:"auto_remove_invalid_accounts"`
	AutoRemoveRateLimited bool `json:"auto_remove_rate_limited_accounts"`
}

// AccountCleanupResult 预览与执行共用结构；执行时 removed_emails 返回实际删除邮箱。
type AccountCleanupResult struct {
	TotalRemoved  int      `json:"total_removed"`
	Invalid       int      `json:"invalid"`
	RateLimited   int      `json:"rate_limited"`
	RemovedEmails []string `json:"removed_emails,omitempty"`
}

// cleanupCandidates 预览和执行共用同一套筛选规则，避免「预览 N 个、实删 M 个」。
// 只返回已禁用/限流账号；正常、待重登、生图失效不在清理范围。
func cleanupCandidates(all []*account.Account, req AccountCleanupRequest) (invalid, limited []*account.Account) {
	for _, a := range all {
		if a == nil {
			continue
		}
		if req.AutoRemoveInvalid && a.Status == account.StatusDisabled {
			invalid = append(invalid, a)
		}
		if req.AutoRemoveRateLimited && a.Status == account.StatusLimited {
			limited = append(limited, a)
		}
	}
	return invalid, limited
}

func cleanupResult(invalid, limited []*account.Account, includeEmails bool) AccountCleanupResult {
	result := AccountCleanupResult{
		TotalRemoved: len(invalid) + len(limited),
		Invalid:      len(invalid),
		RateLimited:  len(limited),
	}
	if includeEmails {
		emails := make([]string, 0, result.TotalRemoved)
		for _, a := range append(append([]*account.Account{}, invalid...), limited...) {
			emails = append(emails, a.Email)
		}
		sort.Strings(emails)
		result.RemovedEmails = emails
	}
	return result
}

// PreviewCleanup 只读预览：POST /api/accounts/cleanup/preview
func (h *AccountsHandler) PreviewCleanup(c *gin.Context) {
	var req AccountCleanupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if h.Accounts == nil {
		c.JSON(http.StatusOK, AccountCleanupResult{})
		return
	}
	invalid, limited := cleanupCandidates(h.Accounts.List(), req)
	c.JSON(http.StatusOK, cleanupResult(invalid, limited, false))
}

// RunCleanup 实际删除：POST /api/accounts/cleanup/run
// 只删除已禁用/限流账号；每个账号同时从持久化与调度池移除。
func (h *AccountsHandler) RunCleanup(c *gin.Context) {
	var req AccountCleanupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if h.Accounts == nil {
		c.JSON(http.StatusOK, AccountCleanupResult{})
		return
	}
	invalid, limited := cleanupCandidates(h.Accounts.List(), req)
	removedInvalid, removedLimited := make([]*account.Account, 0, len(invalid)), make([]*account.Account, 0, len(limited))
	for _, a := range append(append([]*account.Account{}, invalid...), limited...) {
		if err := h.Accounts.Delete(a.ID); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		if h.Pool != nil {
			h.Pool.Remove(a.Token)
		}
		if a.Status == account.StatusDisabled {
			removedInvalid = append(removedInvalid, a)
		} else {
			removedLimited = append(removedLimited, a)
		}
	}
	c.JSON(http.StatusOK, cleanupResult(removedInvalid, removedLimited, true))
}
