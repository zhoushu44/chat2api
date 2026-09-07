package auth

import (
	"os"
	"path/filepath"
	"testing"
)

// TestCreateAuthenticateRoundtrip P2.6：创建 → 明文校验通过 → 列表不含 hash。
func TestCreateAuthenticateRoundtrip(t *testing.T) {
	s := NewWithDir(t.TempDir(), "sk-admin-master")
	item, raw, err := s.CreateKey(RoleUser, "test-user")
	if err != nil {
		t.Fatal(err)
	}
	if raw == "" || len(raw) < 10 {
		t.Fatalf("raw key too short: %q", raw)
	}
	if _, hasHash := item["key_hash"]; hasHash {
		t.Fatal("public item leaks key_hash")
	}
	if item["role"] != "user" || item["name"] != "test-user" {
		t.Fatalf("item=%v", item)
	}
	got := s.Authenticate(raw)
	if got == nil || got["id"] != item["id"] {
		t.Fatalf("authenticate failed: %v", got)
	}
	if got["last_used_at"] == nil {
		t.Fatal("last_used_at not set")
	}
	// 错误密钥
	if s.Authenticate("sk-wrong") != nil {
		t.Fatal("wrong key authenticated")
	}
}

// TestAdminKeyConflict P2.6：与管理员主密钥冲突拒绝。
func TestAdminKeyConflict(t *testing.T) {
	s := NewWithDir(t.TempDir(), "sk-admin-master")
	_, _, err := s.CreateKey(RoleUser, "")
	if err != nil {
		t.Fatal(err)
	}
	// 直接用主密钥明文更新 → 冲突
	items := s.ListKeys(RoleUser)
	id, _ := items[0]["id"].(string)
	raw := "sk-admin-master"
	if _, err := s.UpdateKey(id, KeyUpdate{Key: &raw}, RoleUser); err == nil {
		t.Fatal("admin key conflict should error")
	}
}

// TestDuplicateKeyRejected P2.6：与其他条目重复的密钥拒绝；用自身原值更新允许。
func TestDuplicateKeyRejected(t *testing.T) {
	s := NewWithDir(t.TempDir(), "")
	items0, raw1, err := s.CreateKey(RoleUser, "a")
	if err != nil {
		t.Fatal(err)
	}
	id1, _ := items0["id"].(string)
	if _, _, err := s.CreateKey(RoleUser, "b"); err != nil {
		t.Fatal(err)
	}
	items := s.ListKeys(RoleUser)
	var id2 string
	for _, it := range items {
		if it["id"] != id1 {
			id2, _ = it["id"].(string)
		}
	}
	// key2 的值设为 key1 的明文 → 重复拒绝
	dup := raw1
	if _, err := s.UpdateKey(id2, KeyUpdate{Key: &dup}, RoleUser); err == nil {
		t.Fatal("duplicate key should error")
	}
	// 自身原值更新 → 允许
	if _, err := s.UpdateKey(id1, KeyUpdate{Key: &raw1}, RoleUser); err != nil {
		t.Fatalf("self re-key should be allowed: %v", err)
	}
}

// TestDisabledKeyRejected P2.6：禁用后无法校验。
func TestDisabledKeyRejected(t *testing.T) {
	s := NewWithDir(t.TempDir(), "")
	item, raw, err := s.CreateKey(RoleUser, "")
	if err != nil {
		t.Fatal(err)
	}
	id, _ := item["id"].(string)
	off := false
	if _, err := s.UpdateKey(id, KeyUpdate{Enabled: &off}, RoleUser); err != nil {
		t.Fatal(err)
	}
	if s.Authenticate(raw) != nil {
		t.Fatal("disabled key authenticated")
	}
}

// TestDeleteKey P2.6：删除后列表移除且无法校验。
func TestDeleteKey(t *testing.T) {
	s := NewWithDir(t.TempDir(), "")
	item, raw, err := s.CreateKey(RoleUser, "")
	if err != nil {
		t.Fatal(err)
	}
	id, _ := item["id"].(string)
	if !s.DeleteKey(id, RoleUser) {
		t.Fatal("delete failed")
	}
	if s.Authenticate(raw) != nil {
		t.Fatal("deleted key authenticated")
	}
	if len(s.ListKeys(RoleUser)) != 0 {
		t.Fatal("list not empty after delete")
	}
	if s.DeleteKey("no-such-id", RoleUser) {
		t.Fatal("delete nonexistent should be false")
	}
}

// TestPersistenceRestart P2.6：重启恢复（hash 可用，明文不可恢复但可校验）。
func TestPersistenceRestart(t *testing.T) {
	dir := t.TempDir()
	s1 := NewWithDir(dir, "")
	_, raw, err := s1.CreateKey(RoleUser, "persist")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, fileName)); err != nil {
		t.Fatalf("auth file missing: %v", err)
	}
	s2 := NewWithDir(dir, "")
	if s2.Authenticate(raw) == nil {
		t.Fatal("key not usable after restart")
	}
	if len(s2.ListKeys("")) != 1 {
		t.Fatalf("list=%d", len(s2.ListKeys("")))
	}
}

// TestDefaultName P2.6：空名称自动命名且去重。
func TestDefaultName(t *testing.T) {
	s := NewWithDir(t.TempDir(), "")
	item1, _, err := s.CreateKey(RoleUser, "")
	if err != nil {
		t.Fatal(err)
	}
	item2, _, err := s.CreateKey(RoleUser, "")
	if err != nil {
		t.Fatal(err)
	}
	if item1["name"] == item2["name"] {
		t.Fatalf("duplicate default names: %v", item1["name"])
	}
}
