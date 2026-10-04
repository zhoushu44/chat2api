#!/bin/sh
# ============================================================
# chat2api 密钥/凭据扫描器
#
# 零依赖：仅需 git / awk / grep / sed（Git for Windows 自带的 sh 即可运行）。
#
# 用法：
#   tools/secret-scan.sh              # 扫描本次暂存内容（pre-commit 钩子默认调用）
#   tools/secret-scan.sh --all        # 扫描工作区全部已追踪文件
#   tools/secret-scan.sh --untracked  # 扫描未跟踪且未被忽略的文件
#                                     #（即 `git add -A` 会带入库的对象）
#   tools/secret-scan.sh --help       # 查看用法
#
# 环境变量：
#   SECRET_SCAN_MAX_SHOW=20       每类规则最多显示的条数（默认 5）
#
# 退出码：0=通过；1=命中高危规则，阻断提交；2=用法/环境错误
#
# 设计说明：
#   * 规则为通用模式，刻意不在本文件写入任何真实密钥字面量，
#     避免扫描器自身变成新的泄露源。
#   * 若需硬阻断「历史已泄露的具体值」，把它们逐行写入
#     tools/secrets-known.txt（该文件已被 .gitignore 忽略，绝不入库）。
#     模板见 tools/secrets-known.example.txt。
#   * 扫描范围用「白名单扩展名」而非目录黑名单：.gocache 下的 Go 构建/模块
#     缓存是无扩展名二进制，逐行正则会产生海量误报；白名单方式下它们自动
#     落空，而 .gocache/*.py 运维脚本（曾泄露 root SSH 密码）仍会被扫描。
#   * 暂存模式只扫描暂存区内容（git show :path），不会牵连未暂存文件。
# ============================================================
set -u

# Git for Windows 的 sh 可能未把 MSYS 工具目录放进 PATH
# （表现为 awk/sed/wc 等 command not found）。用纯 shell 参数展开从
# git --exec-path 反推 MSYS 根目录；注意 MSYS sh 只认 POSIX 风格路径
# （/D/... 而非 D:/...），故必须转换盘符。此处不得依赖任何外部命令。
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
            _drive=${MSYS_ROOT%%:*}                # 盘符，如 D
            _rest=${MSYS_ROOT#?:}                  # 其余，如 /软件/Git
            MSYS_POSIX="/$_drive$_rest"
            ;;
        *)
            MSYS_POSIX="$MSYS_ROOT"
            ;;
    esac
    if [ -x "$MSYS_POSIX/usr/bin/awk.exe" ]; then
        PATH="$MSYS_POSIX/usr/bin:$MSYS_POSIX/mingw64/bin:$PATH"
    fi
fi

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "[secret-scan] 不在 Git 仓库中，跳过。" >&2
    exit 0
}
cd "$REPO_ROOT" || exit 2

if [ -f "tools/secret-scan.sh" ]; then
    SCRIPT_DIR="tools"
