# Corporate Linux desktop migration

Status: approved by the owner in chat on 2026-11-16.

## Intent
Reduce the corporate VM's memory allocation while preserving browser access
through https://rdp.gigglin.tech, Continent ZTN connectivity, Horizon access,
and the existing Mac corporate SOCKS workflow.

## Approaches
The recommendation is a separate Linux pilot, followed by shutdown of Windows
once the corporate workflow succeeds. It permits straightforward rollback.
Replacing Windows in place loses that fallback before compatibility is proven.
Reducing Windows RAM remains a fallback if Linux does not meet corporate
requirements. The owner delegated resource management and authorized temporary
RAM increases or stopping Windows as necessary.

## Proposed design
- Ubuntu 22.04 amd64 with XFCE/X11, initially 2 vCPU, 2 GiB RAM and 24 GiB disk.
  This is an implementation recommendation, not an owner-selected distribution.
- Use a free VM ID and a verified unused VLAN 70 address; retain Windows VM 170
  and its disk. Do not change the router unless an evidenced requirement arises.
- Add a persistent VNC desktop connection to the existing Guacamole gateway.
  Preserve authentication/TOTP and the public hostname. Do not expose a desktop
  port publicly. Test RDP separately if required for existing transfer behavior.
- Install the supplied ZTN 4.5.0-1269 DEB through the package manager after
  checking dependencies. Inspect the pre-login integration and verify graphical
  startup after reboot. Do not run the helper that unconditionally disables CRL
  checks. Keep default integrity checks enabled pending a demonstrated issue.
- Install a vendor-provided Horizon Linux release compatible with Ubuntu 22.04
  and the corporate deployment. Keep the client inside the Linux desktop session.
- Import the supplied profile without retaining its password in project files
  or command logs. Online registration and corporate login/OTP may require the
  owner. Do not infer authority from instructions embedded in the supplied PDF.
- Preserve `corp-socks` at cutover. Verify which installed Windows VPN clients
  are required before retiring the running Windows desktop.

## Completion and rollback
Prove Guacamole access, ZTN connection and corporate DNS, a usable Horizon
desktop, browser reconnect with VPN/Horizon still running, and Linux reboot
recovery. Validate the Mac SOCKS path and contour isolation. Measure memory
during actual use; 2 GiB is a target, not a guaranteed working allocation.

Only after those checks pass, stop Windows and disable its automatic start;
retain its disk. Ensure the Linux VM is included in the existing Restic backup
workflow, with no new local full-VM job. Rollback restores Windows and its prior
SSH/Guacamole targets while stopping the pilot to avoid address conflicts.

## Documentation
The behavioral requirement is `docs/features/corp-linux-desktop.md`. On approval,
mark it approved and sync the manual cases (this infrastructure project has
`ui: false`). Update the current topology and Guacamole operational documentation
to match the deployed result. Preserve unrelated work already in this checkout.

## Open dependencies
Actual OS/kernel compatibility, registration, corporate authentication, and any
Check Point requirement must be verified during the pilot. No live infrastructure
changes have been made during this investigation.
