#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="telegram-bot.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
DEPLOY_DIR="/home/zaddi-zk/OTP-Bot-Telegram"

if [ ! -f "$DEPLOY_DIR/$SERVICE_NAME" ]; then
  echo "Error: $DEPLOY_DIR/$SERVICE_NAME not found."
  exit 1
fi

sudo cp "$DEPLOY_DIR/$SERVICE_NAME" "$SERVICE_PATH"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager
