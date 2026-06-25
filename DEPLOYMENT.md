# OTP-Bot-Telegram Deployment Guide

## Files added

- `deploy.sh`
  - pulls the latest code from `main` or a branch argument
  - creates/activates `./.venv`
  - installs `requirements.txt`
  - restarts `telegram-bot.service`

- `telegram-bot.service`
  - systemd unit for `bot.py`
  - runs as `zaddi-zk`
  - uses `/home/zaddi-zk/OTP-Bot-Telegram/.venv/bin/python`
  - automatically restarts on failure
  - loads environment variables from `.env`

- `install_service.sh`
  - installs and enables the systemd service

- `.github/workflows/deploy.yml`
  - GitHub Actions workflow to SSH deploy on `push` to `main`

- `.gitignore`
  - ignores Python artifacts, logs, venv, and IDE files

## Server setup

1. Copy repository to `/home/zaddi-zk/OTP-Bot-Telegram`
2. Ensure the server user is `zaddi-zk`
3. Ensure Python 3, `git`, and `python3 -m venv` are installed
4. Create `.env` in the repo root with your production values
5. Run once on the server:

```bash
cd /home/zaddi-zk/OTP-Bot-Telegram
chmod +x install_service.sh deploy.sh
./install_service.sh
```

## GitHub setup

Add these secrets to your GitHub repository:

- `SERVER_HOST`
- `SERVER_USER`
- `SERVER_SSH_KEY`
- `SERVER_SSH_PORT`
- `SERVER_KNOWN_HOSTS`

## Push-to-deploy

After you commit these files and push to `main`, GitHub Actions will:

1. checkout the repository
2. SSH into the server
3. run `./deploy.sh main`
4. restart the service

## Manual commit and push

This workspace does not contain a Git repository metadata folder (`.git`) and cannot push from here.

From your local clone, run:

```bash
git add deploy.sh install_service.sh telegram-bot.service .github/workflows/deploy.yml .gitignore DEPLOYMENT.md
git commit -m "Add production deployment automation"
git push origin main
```

If you want, I can also help you create a second workflow that verifies the service health after deployment.
