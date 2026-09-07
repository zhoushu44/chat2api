package antibot

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math"
	"math/rand"
	"reflect"
	"strconv"
	"strings"
	"time"
)

// Turnstile VM 完整移植（P2.5）：对等 utils/turnstile.solve_turnstile_token。
// 小端 opcode 虚拟机：process_map 槽位 + 20000 步上限队列 + JS 环境垫片
//（performance.now / Object.create|keys / Math.random / Reflect.set / localStorage）。
// 与 Python 逐语义对齐：float 槽位键、_turnstile_to_str 特殊表、patch 异常吞掉继续。

// SolveTurnstileToken 解算 turnstile dx（对等 utils/turnstile.solve_turnstile_token）。
// 成功返回 token；无法解算返回 nil。VM 步数超限/调用过深返回 nil（防卡死）。
func SolveTurnstileToken(dx, p string) (out *string) {
	if dx == "" || p == "" {
		return nil
	}
	decoded, err := base64.StdEncoding.DecodeString(dx)
	if err != nil {
		if decoded2, err2 := base64.RawStdEncoding.DecodeString(dx); err2 == nil {
			decoded = decoded2
		} else {
			return nil
		}
	}
	var tokenList any
	dec := json.NewDecoder(bytes.NewReader([]byte(xorString(string(decoded), p))))
	dec.UseNumber()
	if err := dec.Decode(&tokenList); err != nil {
		return nil
	}
	// 数字归一（int 保持 int64，与 Python json.loads 一致）
	tokenList = normalizeNumbers(tokenList)
	vm := newTurnstileVM(p, tokenList)
	defer func() {
		// 步数超限/调用过深等 VM 错误 → nil（真实上游 finalize 允许空 turnstile_token 降级）
		_ = recover()
	}()
	vm.runQueueTop()
	if vm.result == "" {
		return nil
	}
	s := vm.result
	return &s
}

// vmKey 槽位键（对等 Python 数字/字符串 dict 键；整数值 float 归一为 int64）。
type vmKey struct {
	kind int // 0=int 1=float 2=string 3=other
	i    int64
	f    float64
	s    string
}

func normalizeVMKey(v any) (vmKey, bool) {
	switch t := v.(type) {
	case int64:
		return vmKey{kind: 0, i: t}, true
	case int:
		return vmKey{kind: 0, i: int64(t)}, true
	case float64:
		if t == math.Trunc(t) && !math.IsInf(t, 0) && math.Abs(t) < 9e15 {
			return vmKey{kind: 0, i: int64(t)}, true
		}
		return vmKey{kind: 1, f: t}, true
	case json.Number:
		if i, err := t.Int64(); err == nil {
			return vmKey{kind: 0, i: i}, true
		}
		if f, err := t.Float64(); err == nil {
			return normalizeVMKey(f)
		}
		return vmKey{}, false
	case string:
		return vmKey{kind: 2, s: t}, true
	case bool:
		if t {
			return vmKey{kind: 0, i: 1}, true
		}
		return vmKey{kind: 0, i: 0}, true
	default:
		return vmKey{}, false
	}
}

// orderedMap 有序映射（对等 OrderedMap）。
type orderedMap struct {
	keys   []string
	values map[string]any
}

func newOrderedMap() *orderedMap {
	return &orderedMap{values: map[string]any{}}
}

func (o *orderedMap) add(key string, value any) {
	if _, ok := o.values[key]; !ok {
		o.keys = append(o.keys, key)
	}
	o.values[key] = value
}

// vmFn VM 可调用值（opcode 与 subroutine 统一签名）。
type vmFn func(args []any)

// vmStepLimit 步数超限（向上传播，不被吞掉）。
type vmStepLimit struct{}

// vmMaxDepth 最大调用深度（防无限递归爆栈；Python 侧为 RecursionError，此处转受控错误）。
const vmMaxDepth = 500

type turnstileVM struct {
	slots  map[vmKey]any
	result string
	rnd    *rand.Rand
	start  time.Time
	depth  int
}

