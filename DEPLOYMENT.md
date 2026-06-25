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

- `.github/workflows/deploy-and-check.yml`
  - SSH deploy + post-deploy verification workflow

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

- `SERVER_HOST` — the SSH hostname or IP of your deployment server
- `SERVER_USER` — the Linux user that owns `/home/zaddi-zk/OTP-Bot-Telegram`
- `SERVER_SSH_KEY` — the private key for SSH access to the server
- `SERVER_SSH_PORT` — the SSH port, usually `22`
- `SERVER_KNOWN_HOSTS` — the server SSH host key entry

To generate `SERVER_KNOWN_HOSTS`, run from a trusted machine:

```bash
ssh-keyscan -p 22 your.server.example.com
```

Copy the resulting line into the secret value.

If you need a private key for deploy, generate one with:

```bash
ssh-keygen -t ed25519 -f deploy_key -N ''
```

Then place the public key in `/home/zaddi-zk/.ssh/authorized_keys` on the server.

## Push-to-deploy

After you commit these files and push to `main`, GitHub Actions will:

1. checkout the repository
2. SSH into the server
3. run `./deploy.sh main`
4. restart the service

If you want a stronger deployment path, use the `Deploy and verify OTP-Bot-Telegram` workflow in `.github/workflows/deploy-and-check.yml`, which also runs `./deploy_check.sh` after deployment.

## Manual commit and push

From your local clone, stage the new deployment files and push them to `main`:

```bash
git add deploy.sh deploy_check.sh install_service.sh telegram-bot.service .github/workflows/deploy.yml .github/workflows/deploy-and-check.yml .gitignore DEPLOYMENT.md
git commit -m "Add production deployment automation and verification workflow"
git push origin main
```

## Notes on sensitive data

- `.env` is intentionally ignored and should store your production secrets on the server only.
- `conf/` is also ignored, because it contains runtime configuration and temporary bot state.
- Do not commit `conf/settings.txt` or any secret-bearing files to the repository.

## Workflow selection

- Use `.github/workflows/deploy.yml` when you want a simple deploy-only pipeline.
- Use `.github/workflows/deploy-and-check.yml` when you want deploy plus automatic post-deploy verification.

If you want, I can also help you extend the verification workflow with additional health checks.
