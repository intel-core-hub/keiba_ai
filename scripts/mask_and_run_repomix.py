#!/usr/bin/env python3
"""
Create a temporary repo copy with sensitive files masked, run repomix on it,
write output to repo root, then remove the temp copy.

Usage: run this with the project's venv python so that `repomix` is available
as a module: `path/to/venv/python scripts/mask_and_run_repomix.py`
"""
from pathlib import Path
import shutil
import re
import subprocess
import sys
import os

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = REPO_ROOT / '.repomix_safe_copy'

# Paths to mask (workspace-relative, using forward slashes)
SENSITIVE_PATHS = {
    'core/ipat_adapter.py',
    'logs/audit_chain_km.jsonl',
    'logs/audit_chain_signed.jsonl',
    'repomix-output.xml',
    'scripts/ev_analysis.py',
    'scripts/integration_demo.py',
    'scripts/market_attribution_utils.py',
    'scripts/publish_pubkey.py',
}

def mask_text(text: str) -> str:
    # Remove private key blocks
    text = re.sub(r'-----BEGIN PRIVATE KEY-----[\s\S]+?-----END PRIVATE KEY-----', '<REDACTED_PRIVATE_KEY>', text)
    text = re.sub(r'-----BEGIN RSA PRIVATE KEY-----[\s\S]+?-----END RSA PRIVATE KEY-----', '<REDACTED_PRIVATE_KEY>', text)

    # Mask api_key assignments or JSON fields (simple heuristic)
    text = re.sub(r'(?i)(api[_-]?key["\']?\s*[:=]\s*["\']?)([^"\'\s,}]+)', r"\1<REDACTED_API_KEY>", text)
    text = re.sub(r'(?i)(secret[_-]?key["\']?\s*[:=]\s*["\']?)([^"\'\s,}]+)', r"\1<REDACTED_SECRET>", text)

    # Mask long hex/base64-looking strings (>=40 chars)
    text = re.sub(r'[A-Fa-f0-9]{40,}', '<REDACTED_HEX>', text)
    text = re.sub(r'([A-Za-z0-9+/]{40,}={0,2})', '<REDACTED_B64>', text)

    return text

def should_copy(path: Path) -> bool:
    # Skip virtualenv, git, and existing temp dir
    parts = [p.lower() for p in path.parts]
    if '.venv' in parts or '.git' in parts or TEMP_DIR.name in parts:
        return False
    return True

def main():
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    for src in REPO_ROOT.rglob('*'):
        if not src.is_file():
            continue
        if not should_copy(src):
            continue

        rel = src.relative_to(REPO_ROOT)
        dest = TEMP_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        rel_posix = str(rel).replace('\\', '/')
        if rel_posix in SENSITIVE_PATHS:
            try:
                text = src.read_text(encoding='utf-8')
            except Exception:
                # If binary or unreadable, write a placeholder
                dest.write_text('<REDACTED_BINARY>')
                continue
            masked = mask_text(text)
            dest.write_text(masked, encoding='utf-8')
        else:
            shutil.copy2(src, dest)

    # Run repomix using the same python interpreter
    outpath = REPO_ROOT / 'repomix-output.xml'
    cmd = [sys.executable, '-m', 'repomix', '-o', str(outpath), '--style', 'xml', str(TEMP_DIR)]
    print('Running:', ' '.join(cmd))
    try:
        subprocess.run(cmd, check=True)
        print('repomix completed, output written to', outpath)
    except subprocess.CalledProcessError as e:
        print('repomix failed:', e)
        sys.exit(2)
    finally:
        try:
            shutil.rmtree(TEMP_DIR)
        except Exception:
            pass

if __name__ == '__main__':
    main()
