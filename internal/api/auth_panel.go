package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// 面板登录（对等 Python api/system.py create_router 的 /auth/login + /auth/status）。
// 前端流程：localStorage存key → 全请求带 Bearer → login/status 验身份；
// 无鉴权配置时保持开放（anonymous 视为通过，对等旧行为）。
const panelAppVersion = "v2.7.0-go"

// RegisterAuthPanel 注册面板登录接口（开放组，接口内部自行鉴权）。
func RegisterAuthPanel(r *gin.RouterGroup, s *Server) {
	r.POST("/auth/login", func(c *gin.Context) {
		id, name, role, ok := s.resolvePanelIdentity(c)
		if !ok {
			c.JSON(http.StatusUnauthorized, gin.H{"error": gin.H{
				"message": "密钥无效或已失效，请重新登录", "type": "invalid_request_error", "code": "invalid_api_key",
			}})
			return
		}
		c.JSON(http.StatusOK, authView(id, name, role, true))
	})
	r.GET("/auth/status", func(c *gin.Context) {
		// 对等 Python：永不 401，无效时返回未认证视图
		id, name, role, ok := s.resolvePanelIdentity(c)
		c.JSON(http.StatusOK, authView(id, name, role, ok))
	})
}

// resolvePanelIdentity 解析面板身份：主密钥→admin/管理员；否则多密钥体系；无配置→开放通过。
func (s *Server) resolvePanelIdentity(c *gin.Context) (id, name, role string, ok bool) {
	token := s.requestToken(c)
	if token != "" {
		if s.Cfg != nil && s.Cfg.AuthKey != "" && token == s.Cfg.AuthKey {
			return "admin", "管理员", "admin", true
		}
		if s.Auth != nil {
			if item := s.Auth.Authenticate(token); item != nil {
				return strOf(item["id"]), strOf(item["name"]), strOf(item["role"]), true
			}
		}
	}
	if (s.Cfg == nil || s.Cfg.AuthKey == "") && (s.Auth == nil || len(s.Auth.ListKeys("")) == 0) {
		return "admin", "管理员", "admin", true
	}
	return "", "", "", false
}

// authView 对等 Python auth_view 的响应形状。
func authView(id, name, role string, authenticated bool) gin.H {
	roleOut := role
	if !authenticated {
		roleOut = "unknown"
	}
	var subject any
	var subjectID, subjectName any
	if authenticated {
		subject = gin.H{"id": id, "name": name, "role": role}
		subjectID, subjectName = id, name
	}
	isAdmin := authenticated && role == "admin"
	home := "/login"
	if isAdmin {
		home = "/"
	} else if authenticated {
		home = "/studio"
	}
	return gin.H{
		"ok": authenticated, "schema_version": 1, "authenticated": authenticated,
		"version": panelAppVersion, "role": roleOutIf(authenticated, roleOut),
		"subject_id": subjectID, "name": subjectName, "subject": subject,
		"capabilities": gin.H{"admin_console": isAdmin, "studio": authenticated},
		"home_route":   home,
	}
}

func roleOutIf(authenticated bool, role string) any {
	if !authenticated {
		return nil
	}
	return role
}

func strOf(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
