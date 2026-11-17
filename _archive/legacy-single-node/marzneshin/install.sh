#!/bin/bash
set -e

echo "Deploying Marzneshin (Master) setup..."

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: ./install.sh <admin_username> <admin_password>"
    echo "Example: ./install.sh myadmin mysecurepass"
    exit 1
fi

ADMIN_USER=$1
ADMIN_PASS=$2

echo "Preparing environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    # Generate random secure passwords
    SECURE_JWT=$(openssl rand -hex 32)
    DB_ROOT_PASS=$(openssl rand -hex 16)
    DB_PASS=$(openssl rand -hex 16)
    
    sed -i "s/your_generated_jwt_secret_here/$SECURE_JWT/" .env
    sed -i "s/your_db_root_password_here/$DB_ROOT_PASS/g" .env
    sed -i "s/your_db_password_here/$DB_PASS/g" .env
    
    # Set default admin
    sed -i "s/SUDO_USERNAME=admin/SUDO_USERNAME=$ADMIN_USER/" .env
    sed -i "s/SUDO_PASSWORD=admin/SUDO_PASSWORD=$ADMIN_PASS/" .env
    echo "Created .env file with secure secrets and credentials."
else
    echo ".env file already exists. Skipping recreation."
fi

echo "Pulling latest Marzneshin image..."
docker compose pull

echo "Starting Marzneshin stack..."
docker compose up -d

echo "---------------------------------------------------------"
echo "Marzneshin deployment initiated."
echo "Wait a few seconds and visit: http://<your_server_ip>:8000/dashboard/"
echo "Username: $ADMIN_USER"
echo "Password: $ADMIN_PASS"
echo "Remember to login and change the password or add further 2FA!"
echo "---------------------------------------------------------"
