#!/usr/bin/env python3
"""Single-entry launcher for OTP Bot.

Usage:
  py run_bot.py           # auto-detect ngrok, set polling mode, run bot.py
  py run_bot.py --webhook true   # enable webhook mode instead

What it does:
- Optionally queries local ngrok (http://127.0.0.1:4040) and updates .env NGROK_URL
- Ensures `USE_WEBHOOK` in .env matches requested mode
- Starts `bot.py` as a subprocess and streams output

This is a convenience wrapper to start the project from one command.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import requests
import sys
import argparse

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"


def get_ngrok_public_url(port: int = 4040) -> str | None:
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/api/tunnels", timeout=2)
        resp.raise_for_status()
        data = resp.json()
        for t in data.get("tunnels", []):
            if t.get("proto") == "https" and t.get("public_url"):
                return t.get("public_url")
        for t in data.get("tunnels", []):
            if t.get("public_url"):
                return t.get("public_url")
    except Exception:
        return None


def get_ngrok_tunnel_for_port(api_port: int = 4040, target_port: int | None = None) -> str | None:
    """Return a public ngrok URL that targets the given local target_port if available.

    Falls back to the first https tunnel if specific port tunnel isn't found.
    """
    try:
        resp = requests.get(f"http://127.0.0.1:{api_port}/api/tunnels", timeout=2)
        resp.raise_for_status()
        data = resp.json()
        tunnels = data.get("tunnels", [])
        # Try to find tunnel whose 'config' or 'addr' mentions the target_port
        if target_port is not None:
            for t in tunnels:
                cfg = t.get("config") or {}
                addr = cfg.get("addr") or t.get("addr") or ""
                try:
                    addr_str = str(addr).lower()
                    if addr_str.startswith(f"http://localhost:{target_port}") or addr_str.startswith(f"http://127.0.0.1:{target_port}") or addr_str == str(target_port):
                        return t.get("public_url")
                except Exception:
                    continue
            # If a specific port was requested, do not fallback to a generic tunnel.
            return None
        # Fallback to general https/public_url selection
        for t in tunnels:
            if t.get("proto") == "https" and t.get("public_url"):
                return t.get("public_url")
        for t in tunnels:
            if t.get("public_url"):
                return t.get("public_url")
    except Exception:
        return None


def ensure_env_key(key: str, value: str) -> None:
    try:
        lines = []
        if ENV_PATH.exists():
            lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")

        content = "\n".join(new_lines)
        if content and not content.endswith("\n"):
            content += "\n"

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(ENV_PATH.parent), delete=False) as handle:
            handle.write(content)
            temp_path = Path(handle.name)

        os.replace(temp_path, ENV_PATH)
    except Exception as exc:
        print(f"[run_bot] Failed to update {ENV_PATH}: {exc}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Single entry launcher for OTP Bot")
    parser.add_argument("--webhook", choices=("true", "false"), default="false",
                        help="Start in Telegram webhook mode (true) or polling (false). Default: false")
    parser.add_argument("--no-ngrok", action="store_true", help="Do not attempt to query local ngrok")
    parser.add_argument("--ngrok-port", type=int, default=4040, help="Local ngrok API port (default 4040)")
    args = parser.parse_args()

    use_webhook = args.webhook.lower() == "true"

    print("[run_bot] Preparing environment...")

    # Try to update NGROK_URL from local ngrok if available
    if not args.no_ngrok:
        ngrok_url = get_ngrok_public_url(args.ngrok_port)
        if ngrok_url:
            print(f"[run_bot] Found ngrok URL: {ngrok_url} — writing to .env")
            ensure_env_key("NGROK_URL", ngrok_url)
            # Also set WEBHOOK_URL to the same base
            ensure_env_key("WEBHOOK_URL", ngrok_url)
            # Try to find a tunnel specifically for the Live Listen FastAPI (port 5001)
            live_tunnel = get_ngrok_tunnel_for_port(args.ngrok_port, target_port=5001)
            if live_tunnel:
                print(f"[run_bot] Found ngrok tunnel for Live Listen: {live_tunnel} — writing to .env")
                ensure_env_key("LIVE_LISTEN_URL", live_tunnel)
            else:
                # If no specific tunnel, default LIVE_LISTEN_URL to local FastAPI
                ensure_env_key("LIVE_LISTEN_URL", "http://127.0.0.1:5001")
        else:
            print("[run_bot] No local ngrok detected (or API unreachable). Skipping ngrok update.")
            # Ensure LIVE_LISTEN_URL points at local FastAPI when no ngrok available
            ensure_env_key("LIVE_LISTEN_URL", "http://127.0.0.1:5001")

    # Ensure USE_WEBHOOK is set as requested
    ensure_env_key("USE_WEBHOOK", "true" if use_webhook else "false")

    print(f"[run_bot] USE_WEBHOOK set to {'true' if use_webhook else 'false'} in .env")

    # Sanity checks (informational)
    if not ENV_PATH.exists():
        print(f"[run_bot] Warning: {ENV_PATH} not found — created minimal .env")

    # Start the main bot
    print("[run_bot] Launching bot.py — logs will appear below. Press Ctrl+C to stop.")
    try:
        # Use same Python executable that runs this script
        proc = subprocess.Popen([sys.executable, "bot.py"], cwd=str(ROOT))
        # Forward exit code when process finishes
        returncode = proc.wait()
        print(f"[run_bot] bot.py exited with code {returncode}")
        sys.exit(returncode)
    except KeyboardInterrupt:
        print("[run_bot] Interrupted by user — terminating bot process.")
        try:
            proc.terminate()
        except Exception:
            pass
        sys.exit(0)
    except Exception as e:
        print(f"[run_bot] Failed to start bot.py: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
