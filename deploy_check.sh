#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="telegram-bot.service"
DEPLOY_DIR="/home/zaddi-zk/OTP-Bot-Telegram"

cd "$DEPLOY_DIR" || exit 1

echo "=== Verifying $SERVICE_NAME ==="

if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "$SERVICE_NAME is active"
else
  echo "ERROR: $SERVICE_NAME is not active"
  sudo systemctl status "$SERVICE_NAME" --no-pager -n 20
  exit 1
fi

echo "=== Recent service log ==="
sudo journalctl -u "$SERVICE_NAME" --no-pager -n 40 | head -n 40 || true

echo "=== Process check ==="
sudo ps -ef | grep -E "python.*bot.py|bot.py" | grep -v grep || true

echo "Deployment verification completed successfully."
