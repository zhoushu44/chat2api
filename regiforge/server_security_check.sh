# 服务器被入侵检查清单
# 连接服务器后依次执行以下命令

echo "=========================================="
echo "1. 检查 CPU 和内存占用最高的进程"
echo "=========================================="
top -bn1 | head -30
# 或者使用 htop（如果已安装）
# htop

echo ""
echo "=========================================="
echo "2. 查找可疑挖矿进程"
echo "=========================================="
ps aux | grep -E "(miner|xmrig|kdevtmpfsi|kinsing|watchdog|cryptonight|monero)" | grep -v grep
ps auxf | grep -v grep | grep -E "[(kworker|ksoftirqd|kdevtmpfsi)]"

echo ""
echo "=========================================="
echo "3. 检查异常网络连接"
echo "=========================================="
netstat -antp | grep ESTABLISHED
ss -antp | grep ESTABLISHED
# 检查是否有异常外连（特别是矿池端口：3333, 4444, 5555, 14444, 45560 等）

echo ""
echo "=========================================="
echo "4. 检查定时任务（常见持久化方式）"
echo "=========================================="
crontab -l
ls -la /etc/cron.d/
cat /etc/crontab
ls -la /var/spool/cron/

echo ""
echo "=========================================="
echo "5. 检查最近登录记录"
echo "=========================================="
last -20
lastb -20  # 失败登录尝试
who
w

echo ""
echo "=========================================="
echo "6. 检查系统负载和历史"
echo "=========================================="
uptime
w
# 查看历史命令
history | tail -50

echo ""
echo "=========================================="
echo "7. 检查异常用户"
echo "=========================================="
cat /etc/passwd | grep -v nologin | grep -v false
# 检查是否有未知用户（特别是 UID=0 的非 root 用户）
awk -F: '$3 == 0 {print $1}' /etc/passwd

echo ""
echo "=========================================="
echo "8. 检查系统服务"
echo "=========================================="
systemctl list-units --type=service --state=running
# 或者
# service --status-all 2>/dev/null | grep +

echo ""
echo "=========================================="
echo "9. 检查临时目录（常见恶意软件藏身处）"
echo "=========================================="
ls -la /tmp/
ls -la /var/tmp/
# 查找最近修改的可执行文件
find /tmp /var/tmp -type f -executable -mtime -7 2>/dev/null

echo ""
echo "=========================================="
echo "10. 检查系统资源占用"
echo "=========================================="
df -h
free -h
vmstat 1 5

echo ""
echo "=========================================="
echo "11. 查找隐藏文件"
echo "=========================================="
find /home /root /tmp -name ".*" -type f 2>/dev/null | head -30

echo ""
echo "=========================================="
echo "12. 检查 SSH 密钥和配置"
echo "=========================================="
ls -la ~/.ssh/
cat ~/.ssh/authorized_keys
cat /etc/ssh/sshd_config | grep -v "^#" | grep -v "^$"

echo ""
echo "=========================================="
echo "如果发现异常，紧急处理步骤："
echo "=========================================="
echo "1. 立即修改 root 密码：passwd"
echo "2. 停止可疑进程：kill -9 <PID>"
echo "3. 删除恶意定时任务：crontab -e"
echo "4. 检查并删除恶意启动项"
echo "5. 检查防火墙规则：iptables -L -n"
echo "6. 考虑重装系统（最安全）"
echo ""
echo "建议：备份重要数据后重装系统，并修改所有密码和密钥"
