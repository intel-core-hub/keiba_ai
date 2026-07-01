Production integration and CI guide
=================================

This document explains how to safely enable production IPAT integration, distribute audit public keys, and run CI load tests.

1) Production IPAT integration
------------------------------
- Do NOT place secrets in code or in this repository.
- Provide `IPAT_API_URL` and `IPAT_API_KEY` as environment variables to the runtime, or place JSON secrets in a file and set `IPAT_SECRETS_FILE=/path/to/secrets.json`.

Example `secrets.json`:

```
{
  "url": "https://ipat.example.com/api",
  "key": "REPLACE_WITH_REAL_KEY"
}
```

Start the safe runner (will use real IPAT if env/secrets are set, otherwise mock):

```
python -m scripts.integration_run_safe
```

2) Key management and public key distribution
--------------------------------------------
- `KeyManager` supports two backends:
  - local development: `KEY_MANAGER_BACKEND=file`
  - production / mounted secrets: `KEY_MANAGER_BACKEND=env`
- `KEY_MANAGER_BACKEND=file` is blocked automatically when `KEIBA_ENV` / `ENVIRONMENT` indicates production unless `KEY_MANAGER_ALLOW_INSECURE_FILE_STORAGE=1` is set as an explicit break-glass override.
- For the env-backed path, provide one of:
  - `AUDIT_PRIVATE_KEY_PEM` or `AUDIT_PRIVATE_KEY_PATH`
  - `AUDIT_PUBLIC_KEY_PEM` or `AUDIT_PUBLIC_KEY_PATH`
- Use `KeyManager.rotate()` only in a secure development or key-ceremony environment to generate new ECDSA key pairs.
- Export the public key for auditors and verification using:

```
python -m scripts.export_pubkey --out /path/to/public.pem
```

- To publish the key to a remote server (example accepts POST /upload):

```
python -m scripts.publish_pubkey --url https://keys.example.com/upload --api-key XXXXXX
```

3) Verifying audit logs
-----------------------
To verify an audit JSONL log with an explicit public key:

```
python -m scripts.verify_audit_log logs/audit_chain_signed.jsonl --pub /path/to/public.pem
```

Or rely on entries that embed the public key (verification will use the embedded key).

4) CI load testing
-------------------
- A GitHub Actions workflow `/.github/workflows/load_test.yml` is provided. It runs `scripts/load_test` and uploads `reports/` as artifacts.
- Configure runner secrets in GitHub if you want to run real IPAT tests in CI (not recommended for production).

Security note
-------------
- Rotate keys regularly and store private keys in a secure KMS, HSM, or mounted secret workflow. Filesystem persistence is now treated as development-only and should remain disabled in production.