func newTurnstileVM(p string, tokenList any) *turnstileVM {
	vm := &turnstileVM{
		slots: map[vmKey]any{},
		rnd:   rand.New(rand.NewSource(time.Now().UnixNano())),
		start: time.Now(),
	}
	vm.set(1, vmFn(vm.fn1))
	vm.set(2, vmFn(vm.fn2))
	vm.set(3, vmFn(vm.fn3))
	vm.set(5, vmFn(vm.fn5))
	vm.set(6, vmFn(vm.fn6))
	vm.set(7, vmFn(vm.fn7))
	vm.set(8, vmFn(vm.fn8))
	vm.set(9, tokenList)
	vm.set(10, "window")
	vm.set(11, vmFn(func(args []any) {
		if len(args) >= 1 {
			vm.set(args[0], nil)
		}
	}))
	vm.set(12, vmFn(func(args []any) {
		if len(args) >= 1 {
			vm.set(args[0], vm.slots)
		}
	}))
	vm.set(13, vmFn(vm.fn13))
	vm.set(14, vmFn(vm.fn14))
	vm.set(15, vmFn(vm.fn15))
	vm.set(16, p)
	vm.set(17, vmFn(vm.fn17))
	vm.set(18, vmFn(vm.fn18))
	vm.set(19, vmFn(vm.fn19))
	vm.set(20, vmFn(vm.fn20))
	vm.set(21, vmFn(vm.fn21))
	vm.set(22, vmFn(vm.fn22))
	vm.set(23, vmFn(vm.fn23))
	vm.set(24, vmFn(vm.fn24))
	vm.set(25, vmFn(func(args []any) {}))
	vm.set(26, vmFn(func(args []any) {}))
	vm.set(27, vmFn(vm.fn27))
	vm.set(28, vmFn(func(args []any) {}))
	vm.set(29, vmFn(vm.fn29))
	vm.set(30, vmFn(vm.fn30))
	vm.set(33, vmFn(vm.fn33))
	vm.set(34, vmFn(vm.fn34))
	return vm
}

func (vm *turnstileVM) set(key, value any) {
	// 对等 process_map[key] = value：不可哈希键抛 TypeError，被 run_queue 吞掉
	k, ok := normalizeVMKey(key)
	if !ok {
		panic(vmKeyError{key: key})
	}
	vm.slots[k] = value
}

func (vm *turnstileVM) get(key any) any {
	// 对等 get_value：process_map.get(key) 在不可哈希键上同样抛 TypeError
	k, ok := normalizeVMKey(key)
	if !ok {
		panic(vmKeyError{key: key})
	}
	return vm.slots[k]
}

// vmKeyError 不可哈希键（被 run_queue 吞掉继续；步数超限类错误向上传播）。
type vmKeyError struct{ key any }

func (e vmKeyError) Error() string { return "unhashable vm key" }

// has 槽位存在性（对等 process_map[t] 直接下标：缺键抛 KeyError 被吞掉，不写槽位）。
func (vm *turnstileVM) has(key any) bool {
	k, ok := normalizeVMKey(key)
	if !ok {
		return false
	}
	_, exists := vm.slots[k]
	return exists
}

// runQueueTop 顶层队列执行。
func (vm *turnstileVM) runQueueTop() {
	vm.runQueue(20000)
}

// runQueue 队列执行（对等 run_queue；单异常吞掉继续，步数超限向上传播）。
func (vm *turnstileVM) runQueue(limit int) {
	steps := 0
	for {
		q, ok := vm.get(9).([]any)
		if !ok || len(q) == 0 {
			return
		}
		steps++
		if steps > limit {
			panic(vmStepLimit{})
		}
		token := q[0]
		vm.set(9, append([]any{}, q[1:]...))
		tok, ok := token.([]any)
		if !ok || len(tok) == 0 {
			continue
		}
		fn, ok := vm.get(tok[0]).(vmFn)
		if !ok {
			continue
		}
		func() {
			defer func() {
				if r := recover(); r != nil {
					if _, isLimit := r.(vmStepLimit); isLimit {
						panic(r)
					}
					// 对等 except Exception: continue
				}
			}()
			fn(tok[1:])
		}()
	}
}

