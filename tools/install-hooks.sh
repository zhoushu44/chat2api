#!/bin/sh
# ============================================================
# 安装 Git 钩子：启用提交前密钥扫描
#
# 用法：
#   sh tools/install-hooks.sh           # 安装
#   sh tools/install-hooks.sh --check   # 仅检查当前是否已启用
#   sh tools/install-hooks.sh --remove  # 卸载（恢复默认钩子目录）
#
# 原理：把 core.hooksPath 指向仓库内的 .githooks/
#   * 钩子随仓库版本化，团队成员 clone 后执行一次本脚本即可
#   * 不覆盖 .git/hooks 下的任何现有钩子
# ============================================================
set -u

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "错误：请在 Git 仓库内运行本脚本。" >&2
    exit 2
}
cd "$REPO_ROOT" || exit 2

HOOKS_DIR=".githooks"
ACTION="${1:-install}"

current=$(git config --get core.hooksPath 2>/dev/null || true)

case "$ACTION" in
    --check|check)
        if [ "$current" = "$HOOKS_DIR" ]; then
            echo "✅ 已启用：core.hooksPath = $current"
            ls -1 "$HOOKS_DIR" 2>/dev/null | sed 's/^/    钩子: /'
            exit 0
        fi
        echo "⚠️  未启用：core.hooksPath = ${current:-（默认 .git/hooks）}"
        echo "   运行 'sh tools/install-hooks.sh' 启用密钥扫描。"
        exit 1
        ;;

    --remove|remove|uninstall)
        git config --unset core.hooksPath 2>/dev/null || true
        echo "✅ 已卸载：已恢复默认钩子目录 .git/hooks"
        exit 0
        ;;

    install)
        if [ ! -f "$HOOKS_DIR/pre-commit" ]; then
            echo "错误：找不到 $HOOKS_DIR/pre-commit" >&2
            exit 2
        fi
        # 确保钩子可执行（Windows 下 git 会忽略位，但 Linux/macOS 必需）
        chmod +x "$HOOKS_DIR"/* 2>/dev/null || true
        chmod +x tools/secret-scan.sh 2>/dev/null || true

        git config core.hooksPath "$HOOKS_DIR"
        echo "✅ 已安装 pre-commit 密钥扫描钩子"
        echo "   core.hooksPath = $HOOKS_DIR"
        echo ""
        echo "   验证： sh tools/secret-scan.sh --help"
        echo "   全量扫描工作区： sh tools/secret-scan.sh --all"
        echo ""
        echo "   注意：钩子只拦新增/修改的暂存内容；若历史上已有密钥入库，"
        echo "   仍需先 'git rm --cached' 解除追踪，并按需重写历史。"
        exit 0
        ;;

    -h|--help|help)
        sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;

    *)
        echo "错误：未知参数 $ACTION（用 --help 查看用法）" >&2
        exit 2
        ;;
esac
