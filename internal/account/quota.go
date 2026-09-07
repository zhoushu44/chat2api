package account

// 对等 account_service.py 的 quota/pending_auth_scope 判定

func IsImageQuotaUnknown(acc *Account) bool {
	return acc.QuotaUnknown || acc.PlanType == "Pro" || acc.PlanType == "ProLite"
}

func HasPendingAuthScope(acc *Account) bool {
	return acc.PendingAuthScope
}

func IsImageAccountAvailable(acc *Account) bool {
	if !acc.Available() {
		return false
	}
	if HasPendingAuthScope(acc) {
		return false
	}
	// image_quota_unknown 为 true 时直接可用
	if IsImageQuotaUnknown(acc) {
		return true
	}
	return acc.Quota > 0 || acc.Quota == 0 // 展示值不阻断，远程限流才阻断
}