func (vm *turnstileVM) arg(args []any, i int) any {
	if i < len(args) {
		return args[i]
	}
	return nil
}

// --- opcode 实现（编号对等 func_N）---

func (vm *turnstileVM) fn1(args []any) {
	vm.set(vm.arg(args, 0), xorString(turnstileToStr(vm.get(vm.arg(args, 0))), turnstileToStr(vm.get(vm.arg(args, 1)))))
}

func (vm *turnstileVM) fn2(args []any) {
	vm.set(vm.arg(args, 0), vm.arg(args, 1))
}

func (vm *turnstileVM) fn3(args []any) {
	if s, ok := vm.arg(args, 0).(string); ok {
		vm.result = base64.StdEncoding.EncodeToString([]byte(s))
	}
	// 非字符串 → 对等 Python AttributeError，被 run_queue 吞掉
}

func (vm *turnstileVM) fn5(args []any) {
	current := vm.get(vm.arg(args, 0))
	incoming := vm.get(vm.arg(args, 1))
	if cl, ok := current.([]any); ok {
		vm.set(vm.arg(args, 0), append(append([]any{}, cl...), incoming))
		return
	}
	if isStrOrNum(current) || isStrOrNum(incoming) {
		vm.set(vm.arg(args, 0), turnstileToStr(current)+turnstileToStr(incoming))
		return
	}
	vm.set(vm.arg(args, 0), "NaN")
}

func (vm *turnstileVM) fn6(args []any) {
	vm.set(vm.arg(args, 0), jsProp(vm.get(vm.arg(args, 1)), vm.get(vm.arg(args, 2))))
}

func (vm *turnstileVM) fn7(args []any) {
	resolved := make([]any, 0, len(args)-1)
	for _, a := range args[1:] {
		resolved = append(resolved, vm.get(a))
	}
	vm.callTarget(vm.get(vm.arg(args, 0)), resolved)
}

func (vm *turnstileVM) fn8(args []any) {
	// process_map[t] 直接下标：缺键 KeyError 被 run_queue 吞掉（槽位不动）
	if !vm.has(vm.arg(args, 1)) {
		return
	}
	vm.set(vm.arg(args, 0), vm.get(vm.arg(args, 1)))
}

func (vm *turnstileVM) fn13(args []any) {
	defer func() {
		if r := recover(); r != nil {
			vm.set(vm.arg(args, 0), fmt.Sprint(r))
		}
	}()
	raw := []any{}
	if len(args) > 2 {
		raw = args[2:]
	}
	vm.callTarget(vm.get(vm.arg(args, 1)), raw)
}

func (vm *turnstileVM) fn14(args []any) {
	s, ok := vm.get(vm.arg(args, 1)).(string)
	if !ok {
		return
	}
	dec := json.NewDecoder(bytes.NewReader([]byte(s)))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return
	}
	vm.set(vm.arg(args, 0), normalizeNumbers(v))
}

func (vm *turnstileVM) fn15(args []any) {
	// json.dumps(process_map[t])：缺键 KeyError 被吞掉
	if !vm.has(vm.arg(args, 1)) {
		return
	}
	b, err := json.Marshal(vm.get(vm.arg(args, 1)))
	if err != nil {
		return
	}
	vm.set(vm.arg(args, 0), string(b))
}

func (vm *turnstileVM) fn17(args []any) {
	resolved := make([]any, 0, len(args)-2)
	for _, a := range args[2:] {
		resolved = append(resolved, vm.get(a))
	}
	vm.set(vm.arg(args, 0), vm.callTarget(vm.get(vm.arg(args, 1)), resolved))
}

func (vm *turnstileVM) fn18(args []any) {
	// b64decode(str(process_map[e]))：缺键 KeyError 被吞掉
	if !vm.has(vm.arg(args, 0)) {
		return
	}
	s := turnstileToStr(vm.get(vm.arg(args, 0)))
	b, err := base64.StdEncoding.DecodeString(s)
	if err != nil {
		if b2, err2 := base64.RawStdEncoding.DecodeString(s); err2 == nil {
			b = b2
		} else {
			return
		}
	}
	vm.set(vm.arg(args, 0), string(b))
}

