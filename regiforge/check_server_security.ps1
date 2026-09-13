# 服务器安全检查脚本
$server = "192.6.121.16"
$user = "root"
$password = "6Qz6ao0T1zvL"

# 创建 secure string
$securePassword = ConvertTo-SecureString $password -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential($user, $securePassword)

# 检查命令列表
$commands = @(
    "echo '=== CPU 和内存使用 ===' && top -bn1 | head -30",
    "echo '=== 最近登录记录 ===' && last -20",
    "echo '=== 可疑进程 ===' && ps aux | grep -E '(miner|xmrig|kdevtmpfsi|kinsing|watchdog)' | head -20",
    "echo '=== 异常网络连接 ===' && netstat -antp | grep ESTABLISHED | head -30",
    "echo '=== 定时任务 ===' && crontab -l 2>/dev/null; ls -la /etc/cron.* 2>/dev/null",
    "echo '=== 系统负载 ===' && uptime && w",
    "echo '=== 检查异常用户 ===' && cat /etc/passwd | grep -v nologin | grep -v false"
)

Write-Host "开始检查服务器：$server" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan

foreach ($cmd in $commands) {
    Write-Host "`n执行：$cmd" -ForegroundColor Yellow
    try {
        # 使用 SSH 执行命令（需要配置 SSH 密钥或使用 sshpass）
        $result = ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$user@$server" $cmd 2>&1
        if ($result) {
            $result | Out-String | Write-Host
        } else {
            Write-Host "命令执行无输出或连接失败" -ForegroundColor Red
        }
    } catch {
        Write-Host "执行失败：$_" -ForegroundColor Red
    }
    Start-Sleep -Seconds 2
}

Write-Host "`n=====================================" -ForegroundColor Cyan
Write-Host "检查完成" -ForegroundColor Cyan
