# Local Matrix Server Deployment Guide

This guide describes how to deploy your Matrix server and Nginx Proxy Manager on your local Mini PC (`192.168.1.11`).

## 1. Prerequisites
Ensure you are logged into your Mini PC:
*   IP: `192.168.1.11`
*   User: `gigglin` (or your sudo user)

## 2. Router Port Forwarding
To make your server accessible from the internet, you need to configure Port Forwarding on your router.

| Protocol | External Port | Internal IP | Internal Port | Service |
| :--- | :--- | :--- | :--- | :--- |
| **TCP** | **80** | `192.168.1.11` | **80** | HTTP (ACME/Web) |
| **TCP** | **443** | `192.168.1.11` | **443** | HTTPS (TLS) |

> [!NOTE]
> If you experience issues with voice/video calls later, you might need to check if TURN/STUN ports are required, but standard HTTPS often suffices for basic setups.

## 3. Preparation

### 1. Create Project Directory
It is best to keep all files in one folder in your home directory.

Run this on your server:
```bash
mkdir -p ~/matrix-server
cd ~/matrix-server
```

**Copy all files from this project into that folder.**
Structure should look like this:
```text
~/matrix-server/
├── docker-compose.yml
├── install-k3s.sh
├── install-matrix.sh
├── .env
└── nginx-landing/
    ├── Dockerfile
    └── ...
```

### 2. Configure Environment
Create/Edit your `.env` file in that directory:
```bash
cp .env.example .env
nano .env
```
Ensure `SERVER_NAME=gigglin.tech` is set correctly.

## 4. Run Nginx Proxy Manager
Start the Nginx Proxy Manager and Landing page containers. This will bind to ports 80 and 443 on your host.

```bash
docker compose up -d
```
*   Admin Interface: http://192.168.1.11:81
*   Default Login: `admin@example.com` / `changeme`

## 5. Install Kubernetes (K3s)
Run the script to install K3s.

```bash
chmod +x install-k3s.sh
./install-k3s.sh
```

## 6. Deploy Matrix
Run the installation script.

```bash
chmod +x install-matrix.sh
./install-matrix.sh
```
*   This script creates the `matrix` services using NodePort.
*   Wait for all pods to be "Running" (`kubectl get pods -n ess -w`).

## 7. Configuration
At the end of `install-matrix.sh`, you will see a list of NodePorts. You need to configure Proxy Hosts in Nginx Proxy Manager pointing to `192.168.1.11` (Host IP) + the NodePort.

**Example Mapping:**
*   `matrix.gigglin.tech` -> `192.168.1.11` : `[Synapse NodePort]`
*   `element.gigglin.tech` -> `192.168.1.11` : `[Element Web NodePort]`
*   (And so on for other subdomains)

Verify everything by visiting `https://element.gigglin.tech`.