func (vm *turnstileVM) fn19(args []any) {
	// _turnstile_to_str(process_map[e])：缺键 KeyError 被吞掉
	if !vm.has(vm.arg(args, 0)) {
		return
	}
	vm.set(vm.arg(args, 0), base64.StdEncoding.EncodeToString([]byte(turnstileToStr(vm.get(vm.arg(args, 0))))))
}

func (vm *turnstileVM) fn20(args []any) {
	if vmEqual(vm.get(vm.arg(args, 0)), vm.get(vm.arg(args, 1))) {
		if target, ok := vm.get(vm.arg(args, 2)).(vmFn); ok {
			raw := []any{}
			if len(args) > 3 {
				raw = args[3:]
			}
			target(raw)
		}
	}
}

func (vm *turnstileVM) fn21(args []any) {
	delta := 0.0
	if a, oka := asFloat(vm.get(vm.arg(args, 0))); oka {
		if b, okb := asFloat(vm.get(vm.arg(args, 1))); okb {
			delta = a - b
		}
	}
	if math.Abs(delta) > jsAbs(vm.get(vm.arg(args, 2))) {
		if target, ok := vm.get(vm.arg(args, 3)).(vmFn); ok {
			raw := []any{}
			if len(args) > 4 {
				raw = args[4:]
			}
			target(raw)
		}
	}
}

func (vm *turnstileVM) fn22(args []any) {
	vm.enterDepth()
	defer vm.exitDepth()
	var previous []any
	if q, ok := vm.get(9).([]any); ok {
		previous = append([]any{}, q...)
	}
	if queue, ok := vm.arg(args, 1).([]any); ok {
		vm.set(9, append([]any{}, queue...))
	} else {
		vm.set(9, []any{})
	}
	vm.runQueue(20000)
	vm.set(vm.arg(args, 0), "None")
	vm.set(9, previous)
}

func (vm *turnstileVM) fn23(args []any) {
	if vm.get(vm.arg(args, 0)) != nil {
		if target, ok := vm.get(vm.arg(args, 1)).(vmFn); ok {
			raw := []any{}
			if len(args) > 2 {
				raw = args[2:]
			}
			target(raw)
		}
	}
}

func (vm *turnstileVM) fn24(args []any) {
	vm.set(vm.arg(args, 0), jsProp(vm.get(vm.arg(args, 1)), vm.get(vm.arg(args, 2))))
}

func (vm *turnstileVM) fn27(args []any) {
	current := vm.get(vm.arg(args, 0))
	incoming := vm.get(vm.arg(args, 1))
	if cl, ok := current.([]any); ok {
		for i, item := range cl {
			if vmEqual(item, incoming) {
				vm.set(vm.arg(args, 0), append(append([]any{}, cl[:i]...), cl[i+1:]...))
				break
			}
		}
		return
	}
	// int-int 保持 int（对等 Python current - incoming 类型语义）
	if ai, oka := asIntPair(current); oka {
		if bi, okb := asIntPair(incoming); okb {
			vm.set(vm.arg(args, 0), ai-bi)
			return
		}
	}
	if a, oka := asFloat(current); oka {
		if b, okb := asFloat(incoming); okb {
			vm.set(vm.arg(args, 0), a-b)
			return
		}
	}
	vm.set(vm.arg(args, 0), 0.0)
}

func (vm *turnstileVM) fn29(args []any) {
	ok, less := vmLess(vm.get(vm.arg(args, 1)), vm.get(vm.arg(args, 2)))
	if !ok {
		vm.set(vm.arg(args, 0), false)
		return
	}
	vm.set(vm.arg(args, 0), less)
}

func (vm *turnstileVM) fn30(args []any) {
	var isArray bool
	var captureKeys []any
	var queue []any
	if r, ok := vm.arg(args, 3).([]any); ok {
		isArray = true
		if n, ok := vm.arg(args, 2).([]any); ok {
			captureKeys = n
		}
		queue = r
	} else if n, ok := vm.arg(args, 2).([]any); ok {
		queue = n
	}
	sub := vmFn(func(callArgs []any) {
		vm.enterDepth()
		defer vm.exitDepth()
		var previous []any
		if q, ok := vm.get(9).([]any); ok {
			previous = append([]any{}, q...)
		}
		if isArray {
			for i, key := range captureKeys {
				if i < len(callArgs) {
					vm.set(key, callArgs[i])
				}
			}
		}
		vm.set(9, append([]any{}, queue...))
		vm.runQueue(20000)
		vm.set(9, previous)
	})
	vm.set(vm.arg(args, 0), sub)
}

