import os
import yaml
import tempfile
import shutil
from pathlib import Path
from typing import Any, Dict
from concurrent.futures import ThreadPoolExecutor


_executor = ThreadPoolExecutor(max_workers=2)


class ConfigManager:
    """In-memory config manager with async-safe background persistence.

    Usage:
        mgr = ConfigManager('config/settings.yaml')
        settings = mgr.load()
        mgr.save_async(new_settings)

    The async save writes atomically to disk in a background thread.
    """

    def __init__(self, path: str = "config/settings.yaml"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _write_atomic(self, payload: Dict[str, Any]):
        tmpfd, tmppath = tempfile.mkstemp(prefix=self.path.name, dir=str(self.path.parent))
        os.close(tmpfd)
        try:
            with open(tmppath, "w", encoding="utf-8") as f:
                yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
            shutil.move(tmppath, str(self.path))
        finally:
            try:
                if os.path.exists(tmppath):
                    os.remove(tmppath)
            except Exception:
                pass

    def save_async(self, payload: Dict[str, Any]) -> None:
        try:
            _executor.submit(self._write_atomic, payload)
        except Exception:
            # Best-effort: try sync write as fallback
            try:
                self._write_atomic(payload)
            except Exception:
                pass

    def save_sync(self, payload: Dict[str, Any]) -> None:
        self._write_atomic(payload)
