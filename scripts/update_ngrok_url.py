#!/usr/bin/env python3
"""
Helper: query local ngrok API and update NGROK_URL in .env and conf/settings.txt.

Usage:
  python scripts/update_ngrok_url.py [--port PORT] [--only-env] [--only-settings]

Requires ngrok running locally (web interface at http://127.0.0.1:4040).
"""
import json
import os
import sys
import argparse
from pathlib import Path
from urllib.parse import urlparse

import requests

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
SETTINGS_PATH = PROJECT_ROOT / "conf" / "settings.txt"

def get_ngrok_public_url(port: int = 4040) -> str | None:
    """
    Query ngrok API to get the public HTTPS URL.

    Args:
        port: Ngrok web interface port (default: 4040)

    Returns:
        Public URL as string, or None if not found.
    """
    try:
        url = f"http://127.0.0.1:{port}/api/tunnels"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        for tunnel in data.get("tunnels", []):
            public_url = tunnel.get("public_url")
            proto = tunnel.get("proto")
            if public_url and proto == "https":
                return public_url
        # fallback: return any public_url
        for tunnel in data.get("tunnels", []):
            if tunnel.get("public_url"):
                return tunnel.get("public_url")
    except requests.RequestException as e:
        print(f"Could not query ngrok API: {e}")
    return None

def write_env_ngrok(url: str) -> None:
    """
    Update or add NGROK_URL in .env file.

    Args:
        url: New NGROK_URL value.
    """
    if not ENV_PATH.exists():
        print(f".env file not found at {ENV_PATH}, creating one.")
        ENV_PATH.write_text("", encoding="utf-8")

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    new_lines = []
    key = "NGROK_URL"
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={url}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={url}")

    ENV_PATH.write_text("\n".join(new_lines), encoding="utf-8")
    print(f"Updated {key} in {ENV_PATH}")

def update_settings_json(url: str) -> None:
    """
    Update ngrok_url field in conf/settings.txt JSON file.

    Args:
        url: New ngrok_url value.
    """
    if not SETTINGS_PATH.exists():
        print(f"{SETTINGS_PATH} not found; skipping JSON update.")
        return
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["ngrok_url"] = url
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        print(f"Updated ngrok_url in {SETTINGS_PATH}")
    except Exception as e:
        print(f"Failed to update {SETTINGS_PATH}: {e}")

def main() -> int:
    parser = argparse.ArgumentParser(description="Update NGROK_URL from local ngrok")
    parser.add_argument("--port", type=int, default=4040, help="Ngrok web interface port (default: 4040)")
    parser.add_argument("--only-env", action="store_true", help="Update only .env file")
    parser.add_argument("--only-settings", action="store_true", help="Update only settings.txt")
    args = parser.parse_args()

    print("Querying local ngrok API...")
    raw_url = get_ngrok_public_url(args.port)
    if not raw_url:
        print("No public ngrok URL found. Ensure ngrok is running with:")
        print("  ngrok http 5000")
        return 1

    # Normalize URL (remove trailing slash)
    parsed = urlparse(raw_url)
    clean_url = f"{parsed.scheme}://{parsed.netloc}"
    print(f"Found public URL: {clean_url}")

    if not args.only_settings:
        write_env_ngrok(clean_url)
    if not args.only_env:
        update_settings_json(clean_url)

    print("Done. Restart your bot process to pick up the new NGROK_URL.")
    return 0

if __name__ == "__main__":
    sys.exit(main())