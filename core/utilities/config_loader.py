# core/utilities/config_loader.py

from pathlib import Path
from typing import Any, Dict, Optional
import yaml


class ConfigLoader:
    """
    YAML 設定ファイル読み込みクラス
    
    使用方法:
        loader = ConfigLoader()
        settings = loader.load_settings()
        bankroll_config = loader.load_bankroll()
    """

    def __init__(self, config_dir: Optional[str] = None):
        """
        初期化
        
        Args:
            config_dir: 設定ディレクトリパス（デフォルト: config/）
        """
        if config_dir is None:
            # プロジェクトルートの config ディレクトリ
            self.config_dir = Path(__file__).parent.parent.parent / "config"
        else:
            self.config_dir = Path(config_dir)

        self.settings = {}
        self.bankroll = {}

    def load_settings(self) -> Dict[str, Any]:
        """
        settings.yaml を読み込む
        
        Returns:
            設定辞書
        """
        settings_path = self.config_dir / "settings.yaml"
        return self._load_yaml(settings_path)

    def load_bankroll(self) -> Dict[str, Any]:
        """
        bankroll.yaml を読み込む
        
        Returns:
            bankroll 設定辞書
        """
        bankroll_path = self.config_dir / "bankroll.yaml"
        return self._load_yaml(bankroll_path)

    def load_model_config(self) -> Dict[str, Any]:
        """
        model_config.yaml を読み込む
        
        Returns:
            モデル設定辞書
        """
        model_path = self.config_dir / "model_config.yaml"
        return self._load_yaml(model_path)

    def _load_yaml(self, filepath: Path) -> Dict[str, Any]:
        """
        YAML ファイルを読み込む
        
        Args:
            filepath: YAMLファイルパス
            
        Returns:
            読み込んだ辞書（ファイルが存在しない場合は空辞書）
        """
        if not filepath.exists():
            print(f"Warning: {filepath} not found. Returning empty dict.")
            return {}

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data if data is not None else {}
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
            return {}

    def load_all(self) -> Dict[str, Dict[str, Any]]:
        """
        すべての設定ファイルを一度に読み込む
        
        Returns:
            {
                'settings': {...},
                'bankroll': {...},
                'model_config': {...}
            }
        """
        return {
            'settings': self.load_settings(),
            'bankroll': self.load_bankroll(),
            'model_config': self.load_model_config(),
        }

    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        特定のキーの設定値を取得
        
        Args:
            key: 設定キー
            default: デフォルト値
            
        Returns:
            設定値またはデフォルト値
        """
        if not self.settings:
            self.settings = self.load_settings()
        return self.settings.get(key, default)

    def get_bankroll_config(self, key: str, default: Any = None) -> Any:
        """
        特定のキーのbankroll設定値を取得
        
        Args:
            key: 設定キー
            default: デフォルト値
            
        Returns:
            設定値またはデフォルト値
        """
        if not self.bankroll:
            self.bankroll = self.load_bankroll()
        return self.bankroll.get(key, default)


# シングルトンインスタンス
_loader = None


def get_config_loader() -> ConfigLoader:
    """
    グローバルな ConfigLoader インスタンスを取得
    
    Returns:
        ConfigLoader インスタンス
    """
    global _loader
    if _loader is None:
        _loader = ConfigLoader()
    return _loader
