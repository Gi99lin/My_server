# reconnect-console.ps1
# ---------------------------------------------------------------------------
# Re-attaches any DISCONNECTED interactive session back to the physical
# console, so the Windows desktop stays "Active" and unlocked even when no
# one is viewing it through Guacamole/RDP.
#
# A session-bound corporate VPN client treats a Disconnected/locked session
# as "no one is here" and tears the tunnel down. Keeping the session Active
# on the console prevents that.
#
# Invoked by the "RDP-KeepConsoleAttached" scheduled task on every RDP
# disconnect (TerminalServices-LocalSessionManager event 24). Runs as SYSTEM.
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'SilentlyContinue'

# `quser` output (a disconnected session has STATE = Disc and a blank
# SESSIONNAME, so the numeric session ID is the token right before "Disc"):
#
#   USERNAME      SESSIONNAME    ID  STATE   IDLE TIME   LOGON TIME
#   ivan                          2  Disc    none        6/3/2026 9:14
#
foreach ($line in (quser 2>$null)) {
    if ($line -match '\s+(\d+)\s+Disc\b') {
        $id = $matches[1]
        # Redirect that session to the console -> it becomes Active again.
        tscon $id /dest:console
    }
}