func (vm *turnstileVM) fn33(args []any) {
	// int-int 保持 int
	if ai, oka := asIntPair(vm.get(vm.arg(args, 1))); oka {
		if bi, okb := asIntPair(vm.get(vm.arg(args, 2))); okb {
			vm.set(vm.arg(args, 0), ai*bi)
			return
		}
	}
	a, oka := asFloat(vm.get(vm.arg(args, 1)))
	b, okb := asFloat(vm.get(vm.arg(args, 2)))
	if !oka || !okb {
		vm.set(vm.arg(args, 0), 0.0)
		return
	}
	vm.set(vm.arg(args, 0), a*b)
}

func (vm *turnstileVM) fn34(args []any) {
	vm.set(vm.arg(args, 0), vm.get(vm.arg(args, 1)))
}

func (vm *turnstileVM) enterDepth() {
	vm.depth++
	if vm.depth > vmMaxDepth {
		panic(vmStepLimit{})
	}
}

func (vm *turnstileVM) exitDepth() {
	vm.depth--
}

// callTarget JS 环境垫片调用（对等 call_target）。
func (vm *turnstileVM) callTarget(target any, args []any) any {
	if s, ok := target.(string); ok {
		switch s {
		case "window.performance.now":
			elapsed := float64(time.Since(vm.start).Nanoseconds()) + vm.rnd.Float64()
			return elapsed / 1e6
		case "window.Object.create":
			return newOrderedMap()
		case "window.Object.keys":
			if len(args) > 0 {
				if args[0] == "window.localStorage" {
					return []any{
						"STATSIG_LOCAL_STORAGE_INTERNAL_STORE_V4",
						"STATSIG_LOCAL_STORAGE_STABLE_ID",
						"client-correlated-secret",
						"oai/apps/capExpiresAt",
						"oai-did",
						"STATSIG_LOCAL_STORAGE_LOGGING_REQUEST",
						"UiState.isNavigationCollapsed.1",
					}
				}
				if om, ok := args[0].(*orderedMap); ok {
					out := make([]any, 0, len(om.keys))
					for _, k := range om.keys {
						out = append(out, k)
					}
					return out
				}
				if m, ok := args[0].(map[string]any); ok {
					out := make([]any, 0, len(m))
					for k := range m {
						out = append(out, k)
					}
					return out
				}
			}
			return nil
		case "window.Math.random":
			return vm.rnd.Float64()
		case "window.Reflect.set":
			// 参数不足时对等 Python 解包错误（fn13 捕获后存 str(exc)）
			if len(args) < 3 {
				panic(fmt.Sprintf("not enough values to unpack (expected 3, got %d)", len(args)))
			}
			obj, keyName, val := args[0], args[1], args[2]
			ks := turnstileToStr(keyName)
			if om, ok := obj.(*orderedMap); ok {
				om.add(ks, val)
				return true
			}
			if m, ok := obj.(map[string]any); ok {
				m[ks] = val
				return true
			}
			return false
		}
		return nil
	}
	if fn, ok := target.(vmFn); ok {
		fn(args)
		return nil
	}
	return nil
}

// jsProp 属性访问（对等 js_prop）。
func jsProp(obj, key any) any {
	if om, ok := obj.(*orderedMap); ok {
		return om.values[turnstileToStr(key)]
	}
	if m, ok := obj.(map[string]any); ok {
		return m[keyToStr(key)]
	}
	if arr, ok := obj.([]any); ok {
		if i, ok := asInt(key); ok && i >= 0 && i < len(arr) {
			return arr[i]
		}
		return nil
	}
	if s, ok := obj.(string); ok {
		keyText := turnstileToStr(key)
		if keyText == "location" && s == "window.document" {
			return "https://chatgpt.com/"
		}
		if keyText != "" && keyText != "undefined" && keyText != "None" {
			return s + "." + keyText
		}
	}
	return nil
}

