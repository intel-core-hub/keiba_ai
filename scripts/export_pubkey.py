"""Export the latest public key to a user-specified path (stdout if not provided)."""
import os
import argparse
from core.key_manager import KeyManager


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", help="output path for public key PEM (defaults to stdout)")
    args = p.parse_args()
    km = KeyManager()
    pub = km.get_public_pem()
    if not pub:
        print("No public key available")
        return
    if args.out:
        with open(args.out, "wb") as f:
            f.write(pub)
        print(f"Wrote public key to {args.out}")
    else:
        print(pub.decode("utf-8"))


if __name__ == "__main__":
    main()
