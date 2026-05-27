# core/utilities/time_utils.py

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import re


# JST (Japan Standard Time)
JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    """
    現在時刻を JST で取得
    
    Returns:
        JST の現在時刻
    """
    return datetime.now(JST)


def utc_to_jst(dt: datetime) -> datetime:
    """
    UTC を JST に変換
    
    Args:
        dt: UTC の datetime オブジェクト
        
    Returns:
        JST の datetime オブジェクト
    """
    if dt.tzinfo is None:
        # timezone情報がない場合はUTCと見なす
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST)


def jst_to_utc(dt: datetime) -> datetime:
    """
    JST を UTC に変換
    
    Args:
        dt: JST の datetime オブジェクト
        
    Returns:
        UTC の datetime オブジェクト
    """
    if dt.tzinfo is None:
        # timezone情報がない場合はJSTと見なす
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(timezone.utc)


def is_during_market_hours(dt: Optional[datetime] = None) -> bool:
    """
    競馬の営業時間内かどうかを判定
    
    競馬の一般的な営業時間: 10:30 - 18:30 (JST)
    
    Args:
        dt: 判定対象の datetime オブジェクト（デフォルト: 現在時刻）
        
    Returns:
        営業時間内なら True
    """
    if dt is None:
        dt = now_jst()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    
    hour = dt.hour
    minute = dt.minute
    time_val = hour * 100 + minute
    
    # 10:30 (1030) - 18:30 (1830)
    return 1030 <= time_val <= 1830


def is_race_day(dt: Optional[datetime] = None) -> bool:
    """
    レース開催日かどうかを判定（簡易版）
    
    土日・祝日を開催日と見なす（実装: 土曜日を開催日）
    
    Args:
        dt: 判定対象の datetime オブジェクト（デフォルト: 現在日付）
        
    Returns:
        開催日なら True
    """
    if dt is None:
        dt = now_jst()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    
    # 土曜日（5）を開催日とする（本来は競馬開催カレンダーで確認）
    weekday = dt.weekday()
    return weekday in [5, 6]  # Saturday, Sunday


def parse_race_time(time_str: str) -> Optional[datetime]:
    """
    レース時刻文字列をパース
    
    フォーマット:
        - "HH:MM" → 本日のレース時刻
        - "YYYY-MM-DD HH:MM" → 指定日時
        
    Args:
        time_str: 時刻文字列
        
    Returns:
        datetime オブジェクト（パース失敗時は None）
    """
    formats = [
        "%H:%M",
        "%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            
            # フォーマットが時刻のみの場合は本日と組み合わせる
            if "%Y" not in fmt:
                today = now_jst().date()
                dt = datetime.combine(today, dt.time())
            
            # timezone情報を付与
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
                
            return dt
        except ValueError:
            continue
    
    return None


def time_until_race(race_time: datetime) -> Optional[Tuple[int, int, int]]:
    """
    レース開始時刻までの時間を計算
    
    Args:
        race_time: レース開始時刻
        
    Returns:
        (時, 分, 秒) のタプル（過去の場合は None）
    """
    if race_time.tzinfo is None:
        race_time = race_time.replace(tzinfo=JST)
    
    now = now_jst()
    diff = race_time - now
    
    if diff.total_seconds() < 0:
        return None
    
    total_seconds = int(diff.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    return (hours, minutes, seconds)


def format_time_until_race(race_time: datetime) -> str:
    """
    レース開始時刻までの時間を人間が読める形式にフォーマット
    
    Args:
        race_time: レース開始時刻
        
    Returns:
        フォーマット済み文字列（例: "1時間30分15秒"）
    """
    time_tuple = time_until_race(race_time)
    
    if time_tuple is None:
        return "既に開始"
    
    hours, minutes, seconds = time_tuple
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}時間")
    if minutes > 0:
        parts.append(f"{minutes}分")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}秒")
    
    return "".join(parts)


def seconds_to_hms(seconds: int) -> Tuple[int, int, int]:
    """
    秒数を時:分:秒に変換
    
    Args:
        seconds: 秒数
        
    Returns:
        (時, 分, 秒) のタプル
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return (hours, minutes, secs)


def hms_to_seconds(hours: int, minutes: int, seconds: int) -> int:
    """
    時:分:秒を秒数に変換
    
    Args:
        hours: 時
        minutes: 分
        seconds: 秒
        
    Returns:
        秒数
    """
    return hours * 3600 + minutes * 60 + seconds


def format_hms(hours: int, minutes: int, seconds: int) -> str:
    """
    時:分:秒をフォーマット
    
    Args:
        hours: 時
        minutes: 分
        seconds: 秒
        
    Returns:
        "HH:MM:SS" 形式の文字列
    """
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def is_night(dt: Optional[datetime] = None) -> bool:
    """
    深夜かどうかを判定
    
    定義: 00:00 - 05:59 を深夜とする
    
    Args:
        dt: 判定対象の datetime オブジェクト（デフォルト: 現在時刻）
        
    Returns:
        深夜なら True
    """
    if dt is None:
        dt = now_jst()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    
    return dt.hour < 6


def is_morning(dt: Optional[datetime] = None) -> bool:
    """
    朝かどうかを判定
    
    定義: 06:00 - 11:59 を朝とする
    
    Args:
        dt: 判定対象の datetime オブジェクト
        
    Returns:
        朝なら True
    """
    if dt is None:
        dt = now_jst()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    
    return 6 <= dt.hour < 12


def is_afternoon(dt: Optional[datetime] = None) -> bool:
    """
    昼かどうかを判定
    
    定義: 12:00 - 17:59 を昼とする
    
    Args:
        dt: 判定対象の datetime オブジェクト
        
    Returns:
        昼なら True
    """
    if dt is None:
        dt = now_jst()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    
    return 12 <= dt.hour < 18


def is_evening(dt: Optional[datetime] = None) -> bool:
    """
    夜かどうかを判定
    
    定義: 18:00 - 23:59 を夜とする
    
    Args:
        dt: 判定対象の datetime オブジェクト
        
    Returns:
        夜なら True
    """
    if dt is None:
        dt = now_jst()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    
    return 18 <= dt.hour <= 23