func keyToStr(key any) string {
	if s, ok := key.(string); ok {
		return s
	}
	return turnstileToStr(key)
}

// turnstileToStr JS 风格转字符串（对等 _turnstile_to_str）。
func turnstileToStr(value any) string {
	switch v := value.(type) {
	case nil:
		return "undefined"
	case bool:
		if v {
			return "True"
		}
		return "False"
	case string:
		if s, ok := turnstileSpecial[v]; ok {
			return s
		}
		return v
	case int64:
		return strconv.FormatInt(v, 10)
	case int:
		return strconv.Itoa(v)
	case float64:
		return pyFloatStr(v)
	case json.Number:
		return v.String()
	case []any:
		allStr := true
		for _, item := range v {
			if _, ok := item.(string); !ok {
				allStr = false
				break
			}
		}
		if allStr {
			parts := make([]string, 0, len(v))
			for _, item := range v {
				parts = append(parts, item.(string))
			}
			return strings.Join(parts, ",")
		}
		return pyRepr(v)
	case map[string]any:
		return pyRepr(v)
	case *orderedMap:
		return pyRepr(v.values)
	default:
		return fmt.Sprint(value)
	}
}

var turnstileSpecial = map[string]string{
	"window.Math":             "[object Math]",
	"window.Reflect":          "[object Reflect]",
	"window.performance":      "[object Performance]",
	"window.localStorage":     "[object Storage]",
	"window.Object":           "function Object() { [native code] }",
	"window.Reflect.set":      "function set() { [native code] }",
	"window.performance.now":  "function () { [native code] }",
	"window.Object.create":    "function create() { [native code] }",
	"window.Object.keys":      "function keys() { [native code] }",
	"window.Math.random":      "function random() { [native code] }",
}

// pyFloatStr Python repr(float) 风格（整数带 .0）。
func pyFloatStr(f float64) string {
	if math.IsNaN(f) {
		return "nan"
	}
	if math.IsInf(f, 1) {
		return "inf"
	}
	if math.IsInf(f, -1) {
		return "-inf"
	}
	if f == math.Trunc(f) && math.Abs(f) < 1e21 {
		return strconv.FormatInt(int64(f), 10) + ".0"
	}
	abs := math.Abs(f)
	if (abs >= 1e16 || (abs < 1e-4 && abs != 0)) {
		s := strconv.FormatFloat(f, 'e', -1, 64)
		// Python 风格指数：1e+16（Go 已同形）
		return s
	}
	return strconv.FormatFloat(f, 'f', -1, 64)
}

