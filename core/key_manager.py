from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Protocol, Tuple

from .audit_hash_log import ImmutableAuditLog


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _deployment_environment() -> str:
    for name in ("KEIBA_ENV", "ENVIRONMENT", "APP_ENV"):
        value = os.getenv(name)
        if value:
            return value.strip().lower()
    return "development"


def _is_production_environment() -> bool:
    return _deployment_environment() in {"prod", "production", "live"}


def _read_pem_bytes(value_env: str, path_env: str) -> bytes | None:
    inline_value = os.getenv(value_env)
    if inline_value:
        return inline_value.encode("utf-8")

    path_value = os.getenv(path_env)
    if not path_value:
        return None

    path = Path(path_value).expanduser()
    if not path.exists():
        return None
    return path.read_bytes()


class _KeyBackend(Protocol):
    def latest_version(self) -> str | None:
        ...

    def get_public_pem(self) -> bytes | None:
        ...

    def load_private_pem(self) -> bytes | None:
        ...

    def latest_private_key_path(self) -> str | None:
        ...

    def rotate(self) -> Tuple[str, str]:
        ...

    def list_versions(self) -> list[str]:
        ...


class _FilesystemKeyBackend:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _version_dir(self, version: str) -> Path:
        return self.base_dir / version

    def latest_version(self) -> str | None:
        latest_file = self.base_dir / "LATEST"
        if not latest_file.exists():
            return None
        return latest_file.read_text(encoding="utf-8").strip() or None

    def get_public_pem(self) -> bytes | None:
        version = self.latest_version()
        if not version:
            return None
        pub = self._version_dir(version) / "pub.pem"
        if not pub.exists():
            return None
        return pub.read_bytes()

    def load_private_pem(self) -> bytes | None:
        private_path = self.latest_private_key_path()
        if not private_path:
            return None
        return Path(private_path).read_bytes()

    def latest_private_key_path(self) -> str | None:
        version = self.latest_version()
        if not version:
            return None
        private_path = self._version_dir(version) / "priv.pem"
        if not private_path.exists():
            return None
        return str(private_path)

    def rotate(self) -> Tuple[str, str]:
        ts = str(int(time.time()))
        version_dir = self._version_dir(ts)
        version_dir.mkdir(exist_ok=False)
        priv = version_dir / "priv.pem"
        pub = version_dir / "pub.pem"
        audit_log = ImmutableAuditLog(os.path.join("logs", "_km_tmp.jsonl"))
        audit_log.generate_ecdsa_keypair(str(priv), str(pub), overwrite=False)
        (self.base_dir / "LATEST").write_text(ts, encoding="utf-8")
        return str(priv), str(pub)

    def list_versions(self) -> list[str]:
        return sorted(path.name for path in self.base_dir.iterdir() if path.is_dir() and path.name.isdigit())


class _EnvKeyBackend:
    def latest_version(self) -> str | None:
        if self.get_public_pem() or self.load_private_pem():
            return os.getenv("KEY_MANAGER_VERSION", "env")
        return None

    def get_public_pem(self) -> bytes | None:
        return _read_pem_bytes("AUDIT_PUBLIC_KEY_PEM", "AUDIT_PUBLIC_KEY_PATH")

    def load_private_pem(self) -> bytes | None:
        return _read_pem_bytes("AUDIT_PRIVATE_KEY_PEM", "AUDIT_PRIVATE_KEY_PATH")

    def latest_private_key_path(self) -> str | None:
        path_value = os.getenv("AUDIT_PRIVATE_KEY_PATH")
        if not path_value:
            return None
        path = Path(path_value).expanduser()
        if not path.exists():
            return None
        return str(path)

    def rotate(self) -> Tuple[str, str]:
        raise RuntimeError("Key rotation is unavailable for KEY_MANAGER_BACKEND=env")

    def list_versions(self) -> list[str]:
        version = self.latest_version()
        return [version] if version else []


class KeyManager:
    """Key manager with a production-safe backend boundary.

    Supported backends:
    - `file`: local development only; persists `priv.pem` / `pub.pem` under `base_dir`.
    - `env`: reads PEM material from env vars or mounted secret paths.

    Production-like environments default to `env` and reject the filesystem backend
    unless `KEY_MANAGER_ALLOW_INSECURE_FILE_STORAGE=1` is set as an explicit break-glass override.
    """

    def __init__(self, base_dir: str = "keys", backend: str | None = None):
        self.base_dir = Path(os.getenv("KEY_MANAGER_BASE_DIR", base_dir))
        resolved_backend = (backend or os.getenv("KEY_MANAGER_BACKEND") or "").strip().lower()
        if not resolved_backend:
            resolved_backend = "env" if _is_production_environment() else "file"

        self.backend_name = resolved_backend
        self._backend = self._build_backend(resolved_backend)

    def _build_backend(self, backend: str) -> _KeyBackend:
        if backend == "file":
            if _is_production_environment() and not _parse_bool(
                os.getenv("KEY_MANAGER_ALLOW_INSECURE_FILE_STORAGE"),
                default=False,
            ):
                raise RuntimeError(
                    "Filesystem key storage is blocked in production. "
                    "Use KEY_MANAGER_BACKEND=env or set KEY_MANAGER_ALLOW_INSECURE_FILE_STORAGE=1 "
                    "only for a temporary break-glass workflow."
                )
            return _FilesystemKeyBackend(self.base_dir)
        if backend == "env":
            return _EnvKeyBackend()
        raise ValueError(f"Unsupported key manager backend: {backend}")

    def _version_dir(self, version: str) -> str:
        return str(self.base_dir / version)

    def latest_version(self) -> str | None:
        return self._backend.latest_version()

    def get_public_pem(self) -> bytes | None:
        return self._backend.get_public_pem()

    def load_private_pem(self) -> bytes | None:
        return self._backend.load_private_pem()

    def latest_private_key_path(self) -> str | None:
        return self._backend.latest_private_key_path()

    def rotate(self) -> Tuple[str, str]:
        return self._backend.rotate()

    def list_versions(self) -> list[str]:
        return self._backend.list_versions()
