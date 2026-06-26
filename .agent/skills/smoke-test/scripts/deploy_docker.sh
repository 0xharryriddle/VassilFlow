#!/usr/bin/env bash
set -e

echo "=========================================="
echo "  Docker Deployment"
echo "=========================================="
echo ""

# Check config.yaml
if [ ! -f "config.yaml" ]; then
    echo "config.yaml does not exist. Generating it..."
    make config
    echo ""
    echo "[WARN]  Please edit config.yaml to configure your models and API keys"
    echo "  Then run this script again"
    exit 1
else
    echo "[OK] config.yaml exists"
fi
echo ""

# Check the .env file
if [ ! -f ".env" ]; then
    echo ".env does not exist. Copying it from the example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "[OK] Created the .env file"
    else
        echo "[WARN]  .env.example does not exist. Please create the .env file manually"
    fi
else
    echo "[OK] .env file exists"
fi
echo ""

# Check the frontend .env file
if [ ! -f "frontend/.env" ]; then
    echo "frontend/.env does not exist. Copying it from the example..."
    if [ -f "frontend/.env.example" ]; then
        cp frontend/.env.example frontend/.env
        echo "[OK] Created the frontend/.env file"
    else
        echo "[WARN]  frontend/.env.example does not exist. Please create frontend/.env manually"
    fi
else
    echo "[OK] frontend/.env file exists"
fi
echo ""
# Initialize the Docker environment
echo "Initializing the Docker environment..."
make docker-init
echo ""

# Start Docker services
echo "Starting Docker services..."
make docker-start
echo ""

echo "=========================================="
echo "  Deployment Complete"
echo "=========================================="
echo ""
echo "[URL] Access URL: http://localhost:2026"
echo "[LOGS] View logs: make docker-logs"
echo "[STOP] Stop services: make docker-stop"
