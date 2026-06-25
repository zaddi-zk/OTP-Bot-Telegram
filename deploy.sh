#!/usr/bin/env bash
set -euo pipefail

# Production deployment script for OTP-Bot-Telegram
# Usage: ./deploy.sh [branch]
# Example: ./deploy.sh main

DEPLOY_DIR="/home/zaddi-zk/OTP-Bot-Telegram"
SERVICE_NAME="telegram-bot.service"
VENV_DIR="$DEPLOY_DIR/.venv"
BRANCH="${1:-main}"

cd "$DEPLOY_DIR"

echo "=== Deploying OTP-Bot-Telegram ==="

echo "Pulling latest code from Git branch '$BRANCH'..."
git pull origin "$BRANCH"

if [ ! -d "$VENV_DIR" ]; then
  echo "Virtual environment not found at $VENV_DIR"
  echo "Creating new venv..."
  python3 -m venv "$VENV_DIR"
fi

# Activate venv and install requirements
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Restarting systemd service: $SERVICE_NAME"
if sudo -n true 2>/dev/null; then
  sudo systemctl restart "$SERVICE_NAME"
else
  echo "ERROR: sudo requires a password. Configure passwordless sudo for the deploy user or run this script as root."
  exit 1
fi

echo "Deployment complete."
