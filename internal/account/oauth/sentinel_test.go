package oauth

import (
	"testing"
)

func TestChallengeSORequired(t *testing.T) {
	cases := []struct {
		name      string
		challenge map[string]any
		want      bool
	}{
		{"无 so 字段", map[string]any{"token": "x"}, false},
		{"so 为空", map[string]any{"so": nil}, false},
		{"so.required=true", map[string]any{"so": map[string]any{"required": true}}, true},
		{"so.required=false", map[string]any{"so": map[string]any{"required": false}}, false},
		{"so 无 required", map[string]any{"so": map[string]any{"foo": "bar"}}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := challengeSORequired(tc.challenge); got != tc.want {
				t.Fatalf("challengeSORequired=%v want=%v", got, tc.want)
			}
		})
	}
}

func TestMergeMaps(t *testing.T) {
	base := map[string]any{"a": 1, "b": 2}
	extra := map[string]any{"b": 9, "c": 3}
	got := mergeMaps(base, extra)
	if got["a"] != 1 || got["b"] != 9 || got["c"] != 3 {
		t.Fatalf("merge 结果错误: %v", got)
	}
	// 不应污染入参
	if base["b"] != 2 {
		t.Fatalf("base 被修改: %v", base)
	}
}

func TestEnvPayloadUsesUAAndDeviceID(t *testing.T) {
	s := &nodeSentinelSolver{ua: loginUA}
	p := s.envPayload("dev-123")
	if p["device_id"] != "dev-123" {
		t.Fatalf("device_id=%v", p["device_id"])
	}
	if p["user_agent"] != loginUA {
		t.Fatalf("user_agent=%v", p["user_agent"])
	}
	if p["platform"] != "Win32" {
		t.Fatalf("platform=%v", p["platform"])
	}
}

func TestNewSentinelSolverEnvOverride(t *testing.T) {
	t.Setenv("OPENAI_SENTINEL_NODE_PATH", "/usr/bin/node")
	t.Setenv("CHAT2API_SENTINEL_SCRIPT", "/custom/script.js")
	s := newSentinelSolver(nil, loginUA, nil)
	ns, ok := s.(*nodeSentinelSolver)
	if !ok {
		t.Fatalf("类型错误: %T", s)
	}
	if ns.node != "/usr/bin/node" {
		t.Fatalf("node=%s", ns.node)
	}
	if ns.script != "/custom/script.js" {
		t.Fatalf("script=%s", ns.script)
	}
}
