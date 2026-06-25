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

echo
echo "=== Bootstrap complete ==="
echo
echo "Next manual steps:"
echo "1) Edit $APP_DIR/.env and fill in all required production values."
echo "2) Add the deploy private key contents from $DEPLOY_KEY to GitHub secret SERVER_SSH_KEY."
echo "3) Add the server host key entry to GitHub secret SERVER_KNOWN_HOSTS."
echo "4) Start the service after .env is ready:"
echo "   sudo systemctl start telegram-bot.service"
echo

echo "=== GitHub secret values ==="
echo
if [ -f "$DEPLOY_KEY" ]; then
  echo "SERVER_SSH_KEY (copy the block below):"
  echo "-----BEGIN SERVER_SSH_KEY-----"
  cat "$DEPLOY_KEY"
  echo "-----END SERVER_SSH_KEY-----"
  echo
else
  echo "ERROR: Deploy key file not found: $DEPLOY_KEY"
fi

echo "SERVER_KNOWN_HOSTS (copy the line below or use the command shown):"
if command -v ssh-keyscan >/dev/null 2>&1; then
  if hostname -f >/dev/null 2>&1; then
    ssh-keyscan -t ed25519,rsa "$(hostname -f)" 2>/dev/null || true
  fi
  ssh-keyscan -t ed25519,rsa localhost 2>/dev/null || true
else
  echo "# ssh-keyscan not available"
fi

echo
if command -v ssh-keyscan >/dev/null 2>&1; then
  echo "If the output above does not match your public server host, run this on a trusted machine:"
  echo "  ssh-keyscan -p 22 YOUR_SERVER_HOST"
fi

echo
echo "Bootstrap details:"
echo "- app directory: $APP_DIR"
echo "- deploy user: $USER"
echo "- deploy key: $DEPLOY_KEY"
echo "- public key: $DEPLOY_KEY.pub"
echo "- .env placeholder: $ENV_FILE"
