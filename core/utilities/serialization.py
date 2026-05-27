# core/utilities/serialization.py

import json
import pickle
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class SerializationError(Exception):
    """シリアライゼーション例外"""
    pass


# =====================================================
# JSON 操作
# =====================================================

def dict_to_json(data: Dict[str, Any]) -> str:
    """
    辞書を JSON 文字列に変換
    
    Args:
        data: 辞書
        
    Returns:
        JSON 文字列
    """
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except TypeError as e:
        raise SerializationError(f"JSON serialization failed: {e}") from e


def json_to_dict(json_str: str) -> Dict[str, Any]:
    """
    JSON 文字列を辞書に変換
    
    Args:
        json_str: JSON 文字列
        
    Returns:
        辞書
    """
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise SerializationError(f"JSON deserialization failed: {e}") from e


def save_json(data: Dict[str, Any], filepath: Path):
    """
    辞書を JSON ファイルに保存
    
    Args:
        data: 辞書
        filepath: 保存先ファイルパス
    """
    try:
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved JSON to {filepath}")
    except Exception as e:
        raise SerializationError(f"Failed to save JSON: {e}") from e


def load_json(filepath: Path) -> Dict[str, Any]:
    """
    JSON ファイルから辞書を読み込む
    
    Args:
        filepath: 読み込むファイルパス
        
    Returns:
        辞書
    """
    try:
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Loaded JSON from {filepath}")
        return data
    except json.JSONDecodeError as e:
        raise SerializationError(f"Invalid JSON format: {e}") from e
    except Exception as e:
        raise SerializationError(f"Failed to load JSON: {e}") from e


# =====================================================
# Pickle 操作
# =====================================================

def obj_to_pickle(obj: Any) -> bytes:
    """
    オブジェクトを pickle バイト列に変換
    
    Args:
        obj: オブジェクト
        
    Returns:
        pickle バイト列
    """
    try:
        return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        raise SerializationError(f"Pickle serialization failed: {e}") from e


def pickle_to_obj(data: bytes) -> Any:
    """
    pickle バイト列をオブジェクトに変換
    
    Args:
        data: pickle バイト列
        
    Returns:
        オブジェクト
    """
    try:
        return pickle.loads(data)
    except Exception as e:
        raise SerializationError(f"Pickle deserialization failed: {e}") from e


def save_pickle(obj: Any, filepath: Path):
    """
    オブジェクトを pickle ファイルに保存
    
    Args:
        obj: オブジェクト
        filepath: 保存先ファイルパス
    """
    try:
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'wb') as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"Saved pickle to {filepath}")
    except Exception as e:
        raise SerializationError(f"Failed to save pickle: {e}") from e


def load_pickle(filepath: Path, expected_type: Optional[Type[T]] = None) -> Any:
    """
    pickle ファイルからオブジェクトを読み込む
    
    Args:
        filepath: 読み込むファイルパス
        expected_type: 期待されるオブジェクトタイプ（型チェック用）
        
    Returns:
        オブジェクト
    """
    try:
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        with open(filepath, 'rb') as f:
            obj = pickle.load(f)
        
        if expected_type is not None and not isinstance(obj, expected_type):
            raise SerializationError(
                f"Type mismatch: expected {expected_type}, got {type(obj)}"
            )
        
        logger.info(f"Loaded pickle from {filepath}")
        return obj
    except Exception as e:
        if isinstance(e, SerializationError):
            raise
        raise SerializationError(f"Failed to load pickle: {e}") from e


# =====================================================
# 統合インターフェース
# =====================================================

class Serializer:
    """
    シリアライゼーション統合クラス
    
    使用例:
        serializer = Serializer()
        serializer.save_as_json(data, "data.json")
        loaded = serializer.load_from_json("data.json")
    """

    @staticmethod
    def save(obj: Any, filepath: Path, format: str = 'auto'):
        """
        オブジェクトを保存
        
        Args:
            obj: オブジェクト
            filepath: 保存先ファイルパス
            format: ファイル形式（'json', 'pickle', 'auto'）
        """
        filepath = Path(filepath)
        
        if format == 'auto':
            # ファイル拡張子から自動判定
            format = filepath.suffix.lower().lstrip('.')
        
        if format == 'json':
            if isinstance(obj, dict):
                save_json(obj, filepath)
            else:
                raise SerializationError(
                    "JSON format requires dict object"
                )
        elif format == 'pickle':
            save_pickle(obj, filepath)
        else:
            raise SerializationError(f"Unsupported format: {format}")

    @staticmethod
    def load(filepath: Path, format: str = 'auto') -> Any:
        """
        ファイルから読み込み
        
        Args:
            filepath: 読み込むファイルパス
            format: ファイル形式（'json', 'pickle', 'auto'）
            
        Returns:
            オブジェクト
        """
        filepath = Path(filepath)
        
        if format == 'auto':
            # ファイル拡張子から自動判定
            format = filepath.suffix.lower().lstrip('.')
        
        if format == 'json':
            return load_json(filepath)
        elif format == 'pickle':
            return load_pickle(filepath)
        else:
            raise SerializationError(f"Unsupported format: {format}")

    @staticmethod
    def serialize_dict(data: Dict[str, Any]) -> str:
        """辞書を JSON 文字列にシリアライズ"""
        return dict_to_json(data)

    @staticmethod
    def deserialize_dict(json_str: str) -> Dict[str, Any]:
        """JSON 文字列を辞書にデシリアライズ"""
        return json_to_dict(json_str)


# 便利な関数
def safe_json_dump(obj: Any, default_str: str = "{}") -> str:
    """
    安全な JSON ダンプ（エラー時はデフォルト値を返す）
    
    Args:
        obj: オブジェクト
        default_str: エラー時のデフォルト値
        
    Returns:
        JSON 文字列
    """
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception as e:
        logger.error(f"JSON dump failed: {e}")
        return default_str


def safe_pickle_dump(obj: Any) -> Optional[bytes]:
    """
    安全な pickle ダンプ（エラー時は None を返す）
    
    Args:
        obj: オブジェクト
        
    Returns:
        pickle バイト列（エラー時は None）
    """
    try:
        return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        logger.error(f"Pickle dump failed: {e}")
        return None
