package antibot

import (
	"encoding/base64"
	"testing"
)

// P2.5 精确断言测试。关键语义（与 Python 一致，需注意的两点）:
// 1. func_3 取字面量（e.encode()，非槽位值），计算结果经 func_20/21 条件门控字面量子程序输出；
// 2. 数据槽位不得复用 opcode 编号（op2 会覆盖 process_map[e] 自身——Python 同理），
//    故测试程序一律使用 100+ 数据槽。
func TestSolveTurnstile(t *testing.T) {
	if tok := SolveTurnstileToken("", "p"); tok != nil {
		t.Fatalf("expected nil for empty dx")
	}
	if tok := SolveTurnstileToken("eA==", ""); tok != nil {
		t.Fatalf("expected nil for empty p")
	}
	p := "gAAAAACdummy"
	solve := func(t *testing.T, tokenList string) *string {
		t.Helper()
		xored := xorString(tokenList, p)
		dx := base64.StdEncoding.EncodeToString([]byte(xored))
		return SolveTurnstileToken(dx, p)
	}
	b64 := func(s string) string {
		return base64.StdEncoding.EncodeToString([]byte(s))
	}
	// 字面量输出
	if tok := solve(t, `[[3,"hello"]]`); tok == nil || *tok != "aGVsbG8=" {
		t.Fatalf("literal: %v", strPtr(tok))
	}
	// 字符串拼接 → 条件观测
	prog := `[[2,101,"foo"],[2,102,"bar"],[5,101,102],[2,103,"foobar"],[30,105,0,[[3,"CONCAT-OK"]]],[20,101,103,105]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("CONCAT-OK") {
		t.Fatalf("concat: %v", strPtr(tok))
	}
	// XOR：xor("ab","k")="\n\t"
	prog = `[[2,101,"ab"],[2,102,"k"],[1,101,102],[2,103,"\n\t"],[30,105,0,[[3,"XOR-OK"]]],[20,101,103,105]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("XOR-OK") {
		t.Fatalf("xor: %v", strPtr(tok))
	}
	// subroutine + 条件成立
	prog = `[[2,101,"x"],[2,102,"x"],[30,105,0,[[3,"YES"]]],[20,101,102,105]]`
	if tok := solve(t, prog); tok == nil || *tok != "WUVT" {
		t.Fatalf("subroutine-taken: %v", strPtr(tok))
	}
	// 条件不成立 → nil
	prog = `[[2,101,"x"],[2,102,"y"],[30,105,0,[[3,"YES"]]],[20,101,102,105]]`
	if tok := solve(t, prog); tok != nil {
		t.Fatalf("subroutine-skipped should be nil: %v", *tok)
	}
	// js_prop：window.document.location
	prog = `[[2,101,"window.document"],[2,102,"location"],[6,103,101,102],[2,104,"https://chatgpt.com/"],[30,105,0,[[3,"PROP-OK"]]],[20,103,104,105]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("PROP-OK") {
		t.Fatalf("jsprop: %v", strPtr(tok))
	}
	// 算术：6*7=42（float）与 int 42 相等
	prog = `[[2,101,6],[2,102,7],[33,103,101,102],[2,104,42],[30,105,0,[[3,"MATH-OK"]]],[20,103,104,105]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("MATH-OK") {
		t.Fatalf("math: %v", strPtr(tok))
	}
	// 减法：10-4=6
	prog = `[[2,101,10],[2,102,4],[27,101,102],[2,103,6],[30,105,0,[[3,"SUB-OK"]]],[20,101,103,105]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("SUB-OK") {
		t.Fatalf("sub: %v", strPtr(tok))
	}
	// 比较：3<5 → true
	prog = `[[2,101,3],[2,102,5],[29,103,101,102],[2,104,true],[30,105,0,[[3,"LT-OK"]]],[20,103,104,105]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("LT-OK") {
		t.Fatalf("less: %v", strPtr(tok))
	}
	// 条件差值：|10-3|=7 > 5 → 调用
	prog = `[[2,101,10],[2,102,3],[2,103,5],[30,105,0,[[3,"GT-OK"]]],[21,101,102,103,105]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("GT-OK") {
		t.Fatalf("cond-delta: %v", strPtr(tok))
	}
	// b64 解码：aGk= → hi
	prog = `[[2,101,"aGk="],[18,101],[2,102,"hi"],[30,105,0,[[3,"B64-OK"]]],[20,101,102,105]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("B64-OK") {
		t.Fatalf("b64decode: %v", strPtr(tok))
	}
	// json 解析 + 属性读取：{"a":1}.a == 1（属性名须先入槽，n 经 get_value 解析）
	prog = `[[2,101,"{\"a\":1}"],[14,102,101],[2,110,"a"],[24,103,102,110],[2,104,1],[30,105,0,[[3,"JSON-OK"]]],[20,103,104,105]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("JSON-OK") {
		t.Fatalf("json: %v", strPtr(tok))
	}
	// Object.keys(dict) + dumps：["b"]（dict 须先入槽，直接传字面量会 TypeError——与 Python 一致）
	prog = `[[2,107,{"b":2}],[2,106,"window.Object.keys"],[17,102,106,107],[15,103,102],[2,104,"[\"b\"]"],[30,105,0,[[3,"KEYS-OK"]]],[20,103,104,105]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("KEYS-OK") {
		t.Fatalf("objkeys: %v", strPtr(tok))
	}
	// OrderedMap 全链：字面量池 + create → fn7 Reflect.set（解析后参数）→ keys → dumps → ["k"]
	// 注意：fn7/fn17 的参数经 get_value 解析，字符串字面量须先 op2 入槽（与 Python 一致）
	prog = `[[2,"k","k"],[2,"v","v"],[2,105,"window.Object.create"],[17,101,105],[2,106,"window.Reflect.set"],[7,106,101,"k","v"],[2,107,"window.Object.keys"],[17,103,107,101],[15,104,103],[2,140,"[\"k\"]"],[30,141,0,[[3,"OMAP-OK"]]],[20,104,140,141]]`
	if tok := solve(t, prog); tok == nil || *tok != b64("OMAP-OK") {
		t.Fatalf("orderedmap: %v", strPtr(tok))
	}
	// func_22 嵌套队列
	if tok := solve(t, `[[22,101,[[3,"NESTED"]]]]`); tok == nil || *tok != b64("NESTED") {
		t.Fatalf("nested queue: %v", strPtr(tok))
	}
	// func_23 非空门控调用
	if tok := solve(t, `[[2,101,"nonull"],[30,105,0,[[3,"W23-OK"]]],[23,101,105]]`); tok == nil || *tok != b64("W23-OK") {
		t.Fatalf("guard call: %v", strPtr(tok))
	}
	// func_7 无返回值调用不崩
	if tok := solve(t, `[[2,105,"window.Object.create"],[7,105]]`); tok != nil {
		t.Fatalf("fire-and-forget should be nil: %v", *tok)
	}
	// 旧桩测试程序 [[1,2],[3,4]]：func_3(4) 非字符串 → nil（与 Python 一致）
	if tok := solve(t, `[[1,2],[3,4]]`); tok != nil {
		t.Fatalf("non-string result should be nil: %v", *tok)
	}
	// 坏 dx → nil
	if tok := SolveTurnstileToken("!!!not-base64!!!", p); tok != nil {
		t.Fatalf("bad dx should be nil")
	}
	// 自递归程序 → 受控 nil（不爆栈；Python 侧为 RecursionError）
	if tok := solve(t, `[[30,105,0,[[7,105]]],[7,105]]`); tok != nil {
		t.Fatalf("recursive program should be nil: %v", *tok)
	}
}

func strPtr(s *string) string {
	if s == nil {
		return "<nil>"
	}
	return *s
}
