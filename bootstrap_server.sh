#!/usr/bin/env bash
set -euo pipefail

USER="zaddi-zk"
HOME_DIR="/home/$USER"
APP_DIR="$HOME_DIR/OTP-Bot-Telegram"
REPO_URL="https://github.com/zaddi-zk/OTP-Bot-Telegram.git"
SSH_DIR="$HOME_DIR/.ssh"
DEPLOY_KEY="$HOME_DIR/deploy_key"
ENV_FILE="$APP_DIR/.env"
SERVICE_FILE="$APP_DIR/telegram-bot.service"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: This script must be run as root."
  echo "sudo ./bootstrap_server.sh"
  exit 1
fi

echo "=== Bootstrapping OTP-Bot-Telegram deployment server ==="

echo "1) Installing required packages"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y git python3 python3-venv python3-pip ssh
else
  echo "ERROR: apt-get not found. This script currently supports Debian/Ubuntu only."
  exit 1
fi

echo "2) Creating deploy user '$USER'"
if ! id "$USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$USER"
fi
mkdir -p "$HOME_DIR"
chown "$USER:$USER" "$HOME_DIR"
chmod 755 "$HOME_DIR"

if [ -d "$APP_DIR/.git" ]; then
  echo "3) Updating existing repository"
  sudo -u "$USER" git -C "$APP_DIR" fetch --all --prune
  sudo -u "$USER" git -C "$APP_DIR" reset --hard origin/main
else
  echo "3) Cloning repository into $APP_DIR"
  sudo -u "$USER" git clone "$REPO_URL" "$APP_DIR"
fi

mkdir -p "$SSH_DIR"
chown "$USER:$USER" "$SSH_DIR"
chmod 700 "$SSH_DIR"

if [ ! -f "$DEPLOY_KEY" ]; then
  echo "4) Generating deploy SSH key"
  ssh-keygen -t ed25519 -f "$DEPLOY_KEY" -N "" -C "deploy@$USER-$(hostname)"
  chown "$USER:$USER" "$DEPLOY_KEY" "$DEPLOY_KEY.pub"
  chmod 600 "$DEPLOY_KEY" "$DEPLOY_KEY.pub"
fi

if ! grep -q -F "$(cat "$DEPLOY_KEY.pub")" "$SSH_DIR/authorized_keys" 2>/dev/null; then
  echo "5) Installing deploy key into authorized_keys"
  touch "$SSH_DIR/authorized_keys"
  cat "$DEPLOY_KEY.pub" >> "$SSH_DIR/authorized_keys"
  chown "$USER:$USER" "$SSH_DIR/authorized_keys"
  chmod 600 "$SSH_DIR/authorized_keys"
fi

echo "6) Ensuring the service file and scripts are executable"
chmod +x "$APP_DIR/install_service.sh" "$APP_DIR/deploy.sh" "$APP_DIR/deploy_check.sh"
chown "$USER:$USER" "$APP_DIR/install_service.sh" "$APP_DIR/deploy.sh" "$APP_DIR/deploy_check.sh"

if [ ! -f "$ENV_FILE" ]; then
  echo "7) Creating .env placeholder file"
  cat > "$ENV_FILE" <<'EOF'
# Rename this file to .env and fill in your real production values.
BOT_TOKEN=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
NGROK_URL=
NGROK_TOKEN=
ELEVENLABS_API_KEY=
MAIN_CHANNEL_ID=
BACKUP_CHANNEL_ID=
ADMIN_ID=
DEVELOPER_IDS=
EOF
  chown "$USER:$USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

if [ -f "$SERVICE_FILE" ]; then
  echo "8) Installing systemd service"
  cp "$SERVICE_FILE" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable telegram-bot.service
else
  echo "WARNING: $SERVICE_FILE not found; service file not installed."
fi

cat <<'EOF'

=== Bootstrap complete ===

Next manual steps:
1) Edit $APP_DIR/.env and fill in all required production values.
2) Add the deploy private key contents from $DEPLOY_KEY to GitHub secret SERVER_SSH_KEY.
3) Add the result of ssh-keyscan -p 22 $SERVER_HOST to GitHub secret SERVER_KNOWN_HOSTS.
4) Start the service after .env is ready:
   systemctl start telegram-bot.service

Bootstrap details:
- app directory: $APP_DIR
- deploy user: $USER
- deploy key: $DEPLOY_KEY
- public key: $DEPLOY_KEY.pub
- .env placeholder: $ENV_FILE

Use the following command on your local machine to get the host key entry:
  ssh-keyscan -p 22 YOUR_SERVER_HOST

EOF
