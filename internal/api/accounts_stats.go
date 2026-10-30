package api

import (
	"net/http"
	"sort"
	"time"

	"chatgpt2api/internal/account"

	"github.com/gin-gonic/gin"
)

// AccountsStatsHandler 账号统计：单号产出 + 存活分析。
// 数据来自 account.Service 里的 Account 统计字段（created_at/died_at/images_ok/revive_count 等）。
type AccountsStatsHandler struct {
	Accounts *account.Service
}

func (h *AccountsStatsHandler) Register(r *gin.RouterGroup) {
	// 注意：不能用 /accounts/stats —— 会与已有的 /accounts/:id 通配路由冲突导致 Gin panic。
	r.GET("/stats/accounts", h.Get)
}

func (h *AccountsStatsHandler) Get(c *gin.Context) {
	out := gin.H{
		"output": gin.H{},
		"life":   gin.H{},
	}
	if h.Accounts == nil {
		c.JSON(http.StatusOK, out)
		return
	}
	items := h.Accounts.List()
	now := time.Now().Unix()

	var (
		alive, dead, relogin, blocked int
		totalOK, totalFail            int64
		totalRevive                   int
		revivedAccounts               int
		withOutput                    int
		oks                           []int64
		lifetimes                     []int64 // 秒
		reasonCount                   = map[string]int{}
		createdByDay                  = map[string]int{}
		diedByDay                     = map[string]int{}
		batchAlive                    = map[string]int{}
		batchTotal                    = map[string]int{}
	)

	for _, a := range items {
		ok := a.ImagesOK
		totalOK += ok
		totalFail += a.ImagesFail
		totalRevive += a.ReviveCount
		if a.ReviveCount > 0 {
			revivedAccounts++
		}
		if ok > 0 {
			withOutput++
			oks = append(oks, ok)
		}

		batchDay := ""
		if a.CreatedAt > 0 {
			batchDay = time.Unix(a.CreatedAt, 0).Format("2006-01-02")
			createdByDay[batchDay]++
			batchTotal[batchDay]++
		}

		switch a.Status {
		case account.StatusNormal:
			alive++
			if batchDay != "" {
				batchAlive[batchDay]++
			}
		case account.StatusNeedRelogin:
			relogin++
		case account.StatusImageBlocked:
			blocked++
		default:
			dead++
			if a.DiedAt > 0 {
				diedByDay[time.Unix(a.DiedAt, 0).Format("2006-01-02")]++
				if a.CreatedAt > 0 && a.DiedAt > a.CreatedAt {
					lifetimes = append(lifetimes, a.DiedAt-a.CreatedAt)
				}
			}
			reason := a.DeathReason
			if reason == "" {
				reason = "unknown"
			}
			reasonCount[reason]++
		}
	}

	// ── 单号产出 ──
	avgOK := 0.0
	if len(oks) > 0 {
		var sum int64
		for _, v := range oks {
			sum += v
		}
		avgOK = float64(sum) / float64(len(oks))
	}
	out["output"] = gin.H{
		"total_images_ok":        totalOK,
		"total_images_fail":      totalFail,
		"accounts_with_output":   withOutput,
		"avg_images_per_account": round2(avgOK),
		"median_images":          percentile(oks, 50),
		"p90_images":             percentile(oks, 90),
		"max_images":             maxInt64(oks),
		"total_revive":           totalRevive,
		"accounts_revived":       revivedAccounts,
		// 含恢复的产出：总产出 ÷ 账号数（所有账号，含没产出的）
		"avg_images_all_accounts": round2(safeDiv(float64(totalOK), float64(len(items)))),
	}

	// ── 存活 ──
	avgLifeHours := 0.0
	if len(lifetimes) > 0 {
		var sum int64
		for _, v := range lifetimes {
			sum += v
		}
		avgLifeHours = float64(sum) / float64(len(lifetimes)) / 3600
	}
	out["life"] = gin.H{
		"total":          len(items),
		"alive":          alive,
		"dead":           dead,
		"need_relogin":   relogin,
		"image_blocked":  blocked,
		"avg_lifetime_h": round2(avgLifeHours),
		"median_lifetime_h": round2(float64(percentile(lifetimes, 50)) / 3600),
		"death_reason":   reasonCount,
		"created_by_day": createdByDay,
		"died_by_day":    diedByDay,
		"batch_survival": buildBatchSurvival(batchTotal, batchAlive),
		"as_of":          now,
	}
	c.JSON(http.StatusOK, out)
}

func buildBatchSurvival(total, alive map[string]int) []gin.H {
	days := make([]string, 0, len(total))
	for d := range total {
		days = append(days, d)
	}
	sort.Strings(days)
	out := make([]gin.H, 0, len(days))
	for _, d := range days {
		t := total[d]
		a := alive[d]
		rate := 0.0
		if t > 0 {
			rate = round2(float64(a) / float64(t) * 100)
		}
		out = append(out, gin.H{"batch": d, "total": t, "alive": a, "survival_pct": rate})
	}
	return out
}

func percentile(v []int64, p int) int64 {
	if len(v) == 0 {
		return 0
	}
	cp := make([]int64, len(v))
	copy(cp, v)
	sort.Slice(cp, func(i, j int) bool { return cp[i] < cp[j] })
	idx := (len(cp) - 1) * p / 100
	return cp[idx]
}

func maxInt64(v []int64) int64 {
	var m int64
	for _, x := range v {
		if x > m {
			m = x
		}
	}
	return m
}

func safeDiv(a, b float64) float64 {
	if b == 0 {
		return 0
	}
	return a / b
}

func round2(v float64) float64 {
	return float64(int64(v*100+0.5)) / 100
}
