@echo off
REM ===========================================================================
REM  install-keepalive.cmd  --  run as Administrator INSIDE the Win10 VM
REM ===========================================================================
REM  Makes the desktop (and the corp VPN running in it) survive any RDP/
REM  Guacamole disconnect, accidental or intentional, until the VM is shut
REM  down. It:
REM    1. installs reconnect-console.ps1 to C:\Scripts
REM    2. registers a scheduled task that re-attaches the session to the
REM       console on every RDP disconnect (event 24)
REM    3. disables sleep / display-off / screensaver / idle auto-lock
REM    4. tells Windows to never time out disconnected or idle RDP sessions
REM
REM  Copy this whole folder into the VM (Guacamole shared drive works), then
REM  right-click install-keepalive.cmd -> "Run as administrator".
REM ===========================================================================
setlocal

set "DST=C:\Scripts"
if not exist "%DST%" mkdir "%DST%"
copy /Y "%~dp0reconnect-console.ps1" "%DST%\reconnect-console.ps1" >nul
echo [1/4] reconnect-console.ps1 -> %DST%

REM --- 2) Re-attach session to console on every RDP disconnect (event 24) ---
schtasks /Create /F /RU SYSTEM /RL HIGHEST /TN "RDP-KeepConsoleAttached" ^
 /SC ONEVENT /EC "Microsoft-Windows-TerminalServices-LocalSessionManager/Operational" ^
 /MO "*[System[Provider[@Name='Microsoft-Windows-TerminalServices-LocalSessionManager'] and (EventID=24)]]" ^
 /TR "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File %DST%\reconnect-console.ps1"
echo [2/4] scheduled task RDP-KeepConsoleAttached registered

REM --- 3) Never sleep / never blank the display / no screensaver / no lock ---
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /hibernate off >nul 2>&1
reg add "HKCU\Control Panel\Desktop" /v ScreenSaveActive /t REG_SZ /d 0 /f >nul
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v InactivityTimeoutSecs /t REG_DWORD /d 0 /f >nul
echo [3/4] sleep / display-off / screensaver / idle-lock disabled

REM --- 4) Never end disconnected or idle RDP sessions -----------------------
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v MaxDisconnectionTime /t REG_DWORD /d 0 /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v MaxIdleTime /t REG_DWORD /d 0 /f >nul
echo [4/4] disconnected/idle session timeouts set to never

echo.
echo Done. TEST: open the VM in Guacamole, then close the tab. Wait ~5 seconds,
echo then on the VM run:  query session
echo Your session should show STATE = Active on "console" (not "Disc").
echo.
echo To remove later:  schtasks /Delete /TN "RDP-KeepConsoleAttached" /F
endlocal
pause
