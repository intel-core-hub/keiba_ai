# core/utilities/retry_utils.py

import asyncio
import time
import logging
from functools import wraps
from typing import Callable, Type, Tuple, Optional, Any

logger = logging.getLogger(__name__)


class RetryException(Exception):
    """リトライ失敗時の例外"""
    pass


def retry(
    times: int = 3,
    delay: float = 1.0,
    backoff: float = 1.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    log: bool = True
):
    """
    リトライデコレータ
    
    使用例:
        @retry(times=3, delay=1.0, exceptions=(ValueError, TimeoutError))
        def fetch_data():
            return requests.get(url)
    
    Args:
        times: リトライ回数（合計試行回数 = times + 1）
        delay: リトライ間隔（秒）
        backoff: バックオフ倍率（delay *= backoff）
        exceptions: キャッチする例外タプル
        log: ログ出力するかどうか
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            current_delay = delay
            last_exception = None

            for attempt in range(times + 1):
                try:
                    result = func(*args, **kwargs)
                    if attempt > 0 and log:
                        logger.info(
                            f"{func.__name__} succeeded after {attempt} retries"
                        )
                    return result
                except exceptions as e:
                    last_exception = e
                    if attempt < times:
                        if log:
                            logger.warning(
                                f"{func.__name__} failed (attempt {attempt + 1}/{times + 1}): {e}. "
                                f"Retrying in {current_delay}s..."
                            )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        if log:
                            logger.error(
                                f"{func.__name__} failed after {times + 1} attempts: {e}"
                            )

            raise RetryException(
                f"{func.__name__} failed after {times + 1} attempts"
            ) from last_exception

        return wrapper
    return decorator


def retry_async(
    times: int = 3,
    delay: float = 1.0,
    backoff: float = 1.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    log: bool = True
):
    """
    非同期関数用リトライデコレータ
    
    使用例:
        @retry_async(times=3)
        async def fetch_data():
            return await http_client.get(url)
    
    Args:
        times: リトライ回数
        delay: リトライ間隔（秒）
        backoff: バックオフ倍率
        exceptions: キャッチする例外タプル
        log: ログ出力するかどうか
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            current_delay = delay
            last_exception = None

            for attempt in range(times + 1):
                try:
                    result = await func(*args, **kwargs)
                    if attempt > 0 and log:
                        logger.info(
                            f"{func.__name__} succeeded after {attempt} retries"
                        )
                    return result
                except exceptions as e:
                    last_exception = e
                    if attempt < times:
                        if log:
                            logger.warning(
                                f"{func.__name__} failed (attempt {attempt + 1}/{times + 1}): {e}. "
                                f"Retrying in {current_delay}s..."
                            )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        if log:
                            logger.error(
                                f"{func.__name__} failed after {times + 1} attempts: {e}"
                            )

            raise RetryException(
                f"{func.__name__} failed after {times + 1} attempts"
            ) from last_exception

        return wrapper
    return decorator


class RetryableOperation:
    """
    リトライ可能な操作のラッパークラス
    
    使用例:
        op = RetryableOperation(my_function, times=3, delay=1.0)
        result = op.execute(arg1, arg2)
    """

    def __init__(
        self,
        func: Callable,
        times: int = 3,
        delay: float = 1.0,
        backoff: float = 1.0,
        exceptions: Tuple[Type[Exception], ...] = (Exception,),
    ):
        """
        初期化
        
        Args:
            func: 実行する関数
            times: リトライ回数
            delay: リトライ間隔
            backoff: バックオフ倍率
            exceptions: キャッチする例外
        """
        self.func = func
        self.times = times
        self.delay = delay
        self.backoff = backoff
        self.exceptions = exceptions
        self.attempts = 0
        self.last_error = None

    def execute(self, *args, **kwargs) -> Any:
        """
        実行
        
        Args:
            *args: 位置引数
            **kwargs: キーワード引数
            
        Returns:
            関数の戻り値
        """
        current_delay = self.delay
        self.attempts = 0

        for attempt in range(self.times + 1):
            self.attempts = attempt + 1
            try:
                return self.func(*args, **kwargs)
            except self.exceptions as e:
                self.last_error = e
                if attempt < self.times:
                    logger.warning(
                        f"Attempt {attempt + 1}/{self.times + 1} failed: {e}. "
                        f"Retrying in {current_delay}s..."
                    )
                    time.sleep(current_delay)
                    current_delay *= self.backoff
                else:
                    logger.error(
                        f"All {self.times + 1} attempts failed: {e}"
                    )
                    raise

    def is_success(self) -> bool:
        """最後の実行が成功したかどうか"""
        return self.last_error is None


# 便利なプリセット
retry_once = lambda f: retry(times=1)(f)
retry_three_times = lambda f: retry(times=3)(f)
retry_with_backoff = lambda f: retry(times=3, backoff=2.0)(f)
retry_http = lambda f: retry(
    times=3,
    delay=0.5,
    exceptions=(ConnectionError, TimeoutError, OSError)
)(f)
