from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional


class ModelRegistry:
    def __init__(self, checkpoint_dir: str = "models/checkpoints"):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.active_dir = self.checkpoint_dir.parent / "active"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.active_dir.mkdir(parents=True, exist_ok=True)

    def save(self, model_path: str) -> Path:
        source = Path(model_path)
        if not source.exists():
            raise FileNotFoundError(str(source))

        target = self.checkpoint_dir / source.name
        shutil.copy2(source, target)
        return target

    def rollback(self, checkpoint_path: Optional[str] = None) -> Optional[Path]:
        # Choose latest checkpoint by modification time if none provided
        if checkpoint_path is None:
            checkpoints = sorted(self.checkpoint_dir.glob("*"), key=lambda path: path.stat().st_mtime)
            if not checkpoints:
                return None
            checkpoint_path = str(checkpoints[-1])

        source = Path(checkpoint_path)
        if not source.exists():
            raise FileNotFoundError(str(source))

        # copy checkpoint into active model location
        target = self.active_dir / source.name
        shutil.copy2(source, target)
        # Optionally, also update a canonical active filename
        canonical = self.active_dir / "predictor.pkl"
        shutil.copy2(source, canonical)
        return canonical

    def latest_checkpoint(self) -> Optional[Path]:
        checkpoints = sorted(self.checkpoint_dir.glob("*"), key=lambda path: path.stat().st_mtime)
        if not checkpoints:
            return None
        return checkpoints[-1]