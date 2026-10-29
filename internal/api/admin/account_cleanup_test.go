package admin

import (
	"testing"

	"chatgpt2api/internal/account"
)

func TestCleanupCandidatesOnlyDisabledAndLimited(t *testing.T) {
	accounts := []*account.Account{
		{ID: "normal", Status: account.StatusNormal},
		{ID: "relogin", Status: account.StatusNeedRelogin},
		{ID: "blocked", Status: account.StatusImageBlocked},
		{ID: "dead", Status: account.StatusDisabled},
		{ID: "limited", Status: account.StatusLimited},
	}
	invalid, limited := cleanupCandidates(accounts, AccountCleanupRequest{
		AutoRemoveInvalid:     true,
		AutoRemoveRateLimited: true,
	})
	if len(invalid) != 1 || invalid[0].ID != "dead" {
		t.Fatalf("invalid = %+v want only dead", invalid)
	}
	if len(limited) != 1 || limited[0].ID != "limited" {
		t.Fatalf("limited = %+v want only limited", limited)
	}
}

func TestCleanupCandidatesNeverRemovesRecoverableAccounts(t *testing.T) {
	accounts := []*account.Account{
		{ID: "normal", Status: account.StatusNormal},
		{ID: "relogin", Status: account.StatusNeedRelogin},
		{ID: "blocked", Status: account.StatusImageBlocked},
	}
	invalid, limited := cleanupCandidates(accounts, AccountCleanupRequest{
		AutoRemoveInvalid:     true,
		AutoRemoveRateLimited: true,
	})
	if len(invalid) != 0 || len(limited) != 0 {
		t.Fatalf("recoverable accounts must never be deleted: invalid=%d limited=%d", len(invalid), len(limited))
	}
}

func TestCleanupCandidatesRespectsSwitches(t *testing.T) {
	accounts := []*account.Account{
		{ID: "dead", Status: account.StatusDisabled},
		{ID: "limited", Status: account.StatusLimited},
	}
	invalid, limited := cleanupCandidates(accounts, AccountCleanupRequest{
		AutoRemoveInvalid:     true,
		AutoRemoveRateLimited: false,
	})
	if len(invalid) != 1 || len(limited) != 0 {
		t.Fatalf("switch mismatch: invalid=%d limited=%d", len(invalid), len(limited))
	}
}
