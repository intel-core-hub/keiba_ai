"""Verify an audit JSONL log using a provided public key or embedded public key.

Usage: python -m scripts.verify_audit_log <logfile> [--pub pub.pem]
"""
import argparse
import json
from core.audit_hash_log import ImmutableAuditLog


def main():
    p = argparse.ArgumentParser()
    p.add_argument("logfile")
    p.add_argument("--pub", help="public key PEM file to use for verification")
    args = p.parse_args()

    al = ImmutableAuditLog(args.logfile)
    pub_pem = None
    if args.pub:
        with open(args.pub, "rb") as f:
            pub_pem = f.read()

    ok = True
    with open(args.logfile, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            entry = json.loads(line)
            v = al.verify_entry(entry, public_key_pem=pub_pem)
            print(f"line {i}: {v}")
            if not v:
                ok = False

    if ok:
        print("All signatures valid")
    else:
        print("Signature verification failed for some entries")


if __name__ == "__main__":
    main()
