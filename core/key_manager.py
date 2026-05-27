import os
import time
from typing import Tuple

from .audit_hash_log import ImmutableAuditLog


class KeyManager:
    """Simple filesystem-backed key manager for ECDSA keys.

    - Keys are stored under `base_dir/{version}/priv.pem` and `pub.pem`.
    - `latest` symlink (or file) points to current version.
    - rotate() generates a new keypair and moves `latest`.
    """

    def __init__(self, base_dir: str = "keys"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _version_dir(self, version: str) -> str:
        return os.path.join(self.base_dir, version)

    def latest_version(self) -> str | None:
        latest_file = os.path.join(self.base_dir, "LATEST")
        if os.path.exists(latest_file):
            with open(latest_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        return None

    def get_public_pem(self) -> bytes | None:
        v = self.latest_version()
        if not v:
            return None
        pub = os.path.join(self._version_dir(v), "pub.pem")
        if not os.path.exists(pub):
            return None
        with open(pub, "rb") as f:
            return f.read()

    def rotate(self) -> Tuple[str, str]:
        """Generate a new keypair version and set as latest. Returns (priv_path, pub_path)."""
        ts = str(int(time.time()))
        vd = self._version_dir(ts)
        os.makedirs(vd, exist_ok=False)
        priv = os.path.join(vd, "priv.pem")
        pub = os.path.join(vd, "pub.pem")
        al = ImmutableAuditLog(os.path.join("logs", "_km_tmp.jsonl"))
        # reuse audit log's key generation
        al.generate_ecdsa_keypair(priv, pub, overwrite=False)
        # write latest pointer
        with open(os.path.join(self.base_dir, "LATEST"), "w", encoding="utf-8") as f:
            f.write(ts)
        return priv, pub

    def list_versions(self):
        return sorted([d for d in os.listdir(self.base_dir) if d.isdigit()])
