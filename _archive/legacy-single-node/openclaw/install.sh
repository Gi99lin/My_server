#!/bin/bash
set -e

# ==================== Configuration ====================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCLAW_CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-$HOME/.openclaw}"
OPENCLAW_WORKSPACE_DIR="${OPENCLAW_WORKSPACE_DIR:-$HOME/.openclaw/workspace}"
DOMAIN="ai.gigglin.tech"

echo "=== Deploying OpenClaw (Docker) ==="
echo "Config dir:    $OPENCLAW_CONFIG_DIR"
echo "Workspace dir: $OPENCLAW_WORKSPACE_DIR"
echo ""

# ==================== 1. Setup .env ====================
if [ ! -f "$SCRIPT_DIR/.env" ]; then
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
  echo "✅  Created .env from .env.example"
else
  echo "ℹ️  .env already exists, skipping"
fi

# ==================== 2. Create host directories ====================
echo "Creating host directories..."
mkdir -p "$OPENCLAW_CONFIG_DIR"
mkdir -p "$OPENCLAW_WORKSPACE_DIR"
echo "✅  Directories created"

# ==================== 3. Ensure proxy_network exists ====================
echo "Checking proxy_network..."
if ! docker network inspect my_server_proxy_network &>/dev/null; then
  echo "⚠️  proxy_network not found. Make sure root docker-compose is running:"
  echo "   cd $(dirname "$SCRIPT_DIR") && docker compose up -d"
  echo ""
  echo "Starting root docker-compose to create network..."
  cd "$(dirname "$SCRIPT_DIR")" && docker compose up -d
  cd "$SCRIPT_DIR"
fi
echo "✅  proxy_network available"

# ==================== 4. Pull image ====================
echo "Pulling OpenClaw image..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" pull
echo "✅  Image pulled"

# ==================== 5. Run onboarding wizard ====================
echo ""
echo "=========================================="
echo "  Starting OpenClaw Setup Wizard"
echo "=========================================="
echo ""
echo "The wizard will ask you to:"
echo "  1. Choose an LLM provider (Anthropic/OpenAI/local)"
echo "  2. Enter your API key"
echo "  3. Configure messaging channels (Telegram, etc.)"
echo ""

docker compose -f "$SCRIPT_DIR/docker-compose.yml" --profile cli \
  run --rm openclaw-cli onboard

# ==================== 6. Start Gateway ====================
echo ""
echo "Starting OpenClaw Gateway..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d openclaw-gateway
echo "✅  Gateway started"

# ==================== 7. Wait for health ====================
echo "Waiting for gateway to become healthy..."
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18789/healthz &>/dev/null; then
    echo "✅  Gateway is healthy!"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "⚠️  Gateway didn't become healthy in 30s. Check logs:"
    echo "   docker compose -f $SCRIPT_DIR/docker-compose.yml logs openclaw-gateway"
    exit 1
  fi
  sleep 1
done

# ==================== 8. Get dashboard URL ====================
echo ""
echo "Getting Control UI info..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" --profile cli \
  run --rm openclaw-cli dashboard --no-open 2>/dev/null || true

# ==================== Done ====================
echo ""
echo "=== Deployment Complete ==="
echo ""
echo "1. Control UI (local):"
echo "   http://localhost:18789"
echo ""
echo "2. Configure Nginx Proxy Manager (NPM):"
echo "   - Domain Names: $DOMAIN"
echo "   - Scheme: http"
echo "   - Forward Hostname / IP: openclaw-gateway"
echo "   - Forward Port: 18789"
echo "   - Websockets Support: ON"
echo "   - SSL: Request new certificate"
echo ""
echo "3. Useful commands:"
echo "   # View logs"
echo "   docker compose -f $SCRIPT_DIR/docker-compose.yml logs -f openclaw-gateway"
echo ""
echo "   # Restart"
echo "   docker compose -f $SCRIPT_DIR/docker-compose.yml restart openclaw-gateway"
echo ""
echo "   # List paired devices"
echo "   docker compose -f $SCRIPT_DIR/docker-compose.yml --profile cli run --rm openclaw-cli devices list"
echo ""
echo "   # Health check"
echo "   curl http://localhost:18789/healthz"
echo ""
