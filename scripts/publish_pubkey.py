"""Publish the latest public key to a remote URL or local pubserver directory.

Usage:
  python -m scripts.publish_pubkey --url https://example.com/upload --api-key SECRET
  OR
  python -m scripts.publish_pubkey --local-dir /var/www/pubkeys

The script will POST the PEM as 'file' form-data with optional Authorization header.
"""
import argparse
import os
import requests
from core.key_manager import KeyManager


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", help="remote upload URL (POST)")
    p.add_argument("--api-key", help="API key for remote upload (Bearer)")
    p.add_argument("--local-dir", help="fallback local directory to write public key")
    args = p.parse_args()

    km = KeyManager()
    pub = km.get_public_pem()
    if not pub:
        print("No public key available")
        return

    if args.url:
        headers = {}
        if args.api_key:
            headers["Authorization"] = f"Bearer {args.api_key}"
        files = {"file": ("pub.pem", pub, "application/x-pem-file")}
        resp = requests.post(args.url, headers=headers, files=files)
        print("HTTP status:", resp.status_code)
        print(resp.text)
        return

    if args.local_dir:
        os.makedirs(args.local_dir, exist_ok=True)
        out = os.path.join(args.local_dir, "latest_pub.pem")
        with open(out, "wb") as f:
            f.write(pub)
        print("Wrote public key to", out)
        return

    print(pub.decode("utf-8"))


if __name__ == "__main__":
    main()
