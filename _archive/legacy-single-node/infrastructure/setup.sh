#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== VPS Server Setup Script ===${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root${NC}"
    exit 1
fi

# Function to check command result
check_status() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}[OK]${NC} $1"
    else
        echo -e "${RED}[FAIL]${NC} $1"
        exit 1
    fi
}

# Update system
echo -e "${YELLOW}Updating system...${NC}"
apt update && apt upgrade -y
check_status "System updated"

# Install Docker
echo -e "${YELLOW}Installing Docker...${NC}"
curl -fsSL https://get.docker.com | sh
check_status "Docker installed"

# Install Docker Compose
echo -e "${YELLOW}Installing Docker Compose...${NC}"
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
check_status "Docker Compose installed"

# Create project directory
echo -e "${YELLOW}Creating project directory...${NC}"
mkdir -p /opt/vps-server
cd /opt/vps-server
check_status "Directory created"

# Download configuration files
echo -e "${YELLOW}Downloading configuration...${NC}"
# In real scenario, you would clone a git repo here
# git clone https://github.com/your-repo.git .

check_status "Configuration ready"

# Copy and configure .env
if [ ! -f .env ]; then
    echo -e "${YELLOW}Creating .env file...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}Please edit .env file with your settings!${NC}"
    echo -e "${YELLOW} nano /opt/vps-server/.env${NC}"
fi

# Install ufw
echo -e "${YELLOW}Installing firewall...${NC}"
apt install -y ufw
check_status "UFW installed"

# Print final instructions
echo ""
echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "Next steps:"
echo "1. Edit .env file: nano /opt/vps-server/.env"
echo "2. Start services: cd /opt/vps-server && docker-compose up -d"
echo "3. Access Nginx Proxy Manager: http://your-server:81"
echo ""
echo -e "${YELLOW}IMPORTANT:${NC} Don't forget to:"
echo "- Point your domain DNS to this server IP"
echo "- Open ports 80, 443, 81 in your VPS firewall"
echo "- Change default passwords"
