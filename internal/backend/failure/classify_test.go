package failure

import (
"errors"
"testing"
)

func TestClassify(t *testing.T) {
cases := []struct{
err error
status int
body string
want string
}{
{errors.New("unauthorized"), 401, "", "auth_invalid"},
{nil, 429, "quota exceeded", "image_quota_exhausted"},
{nil, 429, "", "upstream_rate_limited"},
{errors.New("content policy violation"), 400, "", "content_policy_violation"},
{errors.New("poll timeout"), 0, "", "image_poll_timeout"},
{errors.New("stream timeout"), 0, "", "image_stream_timeout"},
{errors.New("connection failed"), 502, "", "upstream_unavailable"},
{errors.New("stream interrupted: connection reset"), 0, "", "image_stream_interrupted"},
{errors.New("unsupported_model: gpt-99"), 400, "", "unsupported_model"},
{errors.New("image download failed"), 0, "", "image_download_failed"},
{errors.New("task_interrupted"), 0, "", "task_interrupted"},
{errors.New("no available account"), 0, "", "no_available_account"},
{errors.New("insufficient_quota"), 429, "", "insufficient_quota"},
{errors.New("all accounts failed: upload image 0: decode image base64: illegal base64 data at input byte 5"), 0, "", "invalid_image_input"},
{errors.New("content filter rejected"), 0, "", "content_policy_violation"},
{errors.New("upstream_text_reply: I can't draw that"), 0, "", "upstream_text_reply"},}
for _, c := range cases {
got := Classify(c.err, c.status, c.body)
if got.Code != c.want {
t.Errorf("Classify(%v,%d,%q)=%q want %q", c.err, c.status, c.body, got.Code, c.want)
}
if got.StatusCode == 0 {
t.Errorf("status code zero for %q", c.want)
}
}
}

// TestPolicyParity P1.6 验收：policy 条数与 Python FAILURE_POLICIES 的 22 条对齐。
func TestPolicyParity(t *testing.T) {
if len(policies) != PolicyCount {
t.Fatalf("policies=%d want %d", len(policies), PolicyCount)
}
wantCodes := map[string]struct {
status int
scope  string
}{
"upstream_error": {502, "transient"},
"internal_error": {500, "internal"},
"upstream_unavailable": {502, "transient"},
"upstream_connection_failed": {502, "transient"},
"upstream_connection_timeout": {504, "transient"},
"upstream_rate_limited": {429, "transient"},
"image_poll_timeout": {502, "transient"},
"image_stream_timeout": {502, "transient"},
"image_stream_interrupted": {502, "transient"},
"image_tool_error": {502, "account"},
"image_quota_exhausted": {429, "account"},
"file_upload_throttled": {429, "account"},
"auth_invalid": {401, "account"},
"content_policy_violation": {400, "request"},
"invalid_image_input": {400, "request"},
"upstream_text_reply": {400, "request"},
"no_image_generated": {502, "request"},
"unsupported_model": {400, "request"},
"image_download_failed": {502, "delivery"},
"task_interrupted": {503, "request"},
"no_available_account": {503, "transient"},
"insufficient_quota": {429, "account"},
}
for code, want := range wantCodes {
p, ok := policies[code]
if !ok {
t.Errorf("missing policy %q", code)
continue
}
if p.StatusCode != want.status || p.Scope != want.scope {
t.Errorf("policy %q: got (%d,%s) want (%d,%s)", code, p.StatusCode, p.Scope, want.status, want.scope)
}
}
}
func TestSwitchAccount(t *testing.T) {
f := New("image_quota_exhausted", nil)
if !f.SwitchAccount() { t.Error("quota should switch") }
f2 := New("content_policy_violation", nil)
if f2.SwitchAccount() { t.Error("content violation should not switch") }
f3 := Classify(errors.New("upload image 0: decode image base64: illegal base64 data"), 0, "")
if f3.SwitchAccount() { t.Error("local decode error should not switch/cooldown account") }
f4 := Classify(errors.New("upstream_text_reply: nope"), 0, "")
if f4.Code != "upstream_text_reply" || f4.StatusCode != 400 || f4.SwitchAccount() {
t.Error("text reply should be request-scope 400 without switch")
}
}
