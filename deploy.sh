#!/usr/bin/env bash
set -euo pipefail

# Production deployment script for OTP-Bot-Telegram
# Usage: ./deploy.sh [branch]
# Example: ./deploy.sh main

DEPLOY_DIR="/home/zaddi-zk/OTP-Bot-Telegram"
SERVICE_NAME="telegram-bot.service"
VENV_DIR="$DEPLOY_DIR/.venv"
BRANCH="${1:-main}"

cd "$DEPLOY_DIR" || exit 1

echo "=== Deploying OTP-Bot-Telegram ==="

echo "Fetching latest code from Git branch '$BRANCH'..."
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"

if [ ! -d "$VENV_DIR" ]; then
  echo "Virtual environment not found at $VENV_DIR"
  echo "Creating new venv..."
  python3 -m venv "$VENV_DIR"
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required on the server. Install Python 3 and retry."
  exit 1
fi

# Activate venv and install requirements
source "$VENV_DIR/bin/activate"
echo "Using Python: $(python --version)"
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