else
    SCRIPT_DIR=${0%/*}
    [ "$SCRIPT_DIR" = "$0" ] && SCRIPT_DIR="."
fi

KNOWN_FILE="$SCRIPT_DIR/secrets-known.txt"
TMP_BASE="${TMPDIR:-/tmp}"
RULES_TMP="$TMP_BASE/chat2api-rules-$$.txt"
CANDS_TMP="$TMP_BASE/chat2api-cands-$$.txt"
LIST_TMP="$TMP_BASE/chat2api-list-$$.txt"
MAP_TMP="$TMP_BASE/chat2api-map-$$.txt"
KNOWN_TMP="$TMP_BASE/chat2api-known-$$.txt"
RAW_TMP="$TMP_BASE/chat2api-raw-$$.txt"
FINDINGS="$TMP_BASE/chat2api-findings-$$.txt"
STAGE_DIR="$TMP_BASE/chat2api-stage-$$"
: > "$FINDINGS"
trap 'rm -f "$RULES_TMP" "$CANDS_TMP" "$LIST_TMP" "$MAP_TMP" "$KNOWN_TMP" "$RAW_TMP" "$FINDINGS"; rm -rf "$STAGE_DIR"' EXIT INT TERM

MAX_SHOW=${SECRET_SCAN_MAX_SHOW:-5}
case "$MAX_SHOW" in
    ''|*[!0-9]*) MAX_SHOW=5 ;;
esac
TAB=$(printf '\t')
SEP='@@'

# ---------- 内容规则 ----------
# 格式：规范说明@@ERE 模式
# 用 quoted heredoc 写入：单双引号均为字面量，无需转义。
# 注意：模式内不得含 @@（分隔符）；合并为单条 ERE 时以 | 连接，故模式内也不得含 |
cat > "$RULES_TMP" <<'RULES_EOF'
PEM 私钥内容@@-----BEGIN [A-Z ]*PRIVATE KEY-----
AWS Access Key ID@@AKIA[0-9A-Z]{16}
GitHub Token@@gh[pousr]_[A-Za-z0-9]{30,}
GitHub 细粒度 PAT@@github_pat_[A-Za-z0-9_]{30,}
Slack Token@@xox[baprs]-[A-Za-z0-9-]{10,}
OpenAI 风格 API Key@@sk-[A-Za-z0-9_-]{32,}
TokenRhythm API Key@@sk_tr_[A-Za-z0-9_-]{10,}
NoneCap 打码服务 Key@@nc_live_[A-Za-z0-9_-]{10,}
NVIDIA API Key@@nvapi-[A-Za-z0-9_-]{20,}
Google API Key@@AIza[0-9A-Za-z_-]{30,}
OpenAI access_token（JWT）@@eyJhbGciOiJSUzI1NiIs[A-Za-z0-9_-]{20,}
硬编码密码赋值@@(password|passwd|PASSWORD|PASSWD)[[:space:]]*[=:][[:space:]]*['"][^'"]{6,}
SSH 连接串含用户名与口令@@username=[^,)]{2,}.*[[:space:]]*password=
含明文口令的 socks5 URL@@socks5://[^:@[:space:]]+:[^@[:space:]]+@
硬编码 X-API-Key@@X-API-Key"?[[:space:]]*[:=][[:space:]]*"[A-Za-z0-9_-]{12,}
config.json 内明文 auth-key@@"auth-key"[[:space:]]*:[[:space:]]*"[A-Za-z0-9]{6,}
云厂商 SecretId@@SECRET_ID[[:space:]]*[:=][[:space:]]*"[A-Za-z0-9]{10,}
云厂商 SecretKey@@SECRET_KEY[[:space:]]*[:=][[:space:]]*"[A-Za-z0-9]{10,}
RULES_EOF

# ---------- 模式 ----------
MODE="staged"
case "${1:-}" in
    --all)   MODE="all" ;;
    --staged) MODE="staged" ;;
    --untracked) MODE="untracked" ;;
    "")      ;;
    -h|--help|help)
        sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
        exit 0 ;;
    *) echo "[secret-scan] 未知参数: $1（用 --help 查看用法）" >&2; exit 2 ;;
esac

# ---------- 白名单 ----------
# 扫描器自身与示例模板：其内容本就是这些正则模式
is_allowed_path() {
    case "$1" in
        tools/secret-scan.sh)            return 0 ;;
        tools/secrets-known.example.txt) return 0 ;;
        .githooks/*)                     return 0 ;;
    esac
    return 1
}

# 明确的占位符样本行（真实泄露值不在此列）
is_allowed_line() {
    printf '%s' "$1" | grep -qE '换成你的密钥|your[-_ ]?(key|token|secret|pass)|placeholder|XXXX|example\.com|fake|dummy|CAP-XXXX|^-----BEGIN' 2>/dev/null && return 0
    # 通用示例凭据：user1:pass1 / user:password 等文档写法（配 Docker 内网地址）
    printf '%s' "$1" | grep -qE 'socks5://(user|user1|username):(pass|pass1|password|pwd|secret)@' 2>/dev/null && return 0
    return 1
}

# 内容扫描白名单：只扫描源码/配置/文本类文件，跳过二进制与构建缓存
is_scannable() {
    case "$1" in
        .gocache/mod/*)                                  return 1 ;;  # 第三方模块测试夹具
        .gocache/build/*|.gocache/*/*)                   return 1 ;;  # Go 构建缓存二进制分片
        internal/api/web_dist/*|web-vue/node_modules/*)   return 1 ;;  # 前端产物/依赖
        *.go|*.py|*.js|*.mjs|*.cjs|*.ts|*.tsx|*.jsx|*.vue|*.svelte) return 0 ;;
        *.json|*.jsonc|*.yml|*.yaml|*.toml|*.ini|*.cfg|*.conf|*.properties) return 0 ;;
        *.sh|*.bash|*.zsh|*.ps1|*.bat|*.cmd)             return 0 ;;
        *.md|*.txt|*.rst|*.sql|*.xml|*.html|*.htm)       return 0 ;;
        *.pem|*.key|*.crt|*.p12|*.pfx|*.ppk)             return 0 ;;
        .env|*/.env|.env.*|*/.env.*)                     return 0 ;;
        Dockerfile|*/Dockerfile|Dockerfile.*|Makefile|*/Makefile) return 0 ;;
    esac
    return 1
}

