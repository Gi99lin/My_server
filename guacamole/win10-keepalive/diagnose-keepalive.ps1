# diagnose-keepalive.ps1
# Run in an ELEVATED PowerShell inside the Win10 VM, right after a VPN drop.
# Copy the whole output back. Tells us: did the task install + fire, what the
# session state is, and whether the drop was a session disconnect vs real sleep.

Write-Host "===== 1. Scheduled task (installed? last run result?) =====" -ForegroundColor Cyan
schtasks /query /tn "RDP-KeepConsoleAttached" /v /fo LIST 2>&1 |
    Select-String "TaskName|Status|Last Run Time|Last Result|Schedule Type|Run As User"

Write-Host "`n===== 2. Current sessions (Active vs Disc, console vs rdp-tcp) =====" -ForegroundColor Cyan
query session 2>&1

Write-Host "`n===== 3. Last 12 RDP session events (24=disconnect 25=reconnect 21=logon 23=logoff) =====" -ForegroundColor Cyan
try {
    Get-WinEvent -LogName "Microsoft-Windows-TerminalServices-LocalSessionManager/Operational" -MaxEvents 12 -ErrorAction Stop |
        Select-Object TimeCreated, Id, @{n='Msg';e={($_.Message -split "`n")[0]}} | Format-Table -Auto
} catch { Write-Host "  (no events / log empty)" }

Write-Host "`n===== 4. Kernel-Power events (42=ENTER SLEEP 107=resume 41=unexpected) =====" -ForegroundColor Cyan
try {
    Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'} -MaxEvents 10 -ErrorAction Stop |
        Select-Object TimeCreated, Id, @{n='Msg';e={($_.Message -split "`n")[0]}} | Format-Table -Auto
} catch { Write-Host "  (none - good, means it is NOT literally sleeping)" }

Write-Host "`n===== 5. Sleep states that even exist on this VM =====" -ForegroundColor Cyan
powercfg /a