// pyRepr 近似 Python repr（list/dict，供 _turnstile_to_str 兜底）。
func pyRepr(v any) string {
	switch t := v.(type) {
	case string:
		return "'" + t + "'"
	case []any:
		parts := make([]string, 0, len(t))
		for _, item := range t {
			parts = append(parts, pyRepr(item))
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case map[string]any:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		// 排序保证确定性（Python dict 保持插入序；此处尽力）
		for i := 0; i < len(keys); i++ {
			for j := i + 1; j < len(keys); j++ {
				if keys[j] < keys[i] {
					keys[i], keys[j] = keys[j], keys[i]
				}
			}
		}
		parts := make([]string, 0, len(keys))
		for _, k := range keys {
			parts = append(parts, "'"+k+"': "+pyRepr(t[k]))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	case bool:
		if t {
			return "True"
		}
		return "False"
	case nil:
		return "None"
	case int64:
		return strconv.FormatInt(t, 10)
	case float64:
		return pyFloatStr(t)
	default:
		return fmt.Sprint(v)
	}
}

// normalizeNumbers JSON Number → int64/float64（保持 Python int/float 区分）。
func normalizeNumbers(v any) any {
	switch t := v.(type) {
	case json.Number:
		if i, err := t.Int64(); err == nil {
			return i
		}
		if f, err := t.Float64(); err == nil {
			return f
		}
		return t.String()
	case []any:
		for i, item := range t {
			t[i] = normalizeNumbers(item)
		}
		return t
	case map[string]any:
		for k, item := range t {
			t[k] = normalizeNumbers(item)
		}
		return t
	default:
		return v
	}
}

func isStrOrNum(v any) bool {
	switch v.(type) {
	case string, int64, int, float64, json.Number:
		return true
	default:
		return false
	}
}

// asFloat 数值转换（bool 按 Python float(True)=1.0）。
func asFloat(v any) (float64, bool) {
	switch t := v.(type) {
	case float64:
		return t, true
	case int64:
		return float64(t), true
	case int:
		return float64(t), true
	case bool:
		if t {
			return 1, true
		}
		return 0, true
	case json.Number:
		if f, err := t.Float64(); err == nil {
			return f, true
		}
		return 0, false
	case string:
		if f, err := strconv.ParseFloat(strings.TrimSpace(t), 64); err == nil {
			return f, true
		}
		return 0, false
	default:
		return 0, false
	}
}

func asInt(v any) (int, bool) {
	switch t := v.(type) {
	case int64:
		return int(t), true
	case int:
		return t, true
	case bool:
		if t {
			return 1, true
		}
		return 0, true
	case float64:
		return int(t), true
	case json.Number:
		if i, err := t.Int64(); err == nil {
			return int(i), true
		}
		return 0, false
	case string:
		if i, err := strconv.Atoi(strings.TrimSpace(t)); err == nil {
			return i, true
		}
		return 0, false
	default:
		return 0, false
	}
}

// asIntPair 严格整数对（bool 亦可，对等 Python int() 语义子集；float 小数拒绝）。
func asIntPair(v any) (int64, bool) {
	switch t := v.(type) {
	case int64:
		return t, true
	case int:
		return int64(t), true
	case bool:
		if t {
			return 1, true
		}
		return 0, true
	case json.Number:
		if i, err := t.Int64(); err == nil {
			return i, true
		}
		return 0, false
	default:
		return 0, false
	}
}

// jsAbs 对等 js_abs。
func jsAbs(v any) float64 {
	if f, ok := asFloat(v); ok {
		return math.Abs(f)
	}
	return 0
}

// vmEqual Python == 语义（数字含 bool 互比、字符串、list 元素比、其它 DeepEqual）。
func vmEqual(a, b any) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	_, aIsBool := a.(bool)
	_, bIsBool := b.(bool)
	if isNum(a) || isNum(b) || aIsBool || bIsBool {
		if (isNum(a) || aIsBool) && (isNum(b) || bIsBool) {
			af, _ := asFloat(a)
			bf, _ := asFloat(b)
			return af == bf
		}
		return false
	}
	if as, ok := a.(string); ok {
		bs, ok := b.(string)
		return ok && as == bs
	}
	if al, ok := a.([]any); ok {
		bl, ok := b.([]any)
		if !ok || len(al) != len(bl) {
			return false
		}
		for i := range al {
			if !vmEqual(al[i], bl[i]) {
				return false
			}
		}
		return true
	}
	return reflect.DeepEqual(a, b)
}

func isNum(v any) bool {
	switch v.(type) {
	case int64, int, float64, json.Number:
		return true
	default:
		return false
	}
}

// vmLess Python < 语义（数字/字符串同类比，否则不可比）。
func vmLess(a, b any) (bool, bool) {
	if (isNum(a) || isBoolNum(a)) && (isNum(b) || isBoolNum(b)) {
		af, oka := asFloat(a)
		bf, okb := asFloat(b)
		if !oka || !okb {
			return false, false
		}
		return af < bf, true
	}
	if as, ok := a.(string); ok {
		if bs, ok := b.(string); ok {
			return as < bs, true
		}
	}
	return false, false
}

func isBoolNum(v any) bool {
	_, ok := v.(bool)
	return ok
}

func xorString(text, key string) string {
	if key == "" {
		return text
	}
	rText := []rune(text)
	rKey := []rune(key)
	out := make([]rune, len(rText))
	for i, ch := range rText {
		out[i] = ch ^ rKey[i%len(rKey)]
	}
	return string(out)
}
