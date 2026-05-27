import os
import json
import hashlib
import hmac
import time
from typing import Any, Dict, Optional
import threading

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature, decode_dss_signature
    from cryptography.exceptions import InvalidSignature
    CRYPTO_AVAILABLE = True
except Exception:
    CRYPTO_AVAILABLE = False


class ImmutableAuditLog:
    """Append-only JSONL audit log with SHA-256 chaining.

    Each entry is stored as a JSON object with fields:
      - timestamp: UNIX epoch float
      - record: arbitrary JSON-serializable payload
      - prev_hash: hex of previous line's hash ('' for first)
      - hash: SHA-256 hex of (prev_hash + serialized record + timestamp)

    Writes are synchronized with a thread lock and flushed+fsynced to reduce tampering risk.
    """

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()
        self.hmac_key: bytes | None = None
        # ECDSA private key object (cryptography) or None
        self._ecdsa_private = None
        self._ecdsa_public_pem: bytes | None = None

    def enable_hmac(self, key: str | bytes):
        """Enable HMAC signing of each entry using the provided key.

        Key may be a string or bytes. HMAC (SHA256) value is stored in the
        `hmac` field of each entry.
        """
        if isinstance(key, str):
            key = key.encode("utf-8")
        self.hmac_key = key

    def generate_ecdsa_keypair(self, private_path: str, public_path: str, overwrite: bool = False) -> None:
        """Generate an ECDSA P-256 keypair and write PEM files.

        Requires `cryptography` package. Writes private PEM (PKCS8) and public PEM.
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography package not available")
        if (not overwrite) and (os.path.exists(private_path) or os.path.exists(public_path)):
            raise FileExistsError("Key files exist; set overwrite=True to replace")
        private_key = ec.generate_private_key(ec.SECP256R1())
        priv_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        with open(private_path, "wb") as f:
            f.write(priv_pem)
        with open(public_path, "wb") as f:
            f.write(pub_pem)

    def enable_ecdsa_from_private_pem(self, private_pem: bytes, include_public_in_entry: bool = False) -> None:
        """Enable ECDSA signing using a private key in PEM bytes."""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography package not available")
        priv = serialization.load_pem_private_key(private_pem, password=None)
        self._ecdsa_private = priv
        if include_public_in_entry:
            self._ecdsa_public_pem = priv.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )

    def enable_ecdsa_from_file(self, private_path: str, include_public_in_entry: bool = False) -> None:
        with open(private_path, "rb") as f:
            data = f.read()
        self.enable_ecdsa_from_private_pem(data, include_public_in_entry=include_public_in_entry)

    def _compute_hash(self, prev_hash: str, timestamp: float, record_json: str) -> str:
        h = hashlib.sha256()
        h.update(prev_hash.encode("utf-8"))
        h.update(str(timestamp).encode("utf-8"))
        h.update(record_json.encode("utf-8"))
        return h.hexdigest()

    def _read_last_hash(self) -> str:
        if not os.path.exists(self.path):
            return ""
        try:
            with open(self.path, "rb") as f:
                # Seek to end and read last line
                f.seek(0, os.SEEK_END)
                if f.tell() == 0:
                    return ""
                # Read backwards to find last newline
                pos = f.tell() - 1
                while pos > 0:
                    f.seek(pos)
                    if f.read(1) == b"\n":
                        break
                    pos -= 1
                if pos == 0:
                    f.seek(0)
                line = f.readline()
                try:
                    last = json.loads(line.decode("utf-8"))
                    return last.get("hash", "")
                except Exception:
                    return ""
        except Exception:
            return ""

    def _read_last_entry(self) -> dict:
        """Return parsed last JSONL entry or empty dict."""
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "rb") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() == 0:
                    return {}
                pos = f.tell() - 1
                while pos > 0:
                    f.seek(pos)
                    if f.read(1) == b"\n":
                        break
                    pos -= 1
                if pos == 0:
                    f.seek(0)
                line = f.readline()
                try:
                    return json.loads(line.decode("utf-8"))
                except Exception:
                    return {}
        except Exception:
            return {}

    def append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = time.time()
        record_json = json.dumps(record, sort_keys=True, ensure_ascii=False)
        with self._lock:
            prev_entry = self._read_last_entry()
            prev_hash = prev_entry.get("hash", "")
            prev_seq = int(prev_entry.get("sequence", 0) or 0)
            seq = prev_seq + 1
            monotonic_ns = time.monotonic_ns()

            # include some provider sequence if present in record to help with clock skew audits
            source_seq = None
            for k in ("provider_sequence", "sequence_id", "source_seq"):
                if k in record:
                    try:
                        source_seq = int(record.get(k))
                        break
                    except Exception:
                        pass

            h = self._compute_hash(prev_hash, timestamp, record_json)
            entry = {
                "timestamp": timestamp,
                "monotonic_ns": monotonic_ns,
                "sequence": seq,
                "record": record,
                "prev_hash": prev_hash,
                "hash": h,
            }
            if source_seq is not None:
                entry["source_sequence"] = source_seq
            # optional HMAC signature over the hash
            if self.hmac_key is not None:
                mac = hmac.new(self.hmac_key, h.encode("utf-8"), hashlib.sha256).hexdigest()
                entry["hmac"] = mac
            # optional ECDSA signature over the hash
            if self._ecdsa_private is not None:
                # sign the raw hash bytes
                signature = self._ecdsa_private.sign(h.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
                # signature is ASN.1 DER; store hex
                entry["signature"] = signature.hex()
                if self._ecdsa_public_pem is not None:
                    entry["public_key_pem"] = self._ecdsa_public_pem.decode("utf-8")
            line = json.dumps(entry, ensure_ascii=False) + "\n"
            # write, flush, fsync to reduce window for tampering
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
        return entry

    async def append_async(self, record: Dict[str, Any]):
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.append, record)

    def verify_entry(self, entry: Dict[str, Any], public_key_pem: Optional[bytes] = None) -> bool:
        """Verify ECDSA signature on a stored entry. If public_key_pem is None and the entry
        contains `public_key_pem`, that will be used.
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography package not available")
        sig_hex = entry.get("signature")
        if not sig_hex:
            return False
        sig = bytes.fromhex(sig_hex)
        pub_pem = public_key_pem
        if pub_pem is None:
            pk = entry.get("public_key_pem")
            if pk is None:
                return False
            pub_pem = pk.encode("utf-8")
        pub = serialization.load_pem_public_key(pub_pem)
        h = entry.get("hash", "")
        try:
            pub.verify(sig, h.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
            return True
        except InvalidSignature:
            return False
