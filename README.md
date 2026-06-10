# My HomeLab Server

This repository contains the configuration, deployment scripts, and docker-compose files for a personal HomeLab server infrastructure. It combines **Docker Compose** architectures for most services with **K3s (Kubernetes)** for specific enterprise stacks like Matrix.

## 🏗 Infrastructure Overview
- **Base OS**: Ubuntu (VPS / Local Mini PC)
- **Container Runtimes**: Docker (Portainer/Native) & K3s (Lightweight Kubernetes)
- **Ingress & Proxy**: [Nginx Proxy Manager](https://nginxproxymanager.com/) running via docker in the root directory. Handles SSL termination and subdomains.
- **Landing Page**: Custom nginx-based personal portfolio website running alongside NPM from the prebuilt `ghcr.io/gi99lin/portfolio:latest` image.

### 🚀 Quick Start
1. **Basic Host Setup**: Configure your Ubuntu server environment and firewall limits.
2. **Setup Proxy & Landing**: At the root of this project, run `docker compose up -d` to spin up Nginx Proxy Manager and the local Landing page.
3. **Deploy Services**: Navigate to individual directories (e.g., `cd openclaw`) to configure `.env` files and run deployment commands/scripts.

*(For detailed local Matrix deployment and K3s instructions, see [LOCAL_DEPLOY.md](./LOCAL_DEPLOY.md))*

### 🔄 Auto-deploy (Watchtower)
[`watchtower/`](./watchtower) runs [Watchtower](https://containrrr.dev/watchtower/), which polls GHCR every
2 minutes and restarts any container labelled `com.centurylinklabs.watchtower.enable=true` when a newer
`:latest` image is published. With it running, **a `git push` is the whole deploy** — GitHub Actions builds and
pushes the image, Watchtower picks it up. Unlabeled containers (NPM, its DB) are never touched.

```bash
docker login ghcr.io -u Gi99lin   # once, so Watchtower can pull private images
cd watchtower && docker compose up -d
```

### 🌐 Public demos (no password, fake data)
Portfolio-facing demos of the dashboards, safe to expose publicly — they ship canned data and have no backend:
- [`life-dashboard-demo/`](./life-dashboard-demo) → `demo.gigglin.tech`
- [`status-dashboard-demo/`](./status-dashboard-demo) → `infra.gigglin.tech`

```bash
cd life-dashboard-demo && docker compose up -d
cd ../status-dashboard-demo && docker compose up -d
```
Then add the matching Proxy Hosts in NPM. Full runbook (DNS, NPM, phases) lives in the
`status_dashboard` repo at `docs/DEPLOY.md`.

---

## 🤖 AI & LLM Ecosystem

### OpenClaw (Multi-Agent System)
Personal AI assistant framework with persistent memory, multi-agent orchestration, and Telegram bots (Dev Team, QA, FinAnalyst, etc.).
- **Location**: [`openclaw/`](./openclaw)
- **Deployment**: `cd openclaw && docker compose up -d`

### Hermes (AI Agents)
Specialized AI agents including `hermes-qa` for QA automation and `hermes-finanalyst` for financial research.
- **Location**: [`hermes/`](./hermes)

### LibreChat
An enterprise-grade, unified web interface for interacting with various LLM providers.
- **Location**: [`librechat/`](./librechat)

### OmniRoute
API routing proxy and load balancer to manage, monitor, and route inference LLM requests (used seamlessly by OpenClaw).
- **Location**: [`omniroute/`](./omniroute)

### AI Presentation & Testcase Generators
- **AI Presentation**: Web service for generating presentation materials via AI. Location: [`ai-presentation/`](./ai-presentation)
- **AI Testcase Generator**: Service to automatically generate test cases using LLMs. Location: [`ai-testcase-generator/`](./ai-testcase-generator)

---

## 🛡️ Privacy, Proxy, VPN & Remote Access

### Marzneshin (Xray Proxy)
Advanced VPN and proxy management interface using the Xray core. Handles secure access workflows.
- **Location**: [`marzneshin/`](./marzneshin)

### Apache Guacamole
Clientless remote desktop gateway supporting standard protocols like VNC, RDP, and SSH.
- **Location**: [`guacamole/`](./guacamole)

---

## ☁️ Cloud, Synchronization & Dashboards

### Nextcloud
Self-hosted platform for comprehensive file storage, calendar, and contacts synchronization. Includes Talk integration.
- **Location**: [`nextcloud/`](./nextcloud)

### Syncthing
Decentralized, continuous file synchronization service operating smoothly across devices.
- **Location**: [`syncthing/`](./syncthing)

### Life Dashboard
Personal dashboard for metric tracking and analytics visualization.
- **Location**: [`life-dashboard/`](./life-dashboard)

---

## 💬 Communication

### Matrix Server (Element Server Suite)
A complete federated Matrix messaging stack with built-in VoIP via LiveKit. Deployed entirely on K3s.
- **Location**: [`matrix/`](./matrix)
- **Docs**: [Deployment Walkthrough](./matrix/WALKTHROUGH.md)

---

## 📂 Full Directory Structure
- `_archive/` - Archived templates and legacy files.
- `ai-presentation/` - Service for generating presentations using AI.
- `ai-testcase-generator/` - Automatic software testcase generator.
- `backup/` - Tools or scripts associated with taking system backups.
- `dashboard/` - Minimal start dashboard configuration.
- `guacamole/` - Apache Guacamole remote desktop gateway.
- `hermes/` - Hermes QA and Financial AI agents.
- `infrastructure/` - Core host and K3s installation scripts.
- `librechat/` - Chat UI for local and remote LLMs.
- `life-dashboard/` - Personal dashboard for tracking and analytics.
- `livekit-config/` - Custom configuration sets for LiveKit services.
- `marzneshin/` - Xray proxy panel configuration.
- `matrix/` - Complete Matrix deployment scripts for K3s.
- `nextcloud/` - Nextcloud deployment files.
- `omniroute/` - Setup for LLM proxy routing.
- `openclaw/` - The OpenClaw AI Multi-Agent architecture.
- Portfolio landing page - deployed from `ghcr.io/gi99lin/portfolio:latest`; source lives in the separate `portfolio` repository.
- `scripts/` - Maintenance and utility bash scripts.
- `syncthing/` - File synchronization component.
