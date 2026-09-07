// Command migrate-storage:存储后端数据迁移工具。
// 对等 scripts/migrate_storage.py：--export/--import 账号 JSON，--from/--to 在 KV 后端间迁移。
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/storage"
)

func dataDir() string {
	if d := os.Getenv("CHATGPT2API_DATA_DIR"); d != "" {
		return d
	}
	return "./data"
}

func exportAccounts(output string) int {
	svc := account.New(dataDir())
	accs := svc.List()
	var out []any
	for _, a := range accs {
		out = append(out, a)
	}
	if out == nil {
		out = []any{}
	}
	b, _ := json.MarshalIndent(out, "", "  ")
	b = append(b, '\n')
	if err := os.WriteFile(output, b, 0644); err != nil {
		fmt.Fprintf(os.Stderr, "[migrate] write %s: %v\n", output, err)
		return 1
	}
	fmt.Printf("[migrate] Exported %d accounts to %s\n", len(out), output)
	return 0
}

func importAccounts(input string) int {
	raw, err := os.ReadFile(input)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[migrate] Error: File not found: %s\n", input)
		return 1
	}
	var arr []map[string]any
	if err := json.Unmarshal(raw, &arr); err != nil {
		fmt.Fprintf(os.Stderr, "[migrate] Error: Invalid JSON: %v\n", err)
		return 1
	}
	svc := account.New(dataDir())
	n := 0
	for _, m := range arr {
		var a account.Account
		b, _ := json.Marshal(m)
		if err := json.Unmarshal(b, &a); err != nil {
			continue
		}
		if a.Token == "" && a.Email == "" {
			continue
		}
		if err := svc.Add(&a); err == nil {
			n++
		}
	}
	fmt.Printf("[migrate] Imported %d accounts\n", n)
	return 0
}

func migrateKV(from, to string) int {
	fmt.Printf("[migrate] Migrating from %s to %s\n", from, to)
	dir := dataDir()
	os.Setenv("STORAGE_BACKEND", from)
	fromStore, err := storage.NewFromEnv(dir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[migrate] from backend: %v\n", err)
		return 1
	}
	items, err := fromStore.List()
	if err != nil {
		fmt.Fprintf(os.Stderr, "[migrate] list: %v\n", err)
		return 1
	}
	fmt.Printf("[migrate] Loaded %d keys from %s\n", len(items), from)
	os.Setenv("STORAGE_BACKEND", to)
	toStore, err := storage.NewFromEnv(dir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[migrate] to backend: %v\n", err)
		return 1
	}
	for k, v := range items {
		if err := toStore.Set(k, v); err != nil {
			fmt.Fprintf(os.Stderr, "[migrate] set %s: %v\n", k, err)
			return 1
		}
	}
	fmt.Printf("[migrate] Saved %d keys to %s\n", len(items), to)
	fmt.Println("[migrate] Migration completed successfully!")
	return 0
}

func main() {
	from := flag.String("from", "", "源后端 (json|sqlite|postgres|git|pebble)")
	to := flag.String("to", "", "目标后端")
	export := flag.String("export", "", "导出账号到 JSON 文件")
	importFile := flag.String("import", "", "从 JSON 文件导入账号")
	flag.Parse()
	switch {
	case *export != "":
		os.Exit(exportAccounts(*export))
	case *importFile != "":
		os.Exit(importAccounts(*importFile))
	case *from != "" && *to != "":
		os.Exit(migrateKV(*from, *to))
	default:
		fmt.Fprintln(os.Stderr, "用法: migrate-storage --export out.json | --import in.json | --from json --to sqlite")
		os.Exit(2)
	}
}