# 文件名规则：设置 FN_LABEL（不使用命令替换，避免逐文件派生 subshell）
FN_LABEL=""
set_filename_label() {
    FN_LABEL=""
    case "$1" in
        .tmp_*)                                      FN_LABEL='本地临时运维脚本（含服务器 IP / 明文密码）' ;;
        *accounts*.json|*accounts*.csv|*accounts*.txt) FN_LABEL='账号数据文件（含 token）' ;;
        *schema.json)                                FN_LABEL='' ;;   # JSON Schema 属源码，非数据 dump
        *token*.json)                                FN_LABEL='token 数据文件' ;;
        register.json|*/register.json)               FN_LABEL='注册运行数据' ;;
        m9-config.json|*/m9-config.json)             FN_LABEL='含 auth-key 的本地配置' ;;
        .env|*/.env)                                 FN_LABEL='环境变量文件' ;;
        */.env.local|*/.env.prod|*/.env.production|*/.env.dev|*/.env.test) FN_LABEL='环境变量文件' ;;
        *.pem|*.key|*.p12|*.pfx|*.ppk)               FN_LABEL='私钥 / 证书材料' ;;
        id_rsa*|*/id_rsa*|id_ed25519*|*/id_ed25519*|id_ecdsa*|*/id_ecdsa*) FN_LABEL='SSH 私钥' ;;
        *known_hosts)                                FN_LABEL='SSH known_hosts' ;;
        *secrets-known.txt)                          FN_LABEL='已泄露值清单（含真实密钥，必须仅存本地）' ;;
    esac
}

# ---------- 取待扫描文件列表 ----------
if [ "$MODE" = "all" ]; then
    git ls-files > "$CANDS_TMP" 2>/dev/null || : > "$CANDS_TMP"
elif [ "$MODE" = "untracked" ]; then
    # 未跟踪且未被忽略的文件：这些正是 `git add -A` 会带入库、
    # 而 .gitignore 又没兜住的高危对象。
    git ls-files --others --exclude-standard > "$CANDS_TMP" 2>/dev/null || : > "$CANDS_TMP"
else
    git diff --cached --name-only --diff-filter=ACM > "$CANDS_TMP" 2>/dev/null || : > "$CANDS_TMP"
fi

if [ ! -s "$CANDS_TMP" ]; then
    echo "[secret-scan] 没有需要扫描的内容，通过。"
    exit 0
