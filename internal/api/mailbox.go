package api

import (
	"net/http"

	"chatgpt2api/internal/mailbox"

	"github.com/gin-gonic/gin"
)

// MailboxHandler 对齐 abai api/microsoft_mailboxes.py
type MailboxHandler struct {
	Service *mailbox.Service
}

func (h *MailboxHandler) Register(r *gin.RouterGroup) {
	r.GET("/microsoft_mailboxes", h.List)
	r.POST("/microsoft_mailboxes/import", h.Import)
	r.POST("/microsoft_mailboxes/reserve", h.Reserve)
	r.POST("/microsoft_mailboxes/commit", h.Commit)
	r.POST("/microsoft_mailboxes/release", h.Release)
	r.GET("/microsoft_mailboxes/stats", h.Stats)
}

func (h *MailboxHandler) List(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"stats": h.Service.Stats()})
}

func (h *MailboxHandler) Import(c *gin.Context) {
	var body struct {
		Text string `json:"text"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	// 简化：按行解析 email----password----client_id----refresh_token
	entries := parseMailboxText(body.Text)
	h.Service.Import(entries)
	c.JSON(http.StatusOK, gin.H{"ok": true, "imported": len(entries), "stats": h.Service.Stats()})
}

func (h *MailboxHandler) Reserve(c *gin.Context) {
	lease, entry, err := h.Service.Reserve()
	if err != nil {
		c.JSON(500, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"lease": lease, "entry": entry})
}

func (h *MailboxHandler) Commit(c *gin.Context) {
	var body struct{ Token string `json:"lease_token"` }
	_ = c.ShouldBindJSON(&body)
	if err := h.Service.Commit(body.Token); err != nil {
		c.JSON(404, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (h *MailboxHandler) Release(c *gin.Context) {
	var body struct{ Token string `json:"lease_token"` }
	_ = c.ShouldBindJSON(&body)
	if err := h.Service.Release(body.Token); err != nil {
		c.JSON(404, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (h *MailboxHandler) Stats(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"data": h.Service.Stats()})
}

func parseMailboxText(text string) []mailbox.Entry {
	var out []mailbox.Entry
	for _, line := range splitLines(text) {
		parts := splitFields(line)
		if len(parts) < 1 || parts[0] == "" {
			continue
		}
		e := mailbox.Entry{Email: parts[0]}
		if len(parts) > 1 {
			e.Password = parts[1]
		}
		if len(parts) > 2 {
			e.ClientID = parts[2]
		}
		if len(parts) > 3 {
			e.RefreshToken = parts[3]
		}
		out = append(out, e)
	}
	return out
}

func splitLines(s string) []string {
	var res []string
	cur := ""
	for _, c := range s {
		if c == '\n' {
			res = append(res, cur)
			cur = ""
		} else if c != '\r' {
			cur += string(c)
		}
	}
	if cur != "" {
		res = append(res, cur)
	}
	return res
}

func splitFields(line string) []string {
	// 支持 ---- \t , 分隔
	for _, sep := range []string{"----", "\t", ","} {
		if contains(line, sep) {
			return splitBy(line, sep)
		}
	}
	return splitBy(line, " ")
}

func splitBy(s, sep string) []string {
	var out []string
	start := 0
	for i := 0; i <= len(s)-len(sep); i++ {
		if s[i:i+len(sep)] == sep {
			out = append(out, trimSpace(s[start:i]))
			start = i + len(sep)
		}
	}
	out = append(out, trimSpace(s[start:]))
	return out
}

func contains(s, sub string) bool {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}

func trimSpace(s string) string {
	start, end := 0, len(s)
	for start < end && (s[start] == ' ' || s[start] == '\t') {
		start++
	}
	for end > start && (s[end-1] == ' ' || s[end-1] == '\t') {
		end--
	}
	return s[start:end]
}
