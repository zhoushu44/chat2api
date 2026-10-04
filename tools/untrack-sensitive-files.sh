#!/bin/sh
# ============================================================
# 解除「已被追踪但应忽略」文件的追踪状态
#
# 背景：
#   .gitignore 只对「未追踪」文件生效。本仓有大量敏感文件在规则加严前
#   就已被 git 追踪（108 个 .tmp_*.sh 运维脚本、21387 个 .gocache/* 缓存），
#   仅修改 .gitignore 不会让它们从仓库消失，必须显式 `git rm --cached`。
#
# 本脚本做什么：
#   * 对目标文件执行 `git rm --cached`，即「从 Git 索引移除，但保留本地磁盘文件」
#   * 生成一个本地提交（不 push），便于你 review 后再决定是否推送
#
# 本脚本不做什么：
#   * 不删除你磁盘上的任何文件（--cached 只影响索引）
#   * 不重写历史（已推送的历史提交中的密钥仍存在，需另用 git filter-repo 处理）
#   * 不执行 push
#
# 用法：
#   sh tools/untrack-sensitive-files.sh              # 预览（dry-run，默认）
#   sh tools/untrack-sensitive-files.sh --apply      # 实际执行并提交
#   sh tools/untrack-sensitive-files.sh --help
#
# ⚠️ 执行前请务必先完成密钥轮换：
#   历史里已泄露的 root SSH 密码 / 服务管理密钥 / API Key 必须先在
#   服务端轮换或吊销，脚本本身不能挽回已泄露的凭据。
# ============================================================
set -u

# Git for Windows 的 sh 可能未把 MSYS 工具目录放进 PATH（grep/awk 等会 not found）。
# 用纯 shell 参数展开从 git --exec-path 反推 MSYS 根目录；MSYS 只认 /D/... 形式。
GIT_EXEC=$(git --exec-path 2>/dev/null || echo "")
MSYS_ROOT=""
case "$GIT_EXEC" in
    */mingw64/libexec/git-core) MSYS_ROOT=${GIT_EXEC%/mingw64/libexec/git-core} ;;
    */mingw32/libexec/git-core) MSYS_ROOT=${GIT_EXEC%/mingw32/libexec/git-core} ;;
    */libexec/git-core)         MSYS_ROOT=${GIT_EXEC%/libexec/git-core} ;;
esac
if [ -n "$MSYS_ROOT" ]; then
    case "$MSYS_ROOT" in
        [A-Za-z]:/*)
            _drive=${MSYS_ROOT%%:*}
            _rest=${MSYS_ROOT#?:}
            MSYS_POSIX="/$_drive$_rest"
            ;;
        *) MSYS_POSIX="$MSYS_ROOT" ;;
    esac
    if [ -x "$MSYS_POSIX/usr/bin/grep.exe" ]; then
        PATH="$MSYS_POSIX/usr/bin:$MSYS_POSIX/mingw64/bin:$PATH"
    fi
fi

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "错误：请在 Git 仓库内运行本脚本。" >&2
    exit 2
}
cd "$REPO_ROOT" || exit 2

MODE="dry-run"
case "${1:-}" in
    --apply)  MODE="apply" ;;
    ""|--dry-run) MODE="dry-run" ;;
    -h|--help|help)
        sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
        exit 0 ;;
    *) echo "错误：未知参数 $1（用 --help 查看用法）" >&2; exit 2 ;;
esac

# 目标：应忽略但当前仍被追踪的路径
TARGETS=".tmp_* .gocache/* ssh_run.py ssh_*.py"

echo ""
echo "════════════════════════════════════════════════════"
echo "  解除敏感文件追踪  —  模式: $MODE"
echo "════════════════════════════════════════════════════"
echo ""

# 先确认这些路径确实已被追踪
TRACKED=""
for pat in $TARGETS; do
    list=$(git ls-files -- "$pat" 2>/dev/null)
    if [ -n "$list" ]; then
        TRACKED="$TRACKED$list
"
    fi
done
TRACKED=$(printf '%s' "$TRACKED" | grep -v '^$' || true)

if [ -z "$TRACKED" ]; then
    echo "✅ 无需处理：目标文件均未被追踪。"
    echo ""
    exit 0
fi

COUNT=$(printf '%s\n' "$TRACKED" | wc -l | tr -d ' ')
echo "  发现 $COUNT 个已追踪的敏感文件。"
echo ""
echo "  分布："
printf '%s\n' "$TRACKED" | awk '
    {
        if ($0 ~ /^\.gocache\//)        c["gocache 缓存/脚本"]++
        else if ($0 ~ /^\.tmp_/)        c[".tmp_* 运维脚本"]++
        else if ($0 ~ /^ssh_/)          c["ssh_*.py 运维脚本"]++
        else                            c["其他"]++
    }
    END { for (k in c) printf "    %-28s %6d 个\n", k, c[k] }
' | sort
echo ""

if [ "$MODE" = "dry-run" ]; then
    echo "  预览（前 15 个）："
    printf '%s\n' "$TRACKED" | head -n 15 | sed 's/^/    /'
    [ "$COUNT" -gt 15 ] && echo "    ... 其余 $((COUNT - 15)) 个省略"
    echo ""
    echo "  ─────────────────────────────────────────────"
    echo "  这是预览模式，未做任何改动。"
    echo ""
    echo "  实际执行： sh tools/untrack-sensitive-files.sh --apply"
    echo ""
    echo "  ⚠️ 执行前请确认已完成密钥轮换（轮换不能靠本脚本完成）。"
    echo "  ─────────────────────────────────────────────"
    echo ""
    exit 0
fi

# ---------- 实际执行 ----------
echo "  正在解除追踪（本地文件会保留）..."
echo ""
if ! printf '%s\n' "$TRACKED" | git rm --cached --quiet --pathspec-from-file=- 2>/dev/null; then
    # 兼容不支持 --pathspec-from-file 的旧版本 git
    printf '%s\n' "$TRACKED" | while IFS= read -r f; do
        [ -z "$f" ] && continue
        git rm --cached --quiet -- "$f" 2>/dev/null || true
    done
fi

# 顺带把 .gitignore 的改动一起纳入提交
git add .gitignore 2>/dev/null || true

STAGED=$(git diff --cached --name-only | wc -l | tr -d ' ')
echo "  已从索引移除 $STAGED 个路径。"
echo ""

git commit -q -m "chore(security): 停止追踪本地运维脚本与缓存

- 解除 .tmp_* / .gocache/ / ssh_*.py 的追踪（本地文件保留，不再入库）
- .gitignore 补全 .tmp_*、.gocache/、私钥材料、deploy 运行时数据等规则
- 原因：.tmp_* 脚本含服务器 IP 与明文口令，.gocache 含 Go 缓存与
  本地运维脚本（其中曾含 root SSH 密码）

注意：该提交只影响后续版本，已推送历史中的密钥仍需轮换 + 重写历史。" 2>&1 | sed 's/^/  /'

if [ $? -eq 0 ]; then
    echo ""
    echo "  ✅ 已生成提交（尚未 push）"
    echo ""
    echo "  下一步："
    echo "    1) 检查改动： git show --stat HEAD"
    echo "    2) 确认无误后推送： git push"
    echo "    3) 轮换所有已泄露凭据（root 密码 / 管理密钥 / API Key）"
    echo "    4) 如需清理历史中的密钥： 用 git filter-repo 重写后 force push"
    echo ""
else
    echo ""
    echo "  ⚠️ 提交未成功，请检查上方输出。索引改动已保留，可手动提交。"
    echo ""
    exit 1
fi