fi
FILE_COUNT=$(wc -l < "$CANDS_TMP" | tr -d ' ')

# ---------- 检查 1：文件名规则 ----------
# .gocache 内含上万文件，仅汇总计数，避免刷屏
GOCACHE_COUNT=0
while IFS= read -r f; do
    [ -z "$f" ] && continue
    is_allowed_path "$f" && continue
    case "$f" in
        .gocache/*) GOCACHE_COUNT=$((GOCACHE_COUNT + 1)); continue ;;
    esac
    set_filename_label "$f"
    [ -n "$FN_LABEL" ] && printf 'HIGH\t%s\t%s\t(文件名命中)\n' "$FN_LABEL" "$f" >> "$FINDINGS"
done < "$CANDS_TMP"

if [ "$GOCACHE_COUNT" -gt 0 ]; then
    printf 'HIGH\t%s\t%s\t(共 %s 个文件，已整体汇总)\n' \
        'Go 模块缓存 / 本地脚本（曾被误提交进仓）' '.gocache/' "$GOCACHE_COUNT" >> "$FINDINGS"
fi

# ---------- 构建「待扫描内容」清单 ----------
# 格式：原始路径<TAB>内容文件路径
#   --all  ：内容文件即工作区文件本身
#   staged ：内容文件为 `git show :path` 导出的暂存区快照
#             （只取暂存内容，不牵连未暂存的本地修改）
: > "$LIST_TMP"
: > "$MAP_TMP"
while IFS= read -r f; do
    [ -z "$f" ] && continue
    is_allowed_path "$f" && continue
    is_scannable "$f" || continue
    printf '%s\n' "$f" >> "$LIST_TMP"
done < "$CANDS_TMP"

if [ "$MODE" = "all" ] || [ "$MODE" = "untracked" ]; then
    # 这两类都直接读工作区文件（--untracked 的文件本就不在索引中）
    while IFS= read -r f; do
        printf '%s\t%s\n' "$f" "$f" >> "$MAP_TMP"
    done < "$LIST_TMP"
else
    rm -rf "$STAGE_DIR"; mkdir -p "$STAGE_DIR" 2>/dev/null || true
    _i=0
    while IFS= read -r f; do
        _i=$((_i + 1))
        if git show ":$f" > "$STAGE_DIR/$_i" 2>/dev/null; then
            printf '%s\t%s\n' "$f" "$STAGE_DIR/$_i" >> "$MAP_TMP"
        fi
    done < "$LIST_TMP"
fi

# ---------- 检查 2：内容规则（单次 awk 遍历，规则与内容均由文件驱动） ----------
if [ -s "$MAP_TMP" ]; then
    awk -F"$SEP" -v mapfile="$MAP_TMP" '
        NR == FNR { labels[++n] = $1; pats[n] = $2; next }
        END {
            while ((getline line < mapfile) > 0) {
                ti = index(line, "\t")
                if (ti == 0) continue
                orig = substr(line, 1, ti - 1)
                cf = substr(line, ti + 1)
                ln = 0
                while ((getline txt < cf) > 0) {
                    ln++
                    for (i = 1; i <= n; i++) {
                        if (txt ~ pats[i]) {
                            out = txt
                            if (length(out) > 200) out = substr(out, 1, 200)
                            print labels[i] "\t" orig ":" ln "\t" out
                        }
                    }
                }
                close(cf)
            }
        }
    ' "$RULES_TMP" /dev/null > "$RAW_TMP" 2>/dev/null || : > "$RAW_TMP"

    # 应用行级白名单后并入结果
    if [ -s "$RAW_TMP" ]; then
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            exc=$(printf '%s' "$line" | cut -f3)
            is_allowed_line "$exc" && continue
            printf 'HIGH\t%s\n' "$line" >> "$FINDINGS"
        done < "$RAW_TMP"
    fi
fi

# ---------- 检查 3：已泄露字面量硬阻断（可选，来自被忽略的本地文件） ----------
if [ -f "$KNOWN_FILE" ] && [ -s "$MAP_TMP" ]; then
    grep -vE '^[[:space:]]*(#|$)' "$KNOWN_FILE" 2>/dev/null | awk 'length($0) >= 6' > "$KNOWN_TMP" || : > "$KNOWN_TMP"
    if [ -s "$KNOWN_TMP" ]; then
        awk -v secfile="$KNOWN_TMP" -v mapfile="$MAP_TMP" '
            BEGIN {
                while ((getline s < secfile) > 0) { sec[++ns] = s }
                close(secfile)
                while ((getline line < mapfile) > 0) {
                    ti = index(line, "\t")
                    if (ti == 0) continue
                    orig = substr(line, 1, ti - 1)
                    cf = substr(line, ti + 1)
                    ln = 0
                    while ((getline txt < cf) > 0) {
                        ln++
                        for (i = 1; i <= ns; i++) {
                            if (index(txt, sec[i]) > 0) {
                                print orig ":" ln
                                break
                            }
                        }
                    }
                    close(cf)
                }
            }
        ' /dev/null > "$RAW_TMP.known" 2>/dev/null || : > "$RAW_TMP.known"

        if [ -s "$RAW_TMP.known" ]; then
            sort -u "$RAW_TMP.known" | while IFS= read -r loc; do
                [ -z "$loc" ] && continue
                printf 'HIGH\t%s\t%s\t(命中本地已泄露值清单，必须轮换后再入库)\n' '已知泄露值复发' "$loc" >> "$FINDINGS"
            done
        fi
        rm -f "$RAW_TMP.known"
    fi
fi

# ---------- 汇总输出 ----------
TOTAL=$(wc -l < "$FINDINGS" | tr -d ' ')

if [ "$TOTAL" -eq 0 ]; then
    echo "[secret-scan] ✅ 通过：未发现高危密钥/凭据（已扫描 $FILE_COUNT 个文件）。"
    exit 0
fi

echo "" >&2
echo "[secret-scan] ❌ 发现 $TOTAL 处高危疑似密钥/凭据（已扫描 $FILE_COUNT 个文件）：" >&2
echo "" >&2
echo "  按规则统计：" >&2
awk -F'\t' '{print $2}' "$FINDINGS" | sort | uniq -c | sort -rn | sed 's/^ *\([0-9]*\) */    \1 × /' >&2
echo "" >&2
echo "  明细（每类最多 $MAX_SHOW 条，可设 SECRET_SCAN_MAX_SHOW 调整）：" >&2
awk -F'\t' '{print $2}' "$FINDINGS" | sort -u | while IFS= read -r label; do
    echo "" >&2
    echo "  【$label】" >&2
    grep -F "$label" "$FINDINGS" | head -n "$MAX_SHOW" | while IFS= read -r line; do
        loc=$(printf '%s' "$line" | cut -f3)
        exc=$(printf '%s' "$line" | cut -f4)
        echo "      $loc" >&2
        if [ -n "$exc" ] && [ "$exc" != "(文件名命中)" ]; then
            echo "        $exc" >&2
        fi
    done
done
echo "" >&2
echo "  ─────────────────────────────────────────────" >&2
echo "  处理建议：" >&2
echo "    1) 确认为真实密钥的，先轮换/吊销，再决定是否入库。" >&2
echo "    2) 本机专用脚本（.tmp_* 等）应留在 .gitignore 中，不要提交。" >&2
echo "    3) 文件已被追踪时，仅加 .gitignore 无效，需先解除追踪：" >&2
echo "         git rm --cached <文件>" >&2
echo "    4) 误报可加入 tools/secret-scan.sh 的白名单函数；" >&2
echo "       或用 git commit --no-verify 临时跳过（不推荐）。" >&2
echo "  ─────────────────────────────────────────────" >&2
echo "" >&2
exit 1
