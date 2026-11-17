# Matrix Server Local Deployment Walkthrough

## Overview
This document outlines the successful deployment of a Matrix Homeserver (Element Server Suite) on a local Kubernetes (K3s) cluster, specifically addressing challenges with **NAT Loopback**, **RTC Calls (LiveKit)**, and **Public Registration**.

## Key Components
- **K3s**: Lightweight Kubernetes distribution.
- **Element Server Suite (ESS)**: Matrix stack (Synapse, MAS, Element Web, LiveKit).
- **Nginx Proxy Manager (NPM)**: Reverse proxy handling SSL and external access.
- **PostgreSQL**: Internal database.

## Critical Fixes & Configurations

### 1. Public Registration
Public registration was enabled by customizing the Helm chart values:
- **Synapse**: `enable_registration: true`
- **MAS**: `password_registration_enabled: true`
- **Element Web**: `UIFeature.registration: true`

### 2. DNS & NAT Loopback (The "Check Logs" Fix)
The server resides behind a router that does not support Hairpin NAT. This caused internal services to fail when trying to reach the server's public IP (`128.0.130.144`).
- **Fix**: Used `hostAliases` in the Helm values to force all `*.gigglin.tech` domains to resolve to the **local server IP** (`192.168.1.11`) *inside* the pods.
- **Effect**: Pods now route traffic through the Nginx Proxy Manager on the internal network interface, bypassing the router.

### 3. Real-Time Communications (RTC/LiveKit)
Getting voice/video calls working required several layers of fixes:
- **NPM Configuration**:
    - Domain: `sfu.gigglin.tech`
    - Scheme: `http` (Internal)
    - Port: `30880`
    - **Block Common Exploits**: **DISABLED** (Critical! Was blocking `POST /twirp` API calls).
    - **Websockets**: Enabled.
- **Kubernetes NodePort**:
    - The SFU service was patched to listen on a fixed NodePort `30880` (TCP) and `30882` (UDP, for media).
- **Auth Configuration**:
    - The Auth Service was misconfigured to connect to `mrtc` instead of `sfu`.
    - **Fix**: Forced `LIVEKIT_URL="wss://sfu.gigglin.tech"` via environment variable.

## Validation Commands

### Check Pod Status
```bash
kubectl get pods -n ess
```

### Check Service Ports
```bash
kubectl get svc -n ess ess-your_livekit_api_key_here-sfu
# Should show port 30880
```

### Debug External Connectivity
```bash
# Must return 404 or 415 (not Connection Refused or Timeout)
curl -v https://sfu.gigglin.tech/twirp/livekit.RoomService/CreateRoom
```

### Debug Internal Connectivity
Use the `debug_rtc.sh` script to inspect logs and internal pod connectivity.

## Future Maintenance
- **Updates**: Run `./install-matrix.sh` to update the stack. The script now includes all patching steps automatically.
- **Certificates**: Managed by LetsEncrypt in NPM. Ensure port 80 is open to NPM for renewals.

## Deployment Files
- `install-matrix.sh`: Main deployment script (with patches).
- `helm_values.txt`: Base Helm configuration.
- `docker-compose.yml`: NPM configuration.
